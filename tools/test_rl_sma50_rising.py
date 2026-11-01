#!/usr/bin/env python3
"""SMA50-rising snap: pandas 1e-14 leftovers are not a rise."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

import rocket_rl as rl  # noqa: E402


def test_hairline_equal_sums_are_not_rising():
    # House (AWK running sum): 126.1822 == 126.1822 → rising False.
    # pandas leftover on one side must not flip the flag.
    assert not rl._sma_is_rising(126.18220000000001, 126.1822)
    assert not rl._sma_is_rising(126.1822, 126.18220000000001)
    assert not rl._sma_is_rising(126.18220000000007, 126.18220000000007)
    assert not rl._sma_is_rising(126.1822, 126.1822)


def test_true_rise_and_fall_after_snap():
    assert rl._sma_is_rising(126.1823, 126.1822)
    assert not rl._sma_is_rising(126.1821, 126.1822)


def test_snap_is_round_half_even_4dp():
    assert rl._snap_sma_for_compare(126.18220000000001) == 126.1822
    assert rl._snap_sma_for_compare(126.1822) == 126.1822
    # Half-even: 5 with the kept 4th decimal even (2) stays 126.1822.
    assert rl._snap_sma_for_compare(126.18225) == 126.1822


def test_hwkn_current_csv_equal_50_sums_not_rising():
    path = _REPO / "data" / "newdata" / "data" / "HWKN.csv"
    assert path.exists(), f"missing {path}"
    df = pd.read_csv(path, parse_dates=["Date"]).sort_values("Date")
    close = df["Close"].astype(float)
    sma50 = close.rolling(50, min_periods=50).mean()
    t = len(df) - 1
    t4 = t - 4
    raw_t = float(sma50.iloc[t])
    raw_t4 = float(sma50.iloc[t4])
    exact_t = float(close.iloc[t - 49 : t + 1].sum() / 50.0)
    exact_t4 = float(close.iloc[t4 - 49 : t4 + 1].sum() / 50.0)
    assert exact_t == exact_t4, (exact_t, exact_t4)
    assert rl._snap_sma_for_compare(raw_t) == 126.1822
    assert rl._snap_sma_for_compare(raw_t4) == 126.1822
    assert not rl._sma_is_rising(raw_t, raw_t4)


def main() -> int:
    tests = [
        test_hairline_equal_sums_are_not_rising,
        test_true_rise_and_fall_after_snap,
        test_snap_is_round_half_even_4dp,
        test_hwkn_current_csv_equal_50_sums_not_rising,
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
