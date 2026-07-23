"""Temporary NVDA gap clustering for deep-dive report."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
ENG = ROOT / "data" / "newdata" / "data" / "NVDA.csv"


def load_eng_ohlc() -> dict:
    out = {}
    with ENG.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            d = r["Date"][:10]
            out[d] = {
                "open": round(float(r["Open"]), 4),
                "high": round(float(r["High"]), 4),
                "low": round(float(r["Low"]), 4),
                "close": round(float(r["Close"]), 4),
            }
    return out


def main() -> None:
    so, eo = [], []
    with (OUT / "NVDA_breakouts_match_detail.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["status"] == "sheet_only":
                so.append(r)
            elif r["status"] == "engine_only":
                eo.append(r)

    by_date_so = defaultdict(list)
    by_date_eo = defaultdict(list)
    for r in so:
        by_date_so[r["sheet_bo_date"]].append(r)
    for r in eo:
        by_date_eo[r["eng_bo_date"]].append(r)

    paired_dates = sorted(set(by_date_so) & set(by_date_eo))
    print("Same-date sheet-only + engine-only pairs:", len(paired_dates))
    for d in paired_dates:
        s = by_date_so[d][0]
        e = by_date_eo[d][0]
        print(
            f"  {d}: sheet {s['sheet_lo']}/{s['sheet_hi']} "
            f"vs eng {e['eng_lo']}/{e['eng_hi']}"
        )

    so_z = Counter(f"{r['sheet_lo']}/{r['sheet_hi']}" for r in so)
    eo_z = Counter(f"{r['eng_lo']}/{r['eng_hi']}" for r in eo)
    print("\nSheet-only BO zone bands:")
    for z, n in so_z.most_common():
        print(f"  {z}: {n}")
    print("Engine-only BO zone bands:")
    for z, n in eo_z.most_common():
        print(f"  {z}: {n}")

    so_dates = {r["sheet_bo_date"] for r in so}
    eo_dates = {r["eng_bo_date"] for r in eo}
    print(f"\nSheet-only dates not paired: {sorted(so_dates - eo_dates)}")
    print(f"Engine-only dates not paired: {sorted(eo_dates - so_dates)}")

    # 6.30 zone origin
    eng = load_eng_ohlc()
    print("\n=== 6.30 zone pivot hunt (2018 Jan-May highs) ===")
    for d in sorted(eng):
        if d.startswith("2018-0") or d.startswith("2018-05"):
            h = eng[d]["high"]
            if h >= 6.0:
                t2 = round(h, 2)
                print(f"  {d}: H={h:.4f} round2={t2} band={round(t2*0.98,2)}/{round(t2*1.02,2)}")

    # 2015-10-02 trade context
    print("\n=== 2015-10-02 trade context ===")
    for d in ["2015-09-30", "2015-10-01", "2015-10-02", "2015-10-05"]:
        if d in eng:
            print(f"  {d}: {eng[d]}")

    # 2014-04-03 engine-only trade
    print("\n=== 2014-04-03 engine trade context ===")
    for d in ["2014-03-28", "2014-04-01", "2014-04-02", "2014-04-03", "2014-04-04"]:
        if d in eng:
            print(f"  {d}: {eng[d]}")

    # Full OHLC mismatch count
    sheet = {}
    with (OUT / "NVDA_sheet_ohlc.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sheet[r["date"]] = {k: float(r[k]) for k in ("open", "high", "low", "close")}

    mismatches = []
    for d in sorted(set(sheet) & set(eng)):
        for field in ("open", "high", "low", "close"):
            if abs(round(sheet[d][field], 2) - round(eng[d][field], 2)) > 0.02:
                mismatches.append((d, field, sheet[d][field], eng[d][field]))
    print(f"\nOHLC mismatches (>±$0.02): {len(mismatches)}")
    for m in mismatches:
        print(f"  {m[0]} {m[1]}: sheet={m[2]} eng={m[3]}")


if __name__ == "__main__":
    main()
