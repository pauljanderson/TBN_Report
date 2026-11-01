#!/usr/bin/env python3
"""Resample stored 1m parquet bars to 5/10/15/30-minute OHLCV (on demand).

Examples:
  python tools/resample_intraday.py -s SPY,AAPL --tf 5m
  python tools/resample_intraday.py -s SPY --tf 15m --cache
  python tools/resample_intraday.py -s AAPL --tf 30m --out-csv data/intraday/_scratch/AAPL_30m.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SA = _REPO / "stock_analysis"
if str(_SA) not in sys.path:
    sys.path.insert(0, str(_SA))

from intraday_1m import (  # noqa: E402
    DEFAULT_1M_DIR,
    RESAMPLE_RULES,
    resample_symbol_1m,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Resample stored 1m bars to coarser timeframes")
    ap.add_argument("-s", "--symbols", required=True, help="Comma-separated symbols")
    ap.add_argument(
        "--tf",
        "--timeframe",
        dest="timeframe",
        default="5m",
        help=f"Target timeframe: {', '.join(RESAMPLE_RULES)} or a pandas offset (e.g. 5min)",
    )
    ap.add_argument(
        "--in-dir",
        default=str(DEFAULT_1M_DIR),
        help="Directory with 1m parquet files (default: data/intraday/1m)",
    )
    ap.add_argument(
        "--cache",
        action="store_true",
        help="Also write resampled parquet under data/intraday/{tf}/",
    )
    ap.add_argument(
        "--cache-dir",
        default="",
        help="Override cache directory (default: data/intraday/{tf})",
    )
    ap.add_argument(
        "--out-csv",
        default="",
        help="Optional single-symbol CSV path (only valid with one symbol)",
    )
    ap.add_argument("--head", type=int, default=5, help="Print first N rows (0=skip)")
    args = ap.parse_args()

    symbols = [p.strip().upper() for p in args.symbols.replace(";", ",").split(",") if p.strip()]
    if not symbols:
        print("No symbols", file=sys.stderr)
        return 2
    if args.out_csv and len(symbols) != 1:
        print("--out-csv requires exactly one symbol", file=sys.stderr)
        return 2

    for sym in symbols:
        df = resample_symbol_1m(
            sym,
            args.timeframe,
            out_dir=args.in_dir,
            cache=bool(args.cache),
            cache_dir=args.cache_dir or None,
        )
        print(f"{sym} {args.timeframe}: {len(df)} bars", flush=True)
        if args.head and not df.empty:
            print(df.head(int(args.head)).to_string(index=False), flush=True)
        if args.out_csv:
            path = Path(args.out_csv)
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False)
            print(f"Wrote {path}", flush=True)
        if df.empty:
            print(f"[warn] no 1m data for {sym} under {args.in_dir}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
