"""
Profile rocket_brt to identify performance bottlenecks.
Run: python profile_rocket_brt.py [data_dir]

For cProfile inside ``run_brt_backtest`` on one symbol (then ``pstats`` / snakeviz), use the main CLI:
``python rocket_brt.py <data_dir> -s SYMBOL --cprofile`` (add ``--profile`` for per-section ``bt_*`` CSV columns).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else str(SCRIPT_DIR.parent / "data" / "newdata" / "data")
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"Data dir not found: {data_path}")
        return 1

    from rocket_brt_og import (
        BRTConfig,
        load_csv,
        load_all_tickers,
        compute_pivots,
        compute_market_structure,
        compute_touch_stream,
        run_brt_backtest,
        write_brt_closed,
    )
    from BRT_DrawdownCalc import compute_equity_metrics

    cfg = BRTConfig()
    timings = {}

    # 1. Load tickers
    t0 = time.perf_counter()
    tickers = load_all_tickers(str(data_path))
    ticker_list = sorted([s for s, df in tickers.items() if len(df) >= cfg.pivot_k + cfg.pivot_m + 10])
    timings["load_tickers"] = time.perf_counter() - t0
    print(f"[PROFILE] load_tickers: {timings['load_tickers']:.2f}s ({len(ticker_list)} symbols)")

    # 2. Per-symbol backtest (sample first 50 for quick profile)
    n_sample = min(50, len(ticker_list))
    t0 = time.perf_counter()
    t_pivots, t_struct, t_touch, t_backtest = 0, 0, 0, 0
    all_closed = []
    all_open = []

    for sym in ticker_list[:n_sample]:
        df = tickers[sym]
        t1 = time.perf_counter()
        pivot_high, pivot_low, ph_price, pl_price = compute_pivots(df, cfg.pivot_k, cfg.pivot_m, cfg.pivot_d)
        t_pivots += time.perf_counter() - t1
        t1 = time.perf_counter()
        struct = compute_market_structure(df, pivot_high, pivot_low, ph_price, pl_price)
        t_struct += time.perf_counter() - t1
        t1 = time.perf_counter()
        level3 = compute_touch_stream(
            df, pivot_high, pivot_low, ph_price, pl_price,
            cfg.band_pct, cfg.lookback_long, cfg.touch_threshold, cfg.lookback_short,
        )
        t_touch += time.perf_counter() - t1
        t1 = time.perf_counter()
        closed, open_trade, _, _, _, _ = run_brt_backtest(sym, df, cfg, ph_price, pl_price, struct, level3)
        t_backtest += time.perf_counter() - t1
        all_closed.extend(closed)
        if open_trade:
            all_open.append(open_trade)

    timings["per_symbol_total"] = time.perf_counter() - t0
    print(f"[PROFILE] per_symbol ({n_sample} symbols): {timings['per_symbol_total']:.2f}s")
    print(f"  - compute_pivots:      {t_pivots:.2f}s ({t_pivots/n_sample*1000:.1f}ms/symbol)")
    print(f"  - compute_market_struct: {t_struct:.2f}s ({t_struct/n_sample*1000:.1f}ms/symbol)")
    print(f"  - compute_touch_stream: {t_touch:.2f}s ({t_touch/n_sample*1000:.1f}ms/symbol)")
    print(f"  - run_brt_backtest:    {t_backtest:.2f}s ({t_backtest/n_sample*1000:.1f}ms/symbol)")
    print(f"  - Extrapolated full run ({len(ticker_list)} symbols): {timings['per_symbol_total']/n_sample*len(ticker_list):.1f}s")

    # 3. write_brt_closed (hist stats)
    t0 = time.perf_counter()
    write_brt_closed(all_closed, str(SCRIPT_DIR / "profile_test_closed.csv"))
    timings["write_closed"] = time.perf_counter() - t0
    print(f"[PROFILE] write_brt_closed ({len(all_closed)} trades): {timings['write_closed']:.2f}s")

    # 4. compute_equity_metrics
    if all_closed and tickers:
        t0 = time.perf_counter()
        equity = compute_equity_metrics(all_closed, all_open, tickers, cfg.brt_cash)
        timings["compute_equity"] = time.perf_counter() - t0
        print(f"[PROFILE] compute_equity_metrics: {timings['compute_equity']:.2f}s")

    # Cleanup
    (SCRIPT_DIR / "profile_test_closed.csv").unlink(missing_ok=True)

    print("\n[PROFILE] Recommendations:")
    if timings.get("per_symbol_total", 0) > 1:
        print(f"  1. Use -w 4 or -w 8 for parallel workers (biggest win: ~4-8x speedup)")
    if timings.get("write_closed", 0) > 0.5:
        print(f"  2. write_brt_closed HIST_* is O(N*trades) - consider precomputing hist stats")
    if timings.get("compute_equity", 0) > 1:
        print(f"  3. compute_equity_metrics iterates all trades - _get_ticker_df does df.copy() per trade")
    return 0


if __name__ == "__main__":
    sys.exit(main())
