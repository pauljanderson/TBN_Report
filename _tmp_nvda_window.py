# Simulate WPBR signal window after retest 2017-09-25
# Also check sheet rocket formula candidates on neighboring zones that DID fire
import pandas as pd
eng = pd.read_csv("data/newdata/data/NVDA.csv")
eng["Date"]=pd.to_datetime(eng["Date"])
eng=eng.sort_values("Date").reset_index(drop=True)
cc,oc="Close","Open"
# find first green within 0..2 trading days after retest (inclusive/exclusive variants)
retest_i = eng.index[eng["Date"]=="2017-09-25"][0]
print("retest_i", retest_i)
for label, start_off, end_off in [
    ("same_day_plus_2", 0, 2),
    ("next_day_plus_2", 1, 2),
    ("next_day_only_1", 1, 1),
    ("0_to_1", 0, 1),
]:
    hits=[]
    for off in range(start_off, end_off+1):
        i=retest_i+off
        r=eng.iloc[i]
        green=r[cc]>r[oc]
        hits.append((str(r["Date"].date()), green, float(r[oc]), float(r[cc])))
    print(label, hits)

# Check: does sheet require Close > zone_upper on signal day too?
zh_sheet=4.27
zh_eng=4.27
for d in ["2017-09-25","2017-09-26","2017-09-27"]:
    r=eng[eng["Date"]==d].iloc[0]
    print(f"signal-cand {d}: C={r[cc]:.4f} >zh_sheet {r[cc]>zh_sheet} >zh_eng {r[cc]>zh_eng} green={r[cc]>r[oc]}")

# Occupancy: any sheet trade open covering Sep 2017?
trades=pd.read_csv("drive/wpbr_sheet_reconcile/NVDA/sheet_trades.tsv", sep="\t")
print("\ntrades head:")
print(trades.head())
print("first sheet entry", trades.iloc[0]["Entry Date"] if len(trades) else None)
