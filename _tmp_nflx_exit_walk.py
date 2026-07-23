#!/usr/bin/env python3
"""Deep NFLX Aug-2023 exit bar walk: stop base, gap, close vs sheet 36.24."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))

STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_variantC_SC_2016_20260722145207"
DATA = REPO / "data" / "newdata" / "data"


def main():
    # OHLC
    ohlc = DATA / "NFLX.csv"
    if not ohlc.is_file():
        ohlc = next((REPO / "data").rglob("NFLX.csv"))
    df = pd.read_csv(ohlc)
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    closed = pd.read_csv(STAMP_DIR / "WPBR_Closed_260722145252.csv")
    row = closed[(closed.SYMBOL == "NFLX") & (closed.DATE_OPENED == 20230821)].iloc[0]
    print("ENGINE ROW:")
    for c in [
        "DATE_OPENED",
        "ENTRY_PRICE",
        "STOP_PRICE",
        "TARGET_PRICE",
        "DATE_CLOSED",
        "EXIT_PRICE",
        "EXIT_TYPE",
        "PNL_PCT",
        "WPBR_ZONE_ID",
        "BREAKOUT_DATE",
        "CLOSE_ABOVE_DATE",
        "MATURITY_DATE",
    ]:
        print(f"  {c}: {row.get(c)}")

    entry = float(row.ENTRY_PRICE)
    stop = float(row.STOP_PRICE)
    tgt = float(row.TARGET_PRICE)
    print(f"\nentry*0.89={entry*0.89:.4f}  eng_stop={stop:.4f}  stop/entry={stop/entry:.6f}")
    print(f"entry*1.22={entry*1.22:.4f}  eng_tgt={tgt:.4f}")

    # Infer stop base: stop / 0.89 should be signal low if trigger_low
    base = stop / 0.89
    print(f"implied stop base (stop/0.89)={base:.4f}")

    # Find bar whose Low ~= base near Aug 2023 signal (day before entry)
    win = df.loc["2023-08-01":"2023-08-22"]
    print("\nBars around entry (find signal low ~= stop base):")
    for dt, r in win.iterrows():
        mark = ""
        if abs(float(r.low) - base) < 0.05:
            mark = "  << LOW~=stop_base"
        if dt.strftime("%Y-%m-%d") == "2023-08-21":
            mark += "  ENTRY"
        print(
            f"  {dt.date()} O={r.open:.3f} H={r.high:.3f} L={r.low:.3f} C={r.close:.3f}{mark}"
        )

    # Walk Oct
    print("\n=== Oct 2023 bar walk vs eng_stop={:.2f} and entry*0.89={:.2f} ===".format(stop, entry * 0.89))
    e089 = entry * 0.89
    for dt, r in df.loc["2023-10-01":"2023-10-17"].iterrows():
        o, h, l, c = float(r.open), float(r.high), float(r.low), float(r.close)
        flags = []
        if o <= stop:
            flags.append("GAP@eng_stop->exit_OPEN")
        elif l <= stop:
            flags.append("TOUCH@eng_stop->exit_STOP_PX")
        if o <= e089:
            flags.append("GAP@entry*0.89")
        elif l <= e089:
            flags.append("TOUCH@entry*0.89")
        if h >= tgt:
            flags.append("TARGET")
        # sheet exit candidates
        if abs(c - 36.24) < 0.06:
            flags.append("C~=36.24")
        if abs(o - 36.24) < 0.06:
            flags.append("O~=36.24")
        if abs(l - 36.24) < 0.06:
            flags.append("L~=36.24")
        if abs(h - 36.24) < 0.06:
            flags.append("H~=36.24")
        print(
            f"  {dt.date()} O={o:.3f} H={h:.3f} L={l:.3f} C={c:.3f}  "
            f"L-engStop={l-stop:+.3f} L-e089={l-e089:+.3f}  {' | '.join(flags)}"
        )

    # What price is 36.24?
    print("\n=== Reverse-engineer sheet exit 36.24 ===")
    print(f"36.24/40.22 = {36.24/40.22:.6f} (not 0.89)")
    print(f"40.22-36.24 = {40.22-36.24:.2f} ({(40.22-36.24)/40.22*100:.2f}% drop)")
    # Maybe 2-dp round of something on 10/12
    b = df.loc["2023-10-12"]
    print(f"10/12 OHLC: O={b.open:.4f} H={b.high:.4f} L={b.low:.4f} C={b.close:.4f}")
    print(f"round(C,2)={round(float(b.close),2)} round(O,2)={round(float(b.open),2)}")
    # VWAP-ish?
    print(f"(H+L+C)/3={((b.high+b.low+b.close)/3):.4f}")
    print(f"(O+H+L+C)/4={((b.open+b.high+b.low+b.close)/4):.4f}")

    # Check if sheet might use stop_loss_based=entry_open with different mult
    for mult in [0.90, 0.901, 0.902, 0.91, 0.934, 0.95]:
        print(f"  entry*{mult}={entry*mult:.4f}")

    # Check prior day 10/11
    print("\n10/09-10/13 detail:")
    for d in ["2023-10-09", "2023-10-10", "2023-10-11", "2023-10-12", "2023-10-13"]:
        if pd.Timestamp(d) not in df.index:
            print(f"  {d} MISSING")
            continue
        r = df.loc[d]
        print(f"  {d} O={r.open:.4f} H={r.high:.4f} L={r.low:.4f} C={r.close:.4f}")

    # Engine exit simulation day-by-day from entry+1
    print("\n=== Engine exit priority simulation (gap > stop touch > target) ===")
    for dt, r in df.loc["2023-08-22":"2023-10-16"].iterrows():
        o, h, l, c = float(r.open), float(r.high), float(r.low), float(r.close)
        if o <= stop:
            print(f"  FIRST EXIT {dt.date()} GAP_DOWN @ open {o:.2f}")
            break
        if l <= stop:
            print(f"  FIRST EXIT {dt.date()} STOP_LOSS @ stop {stop:.2f} (L={l:.3f} C={c:.3f})")
            break
        if h >= tgt:
            print(f"  FIRST EXIT {dt.date()} TARGET @ {tgt:.2f}")
            break
    else:
        print("  no exit in range")

    # Same with entry*0.89 stop
    print("\n=== If stop were entry*0.89 = {:.4f} ===".format(e089))
    for dt, r in df.loc["2023-08-22":"2023-10-16"].iterrows():
        o, h, l, c = float(r.open), float(r.high), float(r.low), float(r.close)
        if o <= e089:
            print(f"  FIRST EXIT {dt.date()} GAP @ open {o:.2f}")
            break
        if l <= e089:
            print(f"  FIRST EXIT {dt.date()} STOP @ {e089:.2f} (L={l:.3f} C={c:.3f})")
            # would exit_at_close give 36.24? No this would be on 10/13
            print(f"    exit_at_close would be C={c:.2f}; exit_at_stop={e089:.2f}")
            break
        if h >= tgt:
            print(f"  FIRST EXIT {dt.date()} TARGET")
            break

    # Search any day where close rounds to 36.24 while in trade
    print("\n=== Days with close~=36.24 or open~=36.24 during trade ===")
    for dt, r in df.loc["2023-08-21":"2023-10-16"].iterrows():
        if abs(float(r.close) - 36.24) < 0.05 or abs(float(r.open) - 36.24) < 0.05:
            print(f"  {dt.date()} O={r.open:.3f} C={r.close:.3f}")

    # Maybe sheet uses GOOGLEFINANCE different OHLC on 10/12?
    # Check if 36.24 is 2dp of something from adj
    if "adj_close" in df.columns:
        print("\nadj_close 10/12:", df.loc["2023-10-12", "adj_close"])


if __name__ == "__main__":
    main()
