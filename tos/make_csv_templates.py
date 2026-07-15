"""Write example CSV templates for the TOS generator README / release folder."""
from __future__ import annotations

import csv
from pathlib import Path

import gen_nflx_ts

OUT = Path(__file__).resolve().parent.parent / "drive" / "tos" / "release"


def ymd(d: int) -> str:
    s = str(d)
    return f"{s[4:6]}/{s[6:8]}/{s[0:4]}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "NFLX_example.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "record_type",
                "pivot_date",
                "zone_low",
                "zone_high",
                "breakout_date",
                "trade_date",
            ]
        )
        for pivot, lo, hi, bo in gen_nflx_ts.zones:
            w.writerow(
                [
                    "zone",
                    ymd(pivot),
                    f"{lo:.2f}",
                    f"{hi:.2f}",
                    ymd(bo) if bo else "",
                    "",
                ]
            )
        for d in gen_nflx_ts.entries:
            w.writerow(["entry", "", "", "", "", ymd(d)])
        for d in gen_nflx_ts.exits:
            w.writerow(["exit", "", "", "", "", ymd(d)])

    blank = OUT / "SYMBOL_template.csv"
    with blank.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "record_type",
                "pivot_date",
                "zone_low",
                "zone_high",
                "breakout_date",
                "trade_date",
            ]
        )
        w.writerow(["zone", "4/11/2016", "11.02", "11.36", "10/17/2016", ""])
        w.writerow(["zone", "5/23/2016", "10.25", "10.56", "10/17/2016", ""])
        w.writerow(["zone", "7/4/2016", "9.98", "10.28", "", ""])
        w.writerow(["entry", "", "", "", "", "3/16/2020"])
        w.writerow(["exit", "", "", "", "", "3/30/2020"])
    print(f"Wrote {path}")
    print(f"Wrote {blank}")


if __name__ == "__main__":
    main()
