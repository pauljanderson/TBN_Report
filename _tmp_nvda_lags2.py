# Confirm eng has no other lag-2 style eng-only; check 2023 blank zone on eng
import pandas as pd
z=pd.read_csv("drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_2016_20260722161052/WPBR_ZONES_NVDA_260722161242.csv")
# find zones with retest but no trade around 2023-11
for _,r in z.iterrows():
    # RETEST_BAR to date
    if int(r["RETEST_BAR"])<0: continue
    pass
eng=pd.read_csv("data/newdata/data/NVDA.csv"); eng["Date"]=pd.to_datetime(eng["Date"]); eng=eng.sort_values("Date").reset_index(drop=True)
# map
def bdate(b):
    b=int(b)
    if b<0 or b>=len(eng): return None
    return eng.iloc[b]["Date"].date()
print("Engine zones with retest, HAS_TRADE, signal:")
for _,r in z.iterrows():
    rb=int(r["RETEST_BAR"]); sb=int(r["ENTRY_SIGNAL_BAR"]); fb=int(r["ENTRY_FILL_BAR"])
    if rb<0: continue
    rd=bdate(rb); sd=bdate(sb) if sb>=0 else None; fd=bdate(fb) if fb>=0 else None
    lag = (eng.index[eng["Date"]==str(sd)][0]-rb) if sd is not None else None
    if sd is None or (lag is not None and lag>=1) or str(rd).startswith("2017") or str(rd).startswith("2023-11"):
        print(f"  pivot={r['PIVOT_MONDAY']} retest={rd} signal={sd} fill={fd} lag={lag} has_trade={r['HAS_TRADE']} zh={r['ZONE_HIGH']}")

# All eng signal lags
print("\nAll eng trades signal lags:")
for _,r in z.iterrows():
    rb=int(r["RETEST_BAR"]); sb=int(r["ENTRY_SIGNAL_BAR"])
    if rb<0 or sb<0: continue
    print(f"  pivot={r['PIVOT_MONDAY']} retest={bdate(rb)} signal={bdate(sb)} lag={sb-rb} has_trade={r['HAS_TRADE']}")
