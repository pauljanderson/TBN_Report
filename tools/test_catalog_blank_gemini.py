"""Catalog walker: blank Gemini omits Gemini, not the game. No orders. No secrets."""
from __future__ import annotations

import sys
from contextlib import ExitStack
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"))

import overnight_scan as ov
import prediction_pair_scan as pps
import live_lock_orders
import opportunity_considerations
from test_live_lock_orders import Scan, _pair

ET = ZoneInfo("America/New_York")
BLANK_REASON = "A ticker is blank on one venue, so this game was not fetched."
GAME = {
    "teams": ["BUF", "KC"],
    "codes": ["BUF", "KC"],
    "date": "2026-11-01",
    "title_kalshi": "Buffalo vs Kansas City",
    "kalshi_game_ticker": "KXNFLGAME-26NOV01BUFKC",
    "kalshi_spread_ticker": None,
    "kalshi_total_ticker": None,
    "gemini_moneyline_ticker": None,
    "gemini_spread_ticker": None,
    "gemini_total_ticker": None,
}
KALSHI_EVENTS = [
    {
        "ticker": "KXNFLGAME-26NOV01BUFKC",
        "event_ticker": "KXNFLGAME-26NOV01BUFKC",
        "contracts": [
            {
                "ticker": "KXNFLGAME-26NOV01BUFKC-BUF",
                "title": "Buffalo wins",
                "yes_sub_title": "Buffalo",
                "yes_ask_dollars": "0.40",
                "no_ask_dollars": "0.61",
                "yes_ask_size_fp": "10",
                "no_ask_size_fp": "10",
                "status": "active",
            }
        ],
    }
]
POLY_CONTRACTS = [
    {
        "kind": "moneyline",
        "long_name": "Buffalo",
        "short_name": "Kansas City",
        "long_code": "BUF",
        "short_code": "KC",
        "yes_ask": Decimal("0.42"),
        "ask_size": Decimal("8"),
        "yes_bid": Decimal("0.65"),
        "bid_size": Decimal("8"),
        "slug": "nfl-buf-kc-ml",
        "event_title": "BUF vs KC",
        "fee_coefficient": Decimal("0"),
    }
]


def _noop(*_args, **_kwargs):
    return None


def _scan_patches(kalshi_events, gemini_events, polymarket, captured: dict):
    def capture_append(_sport, row):
        captured["row"] = row

    stack = ExitStack()
    stack.enter_context(patch.object(ov, "fetch_pair", return_value=(kalshi_events, gemini_events)))
    stack.enter_context(patch.object(ov, "_read_polymarket", return_value=polymarket))
    stack.enter_context(patch.object(ov, "_read_novig", return_value=[]))
    stack.enter_context(patch.object(ov, "_remember_prices", _noop))
    stack.enter_context(patch.object(ov, "log_venue_metrics", _noop))
    stack.enter_context(patch.object(ov, "log_analysis_metric", _noop))
    stack.enter_context(patch.object(ov, "_log_full_cycle", _noop))
    stack.enter_context(patch.object(ov, "ping_fresh_quotes", _noop))
    stack.enter_context(patch.object(ov, "save_book", _noop))
    stack.enter_context(patch.object(ov, "_append_result", capture_append))
    stack.enter_context(patch.object(ov, "put_last_gross", _noop))
    stack.enter_context(patch.object(ov, "record_opportunity", _noop))
    stack.enter_context(patch.object(ov, "enqueue_watch", _noop))
    stack.enter_context(patch.object(ov, "settle_watch_rows", _noop))
    stack.enter_context(patch.object(ov, "last_gross_map", return_value={}))
    stack.enter_context(patch.object(ov, "log", _noop))
    stack.enter_context(patch.object(opportunity_considerations, "record_catalog", _noop))
    return stack


def test_tickers_of_blank_gemini_keeps_kalshi():
    k, g = ov.tickers_of(GAME)
    assert k == ["KXNFLGAME-26NOV01BUFKC"]
    assert g == []


def test_scan_one_blank_gemini_does_not_skip_game():
    captured: dict = {}
    with _scan_patches(KALSHI_EVENTS, [], [], captured):
        row = ov.scan_one("pro football", GAME, 1, True)
    assert row is not None
    assert row.get("reason") != BLANK_REASON
    assert BLANK_REASON not in str(row.get("reason") or "")
    assert captured.get("row", {}).get("reason") != BLANK_REASON


def test_scan_one_kalshi_only_plus_poly_catalogs_candidate():
    captured: dict = {}
    with _scan_patches(KALSHI_EVENTS, [], POLY_CONTRACTS, captured):
        row = ov.scan_one("pro football", GAME, 1, True)
    assert row is not None
    assert row.get("reason") != BLANK_REASON
    n = int(row.get("candidates_n") or 0)
    assert n >= 1, row.get("reason")
    closest = row.get("closest") or {}
    venues = {closest.get("yes_venue"), closest.get("no_venue")}
    assert "kalshi" in venues
    assert "polymarket" in venues
    assert "gemini" not in venues


def test_scan_game_blank_gemini_fetches_kalshi_and_poly():
    now = datetime.now(ET)
    calls = [
        {
            "url": "https://example.invalid/kalshi",
            "sent_at": now,
            "received_at": now,
            "duration_seconds": 0.01,
            "elapsed": 0.01,
            "http_status": 200,
            "error": None,
        }
    ]
    event = {
        "event_ticker": "KXNFLGAME-26NOV01BUFKC",
        "contracts": KALSHI_EVENTS[0]["contracts"],
        "http_status": 200,
        "error": None,
        "sent_at": now.isoformat(),
        "received_at": now.isoformat(),
        "duration_seconds": 0.01,
    }
    gemini_calls = []

    def fake_gemini(_ticker):
        gemini_calls.append(_ticker)
        raise AssertionError("blank Gemini must not HTTP Gemini")

    def fake_kalshi(_ticker):
        return event, calls

    def fake_append(_path, payload):
        return "{}"

    with ExitStack() as stack:
        stack.enter_context(patch.object(pps, "fetch_gemini", fake_gemini))
        stack.enter_context(patch.object(pps, "fetch_kalshi", fake_kalshi))
        stack.enter_context(patch.object(pps, "save_book", _noop))
        stack.enter_context(patch.object(pps, "append_line", fake_append))
        stack.enter_context(patch.object(pps, "_remember_prices", _noop))
        stack.enter_context(patch.object(ov, "_read_polymarket", return_value=POLY_CONTRACTS))
        stack.enter_context(patch.object(ov, "_read_novig", return_value=[]))
        summary = pps.scan_game(GAME, "bufkc")
    assert summary.get("reason") != "no Gemini ticker"
    assert summary.get("reason") != BLANK_REASON
    assert gemini_calls == []
    cands = summary.get("candidates") or []
    assert cands, summary.get("reason")
    venues = {(c.get("yes_venue"), c.get("no_venue")) for c in cands}
    assert any("kalshi" in pair and "polymarket" in pair for pair in venues)


def test_two_shop_same_settlement_still_required_to_send():
    one = [{"venue": "kalshi", "instrument": "KXNFLGAME-26NOV01BUFKC-BUF", "outcome": "yes"}]
    assert live_lock_orders._pair_legs_ok(one) is False
    same_shop = [
        {"venue": "kalshi", "instrument": "KXNFLGAME-26NOV01BUFKC-BUF", "outcome": "yes"},
        {"venue": "kalshi", "instrument": "KXNFLGAME-26NOV01BUFKC-KC", "outcome": "no"},
    ]
    assert live_lock_orders._pair_legs_ok(same_shop) is False
    two = [
        {"venue": "kalshi", "instrument": "KXNFLGAME-26NOV01BUFKC-BUF", "outcome": "yes"},
        {"venue": "polymarket", "instrument": "nfl-buf-kc-ml", "outcome": "no"},
    ]
    assert live_lock_orders._pair_legs_ok(two) is True
    mismatch = _pair(
        market_type="total",
        yes_venue="kalshi",
        no_venue="polymarket",
        kalshi_ticker="KXNFLTEAMTOTAL-26NOV01BUFKC-BUF30",
        polymarket_slug="nfl-buf-kc-total",
        gemini_symbol="",
    )
    ok, why = live_lock_orders.same_settlement_candidate(mismatch)
    assert ok is False
    assert "settlement" in why.lower() or "team_total" in why
    true_lock = _pair(
        market_type="moneyline",
        yes_venue="kalshi",
        no_venue="polymarket",
        kalshi_ticker="KXNFLGAME-26NOV01BUFKC-BUF",
        polymarket_slug="nfl-buf-kc-ml",
        gemini_symbol="",
        yes_price="0.40",
        no_price="0.35",
        yes_size="8",
        no_size="8",
        fee_coefficient=Decimal("0"),
        polymarket_fee="0",
    )
    ok2, why2 = live_lock_orders.same_settlement_candidate(true_lock)
    assert ok2 is True, why2
    ok3, why3 = live_lock_orders.qualifies(Scan(), true_lock, "Buffalo vs Kansas City", GAME)
    assert ok3 is True, why3


if __name__ == "__main__":
    test_tickers_of_blank_gemini_keeps_kalshi()
    test_scan_one_blank_gemini_does_not_skip_game()
    test_scan_one_kalshi_only_plus_poly_catalogs_candidate()
    test_scan_game_blank_gemini_fetches_kalshi_and_poly()
    test_two_shop_same_settlement_still_required_to_send()
    print("ok")
