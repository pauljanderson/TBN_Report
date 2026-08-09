from pathlib import Path
import csv
import re
from collections import defaultdict

drive = Path(r"C:\Users\songg\Downloads\stockresearch\drive")
systems = ["BRT","YH","WPBR","RS","RL","MTS","IND","SB","MVCP","QULL","KELL","CS","VEC","DB"]

def read_csv_rows(path):
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))

def pick_ann(row):
    for k in ("Ann_ROR","Annualized_ROR","Annualized_Return","AnnROR"):
        if k in row and row[k] not in (None,""):
            return k, row[k]
    return None, None

def pick_days(row):
    out = {}
    for k in ("Avg_Days_Held","Median_Days_Held","P90_Days","Avg_Days","Med_Days","Median_Days"):
        if k in row and row[k] not in (None,""):
            out[k] = row[k]
    return out

def summarize_report(path):
    rows = read_csv_rows(path)
    if not rows:
        return {"n":0}
    # Prefer Total/ALL/portfolio row if present
    preferred = None
    for r in rows:
        key = " ".join(str(r.get(c,"")) for c in r.keys()[:3]).upper()
        if any(x in key for x in ("TOTAL","PORTFOLIO","ALL","AGGREGATE","SUMMARY")):
            preferred = r
            break
    # Or last row often is total
    r = preferred or rows[-1] if len(rows)==1 else (preferred or rows[0])
    # If multi-row audit, look for Param_Name empty or 'baseline'
    if preferred is None and len(rows) > 1:
        for cand in rows:
            pn = str(cand.get("Param_Name","") or "")
            if pn in ("", "baseline", "Baseline", "CURRENT", "current"):
                r = cand
                break
        else:
            # take row with max Ann_ROR? No - take first non-empty Ann
            for cand in rows:
                _, v = pick_ann(cand)
                if v is not None:
                    r = cand
                    break
    ak, av = pick_ann(r)
    days = pick_days(r)
    # also collect interesting fields
    extras = {}
    for k in ("Total_Trades","Total_PNL","Wins","Losses","Profit_Factor","Max_DD","Expectancy","Avg_PNL_Pct","Timestamp_Drive","Param_Name","Param_Value"):
        if k in r and r[k] not in (None,""):
            extras[k] = r[k]
    return {"n": len(rows), "ann_key": ak, "ann": av, "days": days, "extras": extras, "cols": list(rows[0].keys())[:40], "sample_keys_ann": [c for c in rows[0].keys() if "ann" in c.lower() or "ror" in c.lower() or "day" in c.lower()]}

print("=== LatestRun Report / Audit / Summary ===")
for sys in systems:
    candidates = []
    for stem in [f"{sys}_LatestRun_Summary.csv", f"{sys}_LatestRun_Audit_Report.csv", f"{sys}_LatestRun_Report.csv"]:
        p = drive / stem
        if p.exists():
            candidates.append(p)
    # stamped reports matching LatestRun via size or newest
    stamped = sorted(drive.glob(f"{sys}_Report_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    audit = sorted(drive.glob(f"{sys}_Audit_Report_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    summ = sorted(drive.glob(f"{sys}_Summary_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if stamped and stamped[0] not in candidates:
        candidates.append(stamped[0])
    if audit and audit[0] not in candidates:
        candidates.append(audit[0])
    if summ and summ[0] not in candidates and f"{sys}_LatestRun_Summary.csv" not in [c.name for c in candidates]:
        candidates.append(summ[0])

    print(f"\n## {sys}")
    if not candidates and not stamped and not summ:
        print("  (no Report/Summary found)")
        continue
    for p in candidates[:3]:
        try:
            s = summarize_report(p)
            print(f"  {p.name}: ann={s.get('ann')} days={s.get('days')} extras={s.get('extras')} ann_cols={s.get('sample_keys_ann')}")
        except Exception as e:
            print(f"  {p.name}: ERROR {e}")

# RS gold freeze
print("\n=== RS gold freeze 260807141317 ===")
for pat in ["RS_Report_260807141317.csv","RS_Audit_Report_260807141317.csv","RS_Summary_260807141317.csv","RS_Closed_260807141317.csv"]:
    p = drive / pat
    print(f"  {pat}: exists={p.exists()}")
    if p.exists() and "Closed" not in pat:
        print("   ", summarize_report(p))

# Check freeze folder / tools freeze
freeze_docs = list(drive.glob("*260807141317*")) + list(Path(r"C:\Users\songg\Downloads\stockresearch").glob("**/*260807141317*"))
print("\nfreeze files sample:")
for p in sorted(set(freeze_docs), key=lambda x: str(x))[:40]:
    print(" ", p)
