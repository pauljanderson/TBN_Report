#!/usr/bin/env python3
"""Build sheet-equivalent ledger from engine export + OHLC replay (scan_delta=2, fixed zone)."""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def parse_mdy(s: str) -> str:
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def iso_to_mdy(iso: str) -> str:
    if not iso:
        return ""
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%m/%d/%Y")


def replay(ohlc: pd.DataFrame, bo_iso: str, zl: float, zu: float, scan_delta: int) -> tuple[str, int]:
    dates = ohlc["iso"].tolist()
    if bo_iso not in dates:
        return "", -1
    b = dates.index(bo_iso)
    zlr, zur = round(zl, 2), round(zu, 2)
    start = b + max(1, scan_delta)
    for k in range(start, len(ohlc)):
        lo = round(float(ohlc.iloc[k]["Low"]), 2)
        hi = round(float(ohlc.iloc[k]["High"]), 2)
        if lo <= zur and hi >= zlr:
            return dates[k], k + 2
    return "", -1


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260619083217"
    scan_delta = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "tools" / "meta_breakout_ledger_derived.tsv"

    rt_path = ROOT / "Drive" / f"YH_breakout_and_retest_{run_id}.csv"
    ohlc_path = ROOT / "data" / "newdata" / "data" / "META.csv"
    ohlc = pd.read_csv(ohlc_path, parse_dates=["Date"]).sort_values("Date")
    ohlc["iso"] = ohlc["Date"].dt.strftime("%Y-%m-%d")

    headers = [
        "Breakout Date",
        "Zone Lower",
        "Zone Upper",
        "Breakout Active",
        "Main Row",
        "Scan Start Row",
        "retest Row",
        "Retest Date",
        "retest hit",
    ]
    rows_out: list[list[str]] = []
    with rt_path.open() as f:
        for r in csv.DictReader(f):
            if r["SYMBOL"] != "META":
                continue
            bo = r["Breakout Date"]
            bo_iso = parse_mdy(bo)
            zl = float(r["Zone Lower"].replace("$", ""))
            zu = float(r["Zone Upper"])
            mr = int(r["Main Row"])
            scan_row = mr + scan_delta
            rt_iso, rr = replay(ohlc, bo_iso, zl, zu, scan_delta)
            rows_out.append(
                [
                    bo,
                    f"${zl:.2f}",
                    f"{zu:.2f}",
                    "1",
                    str(mr),
                    str(scan_row),
                    str(rr) if rr > 0 else "",
                    iso_to_mdy(rt_iso),
                    "1" if rt_iso else "",
                ]
            )

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(headers)
        w.writerows(rows_out)
    print(f"Wrote {len(rows_out)} rows to {out_path} (scan_delta={scan_delta})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
