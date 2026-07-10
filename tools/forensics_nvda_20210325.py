#!/usr/bin/env python3
"""Forensics for NVDA 2021-03-17 trade stop miss on 2021-03-25."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
meta = pd.read_csv(ROOT / "data" / "newdata" / "data" / "NVDA.csv", parse_dates=["Date"]).sort_values("Date")

def _closed_path(run_id: str) -> Path:
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"YH_Closed_{run_id}.csv"
        if p.exists():
            return p
    return ROOT / "Drive" / f"YH_Closed_{run_id}.csv"

run_id = sys.argv[1] if len(sys.argv) > 1 else "260620125648"
eng = pd.read_csv(_closed_path(run_id))
t = eng[(eng["SYMBOL"] == "NVDA") & (eng["CLOSE_ABOVE_DATE"].astype(str).str.startswith("2021-03-17"))].iloc[0]

print("=== TRADE ===")
for c in [
    "DATE_OPENED", "ENTRY_PRICE", "STOP_PRICE", "TARGET_PRICE", "DATE_CLOSED",
    "EXIT_PRICE", "EXIT_TYPE", "CLOSE_ABOVE_DATE", "BREAKOUT_DATE", "MATURITY_DATE", "DAYS_HELD",
]:
    print(f"  {c}: {t[c]}")

entry = float(t.ENTRY_PRICE)
stop = float(t.STOP_PRICE)
target = float(t.TARGET_PRICE)
print(f"\nentry={entry:.4f}  stop={stop:.4f}  ({(1-stop/entry)*100:.4f}% below entry)  target={target:.4f}")

print("\n=== OHLC WINDOW ===")
for d in [
    "2021-03-17", "2021-03-18", "2021-03-22", "2021-03-23",
    "2021-03-24", "2021-03-25", "2021-03-26", "2021-04-15",
]:
    r = meta[meta["Date"] == d].iloc[0]
    print(f"{d}  O={r.Open:.4f}  H={r.High:.4f}  L={r.Low:.4f}  C={r.Close:.4f}")

r25 = meta[meta["Date"] == "2021-03-25"].iloc[0]
entry_open = float(meta[meta["Date"] == "2021-03-18"].iloc[0].Open)
stop_from_open = entry_open * 0.934
print(f"\nEngine fill uses next-day OPEN: {entry_open:.6f}")
print(f"Stop from open*0.934 = {stop_from_open:.6f}  (CSV rounds to {stop:.2f})")
print(f"Stop from sheet entry 13.14*0.934 = {13.14 * 0.934:.6f}")
stop_round = 2
op_cmp = round(float(r25.Open), stop_round)
lo_cmp = round(float(r25.Low), stop_round)
sp_open = round(entry_open * 0.934, stop_round)
sp_csv = round(stop, stop_round)
print(f"\nWith stop_compare_round_decimals={stop_round}:")
print(f"  lo_cmp={lo_cmp} <= sp_open_cmp={sp_open}?  {lo_cmp <= sp_open}")
print(f"  lo_cmp={lo_cmp} <= sp_csv_cmp={sp_csv}?  {lo_cmp <= sp_csv}")
print(f"2021-03-25 low <= stop_from_open?  {r25.Low <= stop_from_open}")
print(f"2021-03-25 low <= sheet entry stop?  {r25.Low <= 13.14 * 0.934}")
print(f"2021-03-25 open {r25.Open:.6f} <= stop?  {r25.Open <= stop}  (GAP_DOWN)")
print(f"2021-03-25 close {r25.Close:.6f} <= stop?  {r25.Close <= stop}")

# trigger bar stop alternatives
trig = meta[meta["Date"] == "2021-03-17"].iloc[0]
for label, px in [("trigger close", trig.Close), ("trigger low", trig.Low), ("trigger open", trig.Open)]:
    s = px * 0.934
    print(f"alt stop from {label} {px:.4f} * 0.934 = {s:.4f}  | 3/25 low hits? {r25.Low <= s}")

# simulate day-by-day from entry 3/18
print("\n=== DAY-BY-DAY EXIT SIM (long, entry 3/18) ===")
sp, tp = stop, target
for d in pd.date_range("2021-03-18", "2021-04-16"):
    ds = d.strftime("%Y-%m-%d")
    if ds not in set(meta.Date.dt.strftime("%Y-%m-%d")):
        continue
    r = meta[meta["Date"] == ds].iloc[0]
    gd = r.Open <= sp
    sh = r.Low <= sp
    gu = r.Open >= tp
    th = r.High >= tp
    if gd:
        ex = "GAP_DOWN @ open"
    elif gu:
        ex = "GAP_UP @ open"
    elif sh:
        ex = "STOP_LOSS @ stop"
    elif th:
        ex = "TARGET @ target"
    else:
        ex = "-"
    if ex != "-":
        print(f"  {ds}  {ex}  (O={r.Open:.2f} L={r.Low:.2f} H={r.High:.2f})")
