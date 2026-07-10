#!/usr/bin/env python3
"""Compare TSLA engine vs sheet trade log (trigger D -> purchase D+1)."""
from __future__ import annotations

import sys

from compare_sheet_trades import compare_symbol, _closed_path

import pandas as pd


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260621083209"
    print(f"Run: {run_id}")
    eng_all = pd.read_csv(_closed_path(run_id))
    compare_symbol("TSLA", eng_all, verbose=True)


if __name__ == "__main__":
    main()
