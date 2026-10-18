#!/usr/bin/env python3
"""Unit tests for the SMA200 persistence count and the 25/50/75 percent cuts."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

import rocket_tbn as tbn  # noqa: E402


def test_off_when_window_is_zero():
    ok, reason = tbn.sma200_persist_passes(None, 0, 0.75)
    assert ok and reason == ""


def test_missing_window_is_history():
    ok, reason = tbn.sma200_persist_passes(None, 756, 0.25)
    assert not ok and reason == "SMA_HISTORY"


def test_zero_fraction_accepts_any_defined_window():
    ok, reason = tbn.sma200_persist_passes(0, 756, 0.0)
    assert ok and reason == ""


def test_exact_cuts_on_756_sessions():
    cuts = [(0.25, 189), (0.50, 378), (0.75, 567)]
    for frac, need in cuts:
        ok, reason = tbn.sma200_persist_passes(need, 756, frac)
        assert ok and reason == "", (frac, need, reason)
        ok, reason = tbn.sma200_persist_passes(need - 1, 756, frac)
        assert not ok and reason == "SMA_PERSIST", (frac, need - 1, reason)


def test_equal_close_does_not_count_as_above():
    close = np.full(12, 10.0)
    # SMA3 is 10 on every bar from index 2. Window of 4 ending at bar 11 is all equal.
    assert tbn.sma200_persist_above_count(close, end_bar=11, window=4, sma_period=3) == 0


def test_short_history_is_none():
    close = np.arange(1.0, 30.0)
    assert tbn.sma200_persist_above_count(close, end_bar=10, window=8, sma_period=5) is None


def test_rising_closes_count_above():
    close = np.arange(1.0, 40.0)
    above = tbn.sma200_persist_above_count(close, end_bar=30, window=6, sma_period=5)
    assert above == 6


def main() -> int:
    tests = [
        test_off_when_window_is_zero,
        test_missing_window_is_history,
        test_zero_fraction_accepts_any_defined_window,
        test_exact_cuts_on_756_sessions,
        test_equal_close_does_not_count_as_above,
        test_short_history_is_none,
        test_rising_closes_count_above,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"ok {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
