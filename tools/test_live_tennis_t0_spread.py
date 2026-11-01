"""System F gates: cheapest tennis spread 20–49, skip ML, skip-if-B. Does not POST."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders
import live_tennis_t0_spread as f
import prediction_systems as ps


def _spread(side, px, *, venue="kalshi", number="1.5", size=None):
    row = {
        "venue": venue,
        "side": side,
        "team": side,
        "yes": Decimal(str(px)),
        "ask": Decimal(str(px)),
        "kind": "spread",
        "number": str(number),
    }
    if size is not None:
        row["yes_size"] = Decimal(str(size))
        row["spec"] = {"venue": venue, "quote_size": Decimal(str(size)), "yes_size": Decimal(str(size))}
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


def test_band_20_included_50_excluded():
    assert ps.in_f_spread_band(Decimal("0.20")) is True
    assert ps.in_f_spread_band("0.20") is True
    assert ps.in_f_spread_band(Decimal("0.19")) is False
    assert ps.in_f_spread_band(Decimal("0.49")) is True
    assert ps.in_f_spread_band(Decimal("0.50")) is False
    assert ps.in_f_spread_band(Decimal("0.10")) is False
    lo = f.plan_send(quotes=[_spread("A -1.5", "0.20"), _spread("B +1.5", "0.82")])
    assert lo["action"] == "send", lo
    assert lo["ask"] == Decimal("0.20")
    hi = f.plan_send(quotes=[_spread("A -1.5", "0.50"), _spread("B +1.5", "0.52")])
    assert hi["action"] == "skip"
    junk = f.plan_send(quotes=[_spread("A -1.5", "0.19"), _spread("B +1.5", "0.81")])
    assert junk["action"] == "skip"


def test_cheapest_of_venues_and_sides():
    quotes = [
        _spread("Alcaraz -1.5", "0.41", venue="kalshi", number="1.5"),
        _spread("Sinner +1.5", "0.62", venue="kalshi", number="1.5"),
        _spread("Alcaraz -2.5", "0.28", venue="polymarket", number="2.5", size="1"),
        _spread("Sinner +2.5", "0.74", venue="polymarket", number="2.5"),
        _spread("Alcaraz -1.5", "0.33", venue="gemini", number="1.5"),
    ]
    plan = f.plan_send(quotes=quotes, title="Alcaraz vs Sinner")
    assert plan["action"] == "send", plan
    assert plan["ask"] == Decimal("0.28")
    assert plan["venue"] == "polymarket"
    assert plan["number"] == "2.5"
    assert "Alcaraz" in plan["dog"]


def test_skip_moneyline_and_total():
    quotes = [
        _ml("Underdog", "0.29"),
        _ml("Favorite", "0.72"),
        {
            "venue": "kalshi",
            "side": "Over 22.5",
            "yes": Decimal("0.31"),
            "ask": Decimal("0.31"),
            "kind": "total",
            "number": "22.5",
        },
    ]
    plan = f.plan_send(quotes=quotes, title="A vs B")
    assert plan["action"] == "skip", plan
    assert "spread" in plan["reason"] or "moneyline" in plan["reason"]
    mixed = quotes + [_spread("A -1.5", "0.31")]
    ok = f.plan_send(quotes=mixed, title="A vs B")
    assert ok["action"] == "send", ok
    assert ok["ask"] == Decimal("0.31")
    assert ok["kind"] == "spread"


def test_b_already_open_skip():
    quotes = [_spread("A -1.5", "0.31"), _spread("B +1.5", "0.71")]
    b_status = {
        "matches": [
            {"game": "Underdog vs Favorite", "stage": "absorbed", "note": "holding T0 both-Yes"},
        ]
    }
    plan = f.plan_send(quotes=quotes, title="Underdog vs Favorite", b_status=b_status)
    assert plan["action"] == "skip", plan
    assert plan["reason"] == "B already on match"
    c_over = {
        "matches": [
            {
                "game": "Underdog vs Favorite",
                "stage": "abandoned",
                "skip_reason": "t0_allin_c_over_105",
                "note": "t0_allin_c_over_105 all-in C=1.08; no T0, no 50-cross, no dip",
            }
        ]
    }
    allowed = f.plan_send(quotes=quotes, title="Underdog vs Favorite", b_status=c_over)
    assert allowed["action"] == "send", allowed


def test_max_2_blocks_third_and_already_filled():
    quotes = [_spread("A -1.5", "0.31")]
    first = f.plan_send(quotes=quotes, open_n=0, max_open=2)
    second = f.plan_send(quotes=quotes, open_n=1, max_open=2)
    third = f.plan_send(quotes=quotes, open_n=2, max_open=2)
    assert first["action"] == "send"
    assert second["action"] == "send"
    assert third["action"] == "skip"
    assert third["reason"] == "max_open"
    filled = {
        "matches": [
            {
                "game": "A vs B",
                "stage": "filled",
                "last_order": {"fill_qty": "1"},
            }
        ]
    }
    again = f.plan_send(quotes=quotes, title="A vs B", f_status=filled)
    assert again["action"] == "skip"
    assert "already filled" in again["reason"]


def test_poly_size_skip():
    quotes = [_spread("A -1.5", "0.31", venue="polymarket", size="0.3")]
    plan = f.plan_send(quotes=quotes)
    assert plan["action"] == "skip", plan
    assert live_lock_orders.POLY_SIZE_LT_QTY_SKIP in str(plan["reason"])


def test_leftover_watch_does_not_hedge_f():
    spec = {
        "_system": "tennis_t0_spread",
        "_step": "f-t0",
        "_bet_key": "tennis-t0-spread\talcsin\tAlcaraz\t1.5\t1",
    }
    assert live_lock_orders.leftover_watch_skipped(spec) is True
    assert live_lock_orders.leftover_watch_skipped({}, "tennis-t0-spread\tx") is True


def test_tie_venue_rank_kalshi_first():
    quotes = [
        _spread("A -1.5", "0.31", venue="polymarket"),
        _spread("A -1.5", "0.31", venue="kalshi"),
        _spread("A -1.5", "0.31", venue="gemini"),
    ]
    plan = f.plan_send(quotes=quotes)
    assert plan["action"] == "send"
    assert plan["venue"] == "kalshi"


if __name__ == "__main__":
    test_band_20_included_50_excluded()
    test_cheapest_of_venues_and_sides()
    test_skip_moneyline_and_total()
    test_b_already_open_skip()
    test_max_2_blocks_third_and_already_filled()
    test_poly_size_skip()
    test_leftover_watch_does_not_hedge_f()
    test_tie_venue_rank_kalshi_first()
    print("ok")
