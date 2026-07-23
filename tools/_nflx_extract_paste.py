#!/usr/bin/env python3
"""Extract NFLX WPBR user paste from parent transcript -> NFLX/ raw + section files."""
import json
from pathlib import Path

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "NFLX"
OUT.mkdir(parents=True, exist_ok=True)

lines = TRANSCRIPT.read_text(encoding="utf-8", errors="ignore").splitlines()
# Prefer latest full NFLX WPBR paste (2016+ with Weekly + Break out upper).
target = None
for ln in lines:
    if (
        '"role":"user"' in ln
        and "Break out upper" in ln
        and "Weekly Date" in ln
        and ("NFLX\\nDate\\tOpen" in ln or "NFLX\\r\\nDate\\tOpen" in ln or "NFLX\\nDate" in ln)
        and "1/4/2016\\t$10.9000" in ln
    ):
        target = ln
assert target, "no NFLX WPBR paste found"
obj = json.loads(target)
text = "".join(
    b["text"] for b in obj["message"]["content"]
    if isinstance(b, dict) and b.get("type") == "text"
)
if "<user_query>" in text:
    text = text[text.find("<user_query>") + len("<user_query>"):]
if "</user_query>" in text:
    text = text[: text.find("</user_query>")]
text = text.strip()
if text.startswith("NFLX\n") or text.startswith("NFLX\r\n"):
    _, _, text = text.partition("\n")

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
print("indices:", i_ohlc, i_weekly, i_zones, i_trades)


def section(a, b):
    rows = list(lines2[a:b])
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


ohlc = section(i_ohlc, i_weekly)
weekly = section(i_weekly, i_zones)
zones = section(i_zones, i_trades)
trades = section(i_trades, len(lines2))


def to_csv(rows):
    out = []
    for r in rows:
        cells = r.split("\t")
        clean = []
        for c in cells:
            c = c.strip().replace("$", "")
            c2 = c.replace(",", "")
            clean.append(c2)
        out.append(",".join(clean))
    return "\n".join(out)


# Mirror META naming (ohlc/zones/trades.tsv) + NVDA sheet_*.csv
(OUT / "ohlc.tsv").write_text("\n".join(ohlc), encoding="utf-8")
(OUT / "zones.tsv").write_text("\n".join(zones), encoding="utf-8")
(OUT / "trades.tsv").write_text("\n".join(trades), encoding="utf-8")
(OUT / "sheet_weekly.tsv").write_text("\n".join(weekly), encoding="utf-8")

for name, rows in [
    ("ohlc", ohlc),
    ("weekly", weekly),
    ("zones", zones),
    ("trades", trades),
]:
    (OUT / f"sheet_{name}.tsv").write_text("\n".join(rows), encoding="utf-8")
    (OUT / f"sheet_{name}.csv").write_text(to_csv(rows), encoding="utf-8")
    print(f"{name}: rows(incl header)={len(rows)}")

print("\n--- zones tail ---")
for l in zones[-3:]:
    print(l[:120])
print("--- trades ---")
for l in trades:
    print(l)
