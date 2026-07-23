# For every sheet zone with BOTH retest and rocket, compute trading-day lag
import pandas as pd
from datetime import datetime
ohlc=pd.read_csv("drive/wpbr_sheet_reconcile/NVDA/sheet_ohlc.tsv", sep="\t")
ohlc["Date"]=pd.to_datetime(ohlc["Date"])
dates=list(ohlc["Date"])
idx={d:i for i,d in enumerate(dates)}

z=pd.read_csv("drive/wpbr_sheet_reconcile/NVDA/sheet_zones.tsv", sep="\t")
rows=[]
for _,r in z.iterrows():
    rt=str(r.get("Daily Retest Date","")).strip()
    rk=str(r.get("Rocket Buy Date","")).strip()
    if not rt or not rk or rt in ("#N/A","nan") or rk in ("#N/A","nan"):
        continue
    try:
        rtd=pd.to_datetime(rt); rkd=pd.to_datetime(rk)
    except: continue
    if rtd not in idx or rkd not in idx: 
        print("missing", rt, rk); continue
    lag=idx[rkd]-idx[rtd]
    rows.append((str(rtd.date()), str(rkd.date()), lag, r.get("Pivot Date"), r.get("Zone Lower"), r.get("Zone Upper")))
print("retest->rocket lags (trading days):")
for x in rows:
    print(x)
print("max lag", max(x[2] for x in rows) if rows else None)
print("lag value counts", pd.Series([x[2] for x in rows]).value_counts().to_dict())

# blank-rocket with retest: check if any green within 0..2 after retest
eng=pd.read_csv("data/newdata/data/NVDA.csv"); eng["Date"]=pd.to_datetime(eng["Date"]); eng=eng.sort_values("Date").reset_index(drop=True)
print("\nBlank-rocket zones with retest — green window:")
for _,r in z.iterrows():
    rt=str(r.get("Daily Retest Date","")).strip()
    rk=str(r.get("Rocket Buy Date","")).strip()
    if not rt or rt in ("#N/A","nan"): continue
    if rk and rk not in ("#N/A","nan"): continue
    rtd=pd.to_datetime(rt)
    m=eng.index[eng["Date"]==rtd]
    if len(m)==0: continue
    i=int(m[0])
    greens=[]
    for off in range(0,3):
        rr=eng.iloc[i+off]
        greens.append((str(rr["Date"].date()), bool(rr["Close"]>rr["Open"]), float(rr["Close"])))
    print(f"pivot={r.get('Pivot Date')} retest={rtd.date()} greens0..2={greens}")
