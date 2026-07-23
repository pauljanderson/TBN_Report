#!/usr/bin/env python3
"""Extract AMZN WPBR user paste -> AMZN/ raw + section files."""
from pathlib import Path

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "AMZN"
OUT.mkdir(parents=True, exist_ok=True)

raw_path = OUT / "_raw_user_paste.txt"
assert raw_path.exists(), f"missing {raw_path}"
text = raw_path.read_text(encoding="utf-8")
if text.startswith("AMZN\n") or text.startswith("AMZN\r\n"):
    _, _, text = text.partition("\n")
    raw_path.write_text(text, encoding="utf-8")

lines2 = text.splitlines()
print("RAW chars:", len(text), "lines:", len(lines2))


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
assert None not in (i_ohlc, i_weekly, i_zones, i_trades)


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
        clean = [c.strip().replace("$", "").replace(",", "") for c in cells]
        out.append(",".join(clean))
    return "\n".join(out)


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

print("--- trades ---")
for l in trades:
    print(l)
