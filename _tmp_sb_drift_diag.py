import csv
from pathlib import Path
from collections import Counter

root = Path(r"C:\Users\songg\Downloads\stockresearch")
freeze = root / "drive/paul_experiments/sb_baseline_260803184014/engine_closed/SB_Closed_260803184014.csv"
latest = root / "drive/SB_LatestRun_Closed.csv"
fuller = root / "drive/SB_Closed_260808225754.csv"
alias_stamp = root / "drive/SB_Closed_260808225801.csv"

def load(p: Path):
    rows = []
    with p.open(newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            norm = {((k or "").strip().upper().replace(" ", "_")): (v if v is not None else "") for k, v in row.items()}
            sym = str(norm.get("SYMBOL", "")).strip().upper()
            if not sym:
                continue
            opened = str(norm.get("DATE_OPENED", "")).strip()[:10]
            closed = str(norm.get("DATE_CLOSED", "")).strip()[:10]
            pnl = norm.get("PNL_DOLLARS") or norm.get("PNL_$") or ""
            pct = norm.get("PNL_PCT") or norm.get("PNL_%") or ""
            et = str(norm.get("EXIT_TYPE", "")).strip().upper()
            try:
                pnld = float(str(pnl).replace(",", "").replace("$", "")) if str(pnl).strip() else 0.0
            except ValueError:
                pnld = 0.0
            rows.append({"SYMBOL": sym, "DATE_OPENED": opened, "DATE_CLOSED": closed, "PNL_D": pnld, "EXIT_TYPE": et})
    return rows

def stats(name, rows):
    pnl = sum(r["PNL_D"] for r in rows)
    by = Counter(r["EXIT_TYPE"] for r in rows)
    dates = [r["DATE_CLOSED"] for r in rows if r["DATE_CLOSED"]]
    opens = [r["DATE_OPENED"] for r in rows if r["DATE_OPENED"]]
    print(f"=== {name} ===")
    print(f"  trades={len(rows)} symbols={len({r['SYMBOL'] for r in rows})} pnl_d={pnl:,.2f}")
    print(f"  closed_min={min(dates) if dates else None} closed_max={max(dates) if dates else None}")
    print(f"  opened_min={min(opens) if opens else None} opened_max={max(opens) if opens else None}")
    print(f"  exit_mix={dict(by.most_common())}")

fr = load(freeze)
lt = load(latest)
stats("FREEZE 260803184014", fr)
stats("LATEST (SB_LatestRun)", lt)
if fuller.exists():
    fu = load(fuller)
    stats("FULLER 260808225754", fu)
if alias_stamp.exists():
    al = load(alias_stamp)
    stats("ALIAS 260808225801", al)

fk = {(r["SYMBOL"], r["DATE_OPENED"], r["DATE_CLOSED"]) for r in fr}
lk = {(r["SYMBOL"], r["DATE_OPENED"], r["DATE_CLOSED"]) for r in lt}
print("\n=== set compare freeze vs latest ===")
print(f"  intersection={len(fk & lk)} missing_from_latest={len(fk - lk)} new_in_latest={len(lk - fk)}")
print(f"  freeze_pnl={sum(r['PNL_D'] for r in fr):,.2f} latest_pnl={sum(r['PNL_D'] for r in lt):,.2f} delta={sum(r['PNL_D'] for r in lt)-sum(r['PNL_D'] for r in fr):,.2f}")
fby = {(r["SYMBOL"], r["DATE_OPENED"], r["DATE_CLOSED"]): r for r in fr}
miss_pnl = sum(fby[k]["PNL_D"] for k in (fk - lk))
print(f"  missing_baseline_pnl_sum={miss_pnl:,.2f}")
miss_years = Counter((k[1][:4] if k[1] else "?") for k in (fk - lk))
print(f"  missing by open-year: {dict(sorted(miss_years.items()))}")
lat_years = Counter((r["DATE_OPENED"][:4] if r["DATE_OPENED"] else "?") for r in lt)
print(f"  latest by open-year: {dict(sorted(lat_years.items()))}")
fr_years = Counter((r["DATE_OPENED"][:4] if r["DATE_OPENED"] else "?") for r in fr)
print(f"  freeze by open-year: {dict(sorted(fr_years.items()))}")
zero = sorted({r["SYMBOL"] for r in fr} - {r["SYMBOL"] for r in lt})
print(f"  symbols entirely missing in latest ({len(zero)}): {','.join(zero)}")
new = sorted(lk - fk)
print(f"  new_only ({len(new)}): {new}")

if fuller.exists():
    uk = {(r["SYMBOL"], r["DATE_OPENED"], r["DATE_CLOSED"]) for r in fu}
    print("\n=== set compare freeze vs fuller 260808225754 ===")
    print(f"  intersection={len(fk & uk)} missing_from_fuller={len(fk - uk)} new_in_fuller={len(uk - fk)}")

audit = root / "drive/SB_LatestRun_Audit_Report.csv"
if audit.exists():
    with audit.open(newline="", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    print("\n=== LatestRun Audit interesting fields ===")
    for k, v in row.items():
        kl = (k or "").lower()
        if any(x in kl for x in ("burst", "sb_", "target", "risk", "start", "total_trade", "total_pnl", "max_pos", "size_from", "timestamp", "symbol", "universe")):
            print(f"  {k}={v}")

for cand in ["SB_LatestRun_Summary.txt", "SB_Summary_260808225801.txt"]:
    p = root / "drive" / cand
    if p.exists():
        print(f"\n----- {cand} -----")
        print(p.read_text(encoding="utf-8", errors="replace")[:2000])
