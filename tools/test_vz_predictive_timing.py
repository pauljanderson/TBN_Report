"""Smoke asserts for VZ predictive timing (no look-ahead on signal-bar open)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.vol_zone_break_retest import RetestSignal, assert_predictive_entry  # noqa: E402


def _sig(entry_idx: int, signal_idx: int) -> RetestSignal:
    return RetestSignal(
        zone_id="z",
        kind="HL",
        entry_idx=entry_idx,
        entry_date=pd.Timestamp("2020-01-10"),
        entry_price=10.0,
        break_idx=1,
        break_date=pd.Timestamp("2020-01-02"),
        bars_after_break=entry_idx - 1,
        touch_count_all=1,
        touch_count_holds=1,
        pre_break_touches=0,
        post_break_touches=1,
        strength=1.0,
        stop=9.0,
        params_tag="t",
        signal_idx=signal_idx,
        signal_date=pd.Timestamp("2020-01-09"),
    )


def test_close_fill_same_bar_ok() -> None:
    assert_predictive_entry(_sig(5, 5), "close")


def test_next_open_fill_next_bar_ok() -> None:
    assert_predictive_entry(_sig(6, 5), "next_open")


def test_forbid_same_bar_as_next_open() -> None:
    try:
        assert_predictive_entry(_sig(5, 5), "next_open")
    except AssertionError:
        return
    raise AssertionError("expected look-ahead reject")


def test_forbid_entry_before_signal() -> None:
    try:
        assert_predictive_entry(_sig(4, 5), "close")
    except AssertionError:
        return
    raise AssertionError("expected look-ahead reject")


if __name__ == "__main__":
    test_close_fill_same_bar_ok()
    test_next_open_fill_next_bar_ok()
    test_forbid_same_bar_as_next_open()
    test_forbid_entry_before_signal()
    print("vz_predictive_timing OK")
