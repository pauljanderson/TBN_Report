"""Rocket Launcher (50-SMA) configuration — defaults match portfolio_audit.awk BEGIN block."""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Iterable

# AWK -v names (uppercase) and legacy spellings → rocket_brt.py -v keys (rl_* on BRTConfig).
RL_V_ALIASES: dict[str, str] = {
    "SMA_QUAL": "rl_sma_qual",
    "RL_CASH": "rl_cash",
    "RL_DIP_PCT": "rl_dip_pct",
    "RL_50_SMA_LOOKBACK": "rl_50_sma_lookback",
    "RL_STOP_PCT": "rl_stop_pct",
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
# (BRT, WPBR/PBR, RL, MTS, VEC), so `-v start_date=2016-01-01` reconciles all engines to the
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
    }
)


@dataclass(frozen=True)
class RLConfig:
    """50-trigger Rocket Launcher parameters (AWK variable names in comments)."""

    sma_qual: bool = True
    rl_cash: float = 47_500.0
    rl_dip_pct: float = 1.024
    rl_50_sma_lookback: int = 4
    rl_stop_pct: float = 0.934
    rl_target_pct: float = 1.20
    rl_too_high: float = 1.14
    rl_expansion: float = 1.163
    rl_acc_min: int = 8
    rl_acc_count: int = 10
    expansion_lookback_days: int = 10
    rl_cut_the_losers: float = 0.25
    rl_atr_low_percent: float = 0.0244
    rl_atr_high_percent: float = 0.0848
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
