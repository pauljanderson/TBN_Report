#!/usr/bin/env python3
from pathlib import Path

header = (Path(__file__).parent / "sheet_extras_windows.tsv").read_text().splitlines()[0].split("\t")
raw = (
    "12/21/2021\t$305.62\t313.17\t295.37\t312.84\t23,839,305\tFALSE\tFALSE\tTRUE\tFALSE\t"
    "\tFALSE\tTRUE\tTRUE\tTRUE\t\t\t\t\t\t$390.95\t$295.37\t\t\t\t\t\tLL\t\t"
    "Major Low\t\tTRUE\t$295.37\t$289.46\t$301.28\tFALSE\tFALSE\tFALSE\tTRUE\t"
    "TRUE\tTRUE\tTRUE\tTRUE\tTRUE\t1\tFALSE\t\t\tFALSE\tFALSE\tTRUE\t$414.50\t"
    "$254.53\t3\t29\t\t$392.71\tTRUE\t#REF!\tTRUE\t\tTRUE\t275.87558\t\tTRUE\t"
    "1.54\t\t\t$321.89\t12/21/2021\t0.00\t0.00%\t0.00%\tTRUE\tTRUE\tTRUE\tTRUE\t"
    "TRUE\tTRUE\tTRUE\tFALSE"
)
cols = raw.split("\t")
for name in ("magic touch event", "Range Qualifier", "MTS buy", "IN trade", "Entry Price Active"):
    j = header.index(name)
    print(f"{name:25s} [{j}] = {cols[j] if j < len(cols) else 'MISSING'}")
