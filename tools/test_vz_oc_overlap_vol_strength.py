"""Smoke tests for VZ OC-overlap volume strength helper."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.vz_oc_overlap_vol_strength import oc_overlap_mask, rvol20, zone_oc_strength
from tools.vol_zone_break_retest import Zone


def test_oc_overlap_open_or_close() -> None:
    opens = np.array([10.0, 12.0, 8.0, 11.0], dtype=float)
    closes = np.array([11.0, 13.0, 9.0, 7.0], dtype=float)
    # zone [10, 11]: bar0 open+close in; bar1 neither; bar2 neither; bar3 open in
    hit = oc_overlap_mask(opens, closes, 10.0, 11.0)
    assert list(hit) == [True, False, False, True]


def test_zone_strength_no_lookahead() -> None:
    n = 30
    df = pd.DataFrame(
        {
            "Date": pd.date_range("2020-01-01", periods=n, freq="B"),
            "Open": np.full(n, 10.0),
            "High": np.full(n, 11.0),
            "Low": np.full(n, 9.0),
            "Close": np.full(n, 10.5),
            "Volume": np.arange(n, dtype=float) * 1000 + 1000,
        }
    )
    z = Zone(
        zone_id="HL_2020-01-10",
        kind="HL",
        max_vol_idx=5,
        max_vol_date=pd.Timestamp(df["Date"].iloc[5]),
        volume=int(df["Volume"].iloc[5]),
        lo=10.0,
        hi=11.0,
        created_on_idx=8,
        created_on=pd.Timestamp(df["Date"].iloc[8]),
        last_winner_idx=12,
        last_winner_date=pd.Timestamp(df["Date"].iloc[12]),
    )
    rvol = rvol20(df["Volume"].to_numpy(dtype=float), win=5)
    early = zone_oc_strength(df, z, asof_idx=10, rvol=rvol)
    late = zone_oc_strength(df, z, asof_idx=20, rvol=rvol)
    assert early["oc_overlap_n"] < late["oc_overlap_n"]
    # as-of 8 (created_on) should have zero post-creation bars
    at_create = zone_oc_strength(df, z, asof_idx=8, rvol=rvol)
    assert at_create["oc_overlap_n"] == 0.0


if __name__ == "__main__":
    test_oc_overlap_open_or_close()
    test_zone_strength_no_lookahead()
    print("vz_oc_overlap_vol_strength helpers OK")
