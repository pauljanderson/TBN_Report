import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
df = pd.read_csv(ROOT/"data/newdata/data/TSLA.csv", parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
dates = [d.date().isoformat() for d in df["Date"]]
i = dates.index("2024-08-21")
c = df["Close"].astype(float).to_numpy()
h = df["High"].astype(float).to_numpy()
print("trigger", dates[i], float(c[i]))

# ATH-style sheet_growth_ok (>=2 of 1Y/2Y/3Y)
flags = []
for w, thr, name in ((252, 0.3, "1Y"), (504, 0.3, "2Y"), (756, 0.6, "3Y")):
    mx = float(np.max(h[i-w+1:i+1]))
    ok = float(c[i]) >= thr * mx
    flags.append(ok)
    print(f"ATH {name}: maxH={mx:.4f} thr={thr*mx:.4f} ok={ok}")
print("ATH growth_ok (>=2):", sum(flags)>=2, "flags", flags)

# nearby lookback pass/fail table
print("lookback table:")
for dlt in range(750, 761):
    a=i-dlt
    print(f"  i-{dlt} {dates[a]} C={float(c[a]):.4f} pass={float(c[i])>=float(c[a])}")

diag = ROOT/"drive/brt_sheet_reconcile/TSLA_sheet_only_gates_diag.json"
if diag.exists():
    data=json.loads(diag.read_text(encoding="utf-8"))
    for t in data.get("trades", data if isinstance(data, list) else []):
        sh = t.get("sheet", t)
        trig = sh.get("trigger") or t.get("trigger")
        if trig == "2024-08-21" or "2024-08-21" in str(t):
            print("DIAG_KEYS", list(t.keys())[:40])
            print(json.dumps(t, indent=2)[:5000])
            break
    else:
        # search string
        s = diag.read_text(encoding="utf-8")
        idx = s.find("2024-08-21")
        print("found at", idx)
        print(s[max(0,idx-200):idx+1500])

# also check audit reasons / gates md for 2024-08-21
for name in ["TSLA_sheet_only_audit_reasons.md", "TSLA_sheet_only_trades_gates.md"]:
    p = ROOT/"drive/brt_sheet_reconcile"/name
    text = p.read_text(encoding="utf-8")
    idx = text.find("2024-08-21")
    print("===", name, "idx", idx)
    if idx>=0:
        print(text[max(0,idx-300):idx+1200])
