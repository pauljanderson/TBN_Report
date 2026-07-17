#!/usr/bin/env python3
"""IND average pre-pass: per-date cross-sectional average trade-aligned IND_DIFF.

Supports the ``use_average_ind`` IND entry gate in rocket_brt. Instead of a static
``indicator_diff`` threshold, a signal qualifies only when its trigger-bar IND_DIFF is
>= the average IND_DIFF across the run universe on that date.

Caching (incremental, reusable):
- The average for a (universe, date) pair is stable once computed, so results are cached
  on disk per universe and only *uncovered dates* are recomputed on later runs.
- Universe = the exact sorted set of symbols. Its SHA1 (16 hex) is the cache key.
- Cache file: ``<cache_dir>/ind_avg_<key>.csv`` with columns ``date,sum,count`` (avg = sum/count).
  A sidecar ``ind_avg_<key>.symbols.txt`` records the symbol list for identification.

Standalone use (run once; safe to re-run — only new dates are added):
    python stock_analysis/ind_avg_prepass.py --data-dir data/newdata/data -s "AAPL,MSFT,..."
    python stock_analysis/ind_avg_prepass.py --data-dir data/newdata/data          # all CSVs
    python stock_analysis/ind_avg_prepass.py --data-dir data/newdata/data --use-duckdb

rocket_brt calls get_or_build_avg_ind_diff_by_date() automatically when
``-v use_average_ind=true`` (indicator_buy=only/both), so the same cache is shared.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "ind_avg_cache"


def universe_key(symbols: Iterable[str]) -> str:
    """Stable 16-hex key for a universe (order-independent, case-insensitive)."""
    syms = sorted({str(s).strip().upper() for s in symbols if s and str(s).strip()})
    return hashlib.sha1((",".join(syms)).encode("utf-8")).hexdigest()[:16]


def _normalize_universe(symbols: Iterable[str]) -> list[str]:
    return sorted({str(s).strip().upper() for s in symbols if s and str(s).strip()})


def _norm_date(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    return str(d)[:10].replace("-", "")


def _cache_paths(cache_dir: Path, key: str) -> tuple[Path, Path]:
    return cache_dir / f"ind_avg_{key}.csv", cache_dir / f"ind_avg_{key}.symbols.txt"


def _load_cache(csv_path: Path) -> dict[str, list[float]]:
    """Return {date: [sum, count]} from an existing cache CSV (empty dict if none)."""
    out: dict[str, list[float]] = {}
    if not csv_path.exists():
        return out
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = str(row.get("date", "")).strip()
                if not d:
                    continue
                try:
                    out[d] = [float(row.get("sum", 0.0)), float(row.get("count", 0.0))]
                except (TypeError, ValueError):
                    continue
    except OSError:
        return {}
    return out


def _save_cache(csv_path: Path, sym_path: Path, cache: dict[str, list[float]], symbols: list[str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = csv_path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "sum", "count", "avg"])
        for d in sorted(cache.keys()):
            s, c = cache[d]
            avg = (s / c) if c else 0.0
            w.writerow([d, f"{s:.6f}", int(c), f"{avg:.6f}"])
    tmp.replace(csv_path)
    try:
        sym_path.write_text("\n".join(symbols) + "\n", encoding="utf-8")
    except OSError:
        pass


def get_or_build_avg_ind_diff_by_date(
    ticker_list: Iterable[str],
    load_df_fn: Callable[[str], Any],
    *,
    cfg: Optional[Any] = None,
    cache_dir: Optional[Path | str] = None,
    side: str = "LONG",
    verbose: bool = True,
) -> dict[str, float]:
    """Return {YYYYMMDD: mean trade-aligned IND_DIFF across the universe on that date}.

    Loads the per-universe disk cache and computes only dates not already covered, then
    updates the cache. ``load_df_fn(symbol)`` returns an OHLCV DataFrame (or None).
    """
    try:
        from brt_entry_indicators import (
            build_entry_indicator_precompute,
            aligned_bull_bear_diff,
        )
    except ImportError:
        from stock_analysis.brt_entry_indicators import (  # type: ignore
            build_entry_indicator_precompute,
            aligned_bull_bear_diff,
        )

    symbols = _normalize_universe(ticker_list)
    if not symbols:
        return {}
    key = universe_key(symbols)
    cdir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    csv_path, sym_path = _cache_paths(cdir, key)

    cache = _load_cache(csv_path)
    covered = set(cache.keys())

    ind_cache_dir = None
    ind_use_cache = True
    if cfg is not None:
        ind_cache_dir = (str(getattr(cfg, "indicator_cache_dir", "") or "").strip() or None)
        ind_use_cache = bool(getattr(cfg, "indicator_cache", True))

    new_sum: dict[str, float] = defaultdict(float)
    new_cnt: dict[str, int] = defaultdict(int)
    processed = 0
    skipped = 0
    t0 = time.time()
    for sym in symbols:
        try:
            df = load_df_fn(sym)
        except Exception:
            df = None
        if df is None or len(df) < 220:
            continue
        # Skip the (expensive) precompute build when every bar for this symbol is already
        # covered by the cache — the common case on re-runs with no new data.
        try:
            sym_dates = [_norm_date(d) for d in df.index]
        except Exception:
            sym_dates = []
        if sym_dates and all(ds in covered for ds in sym_dates):
            skipped += 1
            continue
        pre = build_entry_indicator_precompute(
            df, symbol=sym, cache_dir=ind_cache_dir, use_cache=ind_use_cache
        )
        if pre is None:
            continue
        processed += 1
        dates = pre.dates
        for i in range(len(dates)):
            ds = _norm_date(dates[i])
            if ds in covered:
                continue
            v = aligned_bull_bear_diff(pre, i, side)
            if v is None:
                continue
            new_sum[ds] += float(v)
            new_cnt[ds] += 1

    for ds, c in new_cnt.items():
        if c > 0:
            cache[ds] = [new_sum[ds], float(c)]

    if new_cnt:
        _save_cache(csv_path, sym_path, cache, symbols)

    if verbose:
        print(
            f"[ind_avg] universe {key} ({len(symbols)} symbols; {processed} computed, "
            f"{skipped} already-covered): {len(new_cnt)} new dates, {len(cache)} total cached "
            f"in {time.time() - t0:.1f}s -> {csv_path.name}",
            flush=True,
        )

    return {d: (s / c) for d, (s, c) in cache.items() if c > 0}


def _load_symbols_arg(symbol_arg: str) -> list[str]:
    """Parse -s as a comma/space list or a path to a file of symbols."""
    if not symbol_arg:
        return []
    p = Path(symbol_arg)
    if p.exists() and p.is_file():
        raw = p.read_text(encoding="utf-8")
    else:
        raw = symbol_arg
    parts: list[str] = []
    for chunk in raw.replace("\n", ",").replace(" ", ",").split(","):
        c = chunk.strip().upper()
        if c:
            parts.append(c)
    return parts


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build/update the per-date universe-average IND_DIFF cache (incremental)."
    )
    ap.add_argument("--data-dir", default="data/newdata/data", help="Directory of ticker CSVs")
    ap.add_argument(
        "-s", "--symbols", default="",
        help="Comma/space list or a file of symbols. Default: all CSVs in data-dir.",
    )
    ap.add_argument("--cache-dir", default=str(_DEFAULT_CACHE_DIR), help="Cache directory")
    ap.add_argument("--side", default="LONG", choices=["LONG", "SHORT"], help="Trade-aligned side")
    ap.add_argument("--use-duckdb", action="store_true", help="Load OHLCV from DuckDB store")
    ap.add_argument("--db-path", default="", help="DuckDB path (with --use-duckdb)")
    ap.add_argument("--db-table", default="prices", help="DuckDB table (with --use-duckdb)")
    ap.add_argument("--indicator-cache-dir", default="", help="Per-symbol indicator cache dir")
    args = ap.parse_args()

    try:
        from rocket_brt import _load_symbol_data, load_all_tickers_source
    except ImportError:
        from stock_analysis.rocket_brt import _load_symbol_data, load_all_tickers_source  # type: ignore

    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = _REPO_ROOT / data_dir

    symbols = _load_symbols_arg(args.symbols)
    if not symbols:
        if args.use_duckdb:
            tickers = load_all_tickers_source(
                str(data_dir), use_duckdb=True, db_path=args.db_path, db_table=args.db_table
            )
            symbols = sorted(tickers.keys())
        else:
            symbols = sorted(p.stem for p in data_dir.glob("*.csv"))
    if not symbols:
        print("[ind_avg] No symbols resolved; nothing to do.", file=sys.stderr)
        return 1

    class _Cfg:
        indicator_cache_dir = args.indicator_cache_dir
        indicator_cache = True

    def _loader(sym: str):
        return _load_symbol_data(
            sym, data_dir, use_duckdb=args.use_duckdb, db_path=args.db_path, db_table=args.db_table
        )

    m = get_or_build_avg_ind_diff_by_date(
        symbols, _loader, cfg=_Cfg(), cache_dir=args.cache_dir, side=args.side, verbose=True
    )
    if m:
        vals = list(m.values())
        print(
            f"[ind_avg] cache ready: {len(m)} dates, avg IND_DIFF range "
            f"{min(vals):.2f}..{max(vals):.2f}, mean {sum(vals) / len(vals):.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
