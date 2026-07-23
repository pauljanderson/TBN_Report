"""Verify engine retest_mode=stop_looking matches sheet Daily Retest Dates on META.

Compares compute_wpbr_touch_stream(stop_looking) and (keep_looking) retest dates
against the pasted sheet zones.tsv Daily Retest Date for all 48 META zones.
"""
from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))

from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

DATA = REPO / "data" / "newdata" / "data" / "META.csv"
BASE = REPO / "drive" / "wpbr_sheet_reconcile" / "META"

PARAMS = dict(
    band_pct=0.015,
    strong_pre_pivot_bars=3,
    strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3,
    strong_post_pivot_pct=0.10,
    strong_pivot_mode="either",
    breakout_confirmation=0.03,
    max_days_after_retest=2,
    zone_price_round_decimals=2,
)


def load_zones() -> pd.DataFrame:
    z = pd.read_csv(BASE / "zones.tsv", sep="\t")
    for c in ["Zone Lower", "Zone Upper"]:
        z[c] = z[c].astype(str).str.replace("$", "", regex=False).astype(float)
    for c in ["Pivot Date", "Next week start date", "Daily Retest Date"]:
        z[c] = pd.to_datetime(z[c], errors="coerce")
    return z


def retest_dates(df: pd.DataFrame, mode: str) -> dict[str, pd.Timestamp | None]:
    out = compute_wpbr_touch_stream(df, retest_mode=mode, **PARAMS)
    res: dict[str, pd.Timestamp | None] = {}
    for ev in out["wpbr_zone_events"]:
        rb = int(ev.get("retest_bar", -1))
        piv = pd.Timestamp(ev["pivot_monday"]).normalize()
        res[piv.strftime("%Y-%m-%d")] = (
            pd.Timestamp(df.index[rb]).normalize() if rb >= 0 else None
        )
    return res


def main() -> int:
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    df = df[df.index >= pd.Timestamp("2016-01-01")]
    zones = load_zones()

    for mode in ("stop_looking", "keep_looking"):
        eng = retest_dates(df, mode)
        match = blank_match = eng_only = sheet_only = date_diff = 0
        misses = []
        for _, z in zones.iterrows():
            piv = z["Pivot Date"]
            if pd.isna(piv):
                continue
            key = piv.strftime("%Y-%m-%d")
            sheet = z["Daily Retest Date"]
            e = eng.get(key, "MISSING_ZONE")
            if e == "MISSING_ZONE":
                misses.append((key, "no engine zone", sheet))
                continue
            if pd.isna(sheet) and e is None:
                blank_match += 1
            elif pd.isna(sheet) and e is not None:
                eng_only += 1
                misses.append((key, f"eng={e.date()}", "sheet=BLANK"))
            elif not pd.isna(sheet) and e is None:
                sheet_only += 1
                misses.append((key, "eng=BLANK", f"sheet={sheet.date()}"))
            elif sheet.normalize() == e.normalize():
                match += 1
            else:
                date_diff += 1
                misses.append((key, f"eng={e.date()}", f"sheet={sheet.date()}"))
        total = len(zones)
        print(f"=== mode={mode} ===")
        print(
            f"  date_match={match} blank_match={blank_match} "
            f"eng_only(sheet_blank)={eng_only} sheet_only(eng_blank)={sheet_only} "
            f"date_diff={date_diff}  parity={match + blank_match}/{total}"
        )
        for k, a, b in misses:
            print(f"    pivot={k}: {a} | {b}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
