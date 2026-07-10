#!/usr/bin/env python3
"""Find when sheet vs engine Main Row diverges per symbol."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compare_breakout_retest import _load_engine_csv, _load_sheet_tsv  # noqa: E402
from brt_sheet_breakout_ledgers import BRT_SHEET_BREAKOUT_LEDGER  # noqa: E402

run_id = sys.argv[1] if len(sys.argv) > 1 else "260621201750"
eng_path = ROOT / "drive" / f"BRT_breakout_and_retest_{run_id}.csv"

for sym in ["AAPL", "GOOGL", "AMZN", "TSLA"]:
    sheet = _load_sheet_tsv(BRT_SHEET_BREAKOUT_LEDGER[sym], sym)
    eng = _load_engine_csv(eng_path, sym)
    se = {(r.breakout_iso, r.zl, r.zu): r for r in sheet}
    pe = {}
    for r in eng:
        pe[(r.breakout_iso, round(r.zl, 2), round(r.zu, 2))] = r

    deltas: list[tuple[int, str, int, int]] = []
    for k, s in se.items():
        p = pe.get(k)
        if p:
            deltas.append((s.main_row - p.main_row, s.breakout_iso, s.main_row, p.main_row))

    if not deltas:
        print(f"{sym}: no zone-key matches")
        continue
    from collections import Counter

    c = Counter(d for d, *_ in deltas)
    print(f"\n{sym} MR delta (sheet - engine) on zone-key matches: {dict(c)}")
    first_off = [x for x in sorted(deltas, key=lambda t: t[1]) if x[0] != 0]
    if first_off:
        d, iso, sm, pm = first_off[0]
        print(f"  first mismatch: {iso} sheet MR{sm} eng MR{pm} delta={d}")
    else:
        print("  all zone-key matches agree on MR")
