#!/usr/bin/env python3
"""Fetch and incrementally upsert Yahoo Finance 1-minute bars to parquet.

Examples:
  python tools/fetch_intraday_1m.py -s SPY,AAPL --lookback-days 5
  python tools/fetch_intraday_1m.py --universe data/rl_gold_universe.txt --lookback-days 7
  python tools/fetch_intraday_1m.py --all --lookback-days 3   # all daily CSV symbols (slow)

See data/intraday/HOW_TO.md for Yahoo limits and schedule notes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SA = _REPO / "stock_analysis"
if str(_SA) not in sys.path:
    sys.path.insert(0, str(_SA))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from intraday_1m import (  # noqa: E402
    DEFAULT_1M_DIR,
    YF_1M_MAX_LOOKBACK_DAYS,
    resolve_symbols,
    upsert_symbol_1m,
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fetch yfinance 1m bars and upsert into data/intraday/1m/{SYMBOL}.parquet"
    )
    ap.add_argument(
        "-s",
        "--symbols",
        default="",
        help="Comma-separated symbols (e.g. SPY,AAPL)",
    )
    ap.add_argument(
        "--universe",
        default="",
        help="Universe file (one ticker per line; same rules as tools/load_universe_csv.py)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="All symbols with a daily CSV under --daily-data-dir (can be large / rate-limited)",
    )
    ap.add_argument(
        "--daily-data-dir",
        default=str(_REPO / "data" / "newdata" / "data"),
        help="Daily CSV directory used by --all (default: data/newdata/data)",
    )
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_1M_DIR),
        help="Output directory for 1m parquet files (default: data/intraday/1m)",
    )
    ap.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help=f"Calendar days to cover (capped at {YF_1M_MAX_LOOKBACK_DAYS}; Yahoo ~7d/request)",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.75,
        help="Seconds to sleep between request windows / symbols (rate limit)",
    )
    ap.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retries per window with exponential backoff",
    )
    ap.add_argument(
        "--force-full-window",
        action="store_true",
        help="Ignore stored max_ts; re-fetch the full lookback window (still upsert/dedupe)",
    )
    ap.add_argument(
        "--json-summary",
        default="",
        help="Optional path to write a JSON run summary",
    )
    args = ap.parse_args()

    sym_list = [p for p in args.symbols.replace(";", ",").split(",") if p.strip()] if args.symbols else []
    symbols = resolve_symbols(
        sym_list or None,
        universe_file=args.universe or None,
        all_from_daily=bool(args.all),
        daily_data_dir=args.daily_data_dir,
    )
    if not symbols:
        print("No symbols resolved. Pass -s, --universe, or --all.", file=sys.stderr)
        return 2

    lookback = max(1, min(int(args.lookback_days), YF_1M_MAX_LOOKBACK_DAYS))
    if int(args.lookback_days) > YF_1M_MAX_LOOKBACK_DAYS:
        print(
            f"[warn] lookback-days capped at {YF_1M_MAX_LOOKBACK_DAYS} (Yahoo 1m retention)",
            flush=True,
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Fetching 1m for {len(symbols)} symbol(s) -> {out_dir} "
        f"(lookback={lookback}d, sleep={args.sleep}s)",
        flush=True,
    )

    results = []
    t0 = time.time()
    for i, sym in enumerate(symbols):
        print(f"[{i + 1}/{len(symbols)}] {sym} ...", flush=True)
        summary = upsert_symbol_1m(
            sym,
            out_dir=out_dir,
            lookback_days=lookback,
            sleep_s=float(args.sleep),
            retries=int(args.retries),
            force_full_window=bool(args.force_full_window),
        )
        results.append(summary)
        err = f" errors={summary['errors']}" if summary.get("errors") else ""
        print(
            f"  rows {summary['rows_before']} -> {summary['rows_after']} "
            f"(fetched {summary['rows_fetched']}) "
            f"store {summary['min_ts']} .. {summary['max_ts']}{err}",
            flush=True,
        )
        if i + 1 < len(symbols) and args.sleep > 0:
            time.sleep(float(args.sleep))

    ok = sum(1 for r in results if r["rows_after"] > 0 and not r.get("errors"))
    partial = sum(1 for r in results if r.get("errors") and r["rows_after"] > 0)
    failed = sum(1 for r in results if r["rows_after"] == 0)
    elapsed = time.time() - t0
    print(
        f"Done in {elapsed:.1f}s: ok={ok} partial={partial} empty/failed={failed}",
        flush=True,
    )

    if args.json_summary:
        path = Path(args.json_summary)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Wrote summary {path}", flush=True)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
