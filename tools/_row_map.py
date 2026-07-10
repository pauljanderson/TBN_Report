#!/usr/bin/env python3
"""Map Excel Main Row to bar index; find row-count drift."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sym = sys.argv[1] if len(sys.argv) > 1 else "GOOGL"
df = pd.read_csv(ROOT / f"data/newdata/data/{sym}.csv", parse_dates=["Date"]).sort_values("Date")

checks = ["2016-10-19", "2023-03-16", "2023-03-17", "2023-03-20"]
first_row = 2
for d in checks:
    ts = pd.Timestamp(d)
    if ts not in set(df["Date"]):
        print(f"{d}: MISSING from CSV")
        continue
    idx = df.index[df["Date"] == ts][0]
    print(f"{d}: pandas_idx={idx} excel_MR={idx + first_row} (first_row={first_row})")

# Find duplicate dates or gaps around Mar 2023
sub = df[(df["Date"] >= "2023-03-01") & (df["Date"] <= "2023-03-31")][["Date"]]
print(f"\nMar 2023 bars in {sym} CSV: {len(sub)}")
