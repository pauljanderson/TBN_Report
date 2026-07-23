# Check growth 3y and red-to-green gates around signal
import pandas as pd
eng = pd.read_csv("data/newdata/data/NVDA.csv")
eng["Date"] = pd.to_datetime(eng["Date"])
eng = eng.sort_values("Date").reset_index(drop=True)
cols = {c.lower():c for c in eng.columns}
oc,hc,lc,cc = cols["open"], cols["high"], cols["low"], cols["close"]

def row(d):
    i = eng.index[eng["Date"]==d][0]
    r = eng.iloc[i]
    return i, r

for d in ["2017-09-25","2017-09-26","2017-09-27","2017-09-28"]:
    i,r = row(d)
    prev = eng.iloc[i-1]
    green = r[cc] > r[oc]
    prior_red = prev[cc] <= prev[oc]
    # growth 3y ~756 trading days
    g = None
    if i >= 756:
        g = r[cc] >= eng.iloc[i-756][cc]
        gclose = eng.iloc[i-756][cc]
    else:
        gclose = None
    print(f"{d}: O={r[oc]:.4f} C={r[cc]:.4f} green={green} prior_redflat={prior_red} growth3y={g} close_3y_ago={gclose} idx={i}")

# sheet zones nearby for occupancy / competing rockets in Sep 2017
print("\nSheet zones with rockets before 2018-06:")
import csv
with open("drive/wpbr_sheet_reconcile/NVDA/sheet_zones.tsv", encoding="utf-8") as f:
    rdr = csv.DictReader(f, delimiter="\t")
    for row in rdr:
        rk = (row.get("Rocket Buy Date") or "").strip()
        rt = (row.get("Daily Retest Date") or "").strip()
        pd_ = (row.get("Pivot Date") or "").strip()
        zu = row.get("Zone Upper")
        zl = row.get("Zone Lower")
        if rk or (rt and "2017" in rt):
            print(f"  pivot={pd_} band={zl}-{zu} retest={rt!r} rocket={rk!r}")
