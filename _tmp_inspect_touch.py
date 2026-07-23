import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
p=open("_tmp_touch_src.py",encoding="utf-8").read().splitlines()
keys=("return {", "zones", "events", "retest", "zone_lo", "zone_hi", "opportunit", "entries", "zl", "zh", "pivot")
for i,l in enumerate(p):
    if any(k in l for k in keys):
        print(f"{i+1}:{l[:200]}")
print("---TAIL---")
for l in p[-50:]:
    print(l[:200])
