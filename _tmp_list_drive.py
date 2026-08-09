from pathlib import Path
import csv
import re

drive = Path(r"C:\Users\songg\Downloads\stockresearch\drive")
print("drive exists:", drive.exists())

# List LatestRun and Report/Summary
patterns = [
    "*_LatestRun_*",
    "*_Report_*.csv",
    "*_Summary_*.csv",
    "*_Audit_Report_*.csv",
    "*_Optimization_Audit*.csv",
]
seen = set()
files = []
for pat in patterns:
    for p in drive.glob(pat):
        if p.resolve() not in seen:
            seen.add(p.resolve())
            files.append(p)
    for p in drive.rglob(pat):
        if p.resolve() not in seen:
            seen.add(p.resolve())
            files.append(p)

files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
print(f"found {len(files)} files")
for p in files[:120]:
    print(f"{p.stat().st_mtime:.0f}\t{p.stat().st_size:10d}\t{p}")

# Also paul_experiments
pe = drive / "paul_experiments"
if pe.exists():
    print("\n=== paul_experiments html ===")
    for p in sorted(pe.glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True)[:30]:
        print(f"{p.name}\t{p.stat().st_size}")
