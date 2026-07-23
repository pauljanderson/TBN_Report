"""AMD sheet vs engine stop91 stamp 260722151857 trade/summary diff."""
from __future__ import annotations

import json
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


def summarize(df, label, pct_col="pct", usd_col="usd", days_col="days"):
    n = len(df)
    wins = df[df[pct_col] > 0]
    losses = df[df[pct_col] <= 0]
    winpct = 100.0 * len(wins) / n if n else 0.0
    avg = float(df[pct_col].mean()) if n else 0.0
    aw = float(wins[pct_col].mean()) if len(wins) else 0.0
    al = abs(float(losses[pct_col].mean())) if len(losses) else 0.0
    ratio = (aw / al) if al else float("inf")
    ad = float(df[days_col].mean()) if n else 0.0
    usd = float(df[usd_col].sum()) if n else 0.0
    print(
        f"{label}: n={n} win%={winpct:.1f}% avg%={avg:.1f}% "
        f"ratio={ratio:.2f} days={ad:.1f} $=${usd:,.2f}"
    )
    return {
        "n": n,
        "winpct": winpct,
        "avg": avg,
        "ratio": ratio,
        "days": ad,
        "usd": usd,
        "wins": int(len(wins)),
        "losses": int(len(losses)),
    }


sheet = pd.read_csv(BASE / "AMD" / "sheet_trades.tsv", sep="\t")
sheet["entry"] = pd.to_datetime(sheet["Entry Date"])
sheet["exit"] = pd.to_datetime(sheet["Exit Date"])
sheet["epx"] = sheet["Entry Price"].map(money)
sheet["xpx"] = sheet["Exit Price"].map(money)
sheet["pct"] = sheet["Profit %"].map(money)
sheet["days"] = pd.to_numeric(sheet["Days In Trade"], errors="coerce")
sheet["usd"] = sheet["Profit per trade"].map(money)

cl = pd.read_csv(OUTDIR / f"WPBR_Closed_{STAMP}.csv")
amd = cl[cl["SYMBOL"].astype(str).str.upper() == "AMD"].copy()
amd["entry"] = pd.to_datetime(amd["DATE_OPENED"].astype(str), format="%Y%m%d")
amd["exit"] = pd.to_datetime(amd["DATE_CLOSED"].astype(str), format="%Y%m%d")
amd["epx"] = amd["ENTRY_PRICE"].astype(float)
amd["xpx"] = amd["EXIT_PRICE"].astype(float)
amd["pct"] = amd["PNL_PCT"].map(money)
amd["days"] = amd["DAYS_HELD"].astype(float)
amd["usd"] = amd["PNL_DOLLARS"].astype(float)
amd["etype"] = amd["EXIT_TYPE"].astype(str)
amd["stop"] = amd["STOP_PRICE"].astype(float)

sset = set(sheet["entry"].dt.strftime("%Y-%m-%d"))
eset = set(amd["entry"].dt.strftime("%Y-%m-%d"))
print("SHEET_ONLY", sorted(sset - eset))
print("ENG_ONLY", sorted(eset - sset))
print("MATCHED", len(sset & eset))

print("\n=== MATCHED FIELD DIFFS ===")
n_price_ok = 0
n_usd_diff = 0
matched_rows = []
for d in sorted(sset & eset):
    s = sheet[sheet["entry"].dt.strftime("%Y-%m-%d") == d].iloc[0]
    e = amd[amd["entry"].dt.strftime("%Y-%m-%d") == d].iloc[0]
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
    usd_ratio = (e["usd"] / s["usd"]) if s["usd"] else None
    if abs(s["usd"] - e["usd"]) > 1.0:
        n_usd_diff += 1
    if diffs:
        print(d, diffs, "etype", e["etype"], f"usd s={s['usd']} e={e['usd']}")
    else:
        n_price_ok += 1
        print(
            f"{d} OK dates/px/pct/days etype={e['etype']} "
            f"usd s={s['usd']:.2f} e={e['usd']:.2f} ratio={usd_ratio:.3f}"
        )
    matched_rows.append(
        {
            "entry": d,
            "exit_ok": s["exit"].date() == e["exit"].date(),
            "px_ok": abs(s["epx"] - e["epx"]) <= 0.011 and abs(s["xpx"] - e["xpx"]) <= 0.011,
            "pct_ok": abs(s["pct"] - e["pct"]) <= 0.02,
            "days_ok": abs(s["days"] - e["days"]) <= 0.5,
            "sheet_usd": float(s["usd"]),
            "eng_usd": float(e["usd"]),
            "etype": e["etype"],
            "diffs": diffs,
        }
    )

print(f"\nmatched price/date/pct/days perfect: {n_price_ok}/{len(sset & eset)}")
print(f"matched with USD dollar PnL mismatch (>$1): {n_usd_diff}/{len(sset & eset)}")

print("\n=== ENG-ONLY DETAIL ===")
for d in sorted(eset - sset):
    e = amd[amd["entry"].dt.strftime("%Y-%m-%d") == d].iloc[0]
    print(
        f"{d} entry={e['epx']:.2f} exit={e['exit'].date()} xpx={e['xpx']:.2f} "
        f"pct={e['pct']} days={int(e['days'])} etype={e['etype']} "
        f"usd={e['usd']:.2f} stop={e['stop']:.2f}"
    )

print("\n=== SUMMARY STATS ===")
s_sum = summarize(sheet, "SHEET_20")
e_sum = summarize(amd, "ENG_ALL_26")
amd_m = amd[amd["entry"].dt.strftime("%Y-%m-%d").isin(sset)]
em_sum = summarize(amd_m, "ENG_MATCHED_20")
amd_eo = amd[amd["entry"].dt.strftime("%Y-%m-%d").isin(eset - sset)]
eo_sum = summarize(amd_eo, "ENG_ONLY_6")

# Compare sheet % metrics to eng matched % metrics
print("\n=== SHEET vs ENG_MATCHED % DELTA ===")
for k in ("n", "winpct", "avg", "ratio", "days", "usd"):
    print(f"  {k}: sheet={s_sum[k]} eng_matched={em_sum[k]} eng_all={e_sum[k]}")

# Check sheet rocket blanks for eng-only period using zones paste
zones = pd.read_csv(BASE / "AMD" / "sheet_zones.tsv", sep="\t")
print("\n=== ZONES COLS ===", list(zones.columns))
# rocket buy date col
rocket_col = [c for c in zones.columns if "rocket" in c.lower() and "date" in c.lower()]
print("rocket cols", rocket_col)
if rocket_col:
    rc = rocket_col[0]
    rockets = zones[rc].dropna().astype(str).str.strip()
    rockets = rockets[rockets != ""]
    print("sheet rocket fire count", len(rockets))
    print("sample rockets", rockets.head(10).tolist())

# entries file
ent = pd.read_csv(OUTDIR / f"WPBR_ZONES_ENTRIES_AMD_{STAMP}.csv")
print("\n=== ENG ENTRIES cols ===", list(ent.columns)[:20], "n", len(ent))
# try find fill/entry date
for c in ent.columns:
    if "date" in c.lower() or "entry" in c.lower() or "fill" in c.lower() or "rocket" in c.lower():
        pass
date_cols = [c for c in ent.columns if "DATE" in c.upper() or "date" in c]
print("date-ish", date_cols)

# payload AMD
payload_path = BASE / "_variantC_SC_stop91_2016_reconcile_payload.json"
payload = json.loads(payload_path.read_text(encoding="utf-8"))
print("\npayload type", type(payload).__name__)
if isinstance(payload, dict):
    print("keys", list(payload.keys())[:40])
    for key in ("AMD", "amd", "by_ticker", "tickers", "results", "symbols"):
        if key in payload:
            print("hit", key, type(payload[key]))
            val = payload[key]
            if isinstance(val, dict) and "AMD" in val:
                print(json.dumps(val["AMD"], indent=2)[:2500])
            elif isinstance(val, dict):
                print(json.dumps(val, indent=2)[:2500])
            break
    # nested search
    def find_amd(obj, path=""):
        if isinstance(obj, dict):
            if obj.get("ticker") == "AMD" or obj.get("symbol") == "AMD":
                return path, obj
            for k, v in obj.items():
                if str(k).upper() == "AMD" and isinstance(v, dict):
                    return path + "/" + str(k), v
                found = find_amd(v, path + "/" + str(k))
                if found:
                    return found
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                found = find_amd(v, path + f"[{i}]")
                if found:
                    return found
        return None

    found = find_amd(payload)
    if found:
        pth, obj = found
        print("found AMD at", pth)
        print(json.dumps(obj, indent=2)[:3500])

# position sizing check on matched wins
print("\n=== POSITION SIZING CHECK (matched wins target 22%) ===")
wins = sheet[(sheet["pct"] > 0) & (sheet["pct"].round(2) == 22.0)]
print("sheet fixed-target wins usd unique", sorted(set(wins["usd"].round(2))))
ew = amd_m[(amd_m["pct"] > 0) & (amd_m["pct"].round(2) == 22.0)]
print("eng matched fixed-target wins usd unique", sorted(set(ew["usd"].round(2))))
print("sheet risk proxy |loss usd| median", sheet[sheet["pct"] < 0]["usd"].abs().median())
print("eng risk proxy |loss usd| median", amd[amd["pct"] < 0]["usd"].abs().median())

out = {
    "stamp": STAMP,
    "sheet_n": int(len(sheet)),
    "eng_n": int(len(amd)),
    "sheet_only": sorted(sset - eset),
    "eng_only": sorted(eset - sset),
    "matched_n": len(sset & eset),
    "matched_price_date_perfect": n_price_ok,
    "matched_usd_mismatch": n_usd_diff,
    "sheet_summary": s_sum,
    "eng_all_summary": e_sum,
    "eng_matched_summary": em_sum,
    "eng_only_summary": eo_sum,
    "matched_rows": matched_rows,
}
(BASE / "AMD" / "_stop91_diff_machine.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print("\nWrote", BASE / "AMD" / "_stop91_diff_machine.json")
