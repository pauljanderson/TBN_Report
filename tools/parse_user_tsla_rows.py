#!/usr/bin/env python3
"""Parse user-pasted TSLA MTS rows."""
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
header = (_REPO / "tools" / "sheet_extras_windows.tsv").read_text().splitlines()[0].split("\t")

ROWS = {
    "2019-01-02": (
        "1/2/2019\t$20.41\t21.01\t19.92\t20.67\t11,658,648\tFALSE\tFALSE\tTRUE\tTRUE\t"
        "\tFALSE\tTRUE\tTRUE\tTRUE\t\t\t\t\t\t$22.61\t$19.61\t\t\t\t\t\t\t\t\t\t"
        "FALSE\tTRUE\tTRUE\tFALSE\tTRUE\tTRUE\tTRUE\tTRUE\tTRUE\t2\tTRUE\t\t\t"
        "FALSE\tTRUE\tFALSE\t$25.19\t$19.61\t1\t4\tTRUE\t$24.97\tTRUE\t#REF!\tTRUE\t"
        "\tTRUE\t18.60528\t\tTRUE\t1.54\t\t\t$20.47\t1/2/2019\t0.00\t0.00%\t0.00%\t"
        "FALSE\tTRUE\tTRUE\tFALSE\tFALSE\tTRUE\tTRUE\tFALSE\t\t\t\t\t\t\t\t\t\t"
        "\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t"
        "$20.70\t$21.54\t701\t3\tTRUE"
    ),
    "2021-12-21": (
        "12/21/2021\t$305.62\t313.17\t295.37\t312.84\t23,839,305\tFALSE\tFALSE\tTRUE\tFALSE\t"
        "\tFALSE\tTRUE\tTRUE\tTRUE\t\t\t\t\t\t$390.95\t$295.37\t\t\t\t\t\tLL\t\t"
        "Major Low\t\tTRUE\t$295.37\t$289.46\t$301.28\tFALSE\tFALSE\tFALSE\tTRUE\t"
        "TRUE\tTRUE\tTRUE\tTRUE\tTRUE\t1\tFALSE\t\t\tFALSE\tFALSE\tTRUE\t$414.50\t"
        "$254.53\t3\t29\t\t$392.71\tTRUE\t#REF!\tTRUE\t\tTRUE\t275.87558\t\tTRUE\t"
        "1.54\t\t\t$321.89\t12/21/2021\t0.00\t0.00%\t0.00%\tTRUE\tTRUE\tTRUE\tTRUE\t"
        "TRUE\tTRUE\tTRUE\tFALSE\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t"
        "\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t"
        "$310.49\t$323.17\t1501\t1\tTRUE"
    ),
}

FOCUS = [
    "Touch Price", "Zone Lower", "Zone Upper",
    "Support test", "Support Evidence", "Zone Eligible Long",
    "Long window Rolling touch count", "magic touch event", "Range Qualifier",
    "Target", "Close above open", "Level Acceptance", "MTS buy",
    "IN trade", "Entry Price Active", "Entry Date Active",
    "Growth 1 Year", "Growth 2 Year", "Growth 3 Year", "Growth OK",
    "Active zone lower", "Active zone upper", "Active zone available row", "Active zone ID",
]


def main() -> None:
    for label, raw in ROWS.items():
        cols = raw.split("\t")
        print(f"=== {label} ({len(cols)} fields, header {len(header)}) ===")
        for name in FOCUS:
            try:
                i = header.index(name)
                val = cols[i] if i < len(cols) else "(missing)"
            except ValueError:
                val = "(no header)"
            print(f"  {name:35s} {val or '(empty)'}")
        print()


if __name__ == "__main__":
    main()
