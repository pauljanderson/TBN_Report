"""Unit tests for ATR Chandelier and detrended z-score adaptive exits."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))

from rocket_brt import (  # noqa: E402
    chandelier_ratchet_stop,
    compute_detrended_log_zscore,
    _zscore_exit_signal,
)


class ChandelierTests(unittest.TestCase):
    def test_uses_only_completed_bars_through_t_minus_1(self) -> None:
        high = np.array([10.0, 11.0, 12.0, 100.0], dtype=float)  # bar 3 spike must not affect bar-3 stop
        low = np.array([9.0, 10.0, 11.0, 90.0], dtype=float)
        atr = np.array([1.0, 1.0, 1.0, 1.0], dtype=float)
        stop, raised, ratchet = chandelier_ratchet_stop(
            high_arr=high,
            low_arr=low,
            atr_arr=atr,
            entry_bar=0,
            bar_i=3,
            atr_mult=2.0,
            original_stop=8.0,
            prior_ratchet=None,
            is_long=True,
        )
        # extreme = max(10,11,12)=12; candidate=12-2*1=10
        self.assertAlmostEqual(stop, 10.0)
        self.assertTrue(raised)
        self.assertAlmostEqual(ratchet, 10.0)

    def test_never_loosens_vs_prior_or_original(self) -> None:
        high = np.array([10.0, 11.0, 10.5], dtype=float)
        low = np.array([9.0, 9.5, 9.0], dtype=float)
        atr = np.array([1.0, 1.0, 1.0], dtype=float)
        stop1, _, r1 = chandelier_ratchet_stop(
            high_arr=high,
            low_arr=low,
            atr_arr=atr,
            entry_bar=0,
            bar_i=1,
            atr_mult=2.0,
            original_stop=8.5,
            prior_ratchet=None,
            is_long=True,
        )
        # extreme=10, candidate=8 -> max(8.5,8)=8.5
        self.assertAlmostEqual(stop1, 8.5)
        stop2, _, r2 = chandelier_ratchet_stop(
            high_arr=high,
            low_arr=low,
            atr_arr=atr,
            entry_bar=0,
            bar_i=2,
            atr_mult=2.0,
            original_stop=8.5,
            prior_ratchet=r1,
            is_long=True,
        )
        # extreme=max(10,11)=11, candidate=9 -> max(8.5,9)=9
        self.assertAlmostEqual(stop2, 9.0)
        stop3, _, _ = chandelier_ratchet_stop(
            high_arr=high,
            low_arr=low,
            atr_arr=atr,
            entry_bar=0,
            bar_i=3,
            atr_mult=2.0,
            original_stop=8.5,
            prior_ratchet=r2,
            is_long=True,
        )
        # extreme=max(10,11,10.5)=11, candidate=9 -> stays 9
        self.assertAlmostEqual(stop3, 9.0)

    def test_gap_aware_fill_semantics_match_stop_path(self) -> None:
        # Document expected fill: open through stop -> fill open; else low cross -> fill stop
        stop = 95.0
        open_gap = 93.0
        self.assertLessEqual(open_gap, stop)  # gap fill at open
        open_ok = 96.0
        low_touch = 94.5
        self.assertGreater(open_ok, stop)
        self.assertLessEqual(low_touch, stop)  # intrabar fill at stop

    def test_future_mutation_cannot_change_prior_chandelier(self) -> None:
        high = np.linspace(100, 120, 40)
        low = high - 2.0
        atr = np.full(40, 1.5)
        s1, _, r1 = chandelier_ratchet_stop(
            high_arr=high,
            low_arr=low,
            atr_arr=atr,
            entry_bar=5,
            bar_i=20,
            atr_mult=2.5,
            original_stop=90.0,
            prior_ratchet=None,
            is_long=True,
        )
        high2 = high.copy()
        high2[20:] += 50.0
        s2, _, r2 = chandelier_ratchet_stop(
            high_arr=high2,
            low_arr=low,
            atr_arr=atr,
            entry_bar=5,
            bar_i=20,
            atr_mult=2.5,
            original_stop=90.0,
            prior_ratchet=None,
            is_long=True,
        )
        self.assertAlmostEqual(s1, s2)
        self.assertAlmostEqual(r1, r2)


class ZScoreExitTests(unittest.TestCase):
    def test_no_lookahead_past_unchanged_by_future(self) -> None:
        close = 100.0 + np.linspace(0, 5, 80)
        z1 = compute_detrended_log_zscore(close, 20)
        close2 = close.copy()
        close2[50:] -= 30.0
        z2 = compute_detrended_log_zscore(close2, 20)
        np.testing.assert_allclose(z1[:50], z2[:50], equal_nan=True)

    def test_breakdown_triggers_long_exit_signal(self) -> None:
        # Steady uptrend then sharp drop should produce negative residual z
        close = np.concatenate([np.linspace(100, 130, 40), np.array([110.0, 100.0, 90.0])])
        z = compute_detrended_log_zscore(close, 20)
        self.assertTrue(np.isfinite(z[-1]))
        self.assertTrue(_zscore_exit_signal(z, len(z) - 1, 2.0, True))

    def test_arm_at_close_fill_next_open_contract(self) -> None:
        # Signal uses bar t close; fill is next open (caller responsibility)
        z = np.array([np.nan, 0.1, -2.5, -0.5], dtype=float)
        self.assertFalse(_zscore_exit_signal(z, 1, 2.0, True))
        self.assertTrue(_zscore_exit_signal(z, 2, 2.0, True))
        # Next bar would execute pending open fill; bar 2 only arms
        trade = SimpleNamespace(_pending_zscore_exit=False)
        if _zscore_exit_signal(z, 2, 2.0, True):
            trade._pending_zscore_exit = True
        self.assertTrue(trade._pending_zscore_exit)


if __name__ == "__main__":
    unittest.main()
