#!/usr/bin/env python3
"""Count how many zone activations would use touch_override at a given gap threshold."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sheet_zone_ledgers import SHEET_ZONE_LEDGER  # noqa: E402


def use_override(working_bar: int, ov_bar: int, yh_p: float, ov_p: float) -> bool:
    if ov_p <= yh_p or yh_p <= 0:
        return False
    gap = (ov_p - yh_p) / yh_p
    bars = ov_bar - int(working_bar)
    # Small gap: always adopt first intermediate YH (AAPL 2018-02-27).
    # Moderate gap after several sessions: adopt (NVDA 2021-11-22).
    # Large gap on very next bar: keep working touch (TSLA 2017-04-03).
    return gap <= 0.0015 or (gap <= 0.015 and bars > 1)


def simulate(sym: str, max_pct: float | None = None) -> tuple[int, int, list[tuple[int, float, float, float]]]:
    lines = SHEET_ZONE_LEDGER[sym].read_text().strip().splitlines()
    sheet_centers = [float(l.split()[0]) for l in lines]
    df = pd.read_csv(ROOT / f"data/newdata/data/{sym}.csv", parse_dates=["Date"]).sort_values("Date").set_index("Date")
    hi = np.round(df["High"].to_numpy(dtype=np.float64), 2)
    yh_lb = 252
    working = None
    touch_override = None
    events: list[tuple[float, float, float, float]] = []  # sheet, working, override, gap_pct
    ei = 0

    for t in range(len(df)):
        activated = False
        if working is not None:
            yh_bar, yh_p, act_p = working
            use_p = yh_p
            if touch_override is not None:
                ov_bar, ov_p = touch_override
                if max_pct is not None:
                    ok = ov_p > yh_p and yh_p > 0 and (ov_p - yh_p) / yh_p <= max_pct
                else:
                    ok = use_override(yh_bar, ov_bar, yh_p, ov_p)
                if ok:
                    use_p = ov_p
            if hi[t] >= act_p:
                sheet = sheet_centers[ei] if ei < len(sheet_centers) else float("nan")
                events.append((sheet, yh_p, use_p, abs(sheet - use_p)))
                ei += 1
                activated = True
                working = None
                touch_override = None
        if t >= yh_lb and hi[t] > float(np.max(hi[t - yh_lb : t])):
            yh_p = round(float(hi[t]), 2)
            act_p = round(yh_p * 1.03, 2)
            if activated:
                working = [t, yh_p, act_p]
                touch_override = None
            elif working is None:
                working = [t, yh_p, act_p]
                touch_override = None
            elif touch_override is None:
                touch_override = (t, yh_p)
    exact = sum(1 for s, w, u, d in events if abs(s - u) < 0.001)
    return exact, len(events), events


if __name__ == "__main__":
    print("=== compound rule (no flat max_pct) ===")
    for sym in ["TSLA", "META", "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "NFLX"]:
        ex, n, _ = simulate(sym, None)
        print(f"  {sym}: {ex}/{n} exact")
    for sym, idx in [("AAPL", 11), ("NVDA", 51)]:
        _, _, ev = simulate(sym, None)
        s, w, u, d = ev[idx - 1]
        print(f"  {sym} #{idx}: sheet={s:.2f} working={w:.2f} used={u:.2f} delta={d:.2f}")

    for pct in (0.005, 0.01, 0.015, 0.02):
        print(f"\n=== max_pct={pct*100:.1f}% ===")
        for sym in ["TSLA", "META", "AAPL", "NVDA"]:
            ex, n, _ = simulate(sym, pct)
            print(f"  {sym}: {ex}/{n} exact")
