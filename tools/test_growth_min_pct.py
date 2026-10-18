#!/usr/bin/env python3
"""Unit tests for the 3-year growth percent hurdle (10 / 25 / 50)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

import rocket_tbn as tbn  # noqa: E402


def test_zero_hurdle_does_not_decide():
    ok, reason = tbn.growth_min_gain_passes(100.0, 100.0, 0.0)
    assert ok and reason == ""
    ok, reason = tbn.growth_min_gain_passes(99.0, 100.0, 0.0)
    assert ok and reason == ""


def test_exact_hurdle_passes():
    for floor in (0.10, 0.25, 0.50):
        ago = 80.0
        now = ago * (1.0 + floor)
        ok, reason = tbn.growth_min_gain_passes(now, ago, floor)
        assert ok and reason == "", (floor, now, reason)


def test_just_under_hurdle_fails():
    for floor in (0.10, 0.25, 0.50):
        ago = 80.0
        now = ago * (1.0 + floor) - 0.01
        ok, reason = tbn.growth_min_gain_passes(now, ago, floor)
        assert not ok and reason == "GROWTH", (floor, now, reason)


def test_down_and_flat_fail_a_positive_hurdle():
    ok, reason = tbn.growth_min_gain_passes(90.0, 100.0, 0.10)
    assert not ok and reason == "GROWTH"
    ok, reason = tbn.growth_min_gain_passes(100.0, 100.0, 0.10)
    assert not ok and reason == "GROWTH"


def test_small_gain_passes_ten_and_fails_higher():
    now = 100.0 * 1.12
    ok, reason = tbn.growth_min_gain_passes(now, 100.0, 0.10)
    assert ok and reason == ""
    ok, reason = tbn.growth_min_gain_passes(now, 100.0, 0.25)
    assert not ok and reason == "GROWTH"


def main() -> int:
    tests = [
        test_zero_hurdle_does_not_decide,
        test_exact_hurdle_passes,
        test_just_under_hurdle_fails,
        test_down_and_flat_fail_a_positive_hurdle,
        test_small_gain_passes_ten_and_fails_higher,
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
