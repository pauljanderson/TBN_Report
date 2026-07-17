"""Post-run BRT-style reports for Python Rocket Launcher (rl_mode) runs."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def write_rl_post_reports(
    *,
    cfg: Any,
    tickers: dict[str, pd.DataFrame],
    output_dir: Path,
    ts: str,
    closed_path: Path,
    open_path: Optional[Path] = None,
    drive_link: str = "",
    cash_per_trade: Optional[float] = None,
) -> None:
    """Emit Summary, EquityCurve/Meta, Correlation/Pairs, underwater, and Audit for an RL run."""
    if not closed_path.is_file():
        print(f"[RL reports] Closed CSV not found: {closed_path}; skip post-reports.", file=sys.stderr)
        return

    try:
        from rl_emit_brt_mirror import (
            _rl_closed_row_to_trade,
            _rl_open_row_to_trade,
            _strip_df_columns,
        )
    except ImportError:
        from stock_analysis.rl_emit_brt_mirror import (  # type: ignore[no-redef]
            _rl_closed_row_to_trade,
            _rl_open_row_to_trade,
            _strip_df_columns,
        )

    try:
        from rocket_brt import (
            HAS_EQUITY_METRICS,
            _apply_report_dollar_scale_to_trades,
            _compute_equity_metrics,
            _effective_margin_utilization,
            _enrich_post_entry_gain_hit,
            _enrich_trades_entry_indicators,
            _generate_underwater_report,
            _normalize_aggressive_sell,
            _write_brt_equity_canonical_outputs,
            compute_metrics,
            write_brt_audit_report,
            write_brt_summary,
        )
    except ImportError:
        from stock_analysis.rocket_brt import (  # type: ignore[no-redef]
            HAS_EQUITY_METRICS,
            _apply_report_dollar_scale_to_trades,
            _compute_equity_metrics,
            _effective_margin_utilization,
            _enrich_post_entry_gain_hit,
            _enrich_trades_entry_indicators,
            _generate_underwater_report,
            _normalize_aggressive_sell,
            _write_brt_equity_canonical_outputs,
            compute_metrics,
            write_brt_audit_report,
            write_brt_summary,
        )

    file_prefix = "RL"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    closed_df = _strip_df_columns(pd.read_csv(closed_path, low_memory=False))
    closed = []
    for _, row in closed_df.iterrows():
        try:
            closed.append(_rl_closed_row_to_trade(row))
        except Exception as e:
            print(f"[RL reports] skip closed row: {e}", file=sys.stderr)

    open_list = []
    if open_path and open_path.is_file():
        open_df = _strip_df_columns(pd.read_csv(open_path, low_memory=False))
        for _, row in open_df.iterrows():
            try:
                open_list.append(_rl_open_row_to_trade(row))
            except Exception as e:
                print(f"[RL reports] skip open row: {e}", file=sys.stderr)

    per_trade = float(
        cash_per_trade
        if cash_per_trade is not None and cash_per_trade > 0
        else getattr(cfg, "rl_cash", None) or getattr(cfg, "brt_cash", 47500.0)
    )
    report_cfg = replace(cfg, brt_cash=per_trade) if hasattr(cfg, "brt_cash") else cfg

    for t in closed:
        if t.entry_price > 0 and per_trade > 0:
            t.pnl_dollars = (per_trade / t.entry_price) * (t.exit_price - t.entry_price)
    for t in open_list:
        if t.entry_price > 0 and per_trade > 0:
            cur = t.entry_price * (1.0 + t.pnl_pct / 100.0)
            t.pnl_dollars = (per_trade / t.entry_price) * (cur - t.entry_price)

    if closed:
        _apply_report_dollar_scale_to_trades(closed, open_list, report_cfg)
    if tickers and (closed or open_list):
        _enrich_post_entry_gain_hit(closed + open_list, tickers, report_cfg)
        _enrich_trades_entry_indicators(closed + open_list, tickers, report_cfg)

    if closed:
        summary_path = out_dir / f"{file_prefix}_Summary_{ts}.csv"
        write_brt_summary(closed, str(summary_path))
        print(f"[RL reports] Wrote {summary_path.name}")

    metrics = dict(compute_metrics(closed, report_cfg))

    do_equity = (
        bool(getattr(report_cfg, "compute_equity_metrics", True))
        and HAS_EQUITY_METRICS
        and closed
        and tickers
        and _compute_equity_metrics is not None
    )
    if do_equity:
        try:
            equity = _compute_equity_metrics(
                closed,
                open_list,
                tickers,
                report_cfg.brt_cash,
                initial_capital=report_cfg.initial_capital,
                aggressive=report_cfg.aggressive,
                aggressive_margin_interest=report_cfg.aggressive_margin_interest,
                aggressive_max_multiple=report_cfg.aggressive_max_multiple,
                aggressive_avg_positions=(
                    report_cfg.aggressive_avg_positions if report_cfg.aggressive_avg_positions > 0 else None
                ),
                aggressive_sizing_equity_cap=report_cfg.aggressive_sizing_equity_cap,
                margin_utilization=_effective_margin_utilization(report_cfg),
                aggressive_sell=_normalize_aggressive_sell(getattr(report_cfg, "aggressive_sell", "false")),
                skip_passive_mtm_for_aggressive=bool(
                    getattr(report_cfg, "equity_fast_aggressive", False) and report_cfg.aggressive
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
                    metrics["DD_Per_Trade"] = f"{(pct_val / len(closed)):.4f}" if closed else "N/A"
                except (ValueError, TypeError):
                    metrics["DD_Per_Trade"] = "N/A"
            else:
                metrics["DD_Per_Trade"] = "N/A"
            _write_brt_equity_canonical_outputs(out_dir, ts, equity, file_prefix)
            if _generate_underwater_report is not None:
                eq_dates = equity.get("equity_dates") or []
                eq_vals = equity.get("equity_values") or []
                if eq_dates and eq_vals and len(eq_dates) == len(eq_vals):
                    try:
                        uw_df = pd.DataFrame({"Date": eq_dates, "Equity": eq_vals})
                        uw_stats = _generate_underwater_report(
                            uw_df, ts, output_dir=str(out_dir), prefix=file_prefix
                        )
                        if isinstance(uw_stats, dict):
                            metrics["Avg_Days_Underwater"] = uw_stats.get("avg_days_underwater", 0)
                            metrics["P90_Days_Underwater"] = uw_stats.get("p90_days_underwater", 0)
                        print(f"[RL reports] Wrote {file_prefix}_underwater_{ts}.csv")
                    except Exception as uw_err:
                        print(f"[RL reports] Underwater report failed: {uw_err}", file=sys.stderr)
        except Exception as e:
            print(f"[RL reports] Equity metrics failed: {e}", file=sys.stderr)

    write_brt_audit_report(
        report_cfg,
        metrics,
        str(out_dir),
        ts,
        drive_link=drive_link,
        file_prefix=file_prefix,
    )
    print(f"[RL reports] Wrote {file_prefix}_Audit_Report_{ts}.csv")

    try:
        from correlate_rl_closed import run_rl_correlation_report
    except ImportError:
        from stock_analysis.correlate_rl_closed import run_rl_correlation_report  # type: ignore[no-redef]

    rl_corr = out_dir / f"RL_Correlation_{ts}.csv"
    try:
        run_rl_correlation_report(str(closed_path), str(rl_corr))
        if rl_corr.exists():
            print(f"[RL reports] Wrote {rl_corr.name}")
            pairs_path = rl_corr.with_name(rl_corr.name.replace("_Correlation_", "_Correlation_Pairs_", 1))
            if pairs_path.exists():
                print(f"[RL reports] Wrote {pairs_path.name}")
    except Exception as e:
        print(f"[RL reports] Correlation report skipped: {e}", file=sys.stderr)
