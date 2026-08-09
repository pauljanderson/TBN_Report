from pathlib import Path
import csv
import statistics as stats

drive = Path(r"C:\Users\songg\Downloads\stockresearch\drive")

def days_from_closed(path, limit=None):
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    # find days column
    if not rows:
        return None
    cols = list(rows[0].keys())
    day_col = None
    for c in cols:
        cl = c.lower()
        if cl in ("days_held","days","hold_days","bars_held","n_days"):
            day_col = c
            break
    if day_col is None:
        for c in cols:
            if "day" in c.lower() and "under" not in c.lower():
                day_col = c
                break
    vals = []
    if day_col:
        for r in rows:
            try:
                vals.append(float(r[day_col]))
            except Exception:
                pass
    return {
        "n": len(rows),
        "day_col": day_col,
        "avg": round(sum(vals)/len(vals),1) if vals else None,
        "med": round(stats.median(vals),1) if vals else None,
        "cols_sample": [c for c in cols if "day" in c.lower() or "pnl" in c.lower()][:15],
    }

for sys in ["MVCP","QULL","KELL","CS","IND"]:
    for stem in [f"{sys}_LatestRun_Closed.csv", f"{sys}_Closed_260803155516.csv" if sys=="MVCP" else None]:
        if not stem:
            continue
        p = drive/stem
        if not p.exists():
            # try glob
            matches = sorted(drive.glob(f"{sys}_Closed_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
            p = matches[0] if matches else None
        if p and p.exists():
            print(sys, p.name, days_from_closed(p))
            break

# MVCP LatestRun Summary first rows
print("\nMVCP Summary sample:")
p = drive/"MVCP_LatestRun_Summary.csv"
with p.open(newline="", encoding="utf-8", errors="replace") as f:
    rows = list(csv.DictReader(f))
print("n", len(rows), "cols", list(rows[0].keys())[:20])
print(rows[0])

# QULL summary
print("\nQULL Summary:")
p = drive/"QULL_LatestRun_Summary.csv"
print(p.read_text(encoding="utf-8", errors="replace")[:800])

print("\nCS Summary:")
p = drive/"CS_LatestRun_Summary.csv"
print(p.read_text(encoding="utf-8", errors="replace")[:800])

print("\nKELL Summary:")
p = drive/"KELL_LatestRun_Summary.csv"
print(p.read_text(encoding="utf-8", errors="replace")[:800])
