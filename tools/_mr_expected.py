#!/usr/bin/env python3
"""Compare sheet MR vs CSV idx+2 for each breakout date."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compare_breakout_retest import _load_sheet_tsv  # noqa: E402
from brt_sheet_breakout_ledgers import BRT_SHEET_BREAKOUT_LEDGER  # noqa: E402

sym = sys.argv[1] if len(sys.argv) > 1 else "GOOGL"
first_row = 2
df = pd.read_csv(ROOT / f"data/newdata/data/{sym}.csv", parse_dates=["Date"]).sort_values("Date")
date_to_idx = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df["Date"])}

sheet = _load_sheet_tsv(BRT_SHEET_BREAKOUT_LEDGER[sym], sym)
print(f"{sym}: sheet MR vs CSV idx+{first_row}")
first = None
for r in sheet:
    idx = date_to_idx.get(r.breakout_iso)
    if idx is None:
        continue
    exp = idx + first_row
    delta = r.main_row - exp
    if delta != 0 and first is None:
        first = (r.breakout_iso, r.main_row, exp, delta)
    if delta not in (0, -1):
        print(f"  unusual delta {delta}: {r.breakout_iso} sheet={r.main_row} exp={exp}")

if first:
    iso, sm, exp, d = first
    print(f"  first nonzero delta: {iso} sheet MR{sm} expected MR{exp} delta={d}")
else:
    print("  all match expected MR")

# count deltas
from collections import Counter

c = Counter()
for r in sheet:
    idx = date_to_idx.get(r.breakout_iso)
    if idx is None:
        continue
    c[r.main_row - (idx + first_row)] += 1
print(f"  delta counts: {dict(c)}")
