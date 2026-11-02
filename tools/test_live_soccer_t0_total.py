"""System G gates: cheapest soccer Points Total 20–49, skip ML/spread, skip-if-A. Does not POST."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders
import live_soccer_t0_total as g
import prediction_systems as ps


def _total(side, px, *, venue="kalshi", number="2.5", size=None, fee_coefficient=None):
    row = {
        "venue": venue,
        "side": side,
        "team": side,
        "yes": Decimal(str(px)),
        "ask": Decimal(str(px)),
        "kind": "total",
        "number": str(number),
    }
    spec = {"venue": venue}
    if size is not None:
        row["yes_size"] = Decimal(str(size))
        spec["quote_size"] = Decimal(str(size))
        spec["yes_size"] = Decimal(str(size))
    if fee_coefficient is not None:
        spec["fee_coefficient"] = fee_coefficient
        row["fee_coefficient"] = fee_coefficient
    row["spec"] = spec
    return row


def _ml(side, px, *, venue="kalshi"):
    return {
        "venue": venue,
        "side": side,
        "team": side,
        "yes": Decimal(str(px)),
        "ask": Decimal(str(px)),
        "kind": "moneyline",
        "number": "",
    }


def _spread(side, px, *, venue="kalshi", number="1.5"):
    return {
        "venue": venue,
        "side": side,
        "team": side,
        "yes": Decimal(str(px)),
        "ask": Decimal(str(px)),
        "kind": "spread",
        "number": str(number),
    }


def test_band_20_included_50_excluded():
    assert ps.in_g_total_band(Decimal("0.20")) is True
    assert ps.in_g_total_band("0.20") is True
    assert ps.in_g_total_band(Decimal("0.19")) is False
    assert ps.in_g_total_band(Decimal("0.49")) is True
    assert ps.in_g_total_band(Decimal("0.50")) is False
    assert ps.in_g_total_band(Decimal("0.10")) is False
    lo = g.plan_send(quotes=[_total("Over 2.5", "0.20"), _total("Under 2.5", "0.82")])
    assert lo["action"] == "send", lo
    assert lo["ask"] == Decimal("0.20")
    hi = g.plan_send(quotes=[_total("Over 2.5", "0.50"), _total("Under 2.5", "0.52")])
    assert hi["action"] == "skip"
    junk = g.plan_send(quotes=[_total("Over 2.5", "0.19"), _total("Under 2.5", "0.81")])
    assert junk["action"] == "skip"


def test_cheapest_of_four_venues_same_line_side():
    quotes = [
        _total("Over 2.5", "0.41", venue="kalshi", number="2.5"),
        _total("Under 2.5", "0.62", venue="kalshi", number="2.5"),
        _total("Over 2.5", "0.28", venue="polymarket", number="2.5", size="1"),
        _total("Under 2.5", "0.74", venue="polymarket", number="2.5"),
        _total("Over 2.5", "0.33", venue="gemini", number="2.5"),
        _total("Over 2.5", "0.36", venue="novig", number="2.5", fee_coefficient="0.02"),
    ]
    plan = g.plan_send(quotes=quotes, title="Arsenal vs Chelsea", sport="soccer")
    assert plan["action"] == "send", plan
    assert plan["ask"] == Decimal("0.28")
    assert plan["venue"] == "polymarket"
    assert plan["number"] == "2.5"
    assert "Over" in plan["dog"]
    assert plan["kind"] == "total"


def test_soccer_only_and_points_total_not_ml_spread():
    quotes = [
        _ml("Arsenal", "0.29"),
        _spread("Arsenal -1.5", "0.31"),
        {
            "venue": "kalshi",
            "side": "Over 22.5",
            "yes": Decimal("0.31"),
            "ask": Decimal("0.31"),
            "kind": "team_total",
            "number": "22.5",
        },
    ]
    plan = g.plan_send(quotes=quotes, title="Arsenal vs Chelsea", sport="soccer")
    assert plan["action"] == "skip", plan
    mixed = quotes + [_total("Over 2.5", "0.31")]
    ok = g.plan_send(quotes=mixed, title="Arsenal vs Chelsea", sport="soccer")
    assert ok["action"] == "send", ok
    assert ok["ask"] == Decimal("0.31")
    assert ok["kind"] == "total"
    tennis = g.plan_send(quotes=[_total("Over 2.5", "0.31")], title="Alcaraz vs Sinner", sport="tennis")
    assert tennis["action"] == "skip"
    assert tennis["reason"] == "not soccer"
    nfl = g.plan_send(quotes=[_total("Over 48.5", "0.31")], title="Chiefs vs Bills", sport="pro football")
    assert nfl["action"] == "skip"


def test_skip_if_a_same_total_not_moneyline():
    quotes = [_total("Over 2.5", "0.31"), _total("Under 2.5", "0.71")]
    a_lock = g.plan_send(
        quotes=quotes,
        title="Arsenal vs Chelsea",
        sport="soccer",
        lock_rows=[{"game": "Arsenal vs Chelsea", "kind": "total", "number": "2.5", "side": "over"}],
    )
    assert a_lock["action"] == "skip", a_lock
    assert a_lock["reason"] == "A already locking this total"
    ml_lock = g.plan_send(
        quotes=quotes,
        title="Arsenal vs Chelsea",
        sport="soccer",
        lock_rows=[{"game": "Arsenal vs Chelsea", "kind": "moneyline", "number": "", "side": "arsenal"}],
    )
    assert ml_lock["action"] == "send", ml_lock
    other_game = g.plan_send(
        quotes=quotes,
        title="Arsenal vs Chelsea",
        sport="soccer",
        lock_rows=[{"game": "Liverpool vs Everton", "kind": "total", "number": "2.5", "side": "over"}],
    )
    assert other_game["action"] == "send", other_game


def test_no_skip_if_b_unless_same_game_key():
    quotes = [_total("Over 2.5", "0.31")]
    b_status = {
        "matches": [
            {"key": "alcsin", "game": "Alcaraz vs Sinner", "stage": "absorbed"},
        ]
    }
    allowed = g.plan_send(
        quotes=quotes,
        title="Arsenal vs Chelsea",
        sport="soccer",
        key="arseche",
        b_status=b_status,
    )
    assert allowed["action"] == "send", allowed
    collide = g.plan_send(
        quotes=quotes,
        title="Arsenal vs Chelsea",
        sport="soccer",
        key="alcsin",
        b_status=b_status,
    )
    assert collide["action"] == "skip"
    assert "game-key" in collide["reason"]


def test_max_2_blocks_third_and_already_filled():
    quotes = [_total("Over 2.5", "0.31")]
    first = g.plan_send(quotes=quotes, open_n=0, max_open=2)
    second = g.plan_send(quotes=quotes, open_n=1, max_open=2)
    third = g.plan_send(quotes=quotes, open_n=2, max_open=2)
    assert first["action"] == "send"
    assert second["action"] == "send"
    assert third["action"] == "skip"
    assert third["reason"] == "max_open"
    filled = {
        "matches": [
            {
                "game": "Arsenal vs Chelsea",
                "stage": "filled",
                "last_order": {"fill_qty": "1"},
            }
        ]
    }
    again = g.plan_send(quotes=quotes, title="Arsenal vs Chelsea", g_status=filled)
    assert again["action"] == "skip"
    assert "already filled" in again["reason"]


def test_poly_size_skip():
    quotes = [_total("Over 2.5", "0.31", venue="polymarket", size="0.3")]
    plan = g.plan_send(quotes=quotes)
    assert plan["action"] == "skip", plan
    assert live_lock_orders.POLY_SIZE_LT_QTY_SKIP in str(plan["reason"])


def test_novig_fee_unknown_skipped():
    quotes = [
        _total("Over 2.5", "0.22", venue="novig", number="2.5"),
        _total("Over 2.5", "0.31", venue="kalshi", number="2.5"),
    ]
    plan = g.plan_send(quotes=quotes, title="Arsenal vs Chelsea")
    assert plan["action"] == "send", plan
    assert plan["venue"] == "kalshi"
    assert plan["ask"] == Decimal("0.31")
    only_novig = g.plan_send(quotes=[_total("Over 2.5", "0.22", venue="novig")])
    assert only_novig["action"] == "skip"
    assert only_novig["reason"] == "novig fee unknown"


def test_leftover_watch_does_not_hedge_g():
    spec = {
        "_system": "soccer_t0_total",
        "_step": "g-t0",
        "_bet_key": "soccer-t0-total\tarseche\tOver 2.5\t2.5\t1",
    }
    assert live_lock_orders.leftover_watch_skipped(spec) is True
    assert live_lock_orders.leftover_watch_skipped({}, "soccer-t0-total\tx") is True


def test_tie_venue_rank_kalshi_first():
    quotes = [
        _total("Over 2.5", "0.31", venue="polymarket"),
        _total("Over 2.5", "0.31", venue="kalshi"),
        _total("Over 2.5", "0.31", venue="gemini"),
    ]
    plan = g.plan_send(quotes=quotes)
    assert plan["action"] == "send"
    assert plan["venue"] == "kalshi"


def test_gemini_cheapest_falls_back_when_quote_only():
    import gemini_private

    quotes = [
        _total("Over 2.5", "0.21", venue="gemini", number="2.5"),
        _total("Over 2.5", "0.29", venue="kalshi", number="2.5"),
        _total("Under 2.5", "0.72", venue="kalshi", number="2.5"),
    ]
    saved = gemini_private.GEMINI_ORDERS_ENABLED
    gemini_private.GEMINI_ORDERS_ENABLED = False
    try:
        plan = g.plan_send(quotes=quotes, title="Arsenal vs Chelsea", sport="soccer")
        assert plan["action"] == "send", plan
        assert plan["venue"] == "kalshi"
        assert plan["ask"] == Decimal("0.29")
    finally:
        gemini_private.GEMINI_ORDERS_ENABLED = saved


if __name__ == "__main__":
    test_band_20_included_50_excluded()
    test_cheapest_of_four_venues_same_line_side()
    test_soccer_only_and_points_total_not_ml_spread()
    test_skip_if_a_same_total_not_moneyline()
    test_no_skip_if_b_unless_same_game_key()
    test_max_2_blocks_third_and_already_filled()
    test_poly_size_skip()
    test_novig_fee_unknown_skipped()
    test_leftover_watch_does_not_hedge_g()
    test_tie_venue_rank_kalshi_first()
    test_gemini_cheapest_falls_back_when_quote_only()
    print("ok")
