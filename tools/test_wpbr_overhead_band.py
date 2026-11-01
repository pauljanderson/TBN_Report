#!/usr/bin/env python3
"""Unit tests for the 22% prior-overhead WPBR zone count."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

import rocket_tbn as tbn  # noqa: E402


def _count(born, lowers, ids, **kw):
    return tbn.prior_overhead_zone_count(
        np.array(born, dtype=np.int32),
        np.array(lowers, dtype=np.float64),
        ids,
        active_id=kw.get("active_id", "A"),
        active_upper=kw.get("active_upper", 100.0),
        trigger_bar=kw.get("trigger_bar", 50),
        max_gap=kw.get("max_gap", 0.22),
    )


def test_off_counts_nothing():
    assert _count([1], [110.0], ["B"], max_gap=0.0) == 0


def test_inside_band_counts():
    assert _count([1], [110.0], ["B"]) == 1
    assert _count([1], [122.0], ["B"]) == 1


def test_outside_band_and_own_zone_do_not_count():
    assert _count([1], [122.01], ["B"]) == 0
    assert _count([1], [110.0], ["A"]) == 0
    assert _count([1], [100.0], ["B"]) == 0
    assert _count([50], [110.0], ["B"]) == 0
    assert _count([51], [110.0], ["B"]) == 0


def main() -> int:
    tests = [
        test_off_counts_nothing,
        test_inside_band_counts,
        test_outside_band_and_own_zone_do_not_count,
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
