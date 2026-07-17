#!/usr/bin/env python3
"""
NewHigh: simplified strategy — long entry when price prints a new high vs the prior N **trading** bars.

Entry rule (only tunable entry input): on bar *i*, let prior_high = max(High[i-N : i]).
If High[i] > prior_high, schedule entry at the **open** of bar i+1 (same convention as rocket_brt).

Exits match rocket_brt intraday resolution order: gap down, gap up, stop, target, with the same
stop_pct / target_pct / atr_target / atr_stop / atr_increment semantics.

Outputs reuse rocket_brt writers so BRT_Closed / BRT_Open / BRT_Report / BRT_Audit_Report / summaries /
equity curve (when equity metrics are on) align with the rest of the toolchain (e.g. BRT_DrawdownCalc).
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from rocket_brt import (  # noqa: E402
    BRTConfig,
    BRTTrade,
    _apply_report_dollar_scale_to_trades,
    _enrich_post_entry_gain_hit,
    _enrich_trades_entry_indicators,
    _enrich_trades_yfinance,
    _precompute_beta_by_bar_index,
    _write_brt_equity_canonical_outputs,
    compute_metrics,
    load_all_tickers,
    load_csv,
    write_brt_audit_report,
    write_brt_closed,
    write_brt_industry_summary,
    write_brt_open,
    write_brt_report,
    write_brt_scanner,
    write_brt_short_candidates,
    write_brt_summary,
    write_brt_watchlist,
)

try:
    from BRT_DrawdownCalc import compute_equity_metrics as _compute_equity_metrics
except ImportError:
    _compute_equity_metrics = None  # type: ignore[misc, assignment]

try:
    import yfinance  # noqa: F401 — checked by _enrich_trades_yfinance
    _HAS_YFIN = True
except ImportError:
    _HAS_YFIN = False


def _index_yyyymmdd(idx: pd.Timestamp) -> str:
    ts = pd.Timestamp(idx)
    return ts.strftime("%Y%m%d")


def _compute_atr_14(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Wilder-style rolling mean TR over 14 bars (same construction as rocket_brt)."""
    n = len(close)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    if n > 1:
        hl = high[1:] - low[1:]
        h_pc = np.abs(high[1:] - close[:-1])
        l_pc = np.abs(low[1:] - close[:-1])
        tr[1:] = np.maximum.reduce([hl, h_pc, l_pc])
    atr = np.full(n, np.nan, dtype=np.float64)
    p = 14
    if n >= p:
        atr[p - 1 :] = np.convolve(tr, np.ones(p, dtype=np.float64) / float(p), mode="valid")
    return atr


def _trigger_metrics(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    open_: np.ndarray,
    atr_14: np.ndarray,
    sig_i: int,
) -> tuple[float, float, float, float, int, int, float]:
    """z-score of close vs prior 20 closes (excl. current), wicks in ATR, 20-bar high/low flags."""
    z = 0.0
    if sig_i >= 20:
        window = close[sig_i - 20 : sig_i]
        m = float(np.mean(window))
        s = float(np.std(window, ddof=1)) if len(window) > 1 else 0.0
        if s > 1e-12:
            z = (float(close[sig_i]) - m) / s
    atr_t = float(atr_14[sig_i]) if sig_i < len(atr_14) and atr_14[sig_i] == atr_14[sig_i] else 0.0
    rng = max(high[sig_i] - low[sig_i], 1e-12)
    body_top = max(open_[sig_i], close[sig_i])
    body_bot = min(open_[sig_i], close[sig_i])
    upper_wick = (high[sig_i] - body_top) / atr_t if atr_t > 0 else 0.0
    lower_wick = (body_bot - low[sig_i]) / atr_t if atr_t > 0 else 0.0
    body_atr = abs(close[sig_i] - open_[sig_i]) / atr_t if atr_t > 0 else 0.0
    start = max(0, sig_i - 19)
    is_hi = 1 if high[sig_i] >= np.max(high[start : sig_i + 1]) else 0
    is_lo = 1 if low[sig_i] <= np.min(low[start : sig_i + 1]) else 0
    return z, upper_wick, lower_wick, body_atr, is_hi, is_lo, atr_t


@dataclass
class _Pending:
    sig_i: int
    zone_center: float
    maturity_iso: str
    close_above_iso: str
    z_score: float
    upper_wick_atr: float
    lower_wick_atr: float
    is_20h: int
    is_20l: int
    move_body_atr: float


@dataclass
class _OpenLeg:
    trade: BRTTrade
    initial_stop: float
    max_high_since_entry: float
    entry_bar_index: int


def run_symbol(
    sym: str,
    df: pd.DataFrame,
    cfg: BRTConfig,
    n_trading_days: int,
    benchmark_df: Optional[pd.DataFrame],
    beta_by_bar: Optional[np.ndarray],
) -> tuple[list[BRTTrade], list[BRTTrade], list[dict]]:
    """Backtest one symbol. Returns (closed, open_positions_len_0_or_1_as_list, scanner_rows)."""
    closed: list[BRTTrade] = []
    scanner: list[dict] = []
    if len(df) < n_trading_days + 3:
        return closed, [], scanner

    dates = df.index
    op = df["Open"].to_numpy(dtype=np.float64)
    hi = df["High"].to_numpy(dtype=np.float64)
    lo = df["Low"].to_numpy(dtype=np.float64)
    cl = df["Close"].to_numpy(dtype=np.float64)
    vol = df["Volume"].to_numpy(dtype=np.float64) if "Volume" in df.columns else None
    n = len(df)
    atr_14 = _compute_atr_14(hi, lo, cl)

    pending: Optional[_Pending] = None
    open_leg: Optional[_OpenLeg] = None

    use_atr_mode = (
        float(getattr(cfg, "atr_target", 0.0) or 0) > 0.0
        or float(getattr(cfg, "atr_stop", 0.0) or 0) > 0.0
        or float(getattr(cfg, "atr_increment", 0.0) or 0) > 0.0
    )

    for i in range(n):
        iso = _index_yyyymmdd(dates[i])

        # --- exits ---
        if open_leg is not None:
            t = open_leg.trade
            open_leg.max_high_since_entry = max(open_leg.max_high_since_entry, hi[i])
            sp = open_leg.initial_stop
            tp = t.target_price
            if float(getattr(cfg, "atr_increment", 0) or 0) > 0 and t.entry_price > 0:
                gain_pct = (open_leg.max_high_since_entry - t.entry_price) / t.entry_price * 100.0
                inc = int(gain_pct / float(cfg.atr_increment))
                sp = open_leg.initial_stop + inc * 0.01 * t.entry_price
            stop_round_decimals = int(getattr(cfg, "stop_compare_round_decimals", 2))
            if stop_round_decimals >= 0:
                op_cmp = round(float(op[i]), stop_round_decimals)
                lo_cmp = round(float(lo[i]), stop_round_decimals)
                sp_cmp = round(float(sp), stop_round_decimals)
            else:
                op_cmp = float(op[i])
                lo_cmp = float(lo[i])
                sp_cmp = float(sp)
            gap_down = op_cmp <= sp_cmp
            gap_up = op[i] >= tp
            stop_hit = lo_cmp <= sp_cmp
            target_hit = hi[i] >= tp
            hit_trailing = use_atr_mode and float(getattr(cfg, "atr_increment", 0) or 0) > 0 and sp > open_leg.initial_stop

            exit_price = 0.0
            exit_type = ""
            if gap_down:
                exit_price = op[i]
                exit_type = ("ATR_Increment" if hit_trailing else "ATR_STOP") if use_atr_mode else "GAP_DOWN"
            elif gap_up:
                exit_price = op[i]
                exit_type = "ATR_TARGET" if use_atr_mode else "GAP_UP"
            elif stop_hit:
                exit_price = cl[i] if cfg.exit_at_close_when_stopped else sp
                exit_type = ("ATR_Increment" if hit_trailing else "ATR_STOP") if use_atr_mode else "STOP_LOSS"
            elif target_hit:
                exit_price = tp
                exit_type = "ATR_TARGET" if use_atr_mode else "TARGET"
            else:
                continue

            pnl_pct = (exit_price - t.entry_price) / t.entry_price * 100.0
            pnl_dollars = (cfg.brt_cash / t.entry_price) * (exit_price - t.entry_price)
            d_open = str(t.date_opened).replace("-", "")[:8]
            d_cl = iso
            days_held = (
                (pd.Timestamp(d_cl[:4] + "-" + d_cl[4:6] + "-" + d_cl[6:8]) - pd.Timestamp(d_open[:4] + "-" + d_open[4:6] + "-" + d_open[6:8])).days
                if len(d_open) == 8 and len(d_cl) == 8
                else 0
            )
            start_dt = pd.Timestamp(d_open[:4] + "-" + d_open[4:6] + "-" + d_open[6:8])
            end_dt = pd.Timestamp(d_cl[:4] + "-" + d_cl[4:6] + "-" + d_cl[6:8])
            mask = (df.index >= start_dt) & (df.index <= end_dt)
            max_price = float(df.loc[mask, "High"].max()) if mask.any() else float(t.entry_price)

            beta_at_entry_val = None
            eb = open_leg.entry_bar_index
            if beta_by_bar is not None and eb < len(beta_by_bar):
                bv = beta_by_bar[eb]
                beta_at_entry_val = float(bv) if (bv == bv and np.isfinite(bv)) else None

            closed.append(
                replace(
                    t,
                    date_closed=iso,
                    exit_price=exit_price,
                    exit_type=exit_type,
                    days_held=days_held,
                    pnl_pct=pnl_pct,
                    pnl_dollars=pnl_dollars,
                    max_price=max_price,
                    beta_at_entry=beta_at_entry_val,
                )
            )
            open_leg = None

        # --- enter at today's open from yesterday's signal ---
        if open_leg is None and pending is not None and pending.sig_i + 1 == i:
            entry_price = float(op[i])
            sig_i = pending.sig_i
            trigger_low = float(lo[sig_i])
            atr_e = float(atr_14[i]) if (i < len(atr_14) and atr_14[i] == atr_14[i]) else None
            atr_pct = (atr_e / entry_price) * 100.0 if (atr_e is not None and entry_price > 0) else None

            if float(getattr(cfg, "atr_target", 0.0) or 0) > 0 and atr_pct is not None:
                target_price = entry_price * (1.0 + atr_pct * float(cfg.atr_target) / 100.0)
            else:
                target_price = entry_price * float(cfg.target_pct)

            if float(getattr(cfg, "atr_stop", 0.0) or 0) > 0 and atr_pct is not None:
                stop_price = entry_price * (1.0 - atr_pct * float(cfg.atr_stop) / 100.0)
            else:
                if cfg.stop_pct_is_multiplier:
                    stop_price = trigger_low * float(cfg.stop_pct)
                else:
                    stop_price = trigger_low * (1.0 - float(cfg.stop_pct))

            vol_entry = float(vol[i]) if vol is not None else None
            avg_10 = float(np.mean(vol[max(0, i - 10) : i])) if vol is not None and i > 0 else None
            rel_vol = (vol_entry / avg_10) if (vol_entry is not None and avg_10 and avg_10 > 0) else None
            rel_on_trig = None
            if vol is not None and sig_i > 0:
                avg_t = float(np.mean(vol[max(0, sig_i - 10) : sig_i]))
                if avg_t > 0:
                    rel_on_trig = float(vol[sig_i]) / avg_t

            open_iso = _index_yyyymmdd(dates[i])
            beta_at_entry_open = None
            if beta_by_bar is not None and i < len(beta_by_bar):
                bv = beta_by_bar[i]
                beta_at_entry_open = float(bv) if (bv == bv and np.isfinite(bv)) else None
            bt = BRTTrade(
                symbol=sym,
                date_opened=open_iso,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                zone_center=float(pending.zone_center),
                touch_count=0,
                touch_count_short=0,
                touch_count_major=0,
                touch_count_minor=0,
                is_tradeable_key_level=False,
                struct_high="",
                struct_low="",
                entry_pivot_type="NH_BREAK",
                entry_struct_regime="NEW_HIGH",
                entry_major_pivot=0,
                entry_pivot_was_strong=0,
                entry_zone_was_strong_pivot=0,
                nearby_zones_above=0,
                nearby_zones_below=0,
                zone_cluster_density=0,
                maturity_date=pending.maturity_iso,
                close_above_date=pending.close_above_iso,
                growth_pct_over_period=None,
                displacement_pct_at_entry=None,
                pivot_run_high=0,
                pivot_run_low=0,
                pivot_switch_h_to_l=False,
                zone_above_center=0.0,
                zone_below_center=0.0,
                pct_entry_to_bottom_zone_above=0.0,
                pct_drop_to_top_zone_below=0.0,
                volume_at_entry=vol_entry,
                avg_volume_10d_at_entry=avg_10,
                rel_vol_at_entry=rel_vol,
                rel_vol_on_trigger=rel_on_trig,
                atr_14_at_entry=atr_e,
                z_score_at_trigger=pending.z_score,
                upper_wick_atr_at_trigger=pending.upper_wick_atr,
                lower_wick_atr_at_trigger=pending.lower_wick_atr,
                is_20bar_high_at_trigger=pending.is_20h,
                is_20bar_low_at_trigger=pending.is_20l,
                move_body_atr_at_trigger=pending.move_body_atr,
                sheet_ladder_rung_at_signal=0,
                beta_at_entry=beta_at_entry_open,
            )
            open_leg = _OpenLeg(
                trade=bt,
                initial_stop=stop_price,
                max_high_since_entry=entry_price,
                entry_bar_index=i,
            )
            pending = None

        # --- new signal (only when flat and not already scheduling) ---
        if open_leg is not None or pending is not None:
            continue
        if i < n_trading_days:
            continue
        prior_max = float(np.max(hi[i - n_trading_days : i]))
        if not (hi[i] > prior_max):
            continue
        if i + 1 >= n:
            dt = f"{iso[:4]}-{iso[4:6]}-{iso[6:8]}"
            # Mirror rocket_brt scanner row shape (approximate stop/target from signal close)
            scanner.append(
                {
                    "symbol": sym,
                    "date": dt,
                    "close": float(cl[i]),
                    "stop": float(lo[i]) * float(cfg.stop_pct) if cfg.stop_pct_is_multiplier else float(lo[i]) * (1.0 - float(cfg.stop_pct)),
                    "target": float(cl[i]) * float(cfg.target_pct),
                    "zone_center": prior_max,
                }
            )
            continue

        z_s, uw, lw, mb, i20h, i20l, _ = _trigger_metrics(cl, hi, lo, op, atr_14, i)
        sig_iso = _index_yyyymmdd(dates[i])
        sig_dash = f"{sig_iso[:4]}-{sig_iso[4:6]}-{sig_iso[6:8]}"
        pending = _Pending(
            sig_i=i,
            zone_center=prior_max,
            maturity_iso=sig_dash,
            close_above_iso=sig_dash,
            z_score=z_s,
            upper_wick_atr=uw,
            lower_wick_atr=lw,
            is_20h=i20h,
            is_20l=i20l,
            move_body_atr=mb,
        )

    open_out: list[BRTTrade] = [open_leg.trade] if open_leg else []
    return closed, open_out, scanner


def main() -> None:
    p = argparse.ArgumentParser(description="New N-day high breakout backtest (BRT-compatible outputs).")
    p.add_argument("data_dir", help="Directory of per-symbol OHLCV CSVs (same as rocket_brt)")
    p.add_argument(
        "n_trading_days",
        type=int,
        help="Lookback length in trading bars; buy when High exceeds max High of prior N bars",
    )
    p.add_argument("-o", "--output-dir", default="", help="Output directory (default: data_dir/NewHigh_Out)")
    p.add_argument("--brt-cash", type=float, default=47500.0, help="Dollars per position (default 47500)")
    p.add_argument("--initial-capital", type=float, default=500000.0, help="For equity / Max DD reconstruction")
    p.add_argument("--stop-pct", type=float, default=0.934, help="Stop vs signal-bar low: default low*stop_pct (BRT multiplier mode)")
    p.add_argument(
        "--stop-pct-fraction",
        action="store_true",
        help="Interpret stop-pct as fraction below low: stop = low * (1 - stop_pct), matching BRT stop_pct_is_multiplier=False",
    )
    p.add_argument("--target-pct", type=float, default=1.22, help="Target as entry * target_pct when not using ATR target")
    p.add_argument("--atr-target", type=float, default=2.0, help="ATR-based target; 0 = use target_pct only")
    p.add_argument("--atr-stop", type=float, default=1.4, help="ATR-based stop; 0 = use stop_pct only")
    p.add_argument("--atr-increment", type=float, default=5.8, help="Trailing: each atr_increment%% up move raises stop by 1%% of entry; 0 = off")
    p.add_argument("--exit-at-close-when-stopped", action="store_true", help="If stop hit intraday, exit at close instead of stop price")
    p.add_argument("--no-yfinance", action="store_true", help="Skip market_cap / sector / industry / beta enrichment")
    p.add_argument("--no-equity-metrics", action="store_true", help="Skip Max DD / BRT_EquityCurve (faster)")
    p.add_argument("--aggressive", action="store_true", help="Pass through to BRT_DrawdownCalc equity sim")
    p.add_argument("--drive-link", default="", help="Hyperlink text for BRT_Report timestamp cell")
    args = p.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.output_dir) if args.output_dir else data_dir / "NewHigh_Out"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%y%m%d%H%M%S")

    cfg = replace(
        BRTConfig(),
        brt_cash=float(args.brt_cash),
        initial_capital=float(args.initial_capital),
        stop_pct=float(args.stop_pct),
        stop_pct_is_multiplier=not bool(args.stop_pct_fraction),
        target_pct=float(args.target_pct),
        atr_target=float(args.atr_target),
        atr_stop=float(args.atr_stop),
        atr_increment=float(args.atr_increment),
        exit_at_close_when_stopped=bool(args.exit_at_close_when_stopped),
        compute_equity_metrics=not bool(args.no_equity_metrics),
        aggressive=bool(args.aggressive),
    )

    print(f"[NewHigh] Loading tickers from {data_dir} ...")
    t0 = time.time()
    tickers = load_all_tickers(str(data_dir))
    print(f"[NewHigh] Loaded {len(tickers)} symbols in {time.time() - t0:.1f}s")

    bench_path = data_dir / "SPY.csv"
    benchmark_df: Optional[pd.DataFrame] = None
    if bench_path.is_file():
        try:
            benchmark_df = load_csv(str(bench_path))
        except Exception:
            benchmark_df = None

    all_closed: list[BRTTrade] = []
    all_open: list[BRTTrade] = []
    all_scanner: list[dict] = []
    n_days = int(args.n_trading_days)
    if n_days < 1:
        raise SystemExit("n_trading_days must be >= 1")

    done = 0
    total = len(tickers)
    t_loop = time.perf_counter()
    for sym, df in sorted(tickers.items()):
        beta_arr = None
        if benchmark_df is not None:
            try:
                beta_arr = _precompute_beta_by_bar_index(df, benchmark_df)
            except Exception:
                beta_arr = None
        c, o, sc = run_symbol(sym, df, cfg, n_days, benchmark_df, beta_arr)
        all_closed.extend(c)
        all_open.extend(o)
        all_scanner.extend(sc)
        done += 1
        if total > 1:
            pct = 100.0 * done / total
            msg = f"\r[NewHigh] {done}/{total} ({pct:.1f}%)"
            try:
                cols = max(40, __import__("shutil").get_terminal_size().columns)
            except OSError:
                cols = 80
            pad = max(0, cols - 1 - len(msg))
            sys.stdout.write(msg + " " * pad)
            sys.stdout.flush()
    if total > 1:
        print()

    if not args.no_yfinance and _HAS_YFIN:
        _enrich_trades_yfinance(all_closed, all_open)

    if all_closed:
        _apply_report_dollar_scale_to_trades(all_closed, all_open, cfg)

    _enrich_post_entry_gain_hit(all_closed + all_open, tickers, cfg)
    _enrich_trades_entry_indicators(all_closed + all_open, tickers, cfg)

    write_brt_closed(all_closed, str(out_dir / f"BRT_Closed_{ts}.csv"), reference_stats=None, cfg=cfg)
    write_brt_open(all_open, str(out_dir / f"BRT_Open_{ts}.csv"), tickers=tickers, brt_cash=cfg.brt_cash, closed=all_closed, cfg=cfg)
    _scanner_path = str(out_dir / f"BRT_Scanner_{ts}.csv")
    if write_brt_scanner(all_scanner, _scanner_path):
        print(f"[NewHigh] Scanner: {_scanner_path} ({len(all_scanner)} rows)")
    write_brt_watchlist([], str(out_dir / f"BRT_Watchlist_{ts}.csv"))
    write_brt_short_candidates([], str(out_dir / f"BRT_ShortCandidates_{ts}.csv"))
    write_brt_summary(all_closed, str(out_dir / f"BRT_Summary_{ts}.csv"))
    write_brt_industry_summary(all_closed, str(out_dir / f"BRT_INDUSTRY_{ts}.csv"))

    try:
        from correlate_brt_closed import run_correlation_report

        run_correlation_report(str(out_dir / f"BRT_Closed_{ts}.csv"), str(out_dir / f"BRT_Correlation_{ts}.csv"))
        print(f"[NewHigh] Correlation report: BRT_Correlation_{ts}.csv")
    except Exception as e:
        print(f"[NewHigh] Correlation report skipped: {e}")

    metrics: dict[str, Any] = compute_metrics(all_closed, cfg)

    if (
        cfg.compute_equity_metrics
        and _compute_equity_metrics is not None
        and all_closed
        and tickers
    ):
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
            _write_brt_equity_canonical_outputs(out_dir, ts, equity)
        except Exception as e:
            print(f"[WARN] Equity metrics failed: {e}", file=sys.stderr)

    write_brt_report(cfg, metrics, str(out_dir), ts, args.drive_link)
    write_brt_audit_report(cfg, metrics, str(out_dir), ts, args.drive_link)

    def _patch_audit_param(path: Path, name: str, value: str) -> None:
        try:
            with path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
            if len(rows) < 2:
                return
            hdr = rows[0]
            if "Param_Name" not in hdr or "Param_Value" not in hdr:
                return
            i_n, i_v = hdr.index("Param_Name"), hdr.index("Param_Value")
            while len(rows[1]) <= max(i_n, i_v):
                rows[1].append("")
            rows[1][i_n] = name
            rows[1][i_v] = value
            with path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(rows)
        except OSError:
            pass

    pv = str(n_days)
    _patch_audit_param(out_dir / f"BRT_Report_{ts}.csv", "new_high_trading_days", pv)
    _patch_audit_param(out_dir / f"BRT_Audit_Report_{ts}.csv", "new_high_trading_days", pv)

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] NewHigh done: {len(all_closed)} closed, {len(all_open)} open "
        f"-> {out_dir} (ts={ts}) in {time.perf_counter() - t_loop:.1f}s"
    )


if __name__ == "__main__":
    main()
