#!/usr/bin/env python3
"""Extract NVDA user paste from parent transcript -> NVDA/ raw + section files."""
import json
from pathlib import Path

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "NVDA"
OUT.mkdir(parents=True, exist_ok=True)

lines = TRANSCRIPT.read_text(encoding="utf-8", errors="ignore").splitlines()
target = None
for ln in lines:
    if "Break out upper" in ln and '"role":"user"' in ln and "NVDA" in ln:
        target = ln
        break
assert target, "no NVDA paste found"
obj = json.loads(target)
text = "".join(b["text"] for b in obj["message"]["content"]
                if isinstance(b, dict) and b.get("type") == "text")
(OUT / "_raw_user_paste.txt").write_text(text, encoding="utf-8")
print("RAW chars:", len(text))

lines2 = text.splitlines()
print("total lines:", len(lines2))

def find(prefix, start=0):
    for i in range(start, len(lines2)):
        if lines2[i].strip().startswith(prefix):
            return i
    return None

i_ohlc = find("Date\t")
i_weekly = find("Weekly Date")
i_zones = find("Break out upper")
i_trades = find("Entry Date")
i_end = find("</user_query>")
print("indices:", i_ohlc, i_weekly, i_zones, i_trades, i_end)

def section(a, b):
    rows = [r for r in lines2[a:b]]
    # drop leading/trailing blank rows
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return rows

ohlc = section(i_ohlc, i_weekly)
weekly = section(i_weekly, i_zones)
zones = section(i_zones, i_trades)
trades = section(i_trades, i_end)

def to_csv(rows):
    out = []
    for r in rows:
        cells = r.split("\t")
        # strip $ and thousands-commas from cells
        clean = []
        for c in cells:
            c = c.strip().replace("$", "")
            # remove commas inside numbers like 1,059
            c2 = c.replace(",", "")
            clean.append(c2)
        out.append(",".join(clean))
    return "\n".join(out)

for name, rows in [("ohlc", ohlc), ("weekly", weekly),
                   ("zones", zones), ("trades", trades)]:
    (OUT / f"sheet_{name}.tsv").write_text("\n".join(rows), encoding="utf-8")
    (OUT / f"sheet_{name}.csv").write_text(to_csv(rows), encoding="utf-8")
    print(f"{name}: rows(incl header)={len(rows)}")

print("\n--- zones tail ---")
for l in zones[-3:]:
    print(l[:100])
print("--- trades ---")
for l in trades:
    print(l)
