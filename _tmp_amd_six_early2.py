"""Deep map: 6 early AMD eng-only fills vs sheet zones/rockets."""
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


def money(x):
    if pd.isna(x):
        return None
    s = str(x).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def main():
    zones = pd.read_csv(AMD / "sheet_zones.tsv", sep="\t")
    closed = pd.read_csv(OUTDIR / f"WPBR_Closed_{STAMP}.csv")
    entries = pd.read_csv(OUTDIR / f"WPBR_ZONES_ENTRIES_AMD_{STAMP}.csv")
    ezones = pd.read_csv(OUTDIR / f"WPBR_ZONES_AMD_{STAMP}.csv")
    audit = pd.read_csv(OUTDIR / f"WPBR_Audit_Report_{STAMP}.csv")

    amd = closed[closed["SYMBOL"].astype(str).str.upper() == "AMD"].copy()
    amd["_entry"] = pd.to_datetime(amd["DATE_OPENED"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d")
    amd["_exit"] = pd.to_datetime(amd["DATE_CLOSED"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d")

    print("=== 6 EARLY ENG-ONLY CLOSED TRADES ===")
    rows = []
    for d in EARLY:
        r = amd[amd["_entry"] == d]
        assert len(r) == 1, (d, len(r))
        rr = r.iloc[0]
        rows.append(rr)
        print(
            f"entry={d} exit={rr['_exit']} px={rr['ENTRY_PRICE']}->{rr['EXIT_PRICE']} "
            f"type={rr['EXIT_TYPE']} days={rr['DAYS_HELD']} pnl%={rr['PNL_PCT']} "
            f"zone={rr['WPBR_ZONE_ID']} center={rr['ZONE_CENTER']} "
            f"BO={rr.get('BREAKOUT_DATE')} mat={rr.get('MATURITY_DATE')} "
            f"close_above={rr.get('CLOSE_ABOVE_DATE')}"
        )

    print("\n=== ENG WPBR_ZONES rows for those zone IDs ===")
    for rr in rows:
        zid = rr["WPBR_ZONE_ID"]
        z = ezones[ezones["WPBR_ZONE_ID"] == zid]
        print(f"\n## zone {zid} n={len(z)}")
        if len(z):
            zz = z.iloc[0]
            cols = [
                "PIVOT_MONDAY",
                "ZONE_CENTER",
                "ZONE_LOW",
                "ZONE_HIGH",
                "BREAKOUT_MONDAY",
                "CONF_MONDAY",
                "RETEST_BAR",
                "ENTRY_SIGNAL_BAR",
                "ENTRY_FILL_BAR",
                "HAS_TRADE",
                "WPBR_DAYS_CONF_TO_RETEST",
                "WPBR_WEEKS_PIVOT_TO_BO",
            ]
            print(zz[cols].to_string())

    # Need OHLC to map bar indices to dates - check pivots file or OHLC
    ohlc = pd.read_csv(AMD / "sheet_ohlc_iso.csv")
    print("\nOHLC cols", list(ohlc.columns)[:10], "n", len(ohlc))
    # try date col
    dcol = [c for c in ohlc.columns if "date" in c.lower() or c.lower() == "d"][0]
    ohlc["_d"] = pd.to_datetime(ohlc[dcol]).dt.strftime("%Y-%m-%d")
    # BAR_INDEX in eng zones — need engine bar index. Check if BAR_INDEX aligns with row.
    # Often BAR_INDEX is absolute in full history. Check range.
    print("eng BAR_INDEX min/max", ezones["BAR_INDEX"].min(), ezones["BAR_INDEX"].max())
    print("sheet ohlc n", len(ohlc), "first/last", ohlc["_d"].iloc[0], ohlc["_d"].iloc[-1])

    # Map signal/fill bars if BAR_INDEX is into a full series - load from brt checkpoint? 
    # Prefer: join via ENTRY dates we already have + zone lifecycle dates from ZONE file Mondays.
    print("\n=== LIFECYCLE DATES FROM ENG ZONES (Mondays) + entry dates ===")
    for rr in rows:
        zid = rr["WPBR_ZONE_ID"]
        z = ezones[ezones["WPBR_ZONE_ID"] == zid].iloc[0]
        print(
            f"fill={rr['_entry']} exit={rr['_exit']} "
            f"piv={z['PIVOT_MONDAY']} BO={z['BREAKOUT_MONDAY']} CONF={z['CONF_MONDAY']} "
            f"ZL={z['ZONE_LOW']:.4f} ZU={z['ZONE_HIGH']:.4f} "
            f"retest_bar={z['RETEST_BAR']} sig_bar={z['ENTRY_SIGNAL_BAR']} fill_bar={z['ENTRY_FILL_BAR']}"
        )

    print("\n=== SHEET ZONE MATCH BY BAND (tolerance 2%) ===")
    zones["_bo"] = zones["Breakout Date"].map(parse_sheet_date)
    zones["_piv"] = zones["Pivot Date"].map(parse_sheet_date)
    zones["_rt"] = zones["Daily Retest Date"].map(parse_sheet_date)
    zones["_rk"] = zones["Rocket Buy Date"].map(parse_sheet_date)
    zones["_zl"] = zones["Zone Lower"].map(money)
    zones["_zu"] = zones["Zone Upper"].map(money)

    for rr in rows:
        zid = rr["WPBR_ZONE_ID"]
        z = ezones[ezones["WPBR_ZONE_ID"] == zid].iloc[0]
        zl, zu = float(z["ZONE_LOW"]), float(z["ZONE_HIGH"])
        print(f"\n## eng fill {rr['_entry']} band [{zl:.4f},{zu:.4f}] piv={z['PIVOT_MONDAY']}")
        hits = []
        for _, s in zones.iterrows():
            if s["_zl"] is None or s["_zu"] is None:
                continue
            # overlap or center proximity
            sc = (s["_zl"] + s["_zu"]) / 2
            ec = (zl + zu) / 2
            if abs(sc - ec) / ec < 0.03 or (s["_zl"] <= zu and s["_zu"] >= zl):
                hits.append(s)
        if not hits:
            print("  NO overlapping sheet zone row")
        for s in hits:
            print(
                f"  SHEET BO={s['_bo']} piv={s['_piv']} ZL={s['_zl']} ZU={s['_zu']} "
                f"retest={s['_rt']} rocket={s['_rk']}"
            )

    print("\n=== ALL SHEET ZONES WITH BLANK ROCKET (full) ===")
    blank = zones[zones["_rk"].isna() | (zones["_rk"] == None)]
    print(f"blank rocket count {len(blank)}/{len(zones)}")
    for _, s in blank.iterrows():
        print(
            f"BO={s['_bo']} piv={s['_piv']} ZL={s['_zl']} ZU={s['_zu']} "
            f"retest={s['_rt']} rocket={s['_rk']}"
        )

    print("\n=== ALL SHEET ZONES WITH ROCKET ===")
    fired = zones[zones["_rk"].notna()]
    for _, s in fired.iterrows():
        print(
            f"BO={s['_bo']} piv={s['_piv']} ZL={s['_zl']} ZU={s['_zu']} "
            f"retest={s['_rt']} rocket={s['_rk']}"
        )

    # Second-chance: 2017-01-19 and 2017-12-06 share zone?
    print("\n=== SHARED ZONE IDS AMONG EARLY 6 ===")
    from collections import Counter
    ids = [rr["WPBR_ZONE_ID"] for rr in rows]
    print(Counter(ids))

    # Audit for these dates
    print("\n=== AUDIT ROWS (AMD) sample cols ===")
    print(list(audit.columns)[:40])
    a_amd = audit[audit["SYMBOL"].astype(str).str.upper() == "AMD"] if "SYMBOL" in audit.columns else audit
    print("audit n", len(a_amd))
    print(a_amd.head(3).to_string())

    # Check if sheet has ANY zone with pivot before 2016
    print("\n=== SHEET PIVOT DATE DISTRIBUTION ===")
    pivs = [p for p in zones["_piv"] if p]
    print("min piv", min(pivs), "max", max(pivs))
    pre2016 = [p for p in pivs if p < "2016-01-01"]
    print("pre-2016 pivots on sheet:", pre2016)

    # Eng zones that have HAS_TRADE and fill in EARLY
    print("\n=== ENG ZONES WITH HAS_TRADE + early fills via ENTRY bars ===")
    # Map fill bar -> date using closed DATE_OPENED already
    traded = ezones[ezones["HAS_TRADE"].astype(str).str.lower().isin(["1", "true", "yes"]) | (ezones["HAS_TRADE"] == 1)]
    print("HAS_TRADE count", len(traded))
    # Show all eng zones with pivot before 2016 that have trades
    ezones["_piv"] = pd.to_datetime(ezones["PIVOT_MONDAY"], errors="coerce").dt.strftime("%Y-%m-%d")
    old_traded = traded[pd.to_datetime(traded["PIVOT_MONDAY"], errors="coerce") < "2016-01-01"]
    print("old-pivot traded zones:", len(old_traded))
    for _, z in old_traded.iterrows():
        print(
            f"  piv={z['PIVOT_MONDAY']} BO={z['BREAKOUT_MONDAY']} CONF={z['CONF_MONDAY']} "
            f"ZL={z['ZONE_LOW']:.4f} ZU={z['ZONE_HIGH']:.4f} id={z['WPBR_ZONE_ID']} "
            f"sig={z['ENTRY_SIGNAL_BAR']} fill={z['ENTRY_FILL_BAR']}"
        )


if __name__ == "__main__":
    main()
