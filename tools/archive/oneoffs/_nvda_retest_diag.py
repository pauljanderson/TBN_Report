#!/usr/bin/env python3
"""Diagnose the pivot 2017-06-05 retest 1-day diff (sheet 9/25 vs engine 9/26)."""
from pathlib import Path
import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
df = pd.read_csv(REPO / "data/newdata/data/NVDA.csv", index_col=0, parse_dates=True)
zl, zh = 4.14, 4.27  # sheet zone lower/upper for pivot 2017-06-05
win = df.loc["2017-09-18":"2017-10-02", ["Open", "High", "Low", "Close"]]
print("ENGINE NVDA.csv daily bars (zone_lower=%.2f zone_upper=%.2f):" % (zl, zh))
prev_c = None
for d, r in win.iterrows():
    low_in = r.Low <= zh
    close_ab = r.Close > zh
    prior_ok = (prev_c is None) or (prev_c >= zl)
    flag = []
    if low_in and close_ab:
        flag.append("WICK+HOLD")
    if prior_ok:
        flag.append("priorOK")
    print(f"  {d.date()} O={r.Open:.4f} H={r.High:.4f} L={r.Low:.4f} C={r.Close:.4f} "
          f"low<=up={low_in} close>up={close_ab} priorC={prev_c} -> {' '.join(flag)}")
    prev_c = r.Close

print("\n--- SHEET ohlc.tsv same window ---")
so = (REPO / "drive/wpbr_sheet_reconcile/NVDA/sheet_ohlc.tsv").read_text().splitlines()
for line in so:
    c = line.split("\t")
    if c and c[0] in ("Date",) or (len(c) >= 5 and "/2017" in c[0]
                                   and c[0].startswith(("9/2", "9/1", "10/"))):
        # match dates 9/18-10/2/2017
        try:
            d = pd.Timestamp(c[0])
        except Exception:
            continue
        if pd.Timestamp("2017-09-18") <= d <= pd.Timestamp("2017-10-02"):
            print("  " + "\t".join(c))
