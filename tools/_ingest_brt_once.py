import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from ingest_mag7_sheet_paste import parse_multisymbol_paste, write_ledgers

p = Path(
    r"C:\Users\songg\.cursor\projects\1779571378307\agent-transcripts"
    r"\112ffbb0-4126-4ba3-a226-b15b0081690a\112ffbb0-4126-4ba3-a226-b15b0081690a.jsonl"
)
best = None
with p.open("r", encoding="utf-8") as f:
    for line in f:
        if '"role":"user"' not in line:
            continue
        if "$46.24" not in line or "Breakout Date" not in line:
            continue
        best = json.loads(line)["message"]["content"][0]["text"]
if not best:
    raise SystemExit("paste line not found")
parsed = parse_multisymbol_paste(best)
write_ledgers(parsed, brt_tab=True)
for sym, d in sorted(parsed.items()):
    print(sym, "zones", len(d.get("zone_rows", [])), "brt", max(0, len(d.get("brt_lines", [])) - 1))
