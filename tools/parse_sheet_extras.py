#!/usr/bin/env python3
"""Parse sheet-paste windows and print the MTS gate columns by header name."""
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
tsv = _REPO / "tools" / "sheet_extras_windows.tsv"
lines = tsv.read_text().splitlines()
header = lines[0].split("\t")

def col(name: str) -> int:
    return header.index(name)

WANT = [
    ("Date", "Date"),
    ("Final pivot low", "FinalPL"),
    ("Pre-Strong Pivot Low", "PreStrPL"),
    ("Touch Price", "TouchPx"),
    ("Zone Lower", "ZoneLo"),
    ("Zone Upper", "ZoneHi"),
    ("Support test", "AK"),
    ("Support Evidence", "AM"),
    ("MTS buy", "BI"),
]
idxs = [(col(h), lbl) for h, lbl in WANT]

hdr = " ".join(f"{lbl:>9}" for _, lbl in idxs) + "  |  " + " ".join(f"{x:>7}" for x in ("DK", "DL", "DM", "DN"))
print(hdr)
print("-" * len(hdr))
for ln in lines[1:]:
    if not ln.strip():
        continue
    f = ln.split("\t")
    row = []
    for ci, _ in idxs:
        v = f[ci] if ci < len(f) else ""
        v = v.strip() or "."
        row.append(f"{v:>9}")
    tail = [x.strip() or "." for x in f[-4:]]
    print(" ".join(row) + "  |  " + " ".join(f"{x:>7}" for x in tail))
