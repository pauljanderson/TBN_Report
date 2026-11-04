"""System C/H CFB movers: 0–19¢ + pair ≤ 1.05, GTC exit offsets. Does not POST."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_cfb_spread_movers as h
import live_cfb_total_movers as c
import live_lock_orders
import prediction_systems as ps


def _row(kind, side, px, *, venue="kalshi", number="45.5", size=None, fee_coefficient=None):
    row = {
        "venue": venue,
        "side": side,
        "team": side,
        "yes": Decimal(str(px)),
        "ask": Decimal(str(px)),
        "kind": kind,
        "number": str(number),
    }
    spec = {"venue": venue, "instrument": f"{venue}-{kind}-{side}-{number}", "outcome": "yes"}
    if size is not None:
        row["yes_size"] = Decimal(str(size))
        spec["quote_size"] = Decimal(str(size))
        spec["yes_size"] = Decimal(str(size))
    if fee_coefficient is not None:
        spec["fee_coefficient"] = fee_coefficient
        row["fee_coefficient"] = fee_coefficient
    if venue == "polymarket":
        spec["intent"] = "ORDER_INTENT_BUY_LONG"
        row["intent"] = "ORDER_INTENT_BUY_LONG"
    row["spec"] = spec
    return row


def test_mover_band_0_to_19_inclusive():
    assert ps.in_mover_band(Decimal("0")) is True
    assert ps.in_mover_band(Decimal("0.19")) is True
    assert ps.in_mover_band("0.19") is True
    assert ps.in_mover_band(Decimal("0.20")) is False
    assert ps.in_mover_band(Decimal("0.10")) is True
    assert ps.in_mover_band(Decimal("-0.01")) is False


def test_pair_gate_and_gtc_offsets():
    assert ps.mover_pair_ok(Decimal("0.12"), Decimal("0.93")) is True  # 1.05
    assert ps.mover_pair_ok(Decimal("0.12"), Decimal("0.94")) is False
    assert ps.gtc_exit_pay(Decimal("0.12"), Decimal("0.15")) == Decimal("0.2700")
    assert ps.gtc_exit_pay(Decimal("0.12"), Decimal("0.10")) == Decimal("0.2200")
    assert ps.gtc_offset_for("cfb_total_movers") == Decimal("0.15")
    assert ps.gtc_offset_for("cfb_spread_movers") == Decimal("0.10")
    assert ps.gtc_exit_pay(Decimal("0.90"), Decimal("0.15")) is None


def test_c_buys_cheap_total_when_pair_ok():
    quotes = [
        _row("total", "Over 45.5", "0.12"),
        _row("total", "Under 45.5", "0.90"),
        _row("moneyline", "Alabama", "0.10"),
        _row("spread", "Alabama -7.5", "0.11"),
    ]
    plan = c.plan_send(quotes=quotes, title="Alabama vs Auburn", sport="college football")
    assert plan["action"] == "send", plan
    assert plan["ask"] == Decimal("0.12")
    assert plan["kind"] == "total"
    assert plan["gtc_offset"] == Decimal("0.15")
    assert plan["gtc_exit_pay"] == Decimal("0.2700")
    assert "Over" in plan["dog"]


def test_c_skips_pair_over_105_and_non_cfb():
    fat = c.plan_send(
        quotes=[_row("total", "Over 45.5", "0.12"), _row("total", "Under 45.5", "0.95")],
        title="Alabama vs Auburn",
        sport="college football",
    )
    assert fat["action"] == "skip", fat
    tennis = c.plan_send(
        quotes=[_row("total", "Over 22.5", "0.12"), _row("total", "Under 22.5", "0.90")],
        title="Alcaraz vs Sinner",
        sport="tennis",
    )
    assert tennis["action"] == "skip"
    assert tennis["reason"] == "not college football"


def test_c_skips_20c_and_picks_cheapest_qualifying():
    quotes = [
        _row("total", "Over 45.5", "0.20"),
        _row("total", "Under 45.5", "0.82"),
        _row("total", "Over 48.5", "0.15", number="48.5"),
        _row("total", "Under 48.5", "0.88", number="48.5"),
        _row("total", "Over 41.5", "0.09", number="41.5", venue="polymarket", size="1"),
        _row("total", "Under 41.5", "0.94", number="41.5", venue="polymarket"),
    ]
    plan = c.plan_send(quotes=quotes, title="Alabama vs Auburn", sport="college football")
    assert plan["action"] == "send", plan
    assert plan["ask"] == Decimal("0.09")
    assert plan["venue"] == "polymarket"
    assert plan["number"] == "41.5"


def test_h_buys_spread_mover_at_10c_gtc():
    quotes = [
        _row("spread", "Alabama -7.5", "0.11"),
        _row("spread", "Auburn +7.5", "0.92"),
        _row("total", "Over 45.5", "0.10"),
        _row("total", "Under 45.5", "0.90"),
    ]
    plan = h.plan_send(quotes=quotes, title="Alabama vs Auburn", sport="college football")
    assert plan["action"] == "send", plan
    assert plan["kind"] == "spread"
    assert plan["ask"] == Decimal("0.11")
    assert plan["gtc_offset"] == Decimal("0.10")
    assert plan["gtc_exit_pay"] == Decimal("0.2100")


def test_h_skips_totals_and_pair_breach():
    only_total = h.plan_send(
        quotes=[_row("total", "Over 45.5", "0.10"), _row("total", "Under 45.5", "0.90")],
        title="Alabama vs Auburn",
        sport="college football",
    )
    assert only_total["action"] == "skip"
    fat = h.plan_send(
        quotes=[_row("spread", "Alabama -3.5", "0.18"), _row("spread", "Auburn +3.5", "0.90")],
        title="Alabama vs Auburn",
        sport="college football",
    )
    assert fat["action"] == "skip", fat


def test_systems_letter_c_and_h():
    assert ps.LETTER["cfb_total_movers"] == "C"
    assert ps.LETTER["cfb_spread_movers"] == "H"
    assert ps.DISPLAY["cfb_total_movers"].startswith("College Football total")
    assert ps.ALIASES["c"] == "cfb_total_movers"
    assert ps.ALIASES["cfb_favorite"] == "cfb_total_movers"
    assert ps.ALIASES["h"] == "cfb_spread_movers"
    assert "cfb_total_movers" in live_lock_orders._DIRECTIONAL_SYSTEMS
    assert "cfb_spread_movers" in live_lock_orders._DIRECTIONAL_SYSTEMS
    assert live_lock_orders._send_blocked({"_system": "cfb_total_movers"}) == ""
    assert live_lock_orders._send_blocked({"_system": "cfb_spread_movers"}) == ""


def test_limit_sell_gtc_kalshi_and_poly():
    kalshi = live_lock_orders.build_limit_sell_spec(
        venue="kalshi",
        instrument="KXCFB-TEST",
        held_side="yes",
        pay=Decimal("0.27"),
        tif="gtc",
    )
    assert kalshi is not None
    assert kalshi["body"]["side"] == "ask"
    assert kalshi["body"]["price"] == "0.2700"
    assert kalshi["body"]["time_in_force"] == "good_till_canceled"
    poly = live_lock_orders.build_limit_sell_spec(
        venue="polymarket",
        instrument="slug-test",
        held_side="yes",
        pay=Decimal("0.27"),
        held_intent="ORDER_INTENT_BUY_LONG",
        tif="gtc",
    )
    assert poly is not None
    assert poly["intent"] == "ORDER_INTENT_SELL_LONG"
    assert poly["body"]["tif"] == live_lock_orders.POLY_TIF_GTC
    assert poly["body"]["synchronousExecution"] is False


def test_market_sell_still_builds_via_limit_helper():
    dump = live_lock_orders.build_market_sell_spec(
        venue="kalshi",
        instrument="KXCFB-TEST",
        held_side="yes",
        tif="ioc",
    )
    assert dump is not None
    assert dump["body"]["side"] == "ask"
    assert dump["tif"] == "ioc"


if __name__ == "__main__":
    test_mover_band_0_to_19_inclusive()
    test_pair_gate_and_gtc_offsets()
    test_c_buys_cheap_total_when_pair_ok()
    test_c_skips_pair_over_105_and_non_cfb()
    test_c_skips_20c_and_picks_cheapest_qualifying()
    test_h_buys_spread_mover_at_10c_gtc()
    test_h_skips_totals_and_pair_breach()
    test_systems_letter_c_and_h()
    test_limit_sell_gtc_kalshi_and_poly()
    test_market_sell_still_builds_via_limit_helper()
    print("test_live_cfb_movers ok")
