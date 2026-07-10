#!/usr/bin/env python3
"""Find when touch_override would fire vs sheet center for a zone index."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from sheet_zone_ledgers import SHEET_ZONE_LEDGER  # noqa: E402


def load_sheet_center(sym: str, idx: int) -> float:
    lines = SHEET_ZONE_LEDGER[sym].read_text().strip().splitlines()
    parts = lines[idx - 1].split()
    return float(parts[0])


def replay(sym: str, zone_idx: int) -> None:
    sheet_ctr = load_sheet_center(sym, zone_idx)
    df = pd.read_csv(ROOT / "data/newdata/data" / f"{sym}.csv", parse_dates=["Date"]).sort_values("Date").set_index("Date")
    hi = np.round(df["High"].to_numpy(dtype=np.float64), 2)
    dates = df.index
    yh_lb = 252
    working = None
    touch_override = None
    event_n = 0
    target_event = zone_idx

    for t in range(len(df)):
        activated = False
        if working is not None:
            yh_bar, yh_p, act_p = working
            use_bar, use_p = (touch_override if touch_override else (yh_bar, yh_p))
            if hi[t] >= act_p:
                event_n += 1
                if event_n == target_event:
                    print(f"{sym} zone #{zone_idx} sheet={sheet_ctr:.2f}")
                    print(f"  ACT {dates[t].date()} working=({yh_bar},{yh_p:.2f},act={act_p:.2f}) override={touch_override} -> touch={use_p:.2f}")
                activated = True
                working = None
                touch_override = None

        if t >= yh_lb:
            prev_max = float(np.max(hi[t - yh_lb : t]))
            if hi[t] > prev_max:
                yh_p = round(float(hi[t]), 2)
                act_p = round(yh_p * 1.03, 2)
                if activated:
                    working = [t, yh_p, act_p]
                    touch_override = None
                elif working is None:
                    working = [t, yh_p, act_p]
                    touch_override = None
                elif touch_override is None:
                    if event_n + 1 == target_event:
                        print(f"  first drop while pending -> ({t},{yh_p:.2f}) on {dates[t].date()}")
                    touch_override = (t, yh_p)


if __name__ == "__main__":
    replay("TSLA", 2)
    replay("AAPL", 11)
    replay("NVDA", 51)
