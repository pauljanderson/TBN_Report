"""Rocket Launcher (50-SMA) configuration — defaults match portfolio_audit.awk BEGIN block."""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Iterable, Optional

# ATR% band bounds: these tokens (case-insensitive) disable that bound.
# Empty string is treated as off only when the key is explicitly set (Python -v).
_ATR_PCT_OFF_TOKENS = frozenset({"off", "none", "false", ""})


def parse_rl_atr_percent_bound(val: Any) -> Optional[float]:
    """Parse RL ATR% low/high. ``off``/``none``/``false``/empty → None (bound disabled)."""
    if val is None:
        return None
    if isinstance(val, bool):
        # bool is a subclass of int; treat False as off, True as invalid for a %.
        return None if not val else float(val)
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    if s in _ATR_PCT_OFF_TOKENS:
        return None
    return float(s)


def parse_rl_too_high(val: Any) -> float:
    """Parse RL too-high fill multiplier. ``off``/``none``/``false``/empty → 0 (gate disabled).

    Fill gate (see rocket_rl): ``next_open <= signal_low * rl_too_high * rl_stop_pct``.
    Default 0 (off); ``0``/``off`` disables. ``1`` with stop 0.934 requires open ≤ low×0.934
    (below the signal low) and almost never fills. Historical production used 1.14.
    """
    if val is None:
        return 0.0
    if isinstance(val, bool):
        return 0.0 if not val else float(val)
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    if s in _ATR_PCT_OFF_TOKENS:
        return 0.0
    return float(s)


def atr_pct_band_passes(
    atr_vol: float,
    low: Optional[float],
    high: Optional[float],
) -> bool:
    """Return True if atr_vol passes the ATR% band (None = unbound).

    Semantics:
    - Both None → no % filter.
    - Both numeric 0 → no % filter (legacy 0/0 footgun fix).
    - Only low set → require atr_vol >= low (low=0 is a no-op floor).
    - Only high set → require atr_vol <= high.
    - Both set (and not dual 0) → require low <= atr_vol <= high.
    Dollar ATR cap and min price are independent of this helper.
    """
    if low is None and high is None:
        return True
    if (
        low is not None
        and high is not None
        and float(low) == 0.0
        and float(high) == 0.0
    ):
        return True
    if low is not None and atr_vol < float(low):
        return False
    if high is not None and atr_vol > float(high):
        return False
    return True

# AWK -v names (uppercase) and legacy spellings → rocket_brt.py -v keys (rl_* on BRTConfig).
RL_V_ALIASES: dict[str, str] = {
    "SMA_QUAL": "rl_sma_qual",
    "RL_CASH": "rl_cash",
    "RL_DIP_PCT": "rl_dip_pct",
    "RL_50_SMA_LOOKBACK": "rl_50_sma_lookback",
    "RL_STOP_PCT": "rl_stop_pct",
    "RL_POST_TARGET_REENTRY_BARS": "rl_post_target_reentry_bars",
    "RL_POST_TARGET_REENTRY_DAYS": "rl_post_target_reentry_bars",
    "rl_post_target_reentry_days": "rl_post_target_reentry_bars",
    "RL_POST_TARGET_REENTRY_MODE": "rl_post_target_reentry_mode",
    "RL_POST_TARGET_STOP_PCT": "rl_post_target_stop_pct",
    "RL_POST_TARGET_MIN_STACK": "rl_post_target_min_stack",
    "RL_POST_TARGET_UNDER_SMA20": "rl_post_target_under_sma20",
    "RL_TARGET_PCT": "rl_target_pct",
    "RL_TOO_HIGH": "rl_too_high",
    "RL_EXPANSION": "rl_expansion",
    "RL_ACC_MIN": "rl_acc_min",
    "RL_ACC_COUNT": "rl_acc_count",
    "RL_CUT_THE_LOSERS": "rl_cut_the_losers",
    "RL_ATR_LOW_PERCENT": "rl_atr_low_percent",
    "RL_ATR_HIGH_PERCENT": "rl_atr_high_percent",
    "RL_ATR_LOW": "rl_atr_low_percent",
    "RL_ATR_HIGH": "rl_atr_high_percent",
    # Short aliases (no RL_ prefix) — same ATR% bounds; accept off via parse_rl_atr_percent_bound.
    "ATR_LOW": "rl_atr_low_percent",
    "ATR_HIGH": "rl_atr_high_percent",
    "atr_low": "rl_atr_low_percent",
    "atr_high": "rl_atr_high_percent",
    "RL_ATR_HIGH_VALUE": "rl_atr_high_value",
    "RL_LOW_PRICE": "rl_low_price",
    "RL_SLOPE_PERIOD": "rl_slope_period",
    "RL_SLOPE_THRESHOLD": "rl_slope_threshold",
    "RL_SHOCK_THRESHOLD": "rl_shock_threshold",
    "RL_SHOCK_REHAB_DAYS": "rl_shock_rehab_days",
    "RL_SHOCK_MAX_ALLOWED": "rl_shock_max_allowed",
    "RL_TRAIL_PROFIT": "rl_trail_profit",
    "RL_TRAIL_STOP": "rl_trail_stop",
    "RL_TRAIL_PROFIT2": "rl_trail_profit2",
    "RL_TRAIL_STOP2": "rl_trail_stop2",
    "RL_EXIT_PERCENT": "rl_exit_percent",
    "RL_EXIT_DAYS": "rl_exit_days",
    "RL_FLUSH_DAYS": "rl_flush_days",
    "PARTIAL_EXIT_TARGET": "rl_partial_exit_target",
    "PARTIAL_EXIT_PERCENT": "rl_partial_exit_percent",
    "PARTIAL_EXIT_FOLLOW_TARGET": "rl_partial_exit_follow_target",
    "SPY_INCLUSION": "rl_spy_inclusion",
    "AVG_VOL_DAYS": "rl_avg_vol_days",
    "VOL_PCT_THRESHOLD": "rl_vol_pct_threshold",
    "WATCH_MIN_SCORE": "rl_watch_min_score",
    "WATCH_DISABLE": "rl_watch_disable",
    "EXPANSION_LOOKBACK_DAYS": "rl_expansion_lookback_days",
    "PEAK_THRESHOLD_MAX": "rl_peak_threshold_max",
}

# Shared data-window aliases (engine-wide): friendly -v names → BRTConfig entry-date window
# fields. These are honored by every system that routes -v through normalize_rl_v_key
# (BRT, WPBR/PBR, RL, MTS, VEC, RS), so `-v start_date=2016-01-01` reconciles all engines to the
# spreadsheet window. Warmup: full OHLC history still loads for indicator/weekly lookback.
# WPBR: pivots/zones with pivot Monday before start_date are excluded from the strategy ledger
# (no BO/retest/rocket from those pivots). Entries before start_date are also blocked
# (entry_start_date). Default (unset) = empty = full history; DailyRun / production bats unchanged.
_SHARED_WINDOW_ALIASES: dict[str, str] = {
    "start_date": "entry_start_date",
    "data_start": "entry_start_date",
    "history_start": "entry_start_date",
    "end_date": "entry_end_date",
    "data_end": "entry_end_date",
}
RL_V_ALIASES.update(_SHARED_WINDOW_ALIASES)

# RS (Relative Strength) mode aliases → BRTConfig.relative_strength_enabled
RL_V_ALIASES.update(
    {
        "rs_mode": "relative_strength_enabled",
        "rs": "relative_strength_enabled",
        # Identity aliases kept for discoverability alongside -v sell_breakdown=...
        "sell_breakdown": "sell_breakdown",
        "rs_sell_breakdown": "sell_breakdown",
    }
)

# Minervini VCP mode aliases → BRTConfig.mvcp_mode
RL_V_ALIASES.update(
    {
        "minervini_vcp": "mvcp_mode",
        "mvcp": "mvcp_mode",
    }
)

# StockBee Momentum Burst aliases → BRTConfig.sb_mode
RL_V_ALIASES.update(
    {
        "stockbee_mode": "sb_mode",
        "stockbee": "sb_mode",
        "sb": "sb_mode",
    }
)

# WPBR daily-retest scan mode: friendly `-v retest_mode=...` alias → BRTConfig field.
# Also accept the explicit `wpbr_retest_mode` spelling (identity; kept for discoverability).
RL_V_ALIASES.update(
    {
        "retest_mode": "wpbr_retest_mode",
        "wpbr_retest_mode": "wpbr_retest_mode",
    }
)

# BRTConfig rl_* field → RLConfig field name (when they differ).
_BRT_KEY_TO_RL: dict[str, str] = {
    "rl_sma_qual": "sma_qual",
    "rl_expansion_lookback_days": "expansion_lookback_days",
    "rl_peak_threshold_max": "peak_threshold_max",
    "rl_partial_exit_target": "partial_exit_target",
    "rl_partial_exit_percent": "partial_exit_percent",
    "rl_partial_exit_follow_target": "partial_exit_follow_target",
    "rl_spy_inclusion": "spy_inclusion",
    "rl_avg_vol_days": "avg_vol_days",
    "rl_vol_pct_threshold": "vol_pct_threshold",
    "rl_watch_min_score": "watch_min_score",
    "rl_watch_disable": "watch_disable",
}

# AWK-only RL100 / Dive Bomber levers (Python port deferred). Serialized into
# RL_Report / RL_Audit_Report with these BEGIN-block defaults when not on BRTConfig.
# Toggle defaults are 0/off so non-RL and Python-RL runs show subsystems disabled.
RL_AWK_SUBSYSTEM_AUDIT_DEFAULTS: dict[str, Any] = {
    # RL100 (100-SMA subsystem)
    "rl100_toggle": 0,
    "rl100_cash": 47_500.0,
    "rl100_dip_pct": 1.041,
    "rl100_expansion": 1.163,
    "rl100_acc_min": 8,
    "rl100_acc_count": 10,
    "rl100_too_high": 1.14,
    "rl100_trail_profit": 0.14,
    "rl100_trail_stop": 0.0,
    "rl100_trail_profit2": 0.40,
    "rl100_trail_stop2": 0.20,
    "rl100_target_pct": 1.29,
    "rl100_stop_pct": 0.934,
    "rl100_exit_percent": 0.22,
    "rl100_exit_days": 17,
    "rl100_slope_period": 30,
    "rl100_slope_threshold": 0.0,
    "rl100_100_sma_lookback": 4,
    "rl100_cut_the_losers": 0.2,
    "rl100_flush_days": 42,
    "rl100_spy_inclusion": 0,
    "rl100_partial_exit_target": 0.0,
    "rl100_partial_exit_percent": 0.50,
    "rl100_partial_exit_follow_target": 0.1,
    "rl100_atr_high_percent": 0.0848,
    "rl100_atr_low_percent": 0.0244,
    "rl100_atr_high_value": 200.0,
    "rl100_low_price": 0.000001,
    # Dive Bomber (shorts; AWK only)
    "db_toggle": 0,
    "db_cash": 47_500.0,
    "db_stop_pct": 1.0946,
    "db_target_pct": 0.92,
    "db_rip_days_min": 3,
    "db_rip_days_max": 5,
    "db_rip_touch_tol": 0.026,
    "db_max_hold_days": 16,
    "db_squeeze_exit": 0,
    "db_inverse_strict": 0,
    "db_slope_lookback": 4,
    "db_gap_up_max": 1.14,
    "db_expansion": 0.98,
    "db_acc_min": 9,
    "db_acc_count": 10,
    "db_peak_trough_max": -0.43,
}

# Optional BRT zone/retest entry gates — not used by portfolio_audit.awk RL path.
# Neutralized on rl_mode=true unless explicitly passed via -v (reserved for future RL wiring).
RL_BRT_GATE_DEFAULTS_OFF: dict[str, Any] = {
    "min_spy_compare_1y_at_trigger": 0.0,
    "max_spy_compare_1y_at_trigger": 0.0,
    "min_spy_compare_2y_at_trigger": 0.0,
    "min_spy_compare_3y_at_trigger": 0.0,
    "min_beta_at_trigger": 0.0,
    "max_beta_at_trigger": 0.0,
    "min_upper_wick_atr_at_trigger": 0.0,
    "min_atr_pct_at_trigger": 0.0,
    "max_atr_pct_at_trigger": 0.0,
    "min_dist_to_52w_high_pct_at_trigger": 0.0,
    "max_dist_to_52w_high_pct_at_trigger": 0.0,
    "growth_filter_enabled": False,
    "rl_brt_entry_gates_enabled": False,
}

# RLConfig fields that map 1:1 onto BRTConfig (no rl_ prefix).
_RL_SHARED_BRT_KEYS = frozenset(
    {
        "mandatory_ind_states_path",
        "exclude_ind_states_path",
        "indicator_cache_dir",
        "indicator_cache",
        "entry_start_date",
        "entry_end_date",
        # SPY TC lag-1 market filters (defaults off; match BRTConfig).
        "spy_int_tc_lag",
        "spy_tc_weak_horizon",
        "block_entries_when_spy_int_weak",
        "exit_when_spy_int_turns_weak",
    }
)


@dataclass(frozen=True)
class RLConfig:
    """50-trigger Rocket Launcher parameters (AWK variable names in comments)."""

    sma_qual: bool = True
    rl_cash: float = 47_500.0
    rl_dip_pct: float = 1.041
    rl_50_sma_lookback: int = 4
    rl_stop_pct: float = 0.934
    # Post-TARGET re-entry window (0 bars = feature fully off; production unchanged).
    # When bars > 0 and prior closed trade exited TARGET with fill within N trading bars,
    # rl_post_target_reentry_mode selects one mutually exclusive policy:
    #   stop_loss      — allow entry; original stop uses rl_post_target_stop_pct
    #                    (fill gates still use rl_stop_pct). Default for backward compat.
    #   min_stack      — block unless (SMA20/SMA50 − 1) ≥ rl_post_target_min_stack
    #                    (evaluated on trigger/signal bar).
    #   under_sma_limit — block unless close ≥ SMA20 × (1 − rl_post_target_under_sma20)
    #                    i.e. depth (SMA20−close)/SMA20 ≤ limit (trigger bar).
    #   none           — block all re-entries in the window (cooldown).
    rl_post_target_reentry_bars: int = 0
    rl_post_target_reentry_mode: str = "stop_loss"
    rl_post_target_stop_pct: float = 0.0
    rl_post_target_min_stack: float = 0.05
    rl_post_target_under_sma20: float = 0.03
    rl_target_pct: float = 1.20
    # Fill gate: next_open <= signal_low * rl_too_high * rl_stop_pct (0 / off disables; default off).
    rl_too_high: float = 0.0
    rl_expansion: float = 1.163
    rl_acc_min: int = 8
    rl_acc_count: int = 10
    expansion_lookback_days: int = 10
    rl_cut_the_losers: float = 0.25
    # ATR% band: None = that bound off (``-v RL_ATR_LOW=off`` / ``ATR_LOW=off`` / ``RL_ATR_HIGH=off``).
    # Dual numeric 0/0 also disables the % band (see atr_pct_band_passes).
    rl_atr_low_percent: Optional[float] = 0.0244
    rl_atr_high_percent: Optional[float] = 0.0848
    rl_atr_high_value: float = 200.0
    rl_low_price: float = 0.000001
    peak_threshold_max: float = 2.0
    rl_slope_period: int = 30
    rl_slope_threshold: float = 0.0643
    rl_shock_threshold: float = 0.0
    rl_shock_rehab_days: int = 120
    rl_shock_max_allowed: int = 1
    rl_trail_profit: float = 0.0
    rl_trail_stop: float = 0.0
    rl_trail_profit2: float = 0.0
    rl_trail_stop2: float = 0.0
    rl_exit_percent: float = 0.29
    rl_exit_days: int = 10000
    rl_flush_days: int = 0
    partial_exit_target: float = 0.0
    partial_exit_percent: float = 0.50
    partial_exit_follow_target: float = 0.1
    spy_inclusion: bool = False
    avg_vol_days: int = 50
    vol_pct_threshold: float = 0.0
    watch_min_score: int = 55
    watch_disable: bool = False
    # Optional IND-state gates (off by default). Paths resolve like BRT mandatory/exclude.
    mandatory_ind_states_path: str = ""
    exclude_ind_states_path: str = ""
    indicator_cache_dir: str = ""
    indicator_cache: bool = True
    # Inclusive entry date window (YYYY-MM-DD / YYYYMMDD). Empty = off.
    entry_start_date: str = ""
    entry_end_date: str = ""
    # SPY IND_TC_{SHORT|INT|LONG}_OUTLOOK lag-1 market filters (shared with BRT; default off).
    # Horizon: spy_tc_weak_horizon=short|int|long (default int; alias intermediate=int).
    # block_entries: evaluate on trigger/signal bar T with outlook[T-lag] (default lag=1);
    #   do not re-check on fill/entry open T+1.
    # exit_on_weak: on each later day D, if lag-1 outlook newly turns Weak, exit at D open.
    spy_int_tc_lag: int = 1
    spy_tc_weak_horizon: str = "int"
    block_entries_when_spy_int_weak: bool = False
    exit_when_spy_int_turns_weak: bool = False


def _brt_key_for_rl_field(rl_field_name: str) -> str:
    if rl_field_name in _RL_SHARED_BRT_KEYS:
        return rl_field_name
    for brt_key, name in _BRT_KEY_TO_RL.items():
        if name == rl_field_name:
            return brt_key
    if rl_field_name.startswith("rl_"):
        return rl_field_name
    return f"rl_{rl_field_name}"


def rl_config_v_keys() -> tuple[str, ...]:
    """All -v keys accepted for RL engine parameters."""
    return tuple(
        sorted(
            {
                *_BRT_KEY_TO_RL.keys(),
                *(_brt_key_for_rl_field(f.name) for f in fields(RLConfig)),
                *RL_V_ALIASES.values(),
            }
        )
    )


def normalize_rl_v_key(key: str) -> str:
    """Map AWK-style -v names to BRTConfig field names."""
    k = (key or "").strip()
    if not k:
        return k
    if k in RL_V_ALIASES:
        return RL_V_ALIASES[k]
    ku = k.upper()
    if ku in RL_V_ALIASES:
        return RL_V_ALIASES[ku]
    return k


def rl_config_from_brt_cfg(cfg: Any) -> RLConfig:
    """Build RLConfig from BRTConfig rl_* fields."""
    base = RLConfig()
    kw: dict[str, Any] = {f.name: getattr(base, f.name) for f in fields(RLConfig)}

    for brt_key, rl_name in _BRT_KEY_TO_RL.items():
        if hasattr(cfg, brt_key):
            kw[rl_name] = getattr(cfg, brt_key)

    for f in fields(RLConfig):
        brt_key = _brt_key_for_rl_field(f.name)
        if hasattr(cfg, brt_key):
            kw[f.name] = getattr(cfg, brt_key)

    # Shared BRTConfig keys (not rl_* prefixed) used by optional IND gates / date windows.
    for shared in _RL_SHARED_BRT_KEYS:
        if hasattr(cfg, shared):
            kw[shared] = getattr(cfg, shared)

    # Normalize ATR% bounds (accept off/none/false strings from JSON / soft overrides).
    for atr_key in ("rl_atr_low_percent", "rl_atr_high_percent"):
        if atr_key in kw:
            kw[atr_key] = parse_rl_atr_percent_bound(kw[atr_key])
    if "rl_too_high" in kw:
        kw["rl_too_high"] = parse_rl_too_high(kw["rl_too_high"])

    return RLConfig(**kw)


def apply_rl_defaults_to_brt_kw(
    kw: dict[str, Any],
    explicit_overrides: Iterable[str] | None = None,
) -> dict[str, Any]:
    """When rl_mode=true: AWK RL defaults, isolate from BRT/IND/YH, neutralize unused BRT gates."""
    out = dict(kw)
    explicit = {normalize_rl_v_key(k) for k in (explicit_overrides or ())}

    if not _rl_mode_active(out.get("rl_mode", "false")):
        return out

    out["rl_mode"] = "true"
    if "brt_zones" not in explicit:
        out["brt_zones"] = False
    if "yh_zones" not in explicit:
        out["yh_zones"] = False
    if "indicator_buy" not in explicit:
        out["indicator_buy"] = "off"

    base = RLConfig()
    for brt_key, rl_name in _BRT_KEY_TO_RL.items():
        if brt_key not in explicit and brt_key not in out:
            out[brt_key] = getattr(base, rl_name)
    for f in fields(RLConfig):
        brt_key = _brt_key_for_rl_field(f.name)
        if brt_key not in explicit and brt_key not in out:
            out[brt_key] = getattr(base, f.name)

    for gate_key, gate_val in RL_BRT_GATE_DEFAULTS_OFF.items():
        if gate_key not in explicit:
            out[gate_key] = gate_val

    return out


def _rl_mode_active(val: Any) -> bool:
    s = str(val if val is not None else "false").strip().lower()
    if s in ("true", "on", "yes", "1", "only"):
        return True
    if s in ("false", "off", "no", "0", ""):
        return False
    return False
