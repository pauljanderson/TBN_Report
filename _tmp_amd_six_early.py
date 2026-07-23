"""Diagnose 6 early AMD eng-only TARGET wins vs sheet blank rockets."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUTDIR = ROOT / "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_2016_20260722151842"
AMD = ROOT / "drive/wpbr_sheet_reconcile/AMD"
STAMP = "260722151857"
EARLY = [
    "2016-04-27",
    "2016-06-27",
    "2016-12-05",
    "2017-01-19",
    "2017-12-06",
    "2018-04-05",
]


def parse_sheet_date(s):
    if pd.isna(s) or str(s).strip() == "":
        return None
    s = str(s).strip().lstrip("$")
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def main():
    zones = pd.read_csv(AMD / "sheet_zones.tsv", sep="\t")
    trades = pd.read_csv(AMD / "sheet_trades.tsv", sep="\t")
    closed = pd.read_csv(OUTDIR / f"WPBR_Closed_{STAMP}.csv")
    entries = pd.read_csv(OUTDIR / f"WPBR_ZONES_ENTRIES_AMD_{STAMP}.csv")
    ezones = pd.read_csv(OUTDIR / f"WPBR_ZONES_AMD_{STAMP}.csv")
    brt = pd.read_csv(OUTDIR / f"WPBR_breakout_and_retest_{STAMP}.csv")
    brt_amd = brt[brt["SYMBOL"].astype(str).str.upper() == "AMD"].copy()

    amd = closed[closed["SYMBOL"].astype(str).str.upper() == "AMD"].copy()

    print("=== ENG CLOSED COLS ===")
    print(list(amd.columns))
    print("N", len(amd))

    # Normalize entry dates
    entry_col = None
    for c in amd.columns:
        if c.upper() in ("ENTRY_DATE", "ENTRY DATE", "ENTRYDATE"):
            entry_col = c
            break
    if entry_col is None:
        # try fuzzy
        for c in amd.columns:
            if "ENTRY" in c.upper() and "DATE" in c.upper():
                entry_col = c
                break
    print("entry_col", entry_col)

    amd["_entry"] = pd.to_datetime(amd[entry_col]).dt.strftime("%Y-%m-%d")
    print("\n=== ALL ENG AMD CLOSED (entry/exit/result) ===")
    show_cols = [c for c in amd.columns if any(
        x in c.upper()
        for x in (
            "ENTRY",
            "EXIT",
            "RESULT",
            "PROFIT",
            "TYPE",
            "ROCKET",
            "PIVOT",
            "ZONE",
            "TRIGGER",
            "FILL",
            "SIGNAL",
            "STOP",
            "TARGET",
            "DAYS",
        )
    )]
    print(amd[["_entry"] + [c for c in show_cols if c != entry_col]].to_string())

    print("\n=== EARLY 6 DETAIL ===")
    for d in EARLY:
        row = amd[amd["_entry"] == d]
        print(f"\n--- entry {d} n={len(row)} ---")
        if len(row):
            print(row.iloc[0][show_cols].to_string())

    print("\n=== SHEET TRADES ===")
    print(trades.to_string())

    print("\n=== SHEET ZONES (pre-2019 + nearby) ===")
    zones["_bo"] = zones["Breakout Date"].map(parse_sheet_date)
    zones["_piv"] = zones["Pivot Date"].map(parse_sheet_date)
    zones["_rt"] = zones["Daily Retest Date"].map(parse_sheet_date)
    zones["_rk"] = zones["Rocket Buy Date"].map(parse_sheet_date)
    for _, r in zones.iterrows():
        if r["_bo"] and r["_bo"] < "2019-06-01":
            print(
                f"BO={r['_bo']} piv={r['_piv']} retest={r['_rt']} rocket={r['_rk']} "
                f"ZL={r['Zone Lower']} ZU={r['Zone Upper']} conf={r.get('Conf Week Date')}"
            )

    print("\n=== ENG ZONES ENTRIES COLS ===")
    print(list(entries.columns))
    print(entries.head(2).to_string())
    print("\n=== ENG ZONES COLS ===")
    print(list(ezones.columns))

    # Map early fills to eng zone rows
    print("\n=== MAP EARLY FILLS TO ENG ZONE/ENTRY ROWS ===")
    # find date cols on entries
    e_date_cols = [c for c in entries.columns if "DATE" in c.upper() or "ROCKET" in c.upper() or "ENTRY" in c.upper()]
    print("entries date-ish", e_date_cols)

    for d in EARLY:
        # match fill date or rocket/signal near entry
        print(f"\n## Looking for eng rows near entry {d}")
        # closed row
        crow = amd[amd["_entry"] == d]
        if len(crow):
            print("closed:", crow.iloc[0][[c for c in show_cols[:20]]].to_dict())

        # try match entries by entry/fill/rocket date
        for c in entries.columns:
            if "DATE" in c.upper() or c.upper() in ("ENTRY", "FILL", "SIGNAL", "ROCKET"):
                try:
                    ser = pd.to_datetime(entries[c], errors="coerce").dt.strftime("%Y-%m-%d")
                    hits = entries[ser == d]
                    if len(hits):
                        print(f"entries hit on {c}:")
                        print(hits.to_string())
                except Exception:
                    pass

        # also search brt stream
        brt_date_cols = [c for c in brt_amd.columns if "DATE" in c.upper()]
        for c in brt_date_cols[:15]:
            try:
                ser = pd.to_datetime(brt_amd[c], errors="coerce").dt.strftime("%Y-%m-%d")
                hits = brt_amd[ser == d]
                if len(hits):
                    print(f"brt hit on {c} n={len(hits)}")
                    print(hits.iloc[0].to_string())
                    break
            except Exception:
                pass


if __name__ == "__main__":
    main()
