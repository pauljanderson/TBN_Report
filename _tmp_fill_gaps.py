from pathlib import Path
import csv
import re

drive = Path(r"C:\Users\songg\Downloads\stockresearch\drive")

def row_from(path):
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    return rows

# MVCP/QULL - Ann_ROR empty?
for sys, stamp in [("MVCP","260803155516"),("QULL","260803155628"),("IND","260803155825")]:
    p = drive / f"{sys}_Audit_Report_{stamp}.csv"
    rows = row_from(p)
    r = rows[0]
    keys = ["Ann_ROR","Avg_Days_Held","Median_Days_Held","P90_Days","Total_Trades","Total_PNL","Profit_Factor","Max_DD"]
    print(sys, {k: repr(r.get(k)) for k in keys})
    # LatestRun?
    for stem in [f"{sys}_LatestRun_Audit_Report.csv", f"{sys}_LatestRun_Summary.csv"]:
        lp = drive/stem
        print(" ", stem, "exists", lp.exists(), "size", lp.stat().st_size if lp.exists() else None)

# KELL / CS
print("\n=== KELL LatestRun ===")
for stem in ["KELL_LatestRun_Audit_Report.csv","KELL_LatestRun_Summary.csv","KELL_LatestRun_Closed.csv"]:
    p = drive/stem
    print(stem, p.exists(), p.stat().st_size if p.exists() else None)
if (drive/"KELL_LatestRun_Audit_Report.csv").exists():
    rows = row_from(drive/"KELL_LatestRun_Audit_Report.csv")
    print("audit rows", len(rows), "keys", list(rows[0].keys())[:30])
    print(rows[0])

print("\n=== CS key/value audit ===")
rows = row_from(drive/"CS_Audit_Report_260803155644.csv")
kv = {r["key"]: r["value"] for r in rows if "key" in r}
for k in sorted(kv):
    if any(x in k.lower() for x in ("ann","day","trade","pnl","ror","median","hold")):
        print(k, kv[k])
print("all keys:", list(kv.keys())[:40])

# CS LatestRun
for stem in ["CS_LatestRun_Audit_Report.csv","CS_LatestRun_Summary.csv","CS_Report_260803155644.csv"]:
    p = drive/stem
    print(stem, p.exists())
    if p.exists() and "Summary" not in stem:
        rows = row_from(p)
        print("  ncols", len(rows[0]), "Ann", rows[0].get("Ann_ROR"), "Avg", rows[0].get("Avg_Days_Held"), "keys sample", [k for k in rows[0] if "Ann" in k or "Day" in k or "Trade" in k][:20])

# Check if IND LatestRun newer than Report stamp
print("\n=== IND LatestRun vs stamp ===")
for p in sorted(drive.glob("IND_*2608*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)[:15]:
    print(p.name, p.stat().st_size)

# VEC any files
print("\n=== VEC ===")
for p in sorted(drive.glob("VEC_*"))[:20]:
    print(p.name)

# Confirm RS LatestRun stamp vs gold - size match?
print("\n=== RS Closed sizes ===")
for s in ["260807141317","260807154639"]:
    p = drive/f"RS_Closed_{s}.csv"
    lr = drive/"RS_LatestRun_Closed.csv"
    print(s, "exists", p.exists(), "size", p.stat().st_size if p.exists() else None)
print("LatestRun Closed size", (drive/"RS_LatestRun_Closed.csv").stat().st_size)

# Freeze note file?
for p in Path(r"C:\Users\songg\Downloads\stockresearch").glob("**/rs*260807141317*"):
    print("freeze doc", p)
for p in drive.glob("*freeze*"):
    print("drive freeze", p.name)
