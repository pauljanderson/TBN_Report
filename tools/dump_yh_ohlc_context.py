#!/usr/bin/env python3
"""Dump OHLC + YH math at dates relevant to zone definition parity."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def show(sym: str, dates: list[str], label: str) -> None:
    df = pd.read_csv(ROOT / f"data/newdata/data/{sym}.csv", parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
    print(f"\n=== {sym}: {label} ===")
    print(f"CSV: {ROOT / f'data/newdata/data/{sym}.csv'}  ({len(df)} rows, {df['Date'].iloc[0].date()} .. {df['Date'].iloc[-1].date()})")
    for d in dates:
        ts = pd.Timestamp(d)
        m = df["Date"] == ts
        if not m.any():
            print(f"  {d}: NOT IN CSV")
            continue
        i = int(df.index[m][0])
        row = df.iloc[i]
        hi = float(row["High"])
        rnd = round(hi, 2)
        act = round(rnd * 1.03, 2)
        prev252 = float(df.iloc[i - 252 : i]["High"].max()) if i >= 252 else float("nan")
        prev252_i = int(df.iloc[i - 252 : i]["High"].idxmax()) if i >= 252 else -1
        prev252_date = df.iloc[prev252_i]["Date"].date() if i >= 252 else None
        new_yh = rnd > round(prev252, 2) if i >= 252 else None
        zlo = round(rnd * (1 - 0.015), 2)
        zhi = round(rnd * (1 + 0.015), 2)
        print(
            f"  {d}  excel_row={i+2}  bar_i={i}  "
            f"O={row['Open']:.4f}  H={hi:.6f}  rnd_H={rnd:.2f}  act>={act:.2f}  "
            f"L={row['Low']:.4f}  C={row['Close']:.4f}"
        )
        if i >= 252:
            print(
                f"       252d_max_high(prior)={prev252:.6f} rnd={round(prev252,2):.2f} on {prev252_date}  "
                f"NEW_YH={new_yh}  band@1.5%={zlo:.2f}/{zhi:.2f}"
            )


def main() -> None:
    show(
        "AAPL",
        [
            "2017-10-31",
            "2017-11-01",
            "2017-11-03",
            "2017-11-06",
            "2017-11-07",
            "2017-11-08",
            "2018-02-26",
            "2018-02-27",
        ],
        "zone ladder #11 — YH assignment + activation (sheet ctr 43.81)",
    )
    show(
        "NVDA",
        [
            "2021-11-02",
            "2021-11-04",
            "2021-11-05",
            "2021-11-09",
            "2021-11-10",
            "2021-11-18",
            "2021-11-19",
            "2021-11-22",
        ],
        "zone ladder #51 — YH assignment + activation (sheet ctr 32.76)",
    )
    show(
        "TSLA",
        ["2017-02-09", "2017-02-13", "2017-02-14", "2017-04-03"],
        "zone ladder #2 — counterexample (sheet ctr 18.72, engine agrees)",
    )


if __name__ == "__main__":
    main()
