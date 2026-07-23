#!/usr/bin/env python3
import pandas as pd
from pathlib import Path

REPO = Path(r"C:/Users/songg/Downloads/stockresearch")
df = pd.read_csv(REPO / "data/newdata/data/NFLX.csv")
df.columns = [c.lower().replace(" ", "_") for c in df.columns]
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date").sort_index()
sig_low = float(df.loc["2023-08-18", "low"])
entry = 40.22
print("sig_low", sig_low)
for mult in [0.89, 0.90, 0.91, 0.911, 0.912]:
    print(f"sig_low*{mult}={sig_low*mult:.4f} round2={round(sig_low*mult,2)}")
for mult in [0.89, 0.90, 0.901, 0.91]:
    print(f"entry*{mult}={entry*mult:.4f} round2={round(entry*mult,2)}")

stop = 36.24
for dt, r in df.loc["2023-08-22":"2023-10-13"].iterrows():
    o, l = float(r.open), float(r.low)
    if o <= stop or l <= stop:
        print(
            f"first touch stop=36.24 on {dt.date()} O={o:.3f} L={l:.3f} C={float(r.close):.3f} gap={o<=stop}"
        )
        break

stop2 = round(entry * 0.89, 2)
for dt, r in df.loc["2023-08-22":"2023-10-13"].iterrows():
    o, l = float(r.open), float(r.low)
    if o <= stop2 or l <= stop2:
        print(f"first touch stop={stop2} on {dt.date()} O={o:.3f} L={l:.3f} gap={o<=stop2}")
        break

print("min Low Aug22-Oct11", float(df.loc["2023-08-22":"2023-10-11", "low"].min()))
print("dates with L<=36.24 before 10/12:")
for dt, r in df.loc["2023-08-22":"2023-10-11"].iterrows():
    if float(r.low) <= 36.24:
        print(dt.date(), float(r.low))

# What if sheet uses Close<=stop with stop=sig_low*0.91?
sp91 = round(sig_low * 0.91, 2)
print(f"\nsp91={sp91}")
for dt, r in df.loc["2023-08-22":"2023-10-13"].iterrows():
    o, l, c = float(r.open), float(r.low), float(r.close)
    if o <= sp91:
        print(f"gap {dt.date()} O={o}")
        break
    if l <= sp91:
        print(f"touch Low {dt.date()} L={l} -> exit @{sp91}")
        break

# Check GOOGLEFINANCE-style: maybe sheet signal low differs
# CLOSE_ABOVE_DATE = 2023-08-18 is signal; Low from yahoo = 39.815
# If sheet rounds Low to 2dp first: 39.82 * 0.89 = 35.4398 -> 35.44 (matches eng)
# 39.82 * 0.91 = 36.2362 -> 36.24
print("39.82*0.91", round(39.82 * 0.91, 2))
print("39.81*0.91", round(39.81 * 0.91, 2))
print("39.815*0.91", round(39.815 * 0.91, 2))

# Could 36.24 be High of a later bar? 10/17 H=36.27
# Or maybe sheet exit formula uses INDEX of first day Close < entry*0.9?
thresh = entry * 0.90
print(f"\nfirst Close < entry*0.90 ({thresh:.2f}):")
for dt, r in df.loc["2023-08-22":"2023-10-13"].iterrows():
    if float(r.close) < thresh:
        print(dt.date(), float(r.close))
        break

# first Close < 36.24
print("first Close < 36.24:")
for dt, r in df.loc["2023-08-22":"2023-10-13"].iterrows():
    if float(r.close) < 36.24:
        print(dt.date(), "C", float(r.close), "O", float(r.open), "L", float(r.low))
        break
