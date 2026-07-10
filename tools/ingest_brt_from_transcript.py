#!/usr/bin/env python3
"""Fast ingest: read latest MAG7 BRT paste from agent transcript tail."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from ingest_mag7_sheet_paste import parse_multisymbol_paste, write_ledgers  # noqa: E402

TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\1779571378307\agent-transcripts\112ffbb0-4126-4ba3-a226-b15b0081690a\112ffbb0-4126-4ba3-a226-b15b0081690a.jsonl"
)
MARKER = "Matured touch price\tMatured Zone lower\tMatured zone upper"


def main() -> None:
    if not TRANSCRIPT.is_file():
        print(f"Missing transcript: {TRANSCRIPT}", file=sys.stderr)
        sys.exit(1)
    best: str | None = None
    with TRANSCRIPT.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        chunk = min(size, 12_000_000)
        f.seek(max(0, size - chunk))
        tail = f.read().decode("utf-8", errors="replace")
    for line in reversed(tail.splitlines()):
        if '"role":"user"' not in line or "AAPL" not in line or MARKER not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        txt = obj["message"]["content"][0]["text"]
        if "Breakout Date" in txt and "MSFT" in txt:
            best = txt
            break
    if not best:
        print("No BRT paste found in transcript tail", file=sys.stderr)
        sys.exit(1)
    parsed = parse_multisymbol_paste(best)
    write_ledgers(parsed, brt_tab=True)


if __name__ == "__main__":
    main()
