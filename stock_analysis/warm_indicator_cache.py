#!/usr/bin/env python3
"""Pre-warm per-symbol indicator disk cache after OHLCV download.

Runs once after pygetallMore so backtests/optimizers hit warm .indcache.pkl files
instead of building indicator precompute on the first run of the day.

Incremental: only new/revised bars are recomputed (see brt_entry_indicators.py).

Usage:
    python stock_analysis/warm_indicator_cache.py data/newdata/data
    python stock_analysis/warm_indicator_cache.py data/newdata/data -w 6
    python stock_analysis/warm_indicator_cache.py data/newdata/data --use-duckdb
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _warm_one(args: tuple[str, str, str]) -> tuple[str, str]:
    sym, csv_path, cache_dir = args
    try:
        from rocket_brt import load_csv
        from brt_entry_indicators import build_entry_indicator_precompute
    except ImportError:
        from stock_analysis.rocket_brt import load_csv  # type: ignore
        from stock_analysis.brt_entry_indicators import build_entry_indicator_precompute  # type: ignore

    try:
        df = load_csv(csv_path)
    except Exception:
        return sym, "load_fail"
    if df is None or len(df) < 220:
        return sym, "short"
    pre = build_entry_indicator_precompute(
        df, symbol=sym, cache_dir=cache_dir or None, use_cache=True
    )
    return sym, "ok" if pre is not None else "fail"


def _warm_duckdb_sym(args: tuple[str, str, str, str, str]) -> tuple[str, str]:
    sym, data_dir_s, db_path, db_table, cache_dir = args
    try:
        from rocket_brt import _load_symbol_data
        from brt_entry_indicators import build_entry_indicator_precompute
    except ImportError:
        from stock_analysis.rocket_brt import _load_symbol_data  # type: ignore
        from stock_analysis.brt_entry_indicators import build_entry_indicator_precompute  # type: ignore

    df = _load_symbol_data(
        sym, Path(data_dir_s), use_duckdb=True, db_path=db_path, db_table=db_table
    )
    if df is None or len(df) < 220:
        return sym, "short"
    pre = build_entry_indicator_precompute(
        df, symbol=sym, cache_dir=cache_dir or None, use_cache=True
    )
    return sym, "ok" if pre is not None else "fail"


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-warm per-symbol indicator disk cache.")
    ap.add_argument("data_dir", nargs="?", default="data/newdata/data", help="OHLCV CSV directory")
    ap.add_argument("-w", "--workers", type=int, default=-1, help="Parallel workers (default: min(6, CPUs))")
    ap.add_argument("--use-duckdb", action="store_true", help="Load from DuckDB instead of CSV")
    ap.add_argument("--db-path", default="", help="DuckDB path (with --use-duckdb)")
    ap.add_argument("--db-table", default="prices", help="DuckDB table (with --use-duckdb)")
    ap.add_argument("--indicator-cache-dir", default="", help="Override indicator cache directory")
    ap.add_argument("-s", "--symbols", default="", help="Comma list or file of symbols (default: all CSVs)")
    args = ap.parse_args()

    try:
        from brt_entry_indicators import (
            format_indicator_cache_stats,
            get_indicator_cache_stats,
            reset_indicator_cache_stats,
            resolve_indicator_cache_dir,
        )
        from rocket_brt import _load_symbol_data, load_all_tickers_source
    except ImportError:
        from stock_analysis.brt_entry_indicators import (  # type: ignore
            format_indicator_cache_stats,
            get_indicator_cache_stats,
            reset_indicator_cache_stats,
            resolve_indicator_cache_dir,
        )
        from stock_analysis.rocket_brt import _load_symbol_data, load_all_tickers_source  # type: ignore

    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = _REPO_ROOT / data_dir

    cache_dir = resolve_indicator_cache_dir(
        args.indicator_cache_dir or None,
        repo_root=_REPO_ROOT,
        data_dir=data_dir,
    )

    symbols: list[str] = []
    if args.symbols.strip():
        p = Path(args.symbols)
        raw = p.read_text(encoding="utf-8") if p.exists() and p.is_file() else args.symbols
        symbols = sorted({c.strip().upper() for c in raw.replace("\n", ",").replace(" ", ",").split(",") if c.strip()})
    elif args.use_duckdb:
        tickers = load_all_tickers_source(
            str(data_dir), use_duckdb=True, db_path=args.db_path, db_table=args.db_table
        )
        symbols = sorted(tickers.keys())
    else:
        symbols = sorted(p.stem for p in data_dir.glob("*.csv") if p.stem.upper() != "XSPY")

    if not symbols:
        print("[warm_ind] No symbols found.", file=sys.stderr)
        return 1

    workers = int(args.workers)
    if workers < 0:
        workers = min(6, os.cpu_count() or 4)
    elif workers > 0:
        workers = min(workers, os.cpu_count() or 4)

    reset_indicator_cache_stats()
    t0 = time.time()
    ok = short = fail = load_fail = 0

    if args.use_duckdb:
        ddb_tasks = [
            (sym, str(data_dir), args.db_path, args.db_table, str(cache_dir)) for sym in symbols
        ]
        if workers > 1 and len(ddb_tasks) > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_warm_duckdb_sym, t): t[0] for t in ddb_tasks}
                done = 0
                for fut in as_completed(futs):
                    _, status = fut.result()
                    if status == "ok":
                        ok += 1
                    elif status == "short":
                        short += 1
                    else:
                        fail += 1
                    done += 1
                    if done % 100 == 0 or done == len(ddb_tasks):
                        print(f"[warm_ind] {done}/{len(ddb_tasks)} ...", flush=True)
        else:
            for i, task in enumerate(ddb_tasks, 1):
                _, status = _warm_duckdb_sym(task)
                if status == "ok":
                    ok += 1
                elif status == "short":
                    short += 1
                else:
                    fail += 1
                if i % 100 == 0 or i == len(ddb_tasks):
                    print(f"[warm_ind] {i}/{len(ddb_tasks)} ...", flush=True)
    else:
        tasks = [(sym, str(data_dir / f"{sym}.csv"), str(cache_dir)) for sym in symbols]
        if workers > 1 and len(tasks) > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_warm_one, t): t[0] for t in tasks}
                done = 0
                for fut in as_completed(futs):
                    _, status = fut.result()
                    if status == "ok":
                        ok += 1
                    elif status == "short":
                        short += 1
                    elif status == "load_fail":
                        load_fail += 1
                    else:
                        fail += 1
                    done += 1
                    if done % 100 == 0 or done == len(tasks):
                        print(f"[warm_ind] {done}/{len(tasks)} ...", flush=True)
        else:
            for i, task in enumerate(tasks, 1):
                _, status = _warm_one(task)
                if status == "ok":
                    ok += 1
                elif status == "short":
                    short += 1
                elif status == "load_fail":
                    load_fail += 1
                else:
                    fail += 1
                if i % 100 == 0 or i == len(tasks):
                    print(f"[warm_ind] {i}/{len(tasks)} ...", flush=True)

    elapsed = time.time() - t0
    stats = get_indicator_cache_stats()
    print(
        f"[warm_ind] Done in {elapsed:.1f}s: {ok} warmed, {short} short history, "
        f"{fail} failed, {load_fail} load errors | cache: {cache_dir}"
    )
    print(f"[warm_ind] {format_indicator_cache_stats(stats)}")
    return 0 if fail == 0 and load_fail == 0 else 0  # non-fatal: short history is normal


if __name__ == "__main__":
    raise SystemExit(main())
