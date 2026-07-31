"""Backward-compatible RL analysis API — implementation in ``rocket_post_analysis``."""
from __future__ import annotations

try:
    from rocket_post_analysis import (  # noqa: F401
        FitResult,
        HAS_MATPLOTLIB,
        ImproveHint,
        _collect_improve_hints,
        _col,
        _fnum,
        _iso_dash,
        _truthy,
        _ymd8,
        assess_symbol_fit,
        enrich_closed_csv_with_one_liners,
        enrich_summary_csv_with_fit,
        format_trade_one_liner,
        plot_rl_symbol_chart,
        write_analysis_artifacts,
        write_improve_hints,
        write_rl_analysis_artifacts,
        write_rl_charts,
        write_system_charts,
    )
except ImportError:
    from stock_analysis.rocket_post_analysis import (  # type: ignore  # noqa: F401
        FitResult,
        HAS_MATPLOTLIB,
        ImproveHint,
        _collect_improve_hints,
        _col,
        _fnum,
        _iso_dash,
        _truthy,
        _ymd8,
        assess_symbol_fit,
        enrich_closed_csv_with_one_liners,
        enrich_summary_csv_with_fit,
        format_trade_one_liner,
        plot_rl_symbol_chart,
        write_analysis_artifacts,
        write_improve_hints,
        write_rl_analysis_artifacts,
        write_rl_charts,
        write_system_charts,
    )
