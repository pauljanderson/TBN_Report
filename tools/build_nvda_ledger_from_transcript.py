#!/usr/bin/env python3
"""Extract NVDA sheet breakout paste from agent transcript -> meta-format TSV."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\1779571378307\agent-transcripts"
    r"\112ffbb0-4126-4ba3-a226-b15b0081690a\112ffbb0-4126-4ba3-a226-b15b0081690a.jsonl"
)
OUT = ROOT / "tools" / "nvda_breakout_ledger_full.tsv"

HEADER = (
    "Breakout Date\tZone Lower\tZone Upper\tBreakout Active\tMain Row\t"
    "Scan Start Row\tretest Row\tRetest Date\tretest hit"
)


def _extract_paste(text: str) -> str:
    marker = "this is from the sheet\n"
    i = text.find(marker)
    if i < 0:
        raise RuntimeError("sheet paste marker not found in transcript")
    block = text[i + len(marker) :]
    end = block.find("\n\nhere is what we have in the engine")
    if end < 0:
        end = block.find("\n\nhere is what")
    if end < 0:
        raise RuntimeError("engine paste end marker not found")
    return block[:end].replace("\r\n", "\n").replace("\r", "\n").strip()


def main() -> None:
    if not TRANSCRIPT.is_file():
        raise SystemExit(f"Transcript not found: {TRANSCRIPT}")
    for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("role") != "user":
            continue
        parts = obj.get("message", {}).get("content", [])
        for part in parts:
            if part.get("type") != "text":
                continue
            text = part.get("text", "")
            if "Breakout Date\tZone Lower" in text and "5/18/2017\t$3.21" in text:
                paste = _extract_paste(text)
                lines = [ln for ln in paste.split("\n") if ln.strip()]
                if not lines:
                    raise RuntimeError("empty paste")
                # Drop duplicate header row from paste if present
                if lines[0].startswith("Breakout Date"):
                    body = lines[1:]
                else:
                    body = lines
                out_lines = [HEADER.rstrip("\n")] + body
                OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
                print(f"Wrote {len(body)} data rows -> {OUT}")
                return
    raise RuntimeError("NVDA paste message not found in transcript")


if __name__ == "__main__":
    main()
