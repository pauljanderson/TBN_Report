#!/usr/bin/env python3
"""Extract META weekly WPBR paste from parent chat transcript -> sheet_weekly.csv."""
import json
from pathlib import Path

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "META"

lines = TRANSCRIPT.read_text(encoding="utf-8", errors="ignore").splitlines()
target = None
for ln in lines:
    if "Qualified Pivot" in ln and '"role":"user"' in ln:
        target = ln
        break
assert target, "no weekly paste found"
obj = json.loads(target)
text = "".join(b["text"] for b in obj["message"]["content"] if b.get("type") == "text")

# isolate weekly table: from header line to end of tabular block
lines2 = text.splitlines()
start = None
end = None
for i, l in enumerate(lines2):
    if l.startswith("Weekly Date\t"):
        start = i
    elif start is not None and "\t" not in l and l.strip() and not l.strip().startswith("$"):
        # first non-tabular line after the table
        end = i
        break
if end is None:
    end = len(lines2)
weekly = lines2[start:end]
# drop trailing blanks
while weekly and not weekly[-1].strip():
    weekly.pop()

(OUT / "sheet_weekly.tsv").write_text("\n".join(weekly), encoding="utf-8")
# also CSV
csv_rows = [",".join(c.replace(",", "") for c in row.split("\t")) for row in weekly]
(OUT / "sheet_weekly.csv").write_text("\n".join(csv_rows), encoding="utf-8")
print("weekly rows (incl header):", len(weekly))
print("head:")
for l in weekly[:6]:
    print(l)
print("tail:")
for l in weekly[-4:]:
    print(l)
