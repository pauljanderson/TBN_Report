#!/usr/bin/env python3
"""Parse user-pasted tab rows D:BQ into column letters."""
from __future__ import annotations

# Headers D through BQ (user authoritative layout)
HEADERS = [
    "Date", "Open", "High", "Low", "Close", "Volume",
    "Local High Test", "Post Pivot Pullback", "No dup Pivot High", "Not also Pivot Low",
    "Final Pivot High", "Local Low test", "Future Rise test", "No dup pivot low",
    "Not also pivot high", "Final pivot low", "Pivot High Price", "Pivot low price",
    "Last Pivot High", "Last Pivot low", "Major Pivot High", "Major Pivot Low",
    "Pre-strong pivot High", "Pre-Strong Pivot Low", "Touch Price", "TP Zone Lower",
    "TP Zone Upper", "Range Qualifier", "Target", "Close above open", "BRT Rocket buy",
    "Stop", "exit hit today", "IN trade", "Risk Reward", "Exit type", "Exit price",
    "Entry Price Active", "Entry Date Active", "Peak High", "Current Drawdown",
    "Max Drawdown", "Growth 1 Year", "Growth 2 Year", "Growth 3 Year", "Raw Growth",
    "Growth OK", "ATH filter", "Matured touch price", "Matured Zone lower",
    "Matured zone upper", "Breakout zone upper", "Selected break upper",
    "Selected Break lower", "Breakout event", "Create Breakout record", "Breakout Date",
    "Zone Lower", "Zone Upper", "Breakout Active", "Main Row", "Scan Start Row",
    "retest Row", "Retest Date", "retest hit", "Too fast retest",
]


def col_from_d(i: int) -> str:
    n = 4 + i
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


ROWS = {
    "2019-02-04": (
        "2/4/2019\t$165.70\t169.3\t163.62\t169.25\t20,036,470\tFALSE\tTRUE\tTRUE\tTRUE\t"
        "\tFALSE\tTRUE\tTRUE\tTRUE\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t$204.67\tTRUE\tTRUE\t"
        "152.821\t\tTRUE\t\t\t\t$169.15\t2/4/2019\t\t\t\t\tTRUE\t\t\t\t\t\t166.19\t"
        "\t$161.27\t1\t1"
    ),
    "2024-11-29": (
        "11/29/2024\t$569.00\t578.46\t566.9\t574.32\t7,130,519\tTRUE\tTRUE\tTRUE\tTRUE\t"
        "Pivot High\tFALSE\tTRUE\tTRUE\tFALSE\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t$698.78\t"
        "TRUE\tTRUE\t529.485\t\tTRUE\t\t\t\t$577.50\t11/29/2024\t\t\t\t\tTRUE\t\t\t\t"
        "\t\t570.50\t\t$553.64\t1\t1"
    ),
    "2023-06-05": (
        "6/5/2023\t$270.30\t275.57\t269.56\t271.39\t20,742,946\tTRUE\tTRUE\tTRUE\tTRUE\t"
        "Pivot High\tFALSE\tTRUE\tTRUE\tFALSE\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t$326.87\t"
        "TRUE\tTRUE\t251.769\t\tTRUE\t\t\t\t$270.14\t6/5/2023\t\t\t\t\tTRUE"
    ),
    "2025-08-26": (
        "8/26/2025\t$750.80\t754.87\t747.94\t754.1\t7,601,800\tFALSE\tTRUE\tTRUE\tTRUE\t"
        "\tFALSE\tTRUE\tTRUE\tTRUE\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t$910.28\tTRUE\tTRUE\t"
        "698.576\t\tTRUE\t\t\t\t$752.30\t8/26/2025\t\t\t\t\tTRUE"
    ),
}

FOCUS = [
    "D", "E", "F", "G", "H", "AG", "AH", "AO", "AP", "AV", "AX",
    "BC", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BK", "BL", "BM", "BN", "BO", "BP", "BQ",
]


def main() -> None:
    for label, raw in ROWS.items():
        cols = raw.split("\t")
        print(f"=== {label} ({len(cols)} fields) ===")
        letter_map = {col_from_d(i): (HEADERS[i], cols[i] if i < len(cols) else "") for i in range(len(HEADERS))}
        for letter in FOCUS:
            name, val = letter_map.get(letter, ("?", ""))
            disp = val if val != "" else "(empty)"
            print(f"  {letter:3s} {name:28s} {disp}")
        print()


if __name__ == "__main__":
    main()
