#!/usr/bin/env python3
"""Diagnose TSLA raw-not-serialized fills post gate-bleed."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream

STAMP = "260722113454"
STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_gatebleed_20260722113454"
BASE = REPO / "drive" / "wpbr_sheet_reconcile" / "TSLA"

df = pd.read_csv(REPO / "data/newdata/data/TSLA.csv", index_col=0, parse_dates=True)
idx = pd.DatetimeIndex(df.index)
stream = compute_wpbr_touch_stream(
    df, band_pct=0.015, strong_pre_pivot_bars=3, strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3, strong_post_pivot_pct=0.10, strong_pivot_mode="either",
    breakout_confirmation=0.03, max_days_after_retest=2, retest_mode="stop_looking",
    zone_price_round_decimals=2,
)

def nd(s):
    try:
        return pd.Timestamp(str(s).strip()).strftime("%Y-%m-%d")
    except Exception:
        return None

def bar(b):
    try:
        b=int(b)
        return idx[b].strftime("%Y-%m-%d") if 0<=b<len(idx) else None
    except Exception:
        return None

raw=set()
for ev in stream["wpbr_zone_events"]:
    f=bar(ev.get("entry_fill_bar"))
    if f and f>="2016-01-01":
        raw.add(f)
for opp in stream.get("wpbr_entry_opportunities") or []:
    f=bar(opp.get("entry_fill_bar"))
    if f and f>="2016-01-01":
        raw.add(f)

closed=pd.read_csv(STAMP_DIR/f"WPBR_Closed_{STAMP}.csv")
closed=closed[closed.SYMBOL=="TSLA"]
ser=set(nd(x) for x in closed.DATE_OPENED)

# sheet trades
trades=[]
for line in (BASE/"trades.tsv").read_text(encoding="utf-8").splitlines():
    if line.startswith("Entry") or not line.strip() or line.strip()=="TSLA":
        continue
    c=line.split("\t")
    e=nd(c[0])
    if e:
        trades.append(e)

print("sheet trades", len(trades))
for e in trades:
    print(e, "raw", e in raw, "ser", e in ser)

print("\nraw not ser among sheet:")
for e in trades:
    if e in raw and e not in ser:
        # occupancy?
        occ=[]
        for _,r in closed.iterrows():
            a=nd(r.DATE_OPENED); b=nd(r.DATE_CLOSED)
            if a and b and a < e <= b:
                occ.append((a,b,r.EXIT_TYPE))
            elif a and a < e and (not b or b>=e):
                occ.append((a,b,r.EXIT_TYPE))
        print(" MISS", e, "occ", occ)

print("\neng-only rockets:")
zones=[]
for line in (BASE/"zones.tsv").read_text(encoding="utf-8").splitlines()[1:]:
    c=line.split("\t")+[""]*20
    piv=nd(c[9]); rocket=nd(c[18]) if c[18].strip() else None
    zones.append((piv, rocket))
eng={nd(ev["pivot_monday"]):(bar(ev.get("entry_signal_bar")), bar(ev.get("entry_fill_bar"))) for ev in stream["wpbr_zone_events"]}
for piv,rocket in zones:
    if piv and piv in eng:
        sig,fil=eng[piv]
        if not rocket and sig:
            print(piv, "sig", sig, "fill", fil)
