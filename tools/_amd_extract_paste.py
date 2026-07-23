#!/usr/bin/env python3
"""Extract AMD WPBR user paste from parent transcript -> AMD/ raw + section files.

AMD paste OHLC has no Date column (Open/High/Low/Close only, starts $2.7700).
Dates are aligned to engine AMD.csv bars from 2016-01-04 onward.
"""
import json
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "AMD"
DATA = REPO / "data" / "newdata" / "data" / "AMD.csv"
OUT.mkdir(parents=True, exist_ok=True)

lines = TRANSCRIPT.read_text(encoding="utf-8", errors="ignore").splitlines()
# Line 1341 = full AMD WPBR paste (2016+, Open/High/Low/Close $2.7700, 18 trades).
target = None
for i, ln in enumerate(lines):
    if (
        '"role":"user"' in ln
        and "Break out upper" in ln
        and "Weekly Date" in ln
        and "Entry Date" in ln
        and "6/19/2019" in ln
        and ("Open\\tHigh\\tLow\\tClose\\n$2.7700" in ln or "Open\tHigh\tLow\tClose\n$2.7700" in ln)
    ):
        target = ln
        print(f"using transcript line {i}")
        break
assert target, "no AMD WPBR paste found"
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
if text.startswith("AMD\n") or text.startswith("AMD\r\n"):
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


i_ohlc = find("Open\t")
if i_ohlc is None:
    i_ohlc = find("Date\t")
i_weekly = find("Weekly Date")
i_zones = find("Break out upper")
i_trades = find("Entry Date")
print("indices:", i_ohlc, i_weekly, i_zones, i_trades)
assert None not in (i_ohlc, i_weekly, i_zones, i_trades)


def section(a, b):
    rows = list(lines2[a:b])
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


ohlc_raw = section(i_ohlc, i_weekly)
weekly = section(i_weekly, i_zones)
zones = section(i_zones, i_trades)
trades = section(i_trades, len(lines2))

# Align dateless OHLC to engine calendar from 2016-01-04
eng = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index()
eng = eng.loc[eng.index >= "2016-01-01"]
n_data = len(ohlc_raw) - 1  # exclude header
print(f"sheet OHLC data rows={n_data}, engine bars from 2016={len(eng)}")
if n_data > len(eng):
    raise SystemExit(f"sheet has more OHLC rows ({n_data}) than engine ({len(eng)})")
dates = [d.strftime("%m/%d/%Y") for d in eng.index[:n_data]]
# Rebuild OHLC with Date column for downstream tools
ohlc = ["Date\tOpen\tHigh\tLow\tClose"]
hdr = ohlc_raw[0].split("\t")
# header may be Open/High/Low/Close without Date
for i, row in enumerate(ohlc_raw[1:]):
    cells = row.split("\t")
    # strip $ already present on some opens
    ohlc.append("\t".join([dates[i]] + cells[:4]))

# Also write ISO-dated csv for convenience
ohlc_iso_rows = ["Date,Open,High,Low,Close"]
for i, row in enumerate(ohlc_raw[1:]):
    cells = [c.strip().replace("$", "").replace(",", "") for c in row.split("\t")[:4]]
    d_iso = eng.index[i].strftime("%Y-%m-%d")
    ohlc_iso_rows.append(",".join([d_iso] + cells))


def to_csv(rows):
    out = []
    for r in rows:
        cells = r.split("\t")
        clean = [c.strip().replace("$", "").replace(",", "") for c in cells]
        out.append(",".join(clean))
    return "\n".join(out)


(OUT / "ohlc.tsv").write_text("\n".join(ohlc), encoding="utf-8")
(OUT / "zones.tsv").write_text("\n".join(zones), encoding="utf-8")
(OUT / "trades.tsv").write_text("\n".join(trades), encoding="utf-8")
(OUT / "sheet_weekly.tsv").write_text("\n".join(weekly), encoding="utf-8")
(OUT / "sheet_ohlc_iso.csv").write_text("\n".join(ohlc_iso_rows), encoding="utf-8")
(OUT / "_ohlc_date_align_note.txt").write_text(
    "Sheet OHLC had no Date column. Dates aligned 1:1 to "
    f"data/newdata/data/AMD.csv from {eng.index[0].date()} for {n_data} bars "
    f"(through {eng.index[n_data-1].date()}).\n",
    encoding="utf-8",
)

for name, rows in [
    ("ohlc", ohlc),
    ("weekly", weekly),
    ("zones", zones),
    ("trades", trades),
]:
    (OUT / f"sheet_{name}.tsv").write_text("\n".join(rows), encoding="utf-8")
    (OUT / f"sheet_{name}.csv").write_text(to_csv(rows), encoding="utf-8")
    print(f"{name}: rows(incl header)={len(rows)}")

# Quick OHLC open parity check vs engine
mism = 0
for i, row in enumerate(ohlc_raw[1:]):
    so = float(row.split("\t")[0].replace("$", "").replace(",", ""))
    eo = float(eng.iloc[i]["Open"])
    if abs(so - eo) > 0.02:
        mism += 1
        if mism <= 5:
            print(f"OHLC open mismatch {eng.index[i].date()}: sheet={so} eng={eo}")
print(f"OHLC open mismatches (±$0.02): {mism}/{n_data}")

print("\n--- trades ---")
for l in trades:
    print(l)
