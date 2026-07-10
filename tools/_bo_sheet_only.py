#!/usr/bin/env python3
"""Categorize AMZN/TSLA sheet-only BO rows (date+zone misses)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compare_breakout_retest import _load_engine_csv, _load_sheet_tsv  # noqa: E402
from brt_sheet_breakout_ledgers import BRT_SHEET_BREAKOUT_LEDGER  # noqa: E402


def analyze(sym: str, run_id: str) -> None:
    eng_path = ROOT / "drive" / f"BRT_breakout_and_retest_{run_id}.csv"
    sheet = _load_sheet_tsv(BRT_SHEET_BREAKOUT_LEDGER[sym], sym)
    eng = _load_engine_csv(eng_path, sym)

    def zk(r):
        return (r.breakout_iso, round(r.zl, 2), round(r.zu, 2))

    sm = {zk(r): r for r in sheet}
    pm = {zk(r): r for r in eng}
    by_date_s = {}
    by_date_p = {}
    for r in sheet:
        by_date_s.setdefault(r.breakout_iso, []).append(r)
    for r in eng:
        by_date_p.setdefault(r.breakout_iso, []).append(r)

    only_s = set(sm) - set(pm)
    print(f"\n{sym}: {len(only_s)} sheet-only date+zone keys")
    same_date_diff_zone = 0
    no_engine_date = 0
    for k in sorted(only_s)[:20]:
        r = sm[k]
        eng_same = by_date_p.get(r.breakout_iso, [])
        if not eng_same:
            no_engine_date += 1
            print(f"  NO ENG DATE {r.breakout_mdy} ${r.zl:.2f}/${r.zu:.2f}")
        else:
            same_date_diff_zone += 1
            ez = [(round(x.zl, 2), round(x.zu, 2)) for x in eng_same]
            print(f"  DATE OK {r.breakout_mdy} sheet ${r.zl:.2f}/${r.zu:.2f}  eng zones {ez[:3]}")
    print(f"  (sample) same_date_diff_zone={same_date_diff_zone} no_engine_date={no_engine_date}")


if __name__ == "__main__":
    run = sys.argv[1] if len(sys.argv) > 1 else "260621201750"
    for s in ["AMZN", "TSLA", "MSFT"]:
        analyze(s, run)
