#!/usr/bin/env python3
"""Extract META user paste (OHLC + zones + trades) from parent chat transcript."""
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
    if "Break out upper" in ln and '"role":"user"' in ln:
        target = ln
        break

assert target, "no user paste line found"
obj = json.loads(target)
text = ""
for block in obj["message"]["content"]:
    if block.get("type") == "text":
        text += block["text"]

raw = OUT / "_raw_user_paste.txt"
raw.write_text(text, encoding="utf-8")
print("RAW paste chars:", len(text))
print("first 200:", repr(text[:200]))

# Split sections. OHLC begins after "Date\tOpen\tHigh\tLow\tClose"
# Zones begins at line containing "Break out upper"
# Trades begins at "Entry Date\tEntry Price"
lines2 = text.splitlines()
idx_zone = None
idx_trades = None
for i, l in enumerate(lines2):
    if idx_zone is None and l.startswith("Break out upper"):
        idx_zone = i
    if idx_trades is None and l.startswith("Entry Date\tEntry Price"):
        idx_trades = i

print("total lines:", len(lines2))
print("idx_zone:", idx_zone, "idx_trades:", idx_trades)

# OHLC section: from first line to idx_zone
ohlc = lines2[:idx_zone] if idx_zone else lines2
zones = lines2[idx_zone:idx_trades] if idx_zone and idx_trades else (lines2[idx_zone:] if idx_zone else [])
trades = lines2[idx_trades:] if idx_trades else []

(OUT / "ohlc.tsv").write_text("\n".join(ohlc), encoding="utf-8")
(OUT / "zones.tsv").write_text("\n".join(zones), encoding="utf-8")
(OUT / "trades_paste.tsv").write_text("\n".join(trades), encoding="utf-8")
print("ohlc lines:", len(ohlc))
print("zones lines:", len(zones))
print("trades lines:", len(trades))
print("--- zones head ---")
for l in zones[:6]:
    print(l)
print("--- zones tail ---")
for l in zones[-6:]:
    print(l)
