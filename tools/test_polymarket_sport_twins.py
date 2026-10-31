"""Unit tests for Kalshi↔Polymarket match twin helpers (tennis / MMA / table tennis / chess)."""
from __future__ import annotations

import unittest

import polymarket_us_live as poly


class CleanTitleTests(unittest.TestCase):
    def test_fight_night_prefix(self):
        self.assertEqual(
            poly._clean_match_title("Fight Night: Zach Reese vs Mickey Gall"),
            "Zach Reese vs Mickey Gall",
        )

    def test_players_match_ignores_fight_night(self):
        self.assertTrue(
            poly._players_match(
                "Fight Night: Zach Reese vs Mickey Gall",
                "Zach Reese vs. Mickey Gall",
            )
        )


class TwinDiscoverTests(unittest.TestCase):
    def test_discover_twins_unique_claim(self):
        kalshi = [
            {
                "event_ticker": "KXUFCFIGHT-26OCT31REEGAL",
                "title": "Fight Night: Zach Reese vs Mickey Gall",
                "series": "KXUFCFIGHT",
            },
            {
                "event_ticker": "KXUFCFIGHT-26OCT31OTHER",
                "title": "Fight Night: Zach Reese vs Mickey Gall",
                "series": "KXUFCFIGHT",
            },
        ]
        polymarket = [
            {
                "title": "Zach Reese vs. Mickey Gall",
                "market": {
                    "slug": "ufc-zacree-micgal-2026-10-31",
                    "long_name": "Zach Reese",
                    "short_name": "Mickey Gall",
                    "kind": "moneyline",
                    "number": "",
                    "date": "2026-10-31",
                    "fee_coefficient": None,
                },
                "series_slug": "ufc-2025",
            }
        ]

        def fake_kalshi(series):
            return [row for row in kalshi if row["series"] == series]

        def fake_poly(sport_path, series_allow=None):
            self.assertEqual(sport_path, "mma")
            return polymarket

        original_k = poly._kalshi_open
        original_p = poly._polymarket_sport_ml_events
        poly._kalshi_open = fake_kalshi
        poly._polymarket_sport_ml_events = fake_poly
        try:
            # Two Kalshi cards claim the same Poly slug → both dropped (unique claim).
            rows = poly._discover_kalshi_poly_twins(["KXUFCFIGHT"], "mma", None)
            self.assertEqual(rows, [])
        finally:
            poly._kalshi_open = original_k
            poly._polymarket_sport_ml_events = original_p

    def test_discover_twins_one_hit(self):
        kalshi = [
            {
                "event_ticker": "KXUFCFIGHT-26OCT31REEGAL",
                "title": "Fight Night: Zach Reese vs Mickey Gall",
                "series": "KXUFCFIGHT",
            },
        ]
        polymarket = [
            {
                "title": "Zach Reese vs. Mickey Gall",
                "market": {
                    "slug": "ufc-zacree-micgal-2026-10-31",
                    "long_name": "Zach Reese",
                    "short_name": "Mickey Gall",
                    "kind": "moneyline",
                    "number": "",
                    "date": "2026-10-31",
                    "fee_coefficient": None,
                },
                "series_slug": "ufc-2025",
            }
        ]

        poly._kalshi_open, original_k = (lambda series: kalshi if series == "KXUFCFIGHT" else []), poly._kalshi_open
        poly._polymarket_sport_ml_events, original_p = (lambda *a, **k: polymarket), poly._polymarket_sport_ml_events
        try:
            rows = poly._discover_kalshi_poly_twins(["KXUFCFIGHT"], "mma", None)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_ticker"], "KXUFCFIGHT-26OCT31REEGAL")
            self.assertEqual(rows[0]["slug"], "ufc-zacree-micgal-2026-10-31")
            self.assertEqual(rows[0]["title"], "Zach Reese vs Mickey Gall")
        finally:
            poly._kalshi_open = original_k
            poly._polymarket_sport_ml_events = original_p

    def test_table_tennis_adds_polymarket_only(self):
        twin = {
            "event_ticker": "KXTTMATCH-26OCT31AB",
            "title": "Alpha vs Beta",
            "date": "2026-10-31",
            "series": "KXTTMATCH",
            "slug": "tt-alpha-beta-2026-10-31",
            "long_name": "Alpha",
            "short_name": "Beta",
            "kind": "moneyline",
            "number": "",
            "fee_coefficient": None,
        }
        poly_only = {
            "title": "Gamma vs Delta",
            "market": {
                "slug": "tt-gamma-delta-2026-10-31",
                "long_name": "Gamma",
                "short_name": "Delta",
                "kind": "moneyline",
                "number": "",
                "date": "2026-10-31",
                "fee_coefficient": None,
            },
            "series_slug": "wtt-2026",
        }

        poly._discover_kalshi_poly_twins, original_d = (lambda *a, **k: [twin]), poly._discover_kalshi_poly_twins
        poly._polymarket_sport_ml_events, original_p = (
            lambda *a, **k: [
                {"title": twin["title"], "market": {**twin, "event_title": twin["title"]}, "series_slug": "wtt"},
                poly_only,
            ],
            poly._polymarket_sport_ml_events,
        )
        try:
            rows = poly.discover_table_tennis_matches()
            slugs = {row["slug"] for row in rows}
            self.assertIn("tt-alpha-beta-2026-10-31", slugs)
            self.assertIn("tt-gamma-delta-2026-10-31", slugs)
            only = next(row for row in rows if row["slug"] == "tt-gamma-delta-2026-10-31")
            self.assertEqual(only["event_ticker"], "")
            self.assertEqual(only["series"], "polymarket-only")
        finally:
            poly._discover_kalshi_poly_twins = original_d
            poly._polymarket_sport_ml_events = original_p


class LivePollerGateTests(unittest.TestCase):
    def test_watchable_book_allows_polymarket_only(self):
        import live_game_pollers as live

        class Scan:
            @staticmethod
            def tickers_of(game):
                return [], []

        game = {"polymarket_markets": [{"slug": "tt-a-b-2026-10-31"}]}
        self.assertTrue(live._has_watchable_book(game, Scan()))
        self.assertFalse(live._has_watchable_book({"kalshi": {}, "gemini": {}}, Scan()))


if __name__ == "__main__":
    unittest.main()
