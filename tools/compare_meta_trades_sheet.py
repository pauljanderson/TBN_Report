#!/usr/bin/env python3
"""Compare META closed trades vs spreadsheet trade log."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

SHEET_TRADES = [
    ("2019-01-04", 137.56, "2019-01-31", 166.45, 21.00, 27, "WIN", 9975.00),
    ("2019-02-04", 169.15, "2019-07-12", 204.67, 21.00, 158, "WIN", 9975.00),
    ("2019-09-09", 187.44, "2019-10-02", 173.58, -7.39, 23, "LOSS", -3511.34),
    ("2019-10-21", 190.00, "2020-03-09", 169.60, -10.74, 140, "LOSS", -5100.00),
    ("2020-03-18", 146.62, "2020-04-14", 178.98, 22.07, 27, "WIN", 10483.56),
    ("2020-04-22", 184.08, "2020-05-20", 223.50, 21.41, 28, "WIN", 10171.94),
    ("2020-06-29", 220.59, "2020-08-07", 266.91, 21.00, 39, "WIN", 9975.00),
    ("2020-09-21", 253.31, "2021-04-05", 306.51, 21.00, 196, "WIN", 9975.00),
    ("2021-05-19", 313.58, "2021-08-30", 379.43, 21.00, 103, "WIN", 9975.00),
    ("2021-10-12", 326.97, "2022-01-24", 296.42, -9.34, 104, "LOSS", -4437.58),
    ("2022-03-22", 213.33, "2022-04-21", 196.31, -7.98, 30, "LOSS", -3790.09),
    ("2022-05-19", 194.97, "2022-05-24", 177.09, -9.17, 5, "LOSS", -4356.93),
    ("2022-06-06", 191.93, "2022-06-10", 175.97, -8.32, 4, "LOSS", -3950.97),
    ("2023-03-08", 186.35, "2023-04-27", 239.89, 28.73, 50, "WIN", 13647.17),
    ("2023-06-05", 270.14, "2023-10-11", 326.87, 21.00, 128, "WIN", 9975.00),
    ("2023-12-04", 318.98, "2024-01-22", 387.95, 21.62, 49, "WIN", 10270.47),
    ("2024-08-05", 479.00, "2024-10-01", 579.59, 21.00, 57, "WIN", 9975.00),
    ("2024-11-29", 577.50, "2025-01-30", 698.78, 21.00, 62, "WIN", 9975.00),
    ("2025-02-28", 673.68, "2025-03-10", 600.19, -10.91, 10, "LOSS", -5181.76),
    ("2025-03-14", 607.46, "2025-03-31", 555.52, -8.55, 17, "LOSS", -4061.07),
    ("2025-04-07", 543.25, "2025-05-13", 657.33, 21.00, 36, "WIN", 9975.00),
    ("2025-05-30", 644.39, "2025-07-31", 779.71, 21.00, 62, "WIN", 9975.00),
    ("2025-08-26", 752.30, "2025-10-06", 698.58, -7.14, 41, "LOSS", -3392.12),
    ("2025-10-13", 707.78, "2025-10-30", 660.94, -6.62, 17, "LOSS", -3143.78),
    ("2026-02-05", 665.49, "2026-03-13", 610.37, -8.28, 36, "LOSS", -3934.32),
]


def _pct(s: str | float) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    return float(str(s).replace("%", ""))


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260619080143"
    drive = ROOT / "Drive"
    closed_path = drive / f"YH_Closed_{run_id}.csv"
    entries_path = drive / f"YH_ZONES_ENTRIES_META_{run_id}.csv"
    retest_path = drive / f"YH_breakout_and_retest_{run_id}.csv"

    eng = pd.read_csv(closed_path)
    eng = eng[eng["SYMBOL"] == "META"].copy()
    eng["DATE_OPENED"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d", errors="coerce")
    eng["DATE_CLOSED"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d", errors="coerce")

    entries = pd.read_csv(entries_path)
    entries["ENTRY_DATE"] = pd.to_datetime(entries["ENTRY_DATE"])

    print(f"=== META trades: sheet vs run {run_id} ===")
    print(f"Sheet trades:          {len(SHEET_TRADES)}")
    print(f"Engine closed trades:  {len(eng)}")
    print(f"Engine zone entries:   {len(entries)}")
    print()

    print("Engine closed:")
    for _, r in eng.iterrows():
        print(
            f"  {r.DATE_OPENED.date()}  entry {r.ENTRY_PRICE:7.2f}  ->  "
            f"{r.DATE_CLOSED.date()}  exit {float(r.EXIT_PRICE):7.2f}  "
            f"{r.EXIT_TYPE:8s}  {_pct(r.PNL_PCT):+6.2f}%  {int(r.DAYS_HELD):3d}d  "
            f"${float(r.PNL_DOLLARS):,.0f}"
        )
    print()

    print("Sheet vs engine (nearest entry within 30 calendar days):")
    matched_eng = set()
    for se, sp, sx, xp, pp, days, res, pnl in SHEET_TRADES:
        se_dt = pd.Timestamp(se)
        best = None
        for idx, r in eng.iterrows():
            delta = abs((r.DATE_OPENED - se_dt).days)
            if best is None or delta < best[0]:
                best = (delta, idx, r)
        if best and best[0] <= 30:
            _, idx, r = best
            matched_eng.add(idx)
            exit_delta = abs((r.DATE_CLOSED - pd.Timestamp(sx)).days)
            price_delta = abs(float(r.ENTRY_PRICE) - sp)
            if price_delta <= 2.0 and exit_delta <= 15:
                tag = "MATCH"
            elif price_delta <= 5.0 or exit_delta <= 30:
                tag = "PARTIAL"
            else:
                tag = "DATE_ONLY"
            print(
                f"  {tag:8s}  sheet {se} ${sp:7.2f} {res:4s} {pp:+6.2f}%  |  "
                f"eng {r.DATE_OPENED.date()} ${float(r.ENTRY_PRICE):7.2f} "
                f"-> {r.DATE_CLOSED.date()} {_pct(r.PNL_PCT):+6.2f}%  "
                f"(entry {best[0]}d, exit {exit_delta}d, price {price_delta:.2f})"
            )
        else:
            nearest = best[0] if best else None
            print(f"  MISSING   sheet {se} ${sp:7.2f} {res:4s} {pp:+6.2f}%  (nearest eng entry {nearest}d)")

    print()
    eng_only = [r for _, r in eng.iterrows() if _ not in matched_eng]
    if eng_only:
        print("Engine-only trades (no sheet entry within 30d):")
        for r in eng_only:
            print(f"  {r.DATE_OPENED.date()} entry {r.ENTRY_PRICE:.2f} -> {r.DATE_CLOSED.date()}")

    if retest_path.is_file():
        rt = pd.read_csv(retest_path)
        rt = rt[rt["Symbol"] == "META"] if "Symbol" in rt.columns else rt
        col = "Retest Date" if "Retest Date" in rt.columns else rt.columns[0]
        print()
        print("Sample retest dates near missing sheet entries:")
        for se, sp, *_ in SHEET_TRADES[:6]:
            se_dt = pd.Timestamp(se)
            near = []
            for _, row in rt.iterrows():
                rd = pd.to_datetime(row.get("Retest Date", row.iloc[1]), errors="coerce")
                if pd.isna(rd):
                    continue
                d = abs((rd - se_dt).days)
                if d <= 5:
                    near.append((d, str(rd.date()), row.get("Breakout Date", "")))
            if near:
                near.sort()
                print(f"  sheet entry {se}: retest {near[0][1]} (delta {near[0][0]}d)")


if __name__ == "__main__":
    main()
