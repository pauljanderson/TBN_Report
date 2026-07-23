import pandas as pd

def parse_money(x):
    if pd.isna(x): return None
    s=str(x).replace("$","").replace(",","").strip()
    try: return float(s)
    except: return None

ohlc = pd.read_csv("drive/wpbr_sheet_reconcile/NVDA/sheet_ohlc.tsv", sep="\t")
ohlc["Date"] = pd.to_datetime(ohlc["Date"])
for c in ["Open","High","Low","Close"]:
    ohlc[c] = ohlc[c].map(parse_money)
sub = ohlc[(ohlc["Date"]>="2017-09-18") & (ohlc["Date"]<="2017-09-29")]
print("SHEET OHLC 2017-09-18..29")
print(sub.to_string(index=False))

eng = pd.read_csv("data/newdata/data/NVDA.csv")
eng["Date"] = pd.to_datetime(eng["Date"])
cols = {c.lower():c for c in eng.columns}
oc,hc,lc,cc = cols["open"], cols["high"], cols["low"], cols["close"]
es = eng[(eng["Date"]>="2017-09-18") & (eng["Date"]<="2017-09-29")][["Date",oc,hc,lc,cc]]
es.columns=["Date","Open","High","Low","Close"]
print("\nENGINE OHLC")
print(es.to_string(index=False))

zones = pd.read_csv("drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_2016_20260722161052/WPBR_ZONES_NVDA_260722161242.csv")
z = zones[zones["PIVOT_MONDAY"]=="2017-06-05"].iloc[0]
print("\nZONE:")
for k in ["PIVOT_MONDAY","ZONE_LOW","ZONE_HIGH","ZONE_CENTER","BREAKOUT_MONDAY","CONF_MONDAY","RETEST_BAR","ENTRY_SIGNAL_BAR","ENTRY_FILL_BAR","HAS_TRADE","WPBR_ZONE_ID"]:
    print(f"  {k}={z[k]}")

eng2 = eng.sort_values("Date").reset_index(drop=True)
# find offset: BAR_INDEX 1867 == 2017-06-05
pivot_idx = eng2.index[eng2["Date"]=="2017-06-05"][0]
print("pivot_idx", pivot_idx, "BAR_INDEX", z["BAR_INDEX"], "delta", int(z["BAR_INDEX"])-pivot_idx)
# Maybe BAR_INDEX is 0-based from full history including pre-csv? Or from a different start
# Try: date for RETEST_BAR via delta
delta = int(z["BAR_INDEX"]) - pivot_idx
for name,b in [("RETEST", int(z["RETEST_BAR"])), ("SIGNAL", int(z["ENTRY_SIGNAL_BAR"])), ("FILL", int(z["ENTRY_FILL_BAR"]))]:
    i = b - delta
    r = eng2.iloc[i]
    print(f"{name} bar={b} idx={i} date={r['Date'].date()} O={r[oc]:.4f} H={r[hc]:.4f} L={r[lc]:.4f} C={r[cc]:.4f}")

# Also check sheet row index 437 for retest
print("\nSheet retest row 437 => date should be 9/25/2017")
print("sheet row 437 (1-based?) Date:", ohlc.iloc[436]["Date"].date() if len(ohlc)>436 else "OOB")
print("sheet row 438:", ohlc.iloc[437]["Date"].date() if len(ohlc)>437 else "OOB")
print("sheet row 439:", ohlc.iloc[438]["Date"].date() if len(ohlc)>438 else "OOB")
# find index of 9/25
for d in ["2017-09-25","2017-09-26","2017-09-27","2017-09-28"]:
    m = ohlc.index[ohlc["Date"]==d]
    print(d, "0-based idx", int(m[0]) if len(m) else None, "1-based row", int(m[0])+2 if len(m) else None)  # +2 if header+1
