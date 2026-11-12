#!/usr/bin/env python3
"""Compare sheet trade ledgers vs BRT_Closed (not YH_Closed)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from compare_sheet_trades import compare_symbol, DEFAULT_SYMBOLS  # noqa: E402


def _brt_closed(run_id: str) -> Path:
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"BRT_Closed_{run_id}.csv"
        if p.is_file():
            return p
    raise FileNotFoundError(f"BRT_Closed_{run_id}.csv")


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260626144407"
    symbols = [a.upper() for a in sys.argv[2:]] if len(sys.argv) > 2 else DEFAULT_SYMBOLS
    path = _brt_closed(run_id)
    print(f"Run: {run_id}  ({path.name})")
    eng_all = pd.read_csv(path)
    results = []
    for sym in symbols:
        results.append(compare_symbol(sym, eng_all, verbose=(len(symbols) == 1)))
    if len(symbols) > 1:
        print(f"\n{'Symbol':<8} {'Sheet':>5} {'Eng':>5} {'Exact':>5} {'Part':>5} {'S-only':>6} {'E-only':>6}")
        print("-" * 48)
        tot = dict(sheet_n=0, eng_n=0, exact=0, partial=0, sheet_only=0, eng_only=0)
        for r in results:
            print(
                f"{r['symbol']:<8} {r['sheet_n']:>5} {r['eng_n']:>5} {r['exact']:>5} "
                f"{r['partial']:>5} {r['sheet_only']:>6} {r['eng_only']:>6}"
            )
            for k in tot:
                tot[k] += r[k]
        print("-" * 48)
        print(
            f"{'TOTAL':<8} {tot['sheet_n']:>5} {tot['eng_n']:>5} {tot['exact']:>5} "
            f"{tot['partial']:>5} {tot['sheet_only']:>6} {tot['eng_only']:>6}"
        )
        ex = tot["exact"]
        sn = tot["sheet_n"]
        print(f"\nExact match: {ex}/{sn} ({100*ex/sn:.1f}%)" if sn else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
