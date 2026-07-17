"""
Per-symbol and universe BRT / RL / MTS / YH parameter optimizer.

Modes (--optimize-mode):
  per-symbol   — one param set per ticker (default)
  universe     — one param set per system across DailyRun symbols (pooled trades)
  hierarchical — universe WF first, then per-symbol tuning from global baseline (less overfit)

Outputs:
  Per_Symbol_Optimizer_Results_<ts>.csv
  Universe_Optimized_Settings_<ts>.json  (universe / hierarchical)
  Per_Symbol_Optimized_Settings_Approved_Latest.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from optimizer_systems import (  # noqa: E402
    BRT_BASELINE,
    BRT_PLAN,
    BRT_SYMBOLS,
    RL_BASELINE,
    RL_PLAN,
    UNIVERSE_SYMBOL,
    SystemSpec,
    brt_cfg_from_dict,
    get_system_spec,
    is_brt_engine,
    load_all_data_symbols,
    merge_baseline,
    rl_cfg_from_dict,
    symbols_for_system,
)

from rocket_brt import (  # noqa: E402
    BRTConfig,
    BRTTrade,
    HAS_EQUITY_METRICS,
    _apply_report_dollar_scale_to_trades,
    _apply_spy_ind_diff_at_entry,
    _compute_equity_metrics,
    _get_spy_ind_diff_lookup,
    _load_benchmark_local,
    _min_bars_required_for_cfg,
    build_level3_for_cfg,
    compute_market_structure,
    compute_metrics,
    compute_pivots,
    load_all_tickers,
    run_brt_backtest,
)
from rocket_rl import RLClosedRow, RLOpenRow, run_rl_backtest_batch  # noqa: E402
from rocket_rl_config import RLConfig  # noqa: E402
from walkforward import (  # noqa: E402
    WalkForwardFold,
    build_rolling_folds,
    median_oos_score,
    median_params_across_folds,
    norm_date_str,
)

DATA_DIR = REPO_ROOT / "data" / "newdata" / "data"
RL_UNIVERSE = REPO_ROOT / "data" / "rl_gold_universe.txt"

MAX_DD_PCT = 35.0

W_PROFIT_PER_CAP_DAY = 15
W_TOTAL_PROFIT = 15
W_MAX_DRAWDOWN = 15
W_PROFIT_FACTOR = 15
W_EXPECTANCY = 15
W_WIN_LOSS_RATIO = 10
W_LOSING_STREAK = 10
W_P90_DAYS = 5


def _min_trades_for(system: str, *, universe: bool = False, wf_train: bool = False, wf_val: bool = False) -> int:
    spec = get_system_spec(system)
    if universe:
        if wf_train:
            return spec.min_trades_wf_train_universe
        if wf_val:
            return spec.min_trades_wf_val_universe
        return spec.min_trades_universe
    if wf_train:
        return spec.min_trades_wf_train_symbol
    if wf_val:
        return spec.min_trades_wf_val_symbol
    return spec.min_trades_symbol


def _wf_label(system: str, sym: str, *, universe: bool, universe_symbols_n: int = 0) -> str:
    if universe or sym == UNIVERSE_SYMBOL:
        suffix = f" ({universe_symbols_n} syms)" if universe_symbols_n else ""
        return f"{system} *UNIVERSE*{suffix}"
    return f"{system} {sym}"


def _log_progress(msg: str) -> None:
    print(msg, flush=True)


def _run_parallel_tasks(
    tasks: list[tuple],
    workers: int,
    *,
    on_done: Any | None = None,
) -> list[dict[str, Any]]:
    """Run optimize_one_symbol on tasks; use ProcessPoolExecutor when workers > 1."""
    if not tasks:
        return []
    pool_workers = max(1, min(workers, len(tasks)))
    results: list[dict[str, Any]] = []
    total = len(tasks)

    if pool_workers == 1:
        for i, task in enumerate(tasks, 1):
            r = optimize_one_symbol(task)
            results.append(r)
            if on_done is not None:
                on_done(i, total, r)
        return results

    with ProcessPoolExecutor(max_workers=pool_workers) as ex:
        futures = {ex.submit(optimize_one_symbol, t): t for t in tasks}
        done = 0
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            results.append(r)
            if on_done is not None:
                on_done(done, total, r)
    return results


def _plan_for(system: str) -> dict[str, tuple[Any, ...]]:
    return dict(get_system_spec(system).plan)


def _default_baseline(system: str) -> dict[str, Any]:
    return dict(get_system_spec(system).baseline)


# Legacy names for any external imports
MIN_TRADES_BRT = _min_trades_for("BRT")
MIN_TRADES_RL = _min_trades_for("RL")
MIN_TRADES_WF_TRAIN_BRT = _min_trades_for("BRT", wf_train=True)
MIN_TRADES_WF_TRAIN_RL = _min_trades_for("RL", wf_train=True)
MIN_TRADES_WF_VAL_BRT = _min_trades_for("BRT", wf_val=True)
MIN_TRADES_WF_VAL_RL = _min_trades_for("RL", wf_val=True)


def _safe_num(x: Any) -> float:
    if x is None or x == "N/A" or (isinstance(x, str) and str(x).strip() == "N/A"):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _metrics_to_row(metrics: dict[str, Any]) -> dict[str, Any]:
    wins = int(metrics.get("Wins", 0))
    losses = int(metrics.get("Losses", 0))
    bes = int(metrics.get("BEs", 0))
    total_trades = wins + losses + bes
    win_loss_ratio = (wins / losses) if losses else (float(wins) if wins else 0.0)
    max_dd_raw = metrics.get("Max_Drawdown", "N/A")
    max_dd = _safe_num(max_dd_raw) if max_dd_raw not in (None, "N/A") else 0.0
    return {
        "Total_PNL": _safe_num(metrics.get("Total_PNL", 0)),
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Total_Trades": total_trades,
        "Profit_Factor": _safe_num(metrics.get("Profit_Factor", 0)),
        "Expectancy": _safe_num(metrics.get("Expectancy", 0)),
        "Avg_PNL_Pct": _safe_num(metrics.get("Avg_PNL_Pct", 0)),
        "Avg_Days_Held": _safe_num(metrics.get("Avg_Days_Held", 0)),
        "P90_Days": _safe_num(metrics.get("P90_Days", 0)),
        "Capital_Days": int(metrics.get("Capital_Days", 0)),
        "Profit_Per_Capital_Day": _safe_num(metrics.get("Profit_Per_Capital_Day", 0)),
        "Ann_ROR": _safe_num(metrics.get("Annualized_ROR", 0)),
        "Max_DD": max_dd,
        "Losing_Streak": int(metrics.get("Losing_Streak", 0)),
        "Win_Loss_Ratio": win_loss_ratio,
    }


def _win_loss_ratio(row: dict[str, Any]) -> float:
    wins = int(row.get("Wins", 0))
    losses = int(row.get("Losses", 0))
    if losses <= 0:
        return 10.0 if wins > 0 else 1.0
    return wins / losses


def _effective_min_trades(baseline_row: dict[str, Any], min_trades: int) -> int:
    """Per-symbol trade gate: don't require more trades than the symbol's baseline produced."""
    baseline_trades = int(baseline_row.get("Total_Trades", 0))
    if baseline_trades <= 0:
        return min_trades
    return min(min_trades, baseline_trades)


def calculate_score(row: dict[str, Any], baseline_row: dict[str, Any], min_trades: int) -> float:
    gate = _effective_min_trades(baseline_row, min_trades)
    if int(row.get("Total_Trades", 0)) < gate:
        return 0.0
    if _safe_num(row.get("Max_DD", 0)) > MAX_DD_PCT:
        return 0.0
    if baseline_row is None:
        return 0.0

    def ratio_higher(v: float, b: float) -> float:
        if b == 0:
            return 1.0 if v == 0 else (2.0 if v > 0 else 0.0)
        return v / b

    def ratio_lower(v: float, b: float) -> float:
        if v == 0:
            return 2.0 if b > 0 else 1.0
        if b == 0:
            return 1.0
        return b / v

    v_ppcd = _safe_num(row.get("Profit_Per_Capital_Day", 0))
    b_ppcd = _safe_num(baseline_row.get("Profit_Per_Capital_Day", 0))
    v_pnl = _safe_num(row.get("Total_PNL", 0))
    b_pnl = _safe_num(baseline_row.get("Total_PNL", 0))
    v_dd = _safe_num(row.get("Max_DD", 0))
    b_dd = _safe_num(baseline_row.get("Max_DD", 0))
    v_pf = _safe_num(row.get("Profit_Factor", 0))
    b_pf = _safe_num(baseline_row.get("Profit_Factor", 0))
    v_exp = _safe_num(row.get("Expectancy", 0))
    b_exp = _safe_num(baseline_row.get("Expectancy", 0))
    v_wlr = _win_loss_ratio(row)
    b_wlr = _win_loss_ratio(baseline_row)
    v_streak = int(row.get("Losing_Streak", 0))
    b_streak = int(baseline_row.get("Losing_Streak", 0))
    v_p90 = _safe_num(row.get("P90_Days", 0))
    b_p90 = _safe_num(baseline_row.get("P90_Days", 0))
    r_dd = ratio_lower(v_dd, b_dd) if (v_dd > 0 and b_dd > 0) else 1.0

    s = 0.0
    s += ratio_higher(v_ppcd, b_ppcd) * (W_PROFIT_PER_CAP_DAY / 100)
    s += ratio_higher(v_pnl, b_pnl) * (W_TOTAL_PROFIT / 100)
    s += r_dd * (W_MAX_DRAWDOWN / 100)
    s += ratio_higher(v_pf, b_pf) * (W_PROFIT_FACTOR / 100)
    s += ratio_higher(v_exp, b_exp) * (W_EXPECTANCY / 100)
    s += ratio_higher(v_wlr, b_wlr) * (W_WIN_LOSS_RATIO / 100)
    s += ratio_lower(float(v_streak), float(b_streak)) * (W_LOSING_STREAK / 100)
    s += ratio_lower(v_p90, b_p90) * (W_P90_DAYS / 100)
    return s * 100


def _trial_rank(row: dict[str, Any], score: float) -> tuple:
    """Pick best trial: score first, then profit/day, PnL, expectancy."""
    return (
        score,
        _safe_num(row.get("Profit_Per_Capital_Day", 0)),
        _safe_num(row.get("Total_PNL", 0)),
        _safe_num(row.get("Expectancy", 0)),
        -_safe_num(row.get("Max_DD", 0)),
    )


def _pick_batch_winner(
    batch: list[tuple[Any, dict[str, Any], float, dict[str, Any]]],
) -> tuple[Any, dict[str, Any], float, dict[str, Any]]:
    return max(batch, key=lambda item: _trial_rank(item[1], item[2]))


def _cfg_value_equal(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return False
    return a == b


def _brt_cfg_from_dict(d: dict[str, Any], system: str = "BRT") -> BRTConfig:
    return brt_cfg_from_dict(d, system)


def _rl_cfg_from_dict(d: dict[str, Any]) -> RLConfig:
    return rl_cfg_from_dict(d)


def run_brt_symbol(sym: str, df: pd.DataFrame, cfg: BRTConfig, benchmark_df: pd.DataFrame | None, spy_lookup) -> dict[str, Any]:
    closed, opens = run_brt_symbol_trades(sym, df, cfg, benchmark_df, spy_lookup)
    metrics = dict(compute_metrics(closed, cfg))
    if cfg.compute_equity_metrics and HAS_EQUITY_METRICS and closed and _compute_equity_metrics:
        try:
            tickers = {sym: df}
            equity = _compute_equity_metrics(
                closed, opens, tickers, cfg.brt_cash,
                initial_capital=cfg.initial_capital, aggressive=False,
            )
            metrics["Max_Drawdown"] = equity["Max_Drawdown"]
        except Exception:
            pass
    return metrics


def run_brt_symbol_trades(
    sym: str,
    df: pd.DataFrame,
    cfg: BRTConfig,
    benchmark_df: pd.DataFrame | None,
    spy_lookup,
) -> tuple[list[BRTTrade], list[BRTTrade]]:
    pivot_high, pivot_low, ph_price, pl_price = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
    level3 = build_level3_for_cfg(df, cfg, pivot_high, pivot_low, ph_price, pl_price, debug_symbol=sym)
    closed, open_trade, _, _, _, _ = run_brt_backtest(
        sym, df, cfg, ph_price, pl_price, struct, level3, benchmark_df=benchmark_df,
    )
    _apply_spy_ind_diff_at_entry(closed, open_trade, [], spy_lookup)
    opens = [open_trade] if open_trade is not None else []
    if closed:
        _apply_report_dollar_scale_to_trades(closed, opens, cfg)
    return closed, opens


def _closed_to_trade(row: RLClosedRow, cash: float) -> BRTTrade:
    dollars = (cash / row.entry_price) * (row.exit_price - row.entry_price) if row.entry_price > 0 else 0.0
    return BRTTrade(
        symbol=row.symbol, date_opened=row.entry_iso, entry_price=row.entry_price,
        stop_price=row.original_stop, target_price=row.original_target,
        date_closed=row.exit_iso, exit_price=row.exit_price, exit_type=row.exit_type,
        days_held=row.hold_days, pnl_pct=row.pnl_pct, pnl_dollars=dollars, max_price=row.max_price,
    )


def _open_to_trade(row: RLOpenRow, cash: float) -> BRTTrade:
    cur = row.current_price if row.current_price > 0 else row.entry_price * (1.0 + row.pnl_pct / 100.0)
    dollars = (cash / row.entry_price) * (cur - row.entry_price) if row.entry_price > 0 else 0.0
    return BRTTrade(
        symbol=row.symbol, date_opened=row.entry_iso, entry_price=row.entry_price,
        stop_price=row.stop, target_price=row.target, pnl_pct=row.pnl_pct,
        pnl_dollars=dollars, max_price=row.entry_price,
    )


def run_rl_symbol(sym: str, df: pd.DataFrame, cfg: RLConfig, spy_df: pd.DataFrame | None) -> dict[str, Any]:
    trades, opens = run_rl_symbol_trades(sym, df, cfg, spy_df)
    brt_cfg = BRTConfig(brt_cash=cfg.rl_cash, compute_equity_metrics=True)
    metrics = dict(compute_metrics(trades, brt_cfg))
    if HAS_EQUITY_METRICS and trades and _compute_equity_metrics:
        try:
            equity = _compute_equity_metrics(
                trades, opens, {sym: df}, cfg.rl_cash,
                initial_capital=brt_cfg.initial_capital, aggressive=False,
            )
            metrics["Max_Drawdown"] = equity["Max_Drawdown"]
        except Exception:
            pass
    return metrics


def run_rl_symbol_trades(
    sym: str,
    df: pd.DataFrame,
    cfg: RLConfig,
    spy_df: pd.DataFrame | None,
) -> tuple[list[BRTTrade], list[BRTTrade]]:
    closed_rows, open_rows, _, _ = run_rl_backtest_batch(
        [sym], {sym: df}, cfg, spy_df=spy_df, workers=0, data_dir=DATA_DIR,
    )
    trades = [_closed_to_trade(r, cfg.rl_cash) for r in closed_rows]
    opens = [_open_to_trade(r, cfg.rl_cash) for r in open_rows]
    return trades, opens


def _effective_min_trades_window(
    baseline_row: dict[str, Any],
    default_min: int,
    *,
    floor: int = 1,
) -> int:
    """Window trade gate: cap by baseline trades in that window, never below floor."""
    baseline_trades = int(baseline_row.get("Total_Trades", 0))
    if baseline_trades <= 0:
        return max(floor, default_min)
    return max(floor, min(default_min, baseline_trades))


def filter_trades_by_entry_window(
    trades: list[BRTTrade],
    start: str,
    end: str,
) -> list[BRTTrade]:
    s, e = norm_date_str(start), norm_date_str(end)
    return [t for t in trades if s <= norm_date_str(t.date_opened) <= e]


def _metrics_cfg_for_system(system: str, cfg_dict: dict[str, Any]) -> BRTConfig:
    if is_brt_engine(system):
        return _brt_cfg_from_dict(cfg_dict, system)
    cash = float(cfg_dict.get("rl_cash", RL_BASELINE["rl_cash"]))
    return BRTConfig(brt_cash=cash, compute_equity_metrics=True)


def _load_tickers_for_symbols(data_dir: Path, symbols: list[str]) -> dict[str, pd.DataFrame]:
    tickers = load_all_tickers(str(data_dir), symbols_filter=set(symbols))
    return {s: tickers[s] for s in symbols if s in tickers and len(tickers[s]) >= 200}


def _run_symbol_trades(
    system: str,
    sym: str,
    cfg_dict: dict[str, Any],
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    spy_lookup,
    spy_df: pd.DataFrame | None,
) -> tuple[list[BRTTrade], list[BRTTrade]]:
    if is_brt_engine(system):
        return run_brt_symbol_trades(
            sym, df, _brt_cfg_from_dict(cfg_dict, system), benchmark_df, spy_lookup,
        )
    return run_rl_symbol_trades(sym, df, _rl_cfg_from_dict(cfg_dict), spy_df)


def _collect_trades_for_symbols(
    system: str,
    symbols: list[str],
    tickers: dict[str, pd.DataFrame],
    cfg_dict: dict[str, Any],
    benchmark_df: pd.DataFrame | None,
    spy_lookup,
    spy_df: pd.DataFrame | None,
    *,
    entry_start: str | None = None,
    entry_end: str | None = None,
) -> tuple[list[BRTTrade], list[BRTTrade], dict[str, pd.DataFrame]]:
    all_closed: list[BRTTrade] = []
    all_opens: list[BRTTrade] = []
    used_dfs: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = tickers.get(sym)
        if df is None:
            continue
        closed, opens = _run_symbol_trades(system, sym, cfg_dict, df, benchmark_df, spy_lookup, spy_df)
        if entry_start and entry_end:
            closed = filter_trades_by_entry_window(closed, entry_start, entry_end)
        all_closed.extend(closed)
        all_opens.extend(opens)
        used_dfs[sym] = df
    return all_closed, all_opens, used_dfs


def _metrics_from_trades(
    system: str,
    sym: str,
    cfg_dict: dict[str, Any],
    closed: list[BRTTrade],
    opens: list[BRTTrade],
    df: pd.DataFrame,
) -> dict[str, Any]:
    cfg = _metrics_cfg_for_system(system, cfg_dict)
    metrics = dict(compute_metrics(closed, cfg))
    if cfg.compute_equity_metrics and HAS_EQUITY_METRICS and closed and _compute_equity_metrics:
        try:
            equity = _compute_equity_metrics(
                closed, opens, {sym: df}, cfg.brt_cash,
                initial_capital=cfg.initial_capital, aggressive=False,
            )
            metrics["Max_Drawdown"] = equity["Max_Drawdown"]
        except Exception:
            pass
    return metrics


def _evaluate_cfg(
    system: str,
    sym: str,
    cfg_dict: dict[str, Any],
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    spy_lookup,
    spy_df: pd.DataFrame | None,
    *,
    entry_start: str | None = None,
    entry_end: str | None = None,
    symbols: list[str] | None = None,
    tickers: dict[str, pd.DataFrame] | None = None,
    min_trades_override: int | None = None,
) -> dict[str, Any]:
    universe_mode = symbols is not None and tickers is not None
    if universe_mode:
        closed, opens, used_dfs = _collect_trades_for_symbols(
            system, symbols or [], tickers or {}, cfg_dict, benchmark_df, spy_lookup, spy_df,
            entry_start=entry_start, entry_end=entry_end,
        )
        metrics = _metrics_from_trades(system, sym, cfg_dict, closed, opens, next(iter(used_dfs.values())) if used_dfs else df)
        min_trades = min_trades_override if min_trades_override is not None else _min_trades_for(system, universe=True, wf_train=bool(entry_start), wf_val=bool(entry_start))
    elif entry_start and entry_end:
        closed, opens = _run_symbol_trades(system, sym, cfg_dict, df, benchmark_df, spy_lookup, spy_df)
        closed = filter_trades_by_entry_window(closed, entry_start, entry_end)
        metrics = _metrics_from_trades(system, sym, cfg_dict, closed, opens, df)
        min_trades = min_trades_override if min_trades_override is not None else _min_trades_for(system, wf_train=True)
    elif is_brt_engine(system):
        metrics = run_brt_symbol(sym, df, _brt_cfg_from_dict(cfg_dict, system), benchmark_df, spy_lookup)
        min_trades = min_trades_override if min_trades_override is not None else _min_trades_for(system)
    else:
        metrics = run_rl_symbol(sym, df, _rl_cfg_from_dict(cfg_dict), spy_df)
        min_trades = min_trades_override if min_trades_override is not None else _min_trades_for(system)
    row = _metrics_to_row(metrics)
    row["min_trades_gate"] = min_trades
    return row


def _run_record(
    system: str,
    sym: str,
    cfg_dict: dict[str, Any],
    metrics_row: dict[str, Any],
    *,
    sweep_param: str,
    param_value: Any,
    run_kind: str,
    score: float,
    baseline_score: float,
    param_winner: bool = False,
    fold: str = "",
    window: str = "",
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "system": system,
        "symbol": sym,
        "fold": fold,
        "window": window,
        "run_kind": run_kind,
        "sweep_param": sweep_param,
        "param_value": param_value,
        "score": round(score, 4),
        "baseline_score": round(baseline_score, 4),
        "param_winner": param_winner,
    }
    rec.update(metrics_row)
    for k, v in cfg_dict.items():
        rec[f"cfg_{k}"] = v
    return rec


def _optimize_coordinate_descent(
    *,
    system: str,
    sym: str,
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None,
    spy_lookup,
    spy_df: pd.DataFrame | None,
    baseline: dict[str, Any],
    plan: dict[str, tuple[Any, ...]],
    cfg_keys: list[str],
    min_trades: int,
    entry_start: str | None = None,
    entry_end: str | None = None,
    fold: str = "",
    symbols: list[str] | None = None,
    tickers: dict[str, pd.DataFrame] | None = None,
    universe: bool = False,
) -> dict[str, Any]:
    """Coordinate-descent grid search; optional entry-date window for walk-forward train folds."""
    window_label = f"{entry_start}:{entry_end}" if entry_start and entry_end else "full"
    eval_kw: dict[str, Any] = {}
    if entry_start and entry_end:
        eval_kw = {"entry_start": entry_start, "entry_end": entry_end}
    if universe and symbols is not None and tickers is not None:
        eval_kw["symbols"] = symbols
        eval_kw["tickers"] = tickers
        eval_kw["min_trades_override"] = min_trades

    sims = 0
    all_runs: list[dict[str, Any]] = []
    best_params = dict(baseline)
    baseline_row = _evaluate_cfg(
        system, sym, best_params, df, benchmark_df, spy_lookup, spy_df, **eval_kw,
    )
    sims += 1
    trade_gate = _effective_min_trades_window(baseline_row, min_trades, floor=1)
    baseline_score = calculate_score(baseline_row, baseline_row, trade_gate)
    best_row = dict(baseline_row)
    best_score = baseline_score
    all_runs.append(
        _run_record(
            system, sym, best_params, baseline_row,
            sweep_param="_baseline_", param_value="",
            run_kind="baseline", score=baseline_score, baseline_score=baseline_score,
            fold=fold, window=window_label,
        )
    )

    changes: list[dict[str, Any]] = []

    for param_name, values in plan.items():
        if param_name not in best_params:
            best_params[param_name] = values[0]
        batch: list[tuple[Any, dict[str, Any], float, dict[str, Any]]] = []
        for v in values:
            trial = dict(best_params)
            trial[param_name] = v
            row = _evaluate_cfg(
                system, sym, trial, df, benchmark_df, spy_lookup, spy_df, **eval_kw,
            )
            sims += 1
            score = calculate_score(row, baseline_row, trade_gate)
            batch.append((v, row, score, trial))
            all_runs.append(
                _run_record(
                    system, sym, trial, row,
                    sweep_param=param_name, param_value=v,
                    run_kind="sweep", score=score, baseline_score=baseline_score,
                    fold=fold, window=window_label,
                )
            )
        winner_v, winner_row, winner_score, _winner_cfg = _pick_batch_winner(batch)
        for rec in all_runs:
            if (
                rec["symbol"] == sym
                and rec["system"] == system
                and rec.get("fold", "") == fold
                and rec["sweep_param"] == param_name
                and rec["param_value"] == winner_v
                and rec["run_kind"] == "sweep"
            ):
                rec["param_winner"] = True
        old_v = best_params.get(param_name)
        best_params[param_name] = winner_v
        if _trial_rank(winner_row, winner_score) > _trial_rank(best_row, best_score):
            best_row = winner_row
            best_score = winner_score
        if not _cfg_value_equal(baseline.get(param_name), winner_v):
            changes.append({
                "param": param_name,
                "from": baseline.get(param_name, old_v),
                "to": winner_v,
                "score": round(winner_score, 2),
                "pnl": round(_safe_num(winner_row.get("Total_PNL", 0)), 2),
            })

    final_cfg = {k: best_params[k] for k in cfg_keys if k in best_params}
    final_row = _evaluate_cfg(
        system, sym, final_cfg, df, benchmark_df, spy_lookup, spy_df, **eval_kw,
    )
    final_score = calculate_score(final_row, baseline_row, trade_gate)
    best_row = final_row
    best_score = final_score
    sims += 1

    all_runs.append(
        _run_record(
            system, sym,
            final_cfg,
            best_row,
            sweep_param="_final_", param_value="",
            run_kind="optimized_final", score=best_score, baseline_score=baseline_score,
            fold=fold, window=window_label,
        )
    )

    return {
        "optimized_params": final_cfg,
        "param_changes": changes,
        "all_runs": all_runs,
        "baseline_row": baseline_row,
        "optimized_row": best_row,
        "baseline_score": baseline_score,
        "optimized_score": best_score,
        "simulations": sims,
    }


def _resolve_baseline(system: str, wf_opts: dict[str, Any] | None) -> dict[str, Any]:
    spec = get_system_spec(system)
    override = (wf_opts or {}).get("baseline_override")
    return merge_baseline(spec, override if isinstance(override, dict) else None)


def _prepare_symbol_task(system: str, sym: str, data_dir: Path, wf_opts: dict[str, Any] | None):
    plan = _plan_for(system)
    baseline = _resolve_baseline(system, wf_opts)
    universe = sym == UNIVERSE_SYMBOL
    if universe:
        symbols = list((wf_opts or {}).get("universe_symbols") or [])
        tickers = _load_tickers_for_symbols(data_dir, symbols)
        if not tickers:
            return None
        ref_df = next(iter(tickers.values()))
        min_trades = _min_trades_for(system, universe=True)
    else:
        symbols = None
        tickers = None
        tickers_one = load_all_tickers(str(data_dir), symbols_filter={sym})
        ref_df = tickers_one.get(sym)
        if ref_df is None or len(ref_df) < 200:
            return None
        min_trades = _min_trades_for(system)
    cfg_keys = sorted(set(list(baseline.keys()) + list(plan.keys())))
    benchmark_df = _load_benchmark_local(data_dir)
    spy_lookup = (
        _get_spy_ind_diff_lookup(benchmark_df, _brt_cfg_from_dict(baseline, system))
        if benchmark_df is not None and is_brt_engine(system)
        else None
    )
    spy_df = benchmark_df
    return {
        "plan": plan,
        "baseline": baseline,
        "cfg_keys": cfg_keys,
        "min_trades": min_trades,
        "df": ref_df,
        "benchmark_df": benchmark_df,
        "spy_lookup": spy_lookup,
        "spy_df": spy_df,
        "symbols": symbols,
        "tickers": tickers,
        "universe": universe,
    }


def optimize_one_symbol(task: tuple) -> dict[str, Any]:
    """Worker: optimize one symbol or universe (full-sample in-sample)."""
    system, sym, data_dir_str, wf_opts = (task + (None,))[:4]
    wf_opts = dict(wf_opts or {})
    if str(wf_opts.get("wf_mode", "")).lower() == "rolling" or wf_opts.get("train_years"):
        return optimize_one_symbol_wf(task)

    data_dir = Path(data_dir_str)
    ctx = _prepare_symbol_task(system, sym, data_dir, wf_opts)
    if ctx is None:
        return {"system": system, "symbol": sym, "status": "skip_no_data", "simulations": 0, "all_runs": []}

    t0 = time.time()
    opt = _optimize_coordinate_descent(
        system=system,
        sym=sym,
        df=ctx["df"],
        benchmark_df=ctx["benchmark_df"],
        spy_lookup=ctx["spy_lookup"],
        spy_df=ctx["spy_df"],
        baseline=ctx["baseline"],
        plan=ctx["plan"],
        cfg_keys=ctx["cfg_keys"],
        min_trades=ctx["min_trades"],
        symbols=ctx["symbols"],
        tickers=ctx["tickers"],
        universe=ctx["universe"],
    )
    baseline_row = opt["baseline_row"]
    best_row = opt["optimized_row"]
    best_score = opt["optimized_score"]
    baseline_score = opt["baseline_score"]
    best_params = opt["optimized_params"]
    changes = opt["param_changes"]
    all_runs = opt["all_runs"]
    sims = opt["simulations"]

    elapsed = time.time() - t0
    baseline_pnl = _safe_num(baseline_row.get("Total_PNL", 0))
    best_pnl = _safe_num(best_row.get("Total_PNL", 0))
    pnl_delta = best_pnl - baseline_pnl
    pnl_pct_delta = (pnl_delta / abs(baseline_pnl) * 100) if baseline_pnl != 0 else (100.0 if best_pnl > 0 else 0.0)

    return {
        "system": system,
        "symbol": sym,
        "status": "ok" if int(baseline_row.get("Total_Trades", 0)) >= ctx["min_trades"] else "low_trades",
        "optimize_scope": "universe" if ctx["universe"] else "per_symbol",
        "baseline_source": (wf_opts or {}).get("baseline_source", "default"),
        "universe_symbols_n": len(ctx["symbols"] or []) if ctx["universe"] else 0,
        "wf_mode": "none",
        "simulations": sims,
        "elapsed_sec": round(elapsed, 1),
        "baseline_trades": int(baseline_row.get("Total_Trades", 0)),
        "baseline_pnl": round(baseline_pnl, 2),
        "baseline_score": round(baseline_score, 2),
        "baseline_pf": round(_safe_num(baseline_row.get("Profit_Factor", 0)), 3),
        "optimized_trades": int(best_row.get("Total_Trades", 0)),
        "optimized_pnl": round(best_pnl, 2),
        "optimized_score": round(best_score, 2),
        "optimized_pf": round(_safe_num(best_row.get("Profit_Factor", 0)), 3),
        "pnl_improvement": round(pnl_delta, 2),
        "pnl_improvement_pct": round(pnl_pct_delta, 2),
        "score_improvement": round(best_score - baseline_score, 2),
        "param_changes": changes,
        "optimized_params": best_params,
        "baseline_params": ctx["baseline"],
        "all_runs": all_runs,
        "wf_folds": [],
    }


def optimize_one_symbol_wf(task: tuple) -> dict[str, Any]:
    """Rolling walk-forward: optimize per train fold, adopt median params, report median OOS."""
    system, sym, data_dir_str, wf_opts = task
    wf_opts = dict(wf_opts or {})
    data_dir = Path(data_dir_str)
    ctx = _prepare_symbol_task(system, sym, data_dir, wf_opts)
    if ctx is None:
        return {"system": system, "symbol": sym, "status": "skip_no_data", "simulations": 0, "all_runs": [], "wf_mode": "rolling"}

    df = ctx["df"]
    plan = ctx["plan"]
    baseline = ctx["baseline"]
    cfg_keys = ctx["cfg_keys"]
    universe = ctx["universe"]
    min_trades_train = int(
        wf_opts.get("min_trades_train", _min_trades_for(system, universe=universe, wf_train=True))
    )
    min_trades_val = int(
        wf_opts.get("min_trades_val", _min_trades_for(system, universe=universe, wf_val=True))
    )

    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)

    folds = build_rolling_folds(
        df.index.min(),
        df.index.max(),
        train_years=int(wf_opts.get("train_years", 3)),
        test_years=int(wf_opts.get("test_years", 1)),
        step_years=int(wf_opts.get("step_years", 1)),
        wf_start=wf_opts.get("wf_start") or None,
        wf_end=wf_opts.get("wf_end") or None,
    )
    if not folds:
        return {
            "system": system,
            "symbol": sym,
            "status": "skip_no_folds",
            "wf_mode": "rolling",
            "simulations": 0,
            "all_runs": [],
            "wf_folds": [],
        }

    benchmark_df = ctx["benchmark_df"]
    spy_lookup = ctx["spy_lookup"]
    spy_df = ctx["spy_df"]
    eval_extra: dict[str, Any] = {}
    if universe:
        eval_extra = {
            "symbols": ctx["symbols"],
            "tickers": ctx["tickers"],
            "min_trades_override": min_trades_val,
        }

    label = _wf_label(
        system,
        sym,
        universe=universe,
        universe_symbols_n=len(ctx["symbols"] or []),
    )
    n_folds = len(folds)
    _log_progress(f"  [WF start] {label}: {n_folds} folds")

    t0 = time.time()
    all_runs: list[dict[str, Any]] = []
    fold_summaries: list[dict[str, Any]] = []
    fold_param_dicts: list[dict[str, Any]] = []
    sims = 0

    for fi, fold in enumerate(folds, 1):
        opt = _optimize_coordinate_descent(
            system=system,
            sym=sym,
            df=df,
            benchmark_df=benchmark_df,
            spy_lookup=spy_lookup,
            spy_df=spy_df,
            baseline=baseline,
            plan=plan,
            cfg_keys=cfg_keys,
            min_trades=min_trades_train,
            entry_start=fold.train_start,
            entry_end=fold.train_end,
            fold=fold.name,
            symbols=ctx["symbols"],
            tickers=ctx["tickers"],
            universe=universe,
        )
        sims += int(opt["simulations"])
        all_runs.extend(opt["all_runs"])

        fold_train_baseline = opt["baseline_row"]
        fold_train_opt = opt["optimized_row"]
        fold_cfg = opt["optimized_params"]

        val_baseline_row = _evaluate_cfg(
            system, sym, baseline, df, benchmark_df, spy_lookup, spy_df,
            entry_start=fold.val_start, entry_end=fold.val_end, **eval_extra,
        )
        val_opt_row = _evaluate_cfg(
            system, sym, fold_cfg, df, benchmark_df, spy_lookup, spy_df,
            entry_start=fold.val_start, entry_end=fold.val_end, **eval_extra,
        )
        sims += 2

        val_gate = _effective_min_trades_window(val_baseline_row, min_trades_val, floor=1)
        val_baseline_score = calculate_score(val_baseline_row, val_baseline_row, val_gate)
        val_opt_score = calculate_score(val_opt_row, val_baseline_row, val_gate)

        fold_summaries.append({
            "fold": fold.name,
            "train_start": fold.train_start,
            "train_end": fold.train_end,
            "val_start": fold.val_start,
            "val_end": fold.val_end,
            "train_baseline_pnl": round(_safe_num(fold_train_baseline.get("Total_PNL", 0)), 2),
            "train_opt_pnl": round(_safe_num(fold_train_opt.get("Total_PNL", 0)), 2),
            "train_baseline_score": round(opt["baseline_score"], 2),
            "train_opt_score": round(opt["optimized_score"], 2),
            "val_baseline_pnl": round(_safe_num(val_baseline_row.get("Total_PNL", 0)), 2),
            "val_opt_pnl": round(_safe_num(val_opt_row.get("Total_PNL", 0)), 2),
            "val_baseline_score": round(val_baseline_score, 2),
            "val_opt_score": round(val_opt_score, 2),
            "val_baseline_trades": int(val_baseline_row.get("Total_Trades", 0)),
            "val_opt_trades": int(val_opt_row.get("Total_Trades", 0)),
            "fold_params": fold_cfg,
            "param_changes_n": len(opt["param_changes"]),
        })
        fold_param_dicts.append(fold_cfg)
        _log_progress(
            f"  [WF {fi}/{n_folds}] {label} {fold.name} "
            f"train={opt['optimized_score']:.1f}/{opt['baseline_score']:.1f} "
            f"val_pnl={_safe_num(val_opt_row.get('Total_PNL', 0)):.0f} "
            f"sims={sims} t={time.time() - t0:.0f}s"
        )

    median_params = median_params_across_folds(fold_param_dicts, baseline, list(plan.keys()))

    oos_baseline_scores: list[float] = []
    oos_median_scores: list[float] = []
    oos_baseline_pnls: list[float] = []
    oos_median_pnls: list[float] = []

    for fold in folds:
        val_baseline_row = _evaluate_cfg(
            system, sym, baseline, df, benchmark_df, spy_lookup, spy_df,
            entry_start=fold.val_start, entry_end=fold.val_end, **eval_extra,
        )
        val_median_row = _evaluate_cfg(
            system, sym, median_params, df, benchmark_df, spy_lookup, spy_df,
            entry_start=fold.val_start, entry_end=fold.val_end, **eval_extra,
        )
        sims += 2
        val_gate = _effective_min_trades_window(val_baseline_row, min_trades_val, floor=1)
        oos_baseline_scores.append(calculate_score(val_baseline_row, val_baseline_row, val_gate))
        oos_median_scores.append(calculate_score(val_median_row, val_baseline_row, val_gate))
        oos_baseline_pnls.append(_safe_num(val_baseline_row.get("Total_PNL", 0)))
        oos_median_pnls.append(_safe_num(val_median_row.get("Total_PNL", 0)))

    median_oos = median_oos_score(oos_median_scores)
    median_oos_baseline = median_oos_score(oos_baseline_scores)
    median_oos_pnl = median_oos_score(oos_median_pnls)
    median_oos_baseline_pnl = median_oos_score(oos_baseline_pnls)

    # Full-sample reference rows for compatibility with existing outputs
    full_eval_extra = dict(eval_extra)
    if universe:
        full_eval_extra["min_trades_override"] = ctx["min_trades"]
    full_baseline_row = _evaluate_cfg(
        system, sym, baseline, df, benchmark_df, spy_lookup, spy_df, **full_eval_extra,
    )
    full_median_row = _evaluate_cfg(
        system, sym, median_params, df, benchmark_df, spy_lookup, spy_df, **full_eval_extra,
    )
    sims += 2

    min_trades = ctx["min_trades"]
    baseline_score = calculate_score(full_baseline_row, full_baseline_row, min_trades)
    optimized_score = calculate_score(full_median_row, full_baseline_row, min_trades)

    changes: list[dict[str, Any]] = []
    for key in plan:
        if key in median_params and not _cfg_value_equal(baseline.get(key), median_params.get(key)):
            changes.append({
                "param": key,
                "from": baseline.get(key),
                "to": median_params.get(key),
                "score": round(median_oos, 2),
                "pnl": round(median_oos_pnl, 2),
            })

    elapsed = time.time() - t0
    baseline_pnl = _safe_num(full_baseline_row.get("Total_PNL", 0))
    best_pnl = _safe_num(full_median_row.get("Total_PNL", 0))
    pnl_delta = best_pnl - baseline_pnl

    _log_progress(
        f"  [WF done] {label}: median_oos_pnl={median_oos_pnl:.0f} "
        f"folds={n_folds} sims={sims} t={elapsed:.0f}s"
    )

    return {
        "system": system,
        "symbol": sym,
        "status": "ok" if int(full_baseline_row.get("Total_Trades", 0)) >= min_trades else "low_trades",
        "optimize_scope": "universe" if universe else "per_symbol",
        "baseline_source": wf_opts.get("baseline_source", "default"),
        "universe_symbols_n": len(ctx["symbols"] or []) if universe else 0,
        "wf_mode": "rolling",
        "wf_folds_n": len(folds),
        "wf_median_oos_score": round(median_oos, 2),
        "wf_median_oos_baseline_score": round(median_oos_baseline, 2),
        "wf_median_oos_pnl": round(median_oos_pnl, 2),
        "wf_median_oos_baseline_pnl": round(median_oos_baseline_pnl, 2),
        "wf_oos_improved_folds": sum(
            1 for a, b in zip(oos_median_scores, oos_baseline_scores) if a > b
        ),
        "wf_active_val_folds": _count_wf_active_val_folds(fold_summaries),
        "wf_oos_improved_pnl_folds": _count_wf_pnl_improved_folds(fold_summaries),
        "simulations": sims,
        "elapsed_sec": round(elapsed, 1),
        "baseline_trades": int(full_baseline_row.get("Total_Trades", 0)),
        "baseline_pnl": round(baseline_pnl, 2),
        "baseline_score": round(baseline_score, 2),
        "baseline_pf": round(_safe_num(full_baseline_row.get("Profit_Factor", 0)), 3),
        "optimized_trades": int(full_median_row.get("Total_Trades", 0)),
        "optimized_pnl": round(best_pnl, 2),
        "optimized_score": round(optimized_score, 2),
        "optimized_pf": round(_safe_num(full_median_row.get("Profit_Factor", 0)), 3),
        "pnl_improvement": round(pnl_delta, 2),
        "pnl_improvement_pct": round((pnl_delta / abs(baseline_pnl) * 100) if baseline_pnl else 0.0, 2),
        "score_improvement": round(optimized_score - baseline_score, 2),
        "param_changes": changes,
        "optimized_params": median_params,
        "baseline_params": ctx["baseline"],
        "all_runs": all_runs,
        "wf_folds": fold_summaries,
    }


def _count_wf_active_val_folds(fold_summaries: list[dict[str, Any]]) -> int:
    return sum(
        1
        for f in fold_summaries
        if int(f.get("val_baseline_trades", 0)) + int(f.get("val_opt_trades", 0)) > 0
    )


def _count_wf_pnl_improved_folds(fold_summaries: list[dict[str, Any]]) -> int:
    improved = 0
    for f in fold_summaries:
        if int(f.get("val_baseline_trades", 0)) + int(f.get("val_opt_trades", 0)) <= 0:
            continue
        if _safe_num(f.get("val_opt_pnl", 0)) > _safe_num(f.get("val_baseline_pnl", 0)):
            improved += 1
    return improved


def evaluate_adoption(result: dict[str, Any]) -> tuple[str, str]:
    """
    Return (adopt_recommendation, adopt_reason).
    ADOPT | REJECT | INSUFFICIENT_DATA
    """
    status = str(result.get("status", ""))
    symbol = result.get("symbol", "?")
    if status in ("skip_no_data", "skip_no_folds"):
        return "INSUFFICIENT_DATA", f"{symbol}: no data or no walk-forward folds"

    changes_n = len(result.get("param_changes") or [])
    if changes_n == 0:
        return "INSUFFICIENT_DATA", f"{symbol}: no parameter changes from baseline"

    wf_mode = str(result.get("wf_mode", "none"))

    if wf_mode == "rolling":
        if status == "low_trades":
            return "INSUFFICIENT_DATA", f"{symbol}: low_trades (need status=ok)"

        active = int(result.get("wf_active_val_folds", 0))
        if active == 0:
            return "INSUFFICIENT_DATA", f"{symbol}: no validation folds with trades"

        oos_pnl = _safe_num(result.get("wf_median_oos_pnl", 0))
        oos_base_pnl = _safe_num(result.get("wf_median_oos_baseline_pnl", 0))
        if oos_pnl <= oos_base_pnl:
            return "REJECT", (
                f"{symbol}: median OOS PnL {oos_pnl:,.0f} <= baseline {oos_base_pnl:,.0f}"
            )
        if oos_pnl <= 0:
            return "REJECT", f"{symbol}: median OOS PnL {oos_pnl:,.0f} not positive"

        pnl_improved = int(result.get("wf_oos_improved_pnl_folds", 0))
        need = max(1, math.ceil(0.5 * active))
        if pnl_improved < need:
            return "REJECT", (
                f"{symbol}: OOS PnL improved in {pnl_improved}/{active} active folds "
                f"(need >={need})"
            )
        return "ADOPT", (
            f"{symbol}: median OOS PnL {oos_pnl:,.0f} > baseline {oos_base_pnl:,.0f}, "
            f"won {pnl_improved}/{active} active val folds"
        )

    # Full-sample (in-sample) mode — conservative
    if status != "ok":
        return "INSUFFICIENT_DATA", f"{symbol}: status={status} (need ok)"
    if int(result.get("baseline_trades", 0)) <= 0:
        return "INSUFFICIENT_DATA", f"{symbol}: no baseline trades"
    if _safe_num(result.get("pnl_improvement", 0)) <= 0:
        return "REJECT", f"{symbol}: full-sample PnL did not improve"
    return "ADOPT", f"{symbol}: full-sample PnL improved by {_safe_num(result.get('pnl_improvement', 0)):,.0f}"


def annotate_adoption(result: dict[str, Any]) -> dict[str, Any]:
    rec, reason = evaluate_adoption(result)
    result["adopt_recommendation"] = rec
    result["adopt_reason"] = reason
    return result


def load_rl_symbols() -> list[str]:
    from optimizer_systems import _load_rl_symbols

    return _load_rl_symbols()


def build_tasks(
    systems: list[str],
    *,
    optimize_mode: str,
    universe: str,
    data_dir: Path,
    symbol_filter: set[str] | None,
    wf_opts: dict[str, Any] | None,
    global_baselines: dict[str, dict[str, Any]] | None = None,
) -> list[tuple]:
    mode = str(optimize_mode).strip().lower()
    tasks: list[tuple] = []

    if mode in ("universe", "hierarchical"):
        for system in systems:
            syms = symbols_for_system(system, universe=universe, data_dir=data_dir, symbol_filter=symbol_filter)
            opts = dict(wf_opts or {})
            opts["universe_symbols"] = syms
            opts["baseline_source"] = "default"
            tasks.append((system, UNIVERSE_SYMBOL, str(data_dir), opts))

    if mode in ("per-symbol", "hierarchical"):
        for system in systems:
            syms = symbols_for_system(system, universe=universe, data_dir=data_dir, symbol_filter=symbol_filter)
            for sym in syms:
                opts = dict(wf_opts or {})
                if global_baselines and system in global_baselines:
                    opts["baseline_override"] = global_baselines[system]
                    opts["baseline_source"] = "universe"
                tasks.append((system, sym, str(data_dir), opts))
    return tasks


def aggregate_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in results if r.get("status") in ("ok", "low_trades")]
    improved = [r for r in ok if _safe_num(r.get("pnl_improvement", 0)) > 0]
    worsened = [r for r in ok if _safe_num(r.get("pnl_improvement", 0)) < 0]
    unchanged = [r for r in ok if _safe_num(r.get("pnl_improvement", 0)) == 0]
    total_sims = sum(int(r.get("simulations", 0)) for r in results)
    total_baseline_pnl = sum(_safe_num(r.get("baseline_pnl", 0)) for r in ok)
    total_optimized_pnl = sum(_safe_num(r.get("optimized_pnl", 0)) for r in ok)
    return {
        "symbols_total": len(results),
        "symbols_ok": len([r for r in results if r.get("status") == "ok"]),
        "symbols_low_trades": len([r for r in results if r.get("status") == "low_trades"]),
        "symbols_skipped": len([r for r in results if r.get("status") == "skip_no_data"]),
        "total_simulations": total_sims,
        "symbols_improved_pnl": len(improved),
        "symbols_worsened_pnl": len(worsened),
        "symbols_unchanged_pnl": len(unchanged),
        "aggregate_baseline_pnl": round(total_baseline_pnl, 2),
        "aggregate_optimized_pnl": round(total_optimized_pnl, 2),
        "aggregate_pnl_improvement": round(total_optimized_pnl - total_baseline_pnl, 2),
        "aggregate_pnl_improvement_pct": round(
            (total_optimized_pnl - total_baseline_pnl) / abs(total_baseline_pnl) * 100, 2
        ) if total_baseline_pnl != 0 else 0.0,
        "avg_score_improvement": round(
            sum(_safe_num(r.get("score_improvement", 0)) for r in ok) / len(ok), 2
        ) if ok else 0.0,
        "top_improvements": sorted(ok, key=lambda r: _safe_num(r.get("pnl_improvement", 0)), reverse=True)[:15],
        "top_degradations": sorted(ok, key=lambda r: _safe_num(r.get("pnl_improvement", 0)))[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-symbol / universe BRT RL MTS YH optimizer")
    ap.add_argument("--systems", default="BRT,RL", help="Comma-separated: BRT, RL, MTS, YH, VEC")
    ap.add_argument(
        "--optimize-mode",
        default="per-symbol",
        choices=("per-symbol", "universe", "hierarchical"),
        help="per-symbol=each ticker; universe=pooled DailyRun set; hierarchical=universe WF then per-symbol from global baseline",
    )
    ap.add_argument(
        "--universe",
        default="daily",
        choices=("daily", "all"),
        help="daily=DailyRun lists per system; all=every *.csv in --data-dir (excl. SPY)",
    )
    ap.add_argument("--workers", "-w", type=int, default=4, help="Parallel symbol workers")
    ap.add_argument("--symbols", default="", help="Optional comma-separated symbol subset")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--output-dir", default=str(SCRIPT_DIR))
    ap.add_argument(
        "--param-summary-only",
        action="store_true",
        help="Print param value counts from latest settings JSON and exit (no optimization).",
    )
    ap.add_argument(
        "--wf-mode",
        default="none",
        choices=("none", "rolling"),
        help="none=full-sample in-sample (default); rolling=train 3y/test 1y walk-forward",
    )
    ap.add_argument("--wf-train-years", type=int, default=3, help="Rolling WF: training window length (years)")
    ap.add_argument("--wf-test-years", type=int, default=1, help="Rolling WF: validation window length (years)")
    ap.add_argument("--wf-step-years", type=int, default=1, help="Rolling WF: advance validation window (years)")
    ap.add_argument("--wf-start", default="2010-01-01", help="Rolling WF: earliest calendar date for folds")
    ap.add_argument("--wf-end", default="", help="Rolling WF: last date (default: last bar in data)")
    ap.add_argument("--wf-min-trades-train", type=int, default=0, help="Min trades in train window (0=auto)")
    ap.add_argument("--wf-min-trades-val", type=int, default=0, help="Min trades in val window (0=auto)")
    args = ap.parse_args()

    if args.param_summary_only:
        from per_symbol_settings import (  # noqa: E402
            load_per_symbol_settings,
            print_param_summary,
            resolve_settings_path,
            write_param_summary_csv,
        )

        settings_path = resolve_settings_path()
        if settings_path is None:
            print("[per-symbol] No Per_Symbol_Optimized_Settings_*.json found.", file=sys.stderr)
            return 1
        settings = load_per_symbol_settings(settings_path)
        print(f"[per-symbol] Settings: {settings_path.name} ({len(settings)} symbols)")
        print_param_summary(settings)
        summary_csv = Path(args.output_dir) / "Per_Symbol_Param_Value_Counts_Latest.csv"
        write_param_summary_csv(settings, summary_csv)
        print(f"\n[DONE] Param summary CSV: {summary_csv.name}")
        return 0

    systems = [s.strip().upper() for s in args.systems.split(",") if s.strip()]
    data_dir = str(Path(args.data_dir).resolve())
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%y%m%d%H%M%S")

    symbol_filter: set[str] | None = None
    if args.symbols.strip():
        symbol_filter = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}

    data_dir_path = Path(data_dir)
    optimize_mode = str(args.optimize_mode).strip().lower()

    wf_opts: dict[str, Any] | None = None
    if str(args.wf_mode).strip().lower() == "rolling":
        wf_opts = {
            "wf_mode": "rolling",
            "train_years": int(args.wf_train_years),
            "test_years": int(args.wf_test_years),
            "step_years": int(args.wf_step_years),
            "wf_start": str(args.wf_start).strip() or "2010-01-01",
            "wf_end": str(args.wf_end).strip() or None,
        }
        if int(args.wf_min_trades_train) > 0:
            wf_opts["min_trades_train"] = int(args.wf_min_trades_train)
        if int(args.wf_min_trades_val) > 0:
            wf_opts["min_trades_val"] = int(args.wf_min_trades_val)

    global_baselines: dict[str, dict[str, Any]] | None = None
    results: list[dict[str, Any]] = []
    session_t0 = time.time()

    if optimize_mode == "hierarchical":
        if not wf_opts:
            print("[per-symbol] hierarchical mode requires --wf-mode rolling", file=sys.stderr)
            return 1
        uni_tasks = build_tasks(
            systems, optimize_mode="universe", universe=str(args.universe), data_dir=data_dir_path,
            symbol_filter=symbol_filter, wf_opts=wf_opts,
        )
        uni_workers = max(1, min(args.workers, len(uni_tasks)))
        print(
            f"[per-symbol] Hierarchical step 1/2: universe WF "
            f"({len(uni_tasks)} systems, {uni_workers} workers)"
        )

        def _on_universe_done(done: int, total: int, r: dict[str, Any]) -> None:
            r_ann = annotate_adoption(r)
            print(
                f"  [{done}/{total}] {r_ann['system']} {r_ann['symbol']}: {r_ann['status']} "
                f"adopt={r_ann.get('adopt_recommendation')} "
                f"wf_oos_pnl={r_ann.get('wf_median_oos_pnl', '?')}",
                flush=True,
            )

        uni_raw = _run_parallel_tasks(uni_tasks, uni_workers, on_done=_on_universe_done)
        results = [annotate_adoption(r) for r in uni_raw]
        global_baselines = {}
        for r in results:
            sys_name = str(r.get("system", "")).upper()
            if r.get("adopt_recommendation") == "ADOPT":
                global_baselines[sys_name] = dict(r.get("optimized_params") or {})
            else:
                global_baselines[sys_name] = _default_baseline(sys_name)
                print(f"[per-symbol] Universe REJECT for {sys_name}; per-symbol uses default baseline")

    tasks = build_tasks(
        systems,
        optimize_mode="per-symbol" if optimize_mode == "hierarchical" else optimize_mode,
        universe=str(args.universe),
        data_dir=data_dir_path,
        symbol_filter=symbol_filter,
        wf_opts=wf_opts,
        global_baselines=global_baselines,
    )

    if optimize_mode != "hierarchical":
        results = []
    print(f"[per-symbol] Optimize mode: {optimize_mode}")
    print(f"[per-symbol] Universe: {args.universe}")
    print(f"[per-symbol] WF mode: {args.wf_mode}")
    if wf_opts:
        print(
            f"[per-symbol] WF rolling: train={wf_opts['train_years']}y test={wf_opts['test_years']}y "
            f"step={wf_opts['step_years']}y start={wf_opts['wf_start']}"
        )
    print(f"[per-symbol] Systems: {systems}")
    est_per_sym = sum(len(_plan_for(t[0])) for t in tasks) + len(tasks)
    if wf_opts:
        est_per_sym *= 4  # rough: ~4 folds typical
    print(f"[per-symbol] Tasks: {len(tasks)}")
    print(f"[per-symbol] Est. simulations (rough): {est_per_sym}")
    print(f"[per-symbol] Workers: {args.workers}")
    print("=" * 60)

    workers = max(1, args.workers)

    def _format_task_line(r: dict[str, Any]) -> str:
        line = (
            f"{r['system']} {r['symbol']}: {r['status']} "
            f"sims={r.get('simulations', 0)} baseline_pnl={r.get('baseline_pnl', '?')} "
            f"opt_pnl={r.get('optimized_pnl', '?')} delta={r.get('pnl_improvement', '?')}"
        )
        if r.get("wf_mode") == "rolling":
            line += (
                f" wf_oos={r.get('wf_median_oos_score', '?')}"
                f"/{r.get('wf_median_oos_baseline_score', '?')}"
                f" folds={r.get('wf_folds_n', 0)}"
            )
        return line

    if tasks:
        def _on_symbol_done(done: int, total: int, r: dict[str, Any]) -> None:
            print(f"[{done}/{total}] {_format_task_line(r)}", flush=True)

        sym_results = _run_parallel_tasks(tasks, workers, on_done=_on_symbol_done)
        results.extend(sym_results)

    if optimize_mode != "hierarchical":
        results = [annotate_adoption(r) for r in results]
    else:
        # Universe rows already annotated; annotate per-symbol rows only
        annotated: list[dict[str, Any]] = []
        for r in results:
            if r.get("symbol") == UNIVERSE_SYMBOL:
                annotated.append(r)
            else:
                annotated.append(annotate_adoption(r))
        results = annotated

    summary = aggregate_summary([r for r in results if r.get("symbol") != UNIVERSE_SYMBOL])
    summary["elapsed_min"] = round((time.time() - session_t0) / 60, 1)
    summary["systems"] = systems
    summary["timestamp"] = ts
    summary["wf_mode"] = str(args.wf_mode)
    if wf_opts:
        summary["wf_options"] = wf_opts
        wf_ok = [r for r in results if r.get("wf_mode") == "rolling" and r.get("status") in ("ok", "low_trades")]
        summary["wf_symbols_with_folds"] = len(wf_ok)
        summary["wf_median_oos_improved"] = len(
            [r for r in wf_ok if _safe_num(r.get("wf_median_oos_score", 0)) > _safe_num(r.get("wf_median_oos_baseline_score", 0))]
        )
        summary["wf_avg_median_oos_score"] = round(
            sum(_safe_num(r.get("wf_median_oos_score", 0)) for r in wf_ok) / len(wf_ok), 2
        ) if wf_ok else 0.0

    summary["symbols_adopt"] = len([r for r in results if r.get("adopt_recommendation") == "ADOPT"])
    summary["symbols_reject"] = len([r for r in results if r.get("adopt_recommendation") == "REJECT"])
    summary["symbols_insufficient_data"] = len(
        [r for r in results if r.get("adopt_recommendation") == "INSUFFICIENT_DATA"]
    )

    # Flatten for CSV
    rows: list[dict[str, Any]] = []
    for r in sorted(results, key=lambda x: (x.get("system", ""), x.get("symbol", ""))):
        flat = {
            k: v
            for k, v in r.items()
            if k not in ("param_changes", "optimized_params", "baseline_params", "wf_folds", "all_runs")
        }
        flat["param_changes_n"] = len(r.get("param_changes", []))
        flat["param_changes"] = json.dumps(r.get("param_changes", []))
        flat["optimized_params"] = json.dumps(r.get("optimized_params", {}))
        flat["wf_folds"] = json.dumps(r.get("wf_folds", []))
        rows.append(flat)

    df = pd.DataFrame(rows)
    csv_path = out_dir / f"Per_Symbol_Optimizer_Results_{ts}.csv"
    df.to_csv(csv_path, index=False)

    all_run_rows: list[dict[str, Any]] = []
    for r in results:
        all_run_rows.extend(r.get("all_runs") or [])
    all_runs_df = pd.DataFrame(all_run_rows)
    all_runs_path = out_dir / f"Per_Symbol_All_Runs_{ts}.csv"
    all_runs_df.to_csv(all_runs_path, index=False)
    # Stable name for easy reference
    all_runs_latest = out_dir / "Per_Symbol_All_Runs_Latest.csv"
    all_runs_df.to_csv(all_runs_latest, index=False)

    wf_fold_rows: list[dict[str, Any]] = []
    for r in results:
        for fold in r.get("wf_folds") or []:
            wf_fold_rows.append({
                "system": r.get("system"),
                "symbol": r.get("symbol"),
                **fold,
            })
    if wf_fold_rows:
        wf_folds_df = pd.DataFrame(wf_fold_rows)
        wf_folds_path = out_dir / f"Per_Symbol_WF_Folds_{ts}.csv"
        wf_folds_df.to_csv(wf_folds_path, index=False)
        wf_folds_df.to_csv(out_dir / "Per_Symbol_WF_Folds_Latest.csv", index=False)

    json_path = out_dir / f"Per_Symbol_Optimizer_Summary_{ts}.json"
    # JSON-safe summary (strip nested full result objects from top lists)
    summary_export = dict(summary)
    for key in ("top_improvements", "top_degradations"):
        summary_export[key] = [
            {k: v for k, v in item.items() if k not in ("optimized_params", "baseline_params")}
            for item in summary.get(key, [])
        ]
    json_path.write_text(json.dumps(summary_export, indent=2), encoding="utf-8")

    settings_path = out_dir / f"Per_Symbol_Optimized_Settings_{ts}.json"
    settings = {
        r["symbol"]: {"system": r["system"], **r.get("optimized_params", {})}
        for r in results
        if r.get("symbol") != UNIVERSE_SYMBOL
        and r.get("status") in ("ok", "low_trades")
        and r.get("param_changes")
    }
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    settings_latest = out_dir / "Per_Symbol_Optimized_Settings_Latest.json"
    settings_latest.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    settings_approved = {
        r["symbol"]: {"system": r["system"], **r.get("optimized_params", {})}
        for r in results
        if r.get("symbol") != UNIVERSE_SYMBOL and r.get("adopt_recommendation") == "ADOPT"
    }
    settings_approved_path = out_dir / f"Per_Symbol_Optimized_Settings_Approved_{ts}.json"
    settings_approved_path.write_text(json.dumps(settings_approved, indent=2), encoding="utf-8")
    settings_approved_latest = out_dir / "Per_Symbol_Optimized_Settings_Approved_Latest.json"
    settings_approved_latest.write_text(json.dumps(settings_approved, indent=2), encoding="utf-8")

    universe_settings = {
        r["system"]: {
            "system": r["system"],
            "scope": "universe",
            **(r.get("optimized_params") or {}),
        }
        for r in results
        if r.get("symbol") == UNIVERSE_SYMBOL and r.get("adopt_recommendation") == "ADOPT"
    }
    if universe_settings:
        uni_path = out_dir / f"Universe_Optimized_Settings_{ts}.json"
        uni_path.write_text(json.dumps(universe_settings, indent=2), encoding="utf-8")
        (out_dir / "Universe_Optimized_Settings_Latest.json").write_text(
            json.dumps(universe_settings, indent=2), encoding="utf-8",
        )
        print(f"[DONE] Universe settings: {uni_path.name} ({len(universe_settings)} systems)")

    from per_symbol_settings import print_param_summary, write_param_summary_csv  # noqa: E402

    param_summary_csv = out_dir / f"Per_Symbol_Param_Value_Counts_{ts}.csv"
    write_param_summary_csv(settings, param_summary_csv)
    param_summary_latest = out_dir / "Per_Symbol_Param_Value_Counts_Latest.csv"
    write_param_summary_csv(settings, param_summary_latest)
    approved_summary_csv = out_dir / f"Per_Symbol_Param_Value_Counts_Approved_{ts}.csv"
    write_param_summary_csv(settings_approved, approved_summary_csv)
    write_param_summary_csv(settings_approved, out_dir / "Per_Symbol_Param_Value_Counts_Approved_Latest.csv")
    print_param_summary(settings_approved)

    print("\n" + "=" * 60)
    print(f"[DONE] {summary['total_simulations']} simulations in {summary['elapsed_min']} min")
    print(f"[DONE] Improved PnL: {summary['symbols_improved_pnl']}/{summary['symbols_ok']+summary['symbols_low_trades']} symbols")
    print(f"[DONE] Aggregate PnL: {summary['aggregate_baseline_pnl']:,.0f} -> {summary['aggregate_optimized_pnl']:,.0f} "
          f"(+{summary['aggregate_pnl_improvement']:,.0f}, {summary['aggregate_pnl_improvement_pct']:+.1f}%)")
    print(f"[DONE] Results: {csv_path.name}")
    print(f"[DONE] All runs ({len(all_runs_df)} rows): {all_runs_path.name}")
    print(f"[DONE] All runs (latest): {all_runs_latest.name}")
    print(f"[DONE] Summary: {json_path.name}")
    if wf_fold_rows:
        print(f"[DONE] WF folds: Per_Symbol_WF_Folds_{ts}.csv ({len(wf_fold_rows)} rows)")
    print(f"[DONE] Settings: {settings_path.name} ({len(settings)} symbols, all candidates)")
    print(f"[DONE] Settings (latest): {settings_latest.name}")
    print(f"[DONE] Settings APPROVED: {settings_approved_path.name} ({len(settings_approved)} symbols)")
    print(f"[DONE] Settings APPROVED (latest): {settings_approved_latest.name}")
    print(f"[DONE] Adoption: ADOPT={summary['symbols_adopt']} REJECT={summary['symbols_reject']} "
          f"INSUFFICIENT_DATA={summary['symbols_insufficient_data']}")
    print(f"[DONE] Param value counts: {param_summary_csv.name}")
    print(f"[DONE] Param value counts (latest): {param_summary_latest.name}")
    print(f"[DONE] Param value counts APPROVED: {approved_summary_csv.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
