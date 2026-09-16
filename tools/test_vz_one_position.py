"""Same-day / overlapping VZ fills must not open a second lot while held."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "stock_analysis") not in sys.path:
    sys.path.insert(0, str(REPO / "stock_analysis"))

from dataclasses import replace

from rocket_vz import enrich_trade_rows  # noqa: E402
from tools.vol_zone_break_retest import (  # noqa: E402
    ExitSpec,
    RESEARCH_CANDIDATE_V2_RW63,
    RetestSignal,
)

PARAMS = replace(RESEARCH_CANDIDATE_V2_RW63, entry_on="next_open")


def _df() -> pd.DataFrame:
    n = 8
    dates = pd.date_range("2020-05-05", periods=n, freq="B")
    close = np.array([6.8, 6.92, 7.2, 7.5, 8.3, 8.1, 8.0, 7.9], dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 0.4,
            "Low": close - 0.4,
            "Close": close,
            "Volume": np.full(n, 1000.0),
        }
    )


def _sig(zone_id: str, stop: float, break_idx: int) -> RetestSignal:
    return RetestSignal(
        zone_id=zone_id,
        kind="HL",
        entry_idx=1,
        entry_date=pd.Timestamp("2020-05-06"),
        entry_price=6.92,
        break_idx=break_idx,
        break_date=pd.Timestamp("2020-04-16"),
        bars_after_break=1,
        touch_count_all=1,
        touch_count_holds=1,
        pre_break_touches=0,
        post_break_touches=1,
        strength=1.0,
        stop=stop,
        params_tag="t",
        signal_idx=0,
        signal_date=pd.Timestamp("2020-05-05"),
        side="long",
    )


def test_same_day_two_zones_keep_one() -> None:
    df = _df()
    atr = np.full(len(df), 0.5)
    exit_spec = ExitSpec(
        name="EXIT_atr4_s025_r15_ts20",
        label="house",
        stop_atr_buffer=0.25,
        target_r=1.5,
        exit_bars=20,
    )
    closed, opens = enrich_trade_rows(
        "GOLD",
        df,
        [_sig("HL_wide", 6.07, 0), _sig("HL_tight", 6.38, 1)],
        PARAMS,
        atr,
        exit_spec,
        45000.0,
        cooldown_after_target_days=0,
    )
    fills = closed + opens
    assert len(fills) == 1, f"expected 1 fill, got {len(fills)}: {fills}"
    assert fills[0]["DATE_OPENED"] == "20200506"
    assert int(fills[0]["N_SIGNALS_THAT_DAY"]) == 2, fills[0]
    assert fills[0]["MULTI_SIGNAL_DAY"] == "YES"


def test_later_entry_while_held_dropped() -> None:
    df = _df()
    atr = np.full(len(df), 0.5)
    exit_spec = ExitSpec(
        name="EXIT_atr4_s025_r15_ts20",
        label="house",
        stop_atr_buffer=0.25,
        target_r=1.5,
        exit_bars=20,
    )
    first = _sig("HL_a", 6.38, 0)
    second = _sig("HL_b", 6.10, 1)
    second.entry_idx = 2
    second.entry_date = pd.Timestamp("2020-05-07")
    second.signal_idx = 1
    second.signal_date = pd.Timestamp("2020-05-06")
    closed, opens = enrich_trade_rows(
        "GOLD",
        df,
        [first, second],
        PARAMS,
        atr,
        exit_spec,
        45000.0,
        cooldown_after_target_days=0,
    )
    fills = closed + opens
    assert len(fills) == 1, f"expected 1 fill, got {len(fills)}"
    assert fills[0]["DATE_OPENED"] == "20200506"
    assert int(fills[0]["N_SIGNALS_THAT_DAY"]) == 1
    assert fills[0]["MULTI_SIGNAL_DAY"] == "NO"


if __name__ == "__main__":
    test_same_day_two_zones_keep_one()
    test_later_entry_while_held_dropped()
    print("vz_one_position OK")
