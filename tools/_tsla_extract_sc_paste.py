#!/usr/bin/env python3
"""Extract latest TSLA WPBR breakout+trade paste; keep existing OHLC/weekly."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "TSLA"
OUT.mkdir(parents=True, exist_ok=True)

lines = TRANSCRIPT.read_text(encoding="utf-8", errors="ignore").splitlines()
print(f"transcript lines: {len(lines)}")

# Prefer latest paste that has zones+trades with TSLA markers.
candidates: list[tuple[int, str]] = []
for i, ln in enumerate(lines):
    if '"role":"user"' not in ln:
        continue
    has_marker = (
        "18.23\\t18.23\\t17.69" in ln
        or "18.23\t18.23\t17.69" in ln
        or "3/1/2017\\t$16.95" in ln
        or "3/1/2017\t$16.95" in ln
    )
    has_sections = ("Break out upper" in ln) and ("Entry Date" in ln)
    if has_marker and has_sections:
        candidates.append((i, ln))

if not candidates:
    # Fallback: any user paste with Break out + Entry Date + TSLA context
    for i, ln in enumerate(lines):
        if '"role":"user"' not in ln:
            continue
        if "Break out upper" in ln and "Entry Date" in ln and (
            "TSLA" in ln or "18.23" in ln
        ):
            candidates.append((i, ln))

assert candidates, "no TSLA paste found"
i, target = candidates[-1]
print(f"using transcript line {i} ({len(candidates)} candidates)")

obj = json.loads(target)
text = "".join(
    b["text"]
    for b in obj["message"]["content"]
    if isinstance(b, dict) and b.get("type") == "text"
)
if "<user_query>" in text:
    text = text[text.find("<user_query>") + len("<user_query>") :]
if "</user_query>" in text:
    text = text[: text.find("</user_query>")]
text = text.strip()
for prefix in ("TSLA\n", "TSLA\r\n"):
    if text.startswith(prefix):
        text = text[len(prefix) :]
        break

(OUT / "_raw_user_paste.txt").write_text(text, encoding="utf-8")
print("RAW chars:", len(text))

rows = text.splitlines()
print("total lines:", len(rows))
print("first line:", repr(rows[0][:100]) if rows else None)


def find(prefix: str, start: int = 0) -> int | None:
    for j in range(start, len(rows)):
        if rows[j].strip().startswith(prefix):
            return j
    return None


i_ohlc = find("Date\t")
i_weekly = find("Weekly Date")
i_zones = find("Break out upper")
i_trades = find("Entry Date")
print("indices:", i_ohlc, i_weekly, i_zones, i_trades)
assert i_zones is not None and i_trades is not None, "missing zones/trades"


def section(a: int, b: int) -> list[str]:
    out = list(rows[a:b])
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


# Zones = from Break out header to Entry Date; trades = Entry Date to end
# If full paste includes OHLC/weekly, still only overwrite zones+trades.
if i_ohlc is not None and i_weekly is not None and i_ohlc < i_weekly < i_zones:
    zones = section(i_zones, i_trades)
else:
    zones = section(i_zones, i_trades)
trades = section(i_trades, len(rows))


def to_csv(tsv_rows: list[str]) -> str:
    out = []
    for r in tsv_rows:
        cells = r.split("\t")
        clean = [c.strip().replace("$", "").replace(",", "") for c in cells]
        out.append(",".join(clean))
    return "\n".join(out)


(OUT / "zones.tsv").write_text("\n".join(zones), encoding="utf-8")
(OUT / "trades.tsv").write_text("\n".join(trades), encoding="utf-8")
(OUT / "sheet_zones.tsv").write_text("\n".join(zones), encoding="utf-8")
(OUT / "sheet_trades.tsv").write_text("\n".join(trades), encoding="utf-8")
(OUT / "sheet_zones.csv").write_text(to_csv(zones), encoding="utf-8")
(OUT / "sheet_trades.csv").write_text(to_csv(trades), encoding="utf-8")

print(f"zones={len(zones)} trades={len(trades)} (OHLC/weekly left unchanged)")
print("--- zones head ---")
for l in zones[:3]:
    print(l[:140])
print("--- trades head ---")
for l in trades[:5]:
    print(l[:140])
print("--- trades tail ---")
for l in trades[-3:]:
    print(l[:140])
