#!/usr/bin/env python3
"""Parse user sheet paste - align from known anchors (AO/AP, BC/BF/BG tail)."""
from __future__ import annotations

from pathlib import Path

# D through BQ (66 cols)
LETTERS = []
for i in range(66):
    n = 4 + i
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    LETTERS.append(s)

NAMES = {
    "D": "Date", "AG": "Close above open", "AH": "BRT Rocket buy", "AK": "IN trade",
    "AO": "Entry Price Active", "AP": "Entry Date Active", "AV": "Growth 3 Year",
    "AX": "Growth OK", "AY": "ATH filter",
    "BC": "Breakout zone upper", "BD": "Sel break upper", "BE": "Sel break lower",
    "BF": "Breakout event", "BG": "Create Breakout record", "BH": "Breakout Date",
    "BI": "Zone Lower", "BJ": "Zone Upper", "BK": "Breakout Active",
    "BL": "Main Row", "BM": "Scan Start Row", "BN": "retest Row", "BO": "Retest Date",
    "BP": "retest hit", "BQ": "Too fast retest",
    "AF": "Target",
}


def align_row(fields: list[str]) -> dict[str, str]:
    """Map fields starting at D (fields[0]=D)."""
    out: dict[str, str] = {}
    for i, v in enumerate(fields):
        if i < len(LETTERS):
            out[LETTERS[i]] = v
    return out


def main() -> None:
    path = Path(__file__).parent / "sheet_paste_rows.tsv"
    focus = [
        "D", "AG", "AH", "AK", "AF", "AO", "AP", "AV", "AX", "AY",
        "BC", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BK",
        "BL", "BM", "BN", "BO", "BP", "BQ",
    ]
    for line in path.read_text(encoding="utf-8").splitlines():
        label, rest = line.split("\t", 1)
        fields = rest.split("\t")
        m = align_row(fields)
        print(f"=== {label} ({len(fields)} fields from D) ===")
        for let in focus:
            v = m.get(let, "")
            print(f"  {let:3s} {NAMES.get(let, let):28s} {v if v else '(empty)'}")
        print()


if __name__ == "__main__":
    main()
