#!/usr/bin/env python3
"""Build MOM ADV$5m universe from the same VZ tradable screen as ADV$2m.

Cut (exact):
  - first_bar <= 2010-01-04
  - as-of 2023-12-29: Close >= $5
  - 20-session ADV$ = mean(Close * Volume) >= $5,000,000
Source table: drive/paul_experiments/vz_tradable_2010_adv2m_20260818/universe_rejects.csv
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REJECT = ROOT / "drive" / "paul_experiments" / "vz_tradable_2010_adv2m_20260818" / "universe_rejects.csv"
OUT = ROOT / "drive" / "universes" / "MOM_universe_adv5m.csv"
MIN_ADV = 5_000_000.0


def main() -> int:
    df = pd.read_csv(REJECT)
    keep = df[(df["pass"] == "Y") & (df["adv20_usd"] >= MIN_ADV)].copy()
    keep = keep.sort_values("SYMBOL")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MOM (Momentum) research universe — ADV$5m liquid cut (not gold / not DailyRun)",
        "# Same methodology as tools/vz_build_tradable_universe.py with MIN_ADV raised to 5e6.",
        "# first_bar <= 2010-01-04; Close >= 5; 20d ADV$ >= 5000000 (as-of 2023-12-29). Not PIT S&P 500.",
        f"# Source screen: {REJECT.as_posix()} (pass=Y & adv20_usd >= 5e6)",
        "SYMBOL",
    ]
    for s in keep["SYMBOL"].astype(str).str.upper():
        lines.append(s)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    n2 = int((df["pass"] == "Y").sum())
    print(f"adv2m_pass={n2} adv5m_pass={len(keep)} dropped={n2 - len(keep)}")
    print(f"wrote={OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
