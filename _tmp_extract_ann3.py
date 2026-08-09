from pathlib import Path
import csv
import re

drive = Path(r"C:\Users\songg\Downloads\stockresearch\drive")

# Report files are often metric/value style (two columns) or wide audit rows
systems = ["BRT","YH","WPBR","RS","RL","MTS","IND","SB","MVCP","QULL","KELL","CS","VEC"]

def parse_report(path):
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {}
    header = rows[0]
    # Case A: wide DictReader style with Ann_ROR column
    if any("Ann_ROR" in (c or "") or "Annualized" in (c or "") for c in header):
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            dicts = list(csv.DictReader(f))
        # pick portfolio/total or first with Ann_ROR
        for r in dicts:
            blob = " ".join(str(v) for v in list(r.values())[:5]).upper()
            if "TOTAL" in blob or "PORTFOLIO" in blob:
                return r
        for r in dicts:
            if str(r.get("Ann_ROR","") or "").strip():
                return r
        return dicts[0] if dicts else {}
    # Case B: two-column Metric,Value
    out = {}
    for r in rows:
        if len(r) >= 2:
            out[r[0].strip()] = r[1].strip()
    # sometimes first row is header Metric,Value
    return out

def get_fields(d):
    if not d:
        return {}
    # normalize keys
    items = {str(k).strip(): str(v).strip() for k,v in d.items() if k is not None}
    def find(*names):
        for n in names:
            if n in items and items[n] not in ("", "None"):
                return items[n]
        # case-insensitive
        lower = {k.lower(): v for k,v in items.items()}
        for n in names:
            if n.lower() in lower and lower[n.lower()] not in ("", "None"):
                return lower[n.lower()]
        return None
    return {
        "Ann_ROR": find("Ann_ROR","Annualized_ROR","ANNUALIZED_ROR","Annualized Return","Annualized_Return"),
        "Avg_Days_Held": find("Avg_Days_Held","Avg_Days","Average_Days_Held","AVG_DAYS_HELD"),
        "Median_Days_Held": find("Median_Days_Held","Med_Days","Median_Days","MEDIAN_DAYS_HELD"),
        "P90_Days": find("P90_Days","P90_Days_Held"),
        "Total_Trades": find("Total_Trades","TOTAL_TRADES","Trades"),
        "Total_PNL": find("Total_PNL","TOTAL_PNL"),
        "Max_DD": find("Max_DD","MAX_DD"),
        "Profit_Factor": find("Profit_Factor","PROFIT_FACTOR"),
    }

def latest_stamp(sys):
    stamps = []
    for p in list(drive.glob(f"{sys}_Report_*.csv")) + list(drive.glob(f"{sys}_Audit_Report_*.csv")):
        m = re.search(r"_(\d{12})\.csv$", p.name)
        if m and "_RL_" not in p.name:
            stamps.append(m.group(1))
    return max(stamps) if stamps else None

print(f"{'Sys':6} {'Stamp':12} {'Ann_ROR':>10} {'AvgDays':>8} {'MedDays':>8} {'P90':>6} {'Trades':>8} file")
rows_out = []
for sys in systems:
    stamp = latest_stamp(sys)
    files = []
    if stamp:
        for stem in [f"{sys}_Report_{stamp}.csv", f"{sys}_Audit_Report_{stamp}.csv", f"{sys}_Summary_{stamp}.csv"]:
            p = drive / stem
            if p.exists():
                files.append(p)
    for stem in [f"{sys}_LatestRun_Audit_Report.csv", f"{sys}_LatestRun_Summary.csv"]:
        p = drive / stem
        if p.exists():
            files.append(p)
    if not files:
        print(f"{sys:6} {'—':12} missing")
        continue
    # prefer Report then Audit
    chosen = None
    fields = {}
    for p in files:
        d = parse_report(p)
        f = get_fields(d)
        if f.get("Ann_ROR") is not None:
            chosen = p
            fields = f
            if "Report" in p.name:
                break
    if chosen is None:
        chosen = files[0]
        fields = get_fields(parse_report(chosen))
        # debug
        d = parse_report(chosen)
        print(f"{sys:6} {stamp or '—':12} NO Ann in {chosen.name}; keys sample={list(d.keys())[:20]}")
        continue
    print(f"{sys:6} {stamp or '—':12} {fields.get('Ann_ROR'):>10} {fields.get('Avg_Days_Held') or '—':>8} {fields.get('Median_Days_Held') or '—':>8} {fields.get('P90_Days') or '—':>6} {fields.get('Total_Trades') or '—':>8} {chosen.name}")
    rows_out.append((sys, stamp, fields, chosen.name))

print("\n=== RS gold freeze 260807141317 ===")
for stem in ["RS_Report_260807141317.csv","RS_Audit_Report_260807141317.csv"]:
    p = drive / stem
    if p.exists():
        print(stem, get_fields(parse_report(p)))

# Also show raw Report for BRT and RL to confirm format
print("\n=== RAW BRT_Report first 40 lines ===")
p = drive/"BRT_Report_260807154202.csv"
print(p.read_text(encoding="utf-8", errors="replace")[:2500])

print("\n=== RAW RL_Report first 40 lines ===")
p = drive/"RL_Report_260807154158.csv"
print(p.read_text(encoding="utf-8", errors="replace")[:2500])

print("\n=== RAW IND_Report ===")
p = drive/"IND_Report_260803155825.csv"
print(p.read_text(encoding="utf-8", errors="replace")[:2500])
