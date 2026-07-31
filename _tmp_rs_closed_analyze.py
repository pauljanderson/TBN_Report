import csv
from pathlib import Path

def analyze(path):
    p = Path(path)
    if not p.exists():
        return {"path": str(p), "exists": False}
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    row_count = max(0, len(lines) - 1) if lines else 0
    out = {"path": str(p), "exists": True, "line_count": len(lines), "trade_count": row_count}
    if len(lines) < 2:
        return out
    import io
    reader = csv.DictReader(io.StringIO(text))
    cols = reader.fieldnames or []
    out["has_ATR_PCT_AT_TRIGGER"] = "ATR_PCT_AT_TRIGGER" in cols
    if "ATR_PCT_AT_TRIGGER" in cols:
        vals = []
        for row in reader:
            v = (row.get("ATR_PCT_AT_TRIGGER") or "").strip()
            if not v or v.lower() in ("nan", "none"):
                continue
            if v.endswith("%"):
                v = v[:-1].strip()
            try:
                vals.append(float(v))
            except ValueError:
                pass
        out["atr_n"] = len(vals)
        if vals:
            vals.sort()
            def pct(q):
                k = (len(vals)-1) * q / 100.0
                f = int(k)
                c = min(f+1, len(vals)-1)
                if f == c:
                    return vals[f]
                return vals[f] + (vals[c]-vals[f]) * (k-f)
            out["atr_percentiles"] = {str(q): round(pct(q), 6) for q in [0,5,10,25,50,75,90,95,100]}
        else:
            out["atr_percentiles"] = None
    return out

main = analyze(r"drive/RS_Closed_260723221911.csv")
print("=== drive/RS_Closed_260723221911.csv ===")
for k, v in main.items():
    print(f"  {k}: {v}")

exp = Path("drive/davey_experiments/rs_oneil_filters/A_near_0p15")
files = sorted(exp.glob("RS_Closed*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
print("\n=== A_near_0p15 RS_Closed*.csv ===")
if not files:
    print("  (none found)")
for fp in files:
    r = analyze(fp)
    print(f"\n  File: {fp.name}")
    for k, v in r.items():
        if k != "path":
            print(f"    {k}: {v}")
