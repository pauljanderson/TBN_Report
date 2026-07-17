"""System definitions for per_symbol_optimizer (BRT, RL, MTS, YH).

DailyRun / standalone launchers own the production symbol lists in each run_*.bat
(BRT_SYMBOLS, RL_SYMBOLS, YH_SYMBOLS, MTS_SYMBOLS, ...). Keep the Python lists below
aligned with those bats when changing universes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dataclasses import fields

from rocket_brt import BRTConfig, mts_sheet_parity_overrides
from rocket_rl_config import RLConfig

REPO_ROOT = Path(__file__).parent.parent
RL_UNIVERSE = REPO_ROOT / "data" / "rl_gold_universe.txt"

BRT_SYMBOLS = [
    "AAPL", "ABBV", "ACN", "ADBE", "ADI", "AMAT", "AMD", "AMZN", "AU", "AVGO", "AXP", "BABA", "BAC",
    "CDNS", "CI", "CRM", "CRWD", "DIS", "GILD", "GOOG", "GOOGL", "HD", "JPM", "KO", "KR", "LOW", "LYV",
    "META", "MPC", "MS", "MSFT", "MU", "NEM", "NFLX", "NVDA", "OMER", "ORCL", "PFE", "PG", "PLTR", "PM",
    "PPTA", "SHOP", "TMUS", "TSLA", "TSM", "UNH", "V", "WFC", "WMT", "XOM",
]

YH_SYMBOLS = [
    "NVDA", "MSFT", "AAPL", "AMZN", "META", "NFLX", "AMD", "AU", "GOOGL", "TSLA",
]

BRT_BASELINE: dict[str, Any] = {
    "brt_cash": 47_500.0,
    "stop_pct": 0.934,
    "stop_pct_is_multiplier": True,
    "target_pct": 1.21,
    "too_high_multiplier": 0.0,
    "band_pct": 0.0154,
    "strong_pre_pivot_pct": 0.081,
    "strong_post_pivot_pct": 0.108,
    "strong_pre_pivot_bars": 7,
    "strong_post_pivot_bars": 7,
    "breakout_bars": 100,
    "tight_range_threshold_pct": 0.35,
    "tight_range_lookback": 105,
    "sheet_breakout_scan_start_row_delta": 2,
    "sheet_touch_pullback_bars": 10,
    "brt_sheet_touch": True,
    "max_positions": 16,
    "min_spy_compare_1y_at_trigger": -1000.0,
    "sheet_red_to_green_entry_enabled": True,
    "sheet_dw_countif_include_prior_bar_date": False,
    "growth_filter_enabled": True,
    "min_ind_score": -1.0,
    "compute_beta": False,
    "brt_zones": True,
    "yh_zones": False,
    "compute_equity_metrics": True,
    "tight_range_enabled": True,
    "strong_pivots_enabled": True,
}

RL_BASELINE: dict[str, Any] = {
    "rl_cash": 47_500.0,
    "rl_dip_pct": 1.018,
    "rl_50_sma_lookback": 4,
    "rl_stop_pct": 0.934,
    "rl_target_pct": 1.20,
    "rl_too_high": 1.14,
    "rl_expansion": 1.163,
    "rl_acc_min": 6,
    "rl_acc_count": 10,
    "rl_expansion_lookback_days": 10,
    "rl_cut_the_losers": 0.20,
    "rl_atr_low_percent": 0.0244,
    "rl_atr_high_percent": 0.0848,
    "rl_atr_high_value": 200.0,
    "rl_low_price": 1e-6,
    "rl_peak_threshold_max": 2.0,
    "rl_slope_period": 30,
    "rl_slope_threshold": 0.0643,
    "rl_shock_threshold": 0.0,
    "rl_exit_percent": 0.25,
    "rl_flush_days": 0,
    "rl_spy_inclusion": False,
    "rl_avg_vol_days": 50,
    "rl_vol_pct_threshold": 0.0,
    "rl_trail_profit": 0.0,
    "rl_trail_stop": 0.0,
    "rl_trail_profit2": 0.0,
    "rl_trail_stop2": 0.0,
}

# run_mts.bat + MTS_Optimizer starting point
MTS_BASELINE: dict[str, Any] = {
    **mts_sheet_parity_overrides(),
    "brt_cash": 47_500.0,
    "band_pct": 0.018,
    "touch_threshold": 2,
    "strong_post_pivot_bars": 7,
    "strong_post_pivot_pct": 0.06,
    "strong_pre_pivot_bars": 7,
    "strong_pre_pivot_pct": 0.12,
    "target_pct": 1.22,
    "stop_pct": 0.934,
    "stop_pct_is_multiplier": True,
    "stop_anchor": "signal_low",
    "compute_equity_metrics": True,
    "brt_zones": True,
    "yh_zones": False,
}

# run_yh.bat
YH_BASELINE: dict[str, Any] = {
    "brt_cash": 47_500.0,
    "yh_zones": True,
    "brt_zones": False,
    "band_pct": 0.0099,
    "strong_pre_pivot_pct": 0.12,
    "strong_post_pivot_pct": 0.109,
    "min_spy_compare_1y_at_trigger": -1000.0,
    "ind_score_weights_path": "",
    "too_high_multiplier": 0.0,
    "yh_move_away_pct": 0.031,
    "target_pct": 1.27,
    "stop_pct": 0.923,
    "stop_pct_is_multiplier": True,
    "compute_equity_metrics": True,
    "growth_filter_enabled": True,
}

BRT_PLAN: dict[str, tuple[Any, ...]] = {
    "band_pct": (0.012, 0.014, 0.0154, 0.017, 0.019, 0.022),
    "stop_pct": (0.920, 0.927, 0.934, 0.940, 0.950),
    "target_pct": (1.15, 1.18, 1.21, 1.24, 1.27),
    "tight_range_threshold_pct": (0.30, 0.33, 0.35, 0.37, 0.40),
    "tight_range_lookback": (90, 105, 120, 140),
    "breakout_bars": (80, 100, 120),
    "strong_pre_pivot_pct": (0.070, 0.081, 0.100, 0.120),
    "strong_post_pivot_pct": (0.090, 0.108, 0.120, 0.140),
    "touch_threshold": (4, 5, 6, 7),
    "pivot_k": (3, 4, 5, 6),
}

RL_PLAN: dict[str, tuple[Any, ...]] = {
    "rl_dip_pct": (1.01, 1.014, 1.018, 1.022, 1.026, 1.03),
    "rl_expansion": (1.1, 1.13, 1.163, 1.18),
    "rl_acc_min": (4, 6, 8, 10),
    "rl_slope_threshold": (0.0, 0.05, 0.0643, 0.08),
    "rl_target_pct": (1.15, 1.18, 1.20, 1.22, 1.25, 1.28),
    "rl_stop_pct": (0.910, 0.927, 0.934, 0.940, 0.950),
    "rl_trail_profit": (0.0, 0.12, 0.16),
    "rl_trail_stop": (0.0, 0.03, 0.07),
    "rl_trail_profit2": (0.0, 0.32, 0.40),
    "rl_trail_stop2": (0.0, 0.14, 0.22),
}

MTS_PLAN: dict[str, tuple[Any, ...]] = {
    "band_pct": (0.015, 0.016, 0.017, 0.018, 0.019, 0.020, 0.022, 0.024),
    "touch_threshold": (2, 3, 4, 5),
    "strong_post_pivot_bars": (5, 6, 7, 8),
    "strong_post_pivot_pct": (0.06, 0.07, 0.08, 0.09, 0.10),
    "strong_pre_pivot_bars": (5, 6, 7, 8),
    "strong_pre_pivot_pct": (0.08, 0.10, 0.12, 0.14),
    "target_pct": (1.18, 1.20, 1.22, 1.24, 1.26),
    "stop_pct": (0.91, 0.92, 0.934, 0.94, 0.95),
}

YH_PLAN: dict[str, tuple[Any, ...]] = {
    "band_pct": (0.008, 0.0099, 0.011, 0.012, 0.013),
    "stop_pct": (0.910, 0.923, 0.934, 0.940),
    "target_pct": (1.20, 1.24, 1.27, 1.30),
    "yh_move_away_pct": (0.025, 0.031, 0.037, 0.043),
    "strong_pre_pivot_pct": (0.10, 0.12, 0.14),
    "strong_post_pivot_pct": (0.09, 0.109, 0.12),
}

# run_vec.bat — Volume + prior-period Extreme Confluence
VEC_BASELINE: dict[str, Any] = {
    "brt_cash": 47_500.0,
    "vec_zones": True,
    "brt_zones": False,
    "yh_zones": False,
    "band_pct": 0.012,
    "vec_vp_lookback": 60,
    "vec_vp_bin_pct": 0.005,
    "vec_prior_bars": 5,
    "vec_prior_side": "high",
    "vec_confluence_pct": 0.0075,
    "vec_move_away_pct": 0.02,
    "vec_min_bars_between": 20,
    "min_spy_compare_1y_at_trigger": -1000.0,
    "too_high_multiplier": 0.0,
    "target_pct": 1.24,
    "stop_pct": 0.927,
    "stop_pct_is_multiplier": True,
    "compute_equity_metrics": True,
    "growth_filter_enabled": True,
}

VEC_PLAN: dict[str, tuple[Any, ...]] = {
    "band_pct": (0.010, 0.012, 0.014, 0.016, 0.018),
    "vec_confluence_pct": (0.005, 0.0075, 0.010, 0.0125),
    "vec_move_away_pct": (0.0, 0.015, 0.02, 0.025, 0.03),
    "vec_vp_lookback": (40, 60, 80, 120),
    "vec_prior_bars": (5, 10, 21),
    "stop_pct": (0.910, 0.923, 0.927, 0.934, 0.940),
    "target_pct": (1.18, 1.21, 1.24, 1.27, 1.30),
}

# run_pbr.bat — Weekly pivot break + daily retest
PBR_BASELINE: dict[str, Any] = {
    "brt_cash": 47_500.0,
    "pbr_zones": True,
    "brt_zones": False,
    "yh_zones": False,
    "vec_zones": False,
    "band_pct": 0.015,
    "strong_pre_pivot_bars": 3,
    "strong_pre_pivot_pct": 0.10,
    "strong_post_pivot_bars": 3,
    "strong_post_pivot_pct": 0.10,
    "strong_pivot_mode": "either",
    "pbr_breakout_confirmation": 0.03,
    "pbr_max_days_after_retest": 2,
    "growth_filter_enabled": False,
    "entry_from_retest_only": True,
    "min_spy_compare_1y_at_trigger": -1000.0,
    "too_high_multiplier": 0.0,
    "target_pct": 1.24,
    "stop_pct": 0.927,
    "stop_pct_is_multiplier": True,
    "compute_equity_metrics": True,
}

PBR_PLAN: dict[str, tuple[Any, ...]] = {
    "band_pct": (0.012, 0.014, 0.015, 0.016, 0.018),
    "strong_pre_pivot_pct": (0.08, 0.10, 0.12),
    "strong_post_pivot_pct": (0.08, 0.10, 0.12),
    "pbr_breakout_confirmation": (0.0, 0.02, 0.03, 0.04),
    "pbr_max_days_after_retest": (1, 2, 3),
    "stop_pct": (0.910, 0.923, 0.927, 0.934),
    "target_pct": (1.20, 1.24, 1.27, 1.30),
}

MARKTEN_PBR = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]


@dataclass(frozen=True)
class SystemSpec:
    name: str
    engine: str  # brt | rl
    baseline: dict[str, Any]
    plan: dict[str, tuple[Any, ...]]
    min_trades_symbol: int
    min_trades_universe: int
    min_trades_wf_train_symbol: int
    min_trades_wf_val_symbol: int
    min_trades_wf_train_universe: int
    min_trades_wf_val_universe: int
    daily_symbols: Callable[[], list[str]]


def _load_rl_symbols() -> list[str]:
    out: list[str] = []
    if not RL_UNIVERSE.is_file():
        return out
    for line in RL_UNIVERSE.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and not t.startswith("#"):
            out.append(t.upper())
    return out


def _load_mts_symbols() -> list[str]:
    from mts_universe import MTS_SYMBOLS

    return list(MTS_SYMBOLS)


SYSTEMS: dict[str, SystemSpec] = {
    "BRT": SystemSpec(
        "BRT", "brt", BRT_BASELINE, BRT_PLAN,
        min_trades_symbol=6, min_trades_universe=40,
        min_trades_wf_train_symbol=3, min_trades_wf_val_symbol=2,
        min_trades_wf_train_universe=15, min_trades_wf_val_universe=8,
        daily_symbols=lambda: list(BRT_SYMBOLS),
    ),
    "RL": SystemSpec(
        "RL", "rl", RL_BASELINE, RL_PLAN,
        min_trades_symbol=4, min_trades_universe=30,
        min_trades_wf_train_symbol=2, min_trades_wf_val_symbol=1,
        min_trades_wf_train_universe=12, min_trades_wf_val_universe=6,
        daily_symbols=_load_rl_symbols,
    ),
    "MTS": SystemSpec(
        "MTS", "brt", MTS_BASELINE, MTS_PLAN,
        min_trades_symbol=4, min_trades_universe=40,
        min_trades_wf_train_symbol=2, min_trades_wf_val_symbol=1,
        min_trades_wf_train_universe=15, min_trades_wf_val_universe=8,
        daily_symbols=_load_mts_symbols,
    ),
    "YH": SystemSpec(
        "YH", "brt", YH_BASELINE, YH_PLAN,
        min_trades_symbol=3, min_trades_universe=20,
        min_trades_wf_train_symbol=2, min_trades_wf_val_symbol=1,
        min_trades_wf_train_universe=10, min_trades_wf_val_universe=5,
        daily_symbols=lambda: list(YH_SYMBOLS),
    ),
    "VEC": SystemSpec(
        "VEC", "brt", VEC_BASELINE, VEC_PLAN,
        min_trades_symbol=3, min_trades_universe=25,
        min_trades_wf_train_symbol=2, min_trades_wf_val_symbol=1,
        min_trades_wf_train_universe=12, min_trades_wf_val_universe=6,
        daily_symbols=lambda: list(BRT_SYMBOLS),
    ),
    "PBR": SystemSpec(
        "PBR", "brt", PBR_BASELINE, PBR_PLAN,
        min_trades_symbol=2, min_trades_universe=15,
        min_trades_wf_train_symbol=1, min_trades_wf_val_symbol=1,
        min_trades_wf_train_universe=8, min_trades_wf_val_universe=4,
        daily_symbols=lambda: list(MARKTEN_PBR),
    ),
}


def get_system_spec(system: str) -> SystemSpec:
    key = str(system).strip().upper()
    if key not in SYSTEMS:
        raise ValueError(f"Unknown system {system!r}; expected one of {sorted(SYSTEMS)}")
    return SYSTEMS[key]


def merge_baseline(spec: SystemSpec, override: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(spec.baseline)
    if override:
        out.update(override)
    return out


def brt_cfg_from_dict(d: dict[str, Any], system: str = "BRT") -> BRTConfig:
    base = dict(d)
    if str(system).upper() == "MTS":
        merged = dict(mts_sheet_parity_overrides())
        merged.update(base)
        base = merged
    valid = {f.name for f in fields(BRTConfig)}
    filtered = {k: v for k, v in base.items() if k in valid}
    return BRTConfig(**filtered)


def rl_cfg_from_dict(d: dict[str, Any]) -> RLConfig:
    base = {f.name: getattr(RLConfig(), f.name) for f in fields(RLConfig)}
    key_map = {
        "rl_expansion_lookback_days": "expansion_lookback_days",
        "rl_peak_threshold_max": "peak_threshold_max",
        "rl_spy_inclusion": "spy_inclusion",
        "rl_avg_vol_days": "avg_vol_days",
        "rl_vol_pct_threshold": "vol_pct_threshold",
    }
    for k, v in d.items():
        if k in key_map:
            base[key_map[k]] = v
        elif k.startswith("rl_"):
            base[k] = v
        elif hasattr(RLConfig, k):
            base[k] = v
    return RLConfig(**base)


def is_brt_engine(system: str) -> bool:
    return get_system_spec(system).engine == "brt"


def load_all_data_symbols(data_dir: Path) -> list[str]:
    skip = {"SPY"}
    out: list[str] = []
    for p in sorted(data_dir.glob("*.csv")):
        sym = p.stem.strip().upper()
        if sym and sym not in skip:
            out.append(sym)
    return out


def symbols_for_system(
    system: str,
    *,
    universe: str,
    data_dir: Path,
    symbol_filter: set[str] | None = None,
) -> list[str]:
    spec = get_system_spec(system)
    u = str(universe).strip().lower()
    if u == "all":
        syms = load_all_data_symbols(data_dir)
    elif u == "daily":
        syms = spec.daily_symbols()
    else:
        raise ValueError(f"Unknown universe {universe!r}")
    if symbol_filter:
        syms = [s for s in syms if s.upper() in symbol_filter]
    return syms


UNIVERSE_SYMBOL = "*UNIVERSE*"
