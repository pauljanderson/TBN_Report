#!/usr/bin/env python3
"""Quick check: ensure each line in the data CSVs has exactly 7 columns (6 commas).
   Run from stock_analysis or pass path to data folder. Reports any line with wrong column count."""
import os
import sys

DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "newdata", "data"
)
EXPECTED_FIELDS = 7  # Date, Open, High, Low, Close, Adj Close, Volume

def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    if not os.path.isdir(data_dir):
        print(f"Not a directory: {data_dir}")
        return 1
    files = sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".csv"))
    print(f"Checking {len(files)} CSV files in {data_dir}")
    bad = []
    for f in files:
        path = os.path.join(data_dir, f)
        with open(path, "r", encoding="utf-8", errors="replace") as fp:
            for i, line in enumerate(fp, 1):
                n = len(line.strip().split(","))
                if n != EXPECTED_FIELDS:
                    bad.append((f, i, n, line.strip()[:80]))
    if not bad:
        print("OK: All lines have 7 columns (6 commas).")
        return 0
    print(f"Found {len(bad)} line(s) with wrong column count:")
    for fn, line_no, n, snippet in bad[:50]:
        print(f"  {fn}:{line_no} fields={n}  {snippet!r}")
    if len(bad) > 50:
        print(f"  ... and {len(bad) - 50} more")
    return 1

if __name__ == "__main__":
    sys.exit(main())
