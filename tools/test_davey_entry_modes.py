"""Focused synthetic tests for Davey-inspired entry/exit primitives."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))

from rocket_brt import (  # noqa: E402
    channel_stop_price,
    compute_wilder_adx,
    stop_order_fill_price,
)


class WilderADXTests(unittest.TestCase):
    def test_flat_market_converges_to_zero(self) -> None:
        n = 80
        close = np.full(n, 100.0)
        high = close + 1.0
        low = close - 1.0
        adx = compute_wilder_adx(high, low, close, 15)
        self.assertTrue(np.allclose(adx[28:], 0.0, atol=1e-12, equal_nan=False))

    def test_future_mutation_cannot_change_past_adx(self) -> None:
        n = 90
        x = np.arange(n, dtype=float)
        close = 100.0 + np.sin(x / 4.0) * 2.0 + x * 0.03
        high = close + 1.0 + (x % 3) * 0.1
        low = close - 1.0 - (x % 4) * 0.1
        original = compute_wilder_adx(high, low, close, 15)
        high2, low2, close2 = high.copy(), low.copy(), close.copy()
        high2[60:] += 500.0
        low2[60:] -= 400.0
        close2[60:] += 100.0
        mutated = compute_wilder_adx(high2, low2, close2, 15)
        np.testing.assert_allclose(original[:60], mutated[:60], rtol=0, atol=0, equal_nan=True)


class StopOrderTests(unittest.TestCase):
    def test_long_gap_fills_at_open(self) -> None:
        self.assertEqual(
            stop_order_fill_price(
                stop_price=105, bar_open=108, bar_high=110, bar_low=107, is_long=True
            ),
            108,
        )

    def test_long_intrabar_cross_fills_at_stop(self) -> None:
        self.assertEqual(
            stop_order_fill_price(
                stop_price=105, bar_open=103, bar_high=106, bar_low=102, is_long=True
            ),
            105,
        )

    def test_short_gap_and_no_fill(self) -> None:
        self.assertEqual(
            stop_order_fill_price(
                stop_price=95, bar_open=92, bar_high=94, bar_low=90, is_long=False
            ),
            92,
        )
        self.assertIsNone(
            stop_order_fill_price(
                stop_price=95, bar_open=97, bar_high=99, bar_low=96, is_long=False
            )
        )

    def test_channel_uses_completed_signal_window_only(self) -> None:
        high = np.array([10, 11, 12, 13, 14, 99], dtype=float)
        low = np.array([9, 8, 7, 6, 5, 1], dtype=float)
        self.assertEqual(channel_stop_price(high, low, signal_bar=4, channel_length=3, is_long=True), 14)
        self.assertEqual(channel_stop_price(high, low, signal_bar=4, channel_length=3, is_long=False), 5)


if __name__ == "__main__":
    unittest.main()
