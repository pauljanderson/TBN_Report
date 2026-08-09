from pathlib import Path
import csv
import re

drive = Path(r"C:\Users\songg\Downloads\stockresearch\drive")
systems = ["BRT","YH","WPBR","RS","RL","MTS","IND","SB","MVCP","QULL","KELL","CS","VEC"]

def read_csv_rows(path):
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))

def pick_ann(row):
    for k in ("Ann_ROR","Annualized_ROR","Annualized_Return","AnnROR","ANNUALIZED_ROR"):
        if k in row and str(row[k]).strip() not in ("", "None"):
            return k, row[k]
    # case-insensitive
    for k,v in row.items():
        if k and ("ann" in k.lower() and "ror" in k.lower()) and str(v).strip() not in ("", "None"):
            return k, v
    return None, None

def pick_days(row):
    out = {}
    for k,v in row.items():
        if not k:
            continue
        kl = k.lower()
        if any(x in kl for x in ("avg_days","median_days","med_days","p90_days","avg days","median days")):
            if str(v).strip() not in ("", "None"):
                out[k] = v
    return out

def summarize_report(path):
    rows = read_csv_rows(path)
    if not rows:
        return {"n":0}
    cols = list(rows[0].keys())
    preferred = None
    for r in rows:
        vals = " ".join(str(r.get(c,"")) for c in cols[:5]).upper()
        if any(x in vals for x in ("TOTAL","PORTFOLIO","ALL","AGGREGATE")):
            preferred = r
            break
    r = preferred
    if r is None:
        # Prefer blank Param_Name / baseline
        for cand in rows:
            pn = str(cand.get("Param_Name","") or "")
            if pn in ("", "baseline", "Baseline", "CURRENT", "current", "n/a", "N/A"):
                _, v = pick_ann(cand)
                if v is not None:
                    r = cand
                    break
    if r is None:
        for cand in rows:
            _, v = pick_ann(cand)
            if v is not None:
                r = cand
                break
    if r is None:
        r = rows[0]
    ak, av = pick_ann(r)
    days = pick_days(r)
    extras = {}
    for k in ("Total_Trades","TOTAL_TRADES","Total_PNL","TOTAL_PNL","Wins","Losses","Profit_Factor","Max_DD","Expectancy","Avg_PNL_Pct","Timestamp_Drive","Param_Name","Param_Value","Symbol","SYMBOL"):
        if k in r and str(r[k]).strip() not in ("", "None"):
            extras[k] = r[k]
    return {
        "n": len(rows),
        "ann_key": ak,
        "ann": av,
        "days": days,
        "extras": extras,
        "ann_day_cols": [c for c in cols if c and (("ann" in c.lower() and "ror" in c.lower()) or "day" in c.lower())],
    }

def latest_stamp_for(sys):
    stamps = []
    for p in drive.glob(f"{sys}_Report_*.csv"):
        m = re.search(r"_(\d{12})\.csv$", p.name)
        if m:
            stamps.append((m.group(1), p))
    for p in drive.glob(f"{sys}_Audit_Report_*.csv"):
        m = re.search(r"_(\d{12})\.csv$", p.name)
        if m:
            stamps.append((m.group(1), p))
    if not stamps:
        return None, []
    stamps.sort(key=lambda x: x[0], reverse=True)
    return stamps[0][0], stamps

results = []
print("=== Per-system Latest Report Ann_ROR ===\n")
for sys in systems:
    stamp, all_stamps = latest_stamp_for(sys)
    paths = []
    # Prefer Audit_Report stamped, then Report, then LatestRun Summary aggregate
    if stamp:
        for stem in [f"{sys}_Audit_Report_{stamp}.csv", f"{sys}_Report_{stamp}.csv", f"{sys}_Summary_{stamp}.csv"]:
            p = drive / stem
            if p.exists():
                paths.append(p)
    for stem in [f"{sys}_LatestRun_Audit_Report.csv", f"{sys}_LatestRun_Summary.csv"]:
        p = drive / stem
        if p.exists() and p not in paths:
            paths.append(p)

    if not paths:
        print(f"{sys}: NO FILES")
        results.append({"sys": sys, "stamp": None, "ann": None, "note": "missing"})
        continue

    # Prefer Audit_Report / Report over Summary (Summary is often per-symbol)
    chosen = None
    for p in paths:
        if "Audit_Report" in p.name or re.search(rf"{sys}_Report_", p.name):
            chosen = p
            break
    if chosen is None:
        chosen = paths[0]

    s = summarize_report(chosen)
    # If Summary and n>1 with no TOTAL, try Report
    if s.get("ann") is None or (chosen.name.endswith("Summary.csv") and s["n"] > 5 and "TOTAL" not in str(s.get("extras",{}))):
        for p in paths:
            if p == chosen:
                continue
            s2 = summarize_report(p)
            if s2.get("ann") is not None:
                chosen, s = p, s2
                break

    # For multi-row reports that are metric-name/value style, detect
    if s.get("ann") is None:
        rows = read_csv_rows(chosen)
        # metric transpose style?
        for r in rows:
            joined = " ".join(str(x) for x in r.values()).lower()
            if "ann_ror" in joined or "annualized" in joined:
                print(f"  debug row: {r}")

    print(f"{sys} stamp={stamp} file={chosen.name}")
    print(f"  Ann={s.get('ann')} days={s.get('days')} extras={s.get('extras')} cols={s.get('ann_day_cols')}")
    # also show first 2 rows keys if needed
    rows = read_csv_rows(chosen)
    if s.get("ann") is None:
        print(f"  COLS: {list(rows[0].keys())[:50]}")
        print(f"  ROW0: { {k:rows[0][k] for k in list(rows[0].keys())[:15]} }")
        if len(rows)>1:
            print(f"  ROW1: { {k:rows[1][k] for k in list(rows[1].keys())[:15]} }")

    results.append({"sys": sys, "stamp": stamp, "file": chosen.name, **s})

# RS gold
print("\n=== RS gold 260807141317 ===")
for stem in ["RS_Audit_Report_260807141317.csv","RS_Report_260807141317.csv","RS_Summary_260807141317.csv"]:
    p = drive / stem
    if p.exists():
        print(stem, summarize_report(p))

# Peek Report structure
print("\n=== Sample BRT_Report head ===")
p = drive / "BRT_Report_260807154202.csv"
rows = read_csv_rows(p)
print("cols", list(rows[0].keys()))
for r in rows[:5]:
    print(r)

print("\n=== Sample BRT_Audit_Report head ===")
p = drive / "BRT_Audit_Report_260807154202.csv"
rows = read_csv_rows(p)
print("cols", list(rows[0].keys()))
for r in rows[:8]:
    print(r)
