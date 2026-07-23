import pandas as pd
import os

sheet = pd.read_csv(r"drive/wpbr_sheet_reconcile/NVDA/sheet_trades.tsv", sep="\t")
eng = pd.read_csv(r"drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_2016_20260722151842/WPBR_Closed_260722151857.csv")
eng = eng[eng["SYMBOL"] == "NVDA"].copy()

def parse_money(x):
    if pd.isna(x):
        return float("nan")
    s = str(x).strip().replace("$", "").replace(",", "").replace("(", "-").replace(")", "")
    return float(s)

def parse_pct(x):
    if pd.isna(x):
        return float("nan")
    return float(str(x).strip().replace("%", ""))

sheet["entry_dt"] = pd.to_datetime(sheet["Entry Date"])
sheet["exit_dt"] = pd.to_datetime(sheet["Exit Date"])
sheet["entry"] = sheet["Entry Price"].apply(parse_money)
sheet["exit"] = sheet["Exit Price"].apply(parse_money)
sheet["profit_pct_rep"] = sheet["Profit %"].apply(parse_pct)
sheet["profit_usd"] = sheet["Profit per trade"].apply(parse_money)

eng["entry_dt"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
eng["pnl_pct_rep"] = eng["PNL_PCT"].apply(parse_pct)

m = sheet.merge(eng, on="entry_dt", how="inner", suffixes=("_s", "_e"))
print("matched", len(m), "sheet", len(sheet), "eng", len(eng))

focus = pd.to_datetime(["2018-06-21", "2018-09-11", "2021-04-26", "2022-03-29"])
print("\n===1) Focus STOP trades===")
for d in focus:
    r = m[m["entry_dt"] == d]
    if r.empty:
        print(f"{d.date()}: NOT FOUND")
        continue
    row = r.iloc[0]
    sc = (row["exit"] - row["entry"]) / row["entry"] * 100
    ec = (row["EXIT_PRICE"] - row["ENTRY_PRICE"]) / row["ENTRY_PRICE"] * 100
    s91 = row["ENTRY_PRICE"] * 0.91
    print(f"{d.date()} EXIT_TYPE={row['EXIT_TYPE']}")
    print(f"  sheet calc={sc:.4f}% vs Profit%={row['profit_pct_rep']:.4f}% delta={sc - row['profit_pct_rep']:.4f}")
    print(f"  eng calc={ec:.4f}% vs PNL_PCT={row['pnl_pct_rep']:.4f}% delta={ec - row['pnl_pct_rep']:.4f}")
    print(f"  stop91={s91:.6f} vs STOP_PRICE={row['STOP_PRICE']:.6f} delta={s91 - row['STOP_PRICE']:.6f}")

print("\n===2) USD ratio eng/sheet===")
for typ, label in [("TARGET", "targets"), ("STOP", "stops")]:
    sub = m[m["EXIT_TYPE"].astype(str).str.contains(typ, case=False, na=False)].copy()
    sub = sub[sub["profit_usd"].abs() > 1e-9]
    ratio = sub["PNL_DOLLARS"] / sub["profit_usd"]
    print(f"{label}: n={len(sub)} mean={ratio.mean():.6f} med={ratio.median():.6f}")
    print(" ", ", ".join(f"{x:.4f}" for x in ratio.tolist()))

print("\n===3) Open 20260507 vs sheet last exit===")
last_exit = sheet["exit_dt"].max()
open_dt = pd.Timestamp("2026-05-07")
print(f"sheet last exit: {last_exit.date()}")
print(f"open 20260507 after last exit: {bool(open_dt > last_exit)}")

base = r"drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_2016_20260722151842"
print("files:", [f for f in os.listdir(base) if "pen" in f.lower() or f.startswith("WPBR")])
