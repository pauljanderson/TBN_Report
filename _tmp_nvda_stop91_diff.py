from pathlib import Path
import pandas as pd

BASE = Path(r"C:\Users\songg\Downloads\stockresearch\drive\wpbr_sheet_reconcile")
STAMP = "260722151857"
OUTDIR = BASE / "_markten_variantC_SC_stop91_2016_20260722151842"

def money(x):
    if pd.isna(x):
        return None
    s = str(x).replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return None

sheet = pd.read_csv(BASE / "NVDA" / "sheet_trades.tsv", sep="\t")
sheet["entry"] = pd.to_datetime(sheet["Entry Date"])
sheet["exit"] = pd.to_datetime(sheet["Exit Date"])
sheet["epx"] = sheet["Entry Price"].map(money)
sheet["xpx"] = sheet["Exit Price"].map(money)
sheet["pct"] = sheet["Profit %"].map(money)
sheet["days"] = pd.to_numeric(sheet["Days In Trade"], errors="coerce")
sheet["usd"] = sheet["Profit per trade"].map(money)

cl = pd.read_csv(OUTDIR / f"WPBR_Closed_{STAMP}.csv")
nv = cl[cl["SYMBOL"].astype(str).str.upper() == "NVDA"].copy()
print("closed_file_exists", (OUTDIR / f"WPBR_Closed_{STAMP}.csv").exists())
print("nvda_closed_n", len(nv))
print("outdir_listing:")
for p in sorted(OUTDIR.glob("*"))[:80]:
    print(" ", p.name)

# encoding debug: first 5 chars of any SYMBOL starting with N
syms = cl["SYMBOL"].astype(str)
n_syms = syms[syms.str.upper().str.startswith("N")]
print("symbols_starting_N_unique:")
for s in sorted(n_syms.unique()):
    print(f"  repr={s!r} first5={s[:5]!r} len={len(s)}")

# open trades if any
open_path = OUTDIR / f"WPBR_Open_{STAMP}.csv"
if open_path.exists():
    op = pd.read_csv(open_path)
    nvo = op[op["SYMBOL"].astype(str).str.upper()=="NVDA"]
    print("nvda_open_n", len(nvo))
    if len(nvo):
        print(nvo[["DATE_OPENED","ENTRY_PRICE","STOP_PRICE","TARGET_PRICE"]].to_string())
else:
    print("no open file")

nv["entry"] = pd.to_datetime(nv["DATE_OPENED"].astype(str), format="%Y%m%d")
nv["exit"] = pd.to_datetime(nv["DATE_CLOSED"].astype(str), format="%Y%m%d")
nv["epx"] = nv["ENTRY_PRICE"].astype(float)
nv["xpx"] = nv["EXIT_PRICE"].astype(float)
nv["pct"] = nv["PNL_PCT"].map(money)
nv["days"] = nv["DAYS_HELD"].astype(float)
nv["usd"] = nv["PNL_DOLLARS"].astype(float)
nv["etype"] = nv["EXIT_TYPE"].astype(str)
nv["stop"] = nv["STOP_PRICE"].astype(float)

sset = set(sheet["entry"].dt.strftime("%Y-%m-%d"))
eset = set(nv["entry"].dt.strftime("%Y-%m-%d"))
print("SHEET_ONLY", sorted(sset - eset))
print("ENG_ONLY", sorted(eset - sset))
print("MATCHED", len(sset & eset))

print("\n=== MATCHED FIELD DIFFS ===")
for d in sorted(sset & eset):
    s = sheet[sheet["entry"].dt.strftime("%Y-%m-%d") == d].iloc[0]
    e = nv[nv["entry"].dt.strftime("%Y-%m-%d") == d].iloc[0]
    diffs = []
    if s["exit"].date() != e["exit"].date():
        diffs.append(f"exit_date sheet={s['exit'].date()} eng={e['exit'].date()}")
    if abs(s["epx"] - e["epx"]) > 0.011:
        diffs.append(f"entry_px sheet={s['epx']} eng={e['epx']}")
    if abs(s["xpx"] - e["xpx"]) > 0.011:
        diffs.append(f"exit_px sheet={s['xpx']} eng={e['xpx']}")
    if abs(s["pct"] - e["pct"]) > 0.02:
        diffs.append(f"pnl% sheet={s['pct']} eng={e['pct']}")
    if abs(s["days"] - e["days"]) > 0.5:
        diffs.append(f"days sheet={s['days']} eng={e['days']}")
    usd_note = f"usd s={s['usd']:.2f} e={e['usd']:.2f}"
    if diffs:
        print(d, diffs, "etype", e["etype"], usd_note)
    else:
        print(f"{d} OK dates/px/pct/days etype={e['etype']} {usd_note}")

print("\n=== ENG-ONLY DETAIL ===")
for d in sorted(eset - sset):
    e = nv[nv["entry"].dt.strftime("%Y-%m-%d") == d].iloc[0]
    print(f"{d} entry={e['epx']:.2f} exit={e['exit'].date()} xpx={e['xpx']:.2f} pct={e['pct']} days={int(e['days'])} etype={e['etype']} usd={e['usd']:.2f} stop={e['stop']:.2f}")

print("\n=== SHEET-ONLY DETAIL ===")
for d in sorted(sset - eset):
    s = sheet[sheet["entry"].dt.strftime("%Y-%m-%d") == d].iloc[0]
    print(f"{d} entry={s['epx']:.2f} exit={s['exit'].date()} xpx={s['xpx']:.2f} pct={s['pct']} days={int(s['days'])} usd={s['usd']:.2f}")

def summarize(df, label):
    n = len(df)
    wins = df[df["pct"] > 0]
    losses = df[df["pct"] <= 0]
    winpct = 100.0 * len(wins) / n if n else 0.0
    avg = float(df["pct"].mean()) if n else 0.0
    aw = float(wins["pct"].mean()) if len(wins) else 0.0
    al = abs(float(losses["pct"].mean())) if len(losses) else 0.0
    ratio = (aw / al) if al else float("inf")
    ad = float(df["days"].mean()) if n else 0.0
    usd = float(df["usd"].sum()) if n else 0.0
    print(f"{label}: n={n} win%={winpct:.1f}% avg%={avg:.1f}% ratio={ratio:.2f} days={ad:.1f} $={usd:,.2f}")

print("\n=== SUMMARY STATS ===")
summarize(sheet, "SHEET")
summarize(nv, "ENG_CLOSED")

# payload NVDA if present
import json
payload_path = BASE / "_variantC_SC_stop91_2016_reconcile_payload.json"
if payload_path.exists():
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    def find_nv(obj, path=""):
        if isinstance(obj, dict):
            if str(obj.get("ticker","")).upper()=="NVDA" or str(obj.get("symbol","")).upper()=="NVDA":
                return path, obj
            for k,v in obj.items():
                if str(k).upper()=="NVDA":
                    return path+"/"+str(k), v
                found = find_nv(v, path+"/"+str(k))
                if found: return found
        elif isinstance(obj, list):
            for i,v in enumerate(obj):
                found = find_nv(v, path+f"[{i}]")
                if found: return found
        return None
    found = find_nv(payload)
    if found:
        p, obj = found
        print("\nPAYLOAD path", p)
        if isinstance(obj, dict):
            # print compact summary keys
            for k in ("raw","ser","orphans","raw_orphans","ser_orphans","eng_only","eng_only_rockets","closed_n","notes"):
                if k in obj:
                    print(k, obj[k])
            print("keys", list(obj.keys())[:40])
            print(json.dumps(obj, indent=2, default=str)[:4000])
