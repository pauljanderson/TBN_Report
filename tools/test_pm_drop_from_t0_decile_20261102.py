"""Unit tests for drop-from-T0 helpers. No network. No orders."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

SPEC = importlib.util.spec_from_file_location(
    "pm_drop_from_t0_decile_20261102",
    ROOT / "tools" / "pm_drop_from_t0_decile_20261102.py",
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


class DropFromT0Tests(unittest.TestCase):
    def test_decile_of(self):
        self.assertEqual(mod.decile_of(0.29), "20-29")
        self.assertEqual(mod.decile_of(0.55), "50-59")
        self.assertEqual(mod.decile_of(0.90), "90-99")
        self.assertEqual(mod.decile_of(0.995), "90-99")

    def test_side_metrics_dip(self):
        t0 = 1_000_000
        path = [
            [t0 - 60, 0.40],
            [t0, 0.29],
            [t0 + 60, 0.25],
            [t0 + 120, 0.183],
            [t0 + 180, 0.22],
            [t0 + 240, 0.30],
            [t0 + 300, 0.35],
            [t0 + 360, 0.40],
        ]
        m = mod.side_metrics(path, t0)
        assert m is not None
        self.assertAlmostEqual(m["t0_px"], 0.29, places=4)
        self.assertAlmostEqual(m["min_px"], 0.183, places=4)
        self.assertAlmostEqual(m["max_dip"], 0.107, places=3)
        self.assertTrue(m["hit"]["d10"])
        self.assertFalse(m["hit"]["d15"])

    def test_side_metrics_rejects_short_path(self):
        t0 = 1_000_000
        path = [[t0, 0.50], [t0 + 60, 0.40]]
        self.assertIsNone(mod.side_metrics(path, t0))

    def test_summarize_and_pairs(self):
        sides = [
            {"t0_px": 0.55, "max_dip": 0.20, "sport": "tennis", "kind": "moneyline",
             "event_ticker": "E1", "title": "A", "source": "t"},
            {"t0_px": 0.45, "max_dip": 0.15, "sport": "tennis", "kind": "moneyline",
             "event_ticker": "E1", "title": "B", "source": "t"},
            {"t0_px": 0.80, "max_dip": 0.05, "sport": "tennis", "kind": "moneyline",
             "event_ticker": "E2", "title": "C", "source": "t"},
            {"t0_px": 0.20, "max_dip": 0.02, "sport": "tennis", "kind": "moneyline",
             "event_ticker": "E2", "title": "D", "source": "t"},
        ]
        summ = mod.summarize_dips(sides)
        self.assertEqual(summ["n"], 4)
        self.assertAlmostEqual(summ["mean"], 0.105, places=3)
        pairs = mod.pair_event_sides(sides)
        self.assertEqual(len(pairs), 2)
        ps = mod.summarize_pairs(pairs)
        self.assertEqual(ps["n"], 2)
        # only E1 both-hits 10¢
        self.assertEqual(ps["both_hit_pct"]["d10"], 50.0)

    def test_pctile(self):
        xs = [0.0, 0.1, 0.2, 0.3, 0.4]
        self.assertAlmostEqual(mod.pctile(xs, 50) or 0, 0.2, places=6)


if __name__ == "__main__":
    unittest.main()
