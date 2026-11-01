"""Novig quote identity. No network and no orders."""
from decimal import Decimal

import novig_live


def test_ask_is_one_minus_the_other_bid():
    contract = {
        "yes_outcome": "LAC",
        "no_outcome": "SAC",
        "orders": {
            "LAC": [{"price": "0.615", "qty": 200}],
            "SAC": [{"price": "0.380", "qty": 100}],
        },
    }
    novig_live.refresh_quotes(contract)
    assert contract["yes_ask"] == Decimal("0.620")
    assert contract["ask_size"] == Decimal("1")
    assert contract["no_ask"] == Decimal("0.385")
    assert contract["no_ask_size"] == Decimal("2")


def test_zero_size_is_not_an_ask():
    contract = {
        "yes_outcome": "A",
        "no_outcome": "B",
        "orders": {"A": [{"price": "0.40", "qty": 0}], "B": []},
    }
    novig_live.refresh_quotes(contract)
    assert contract["yes_ask"] is None
    assert contract["no_ask"] is None


def test_spread_keeps_the_minus_side_only():
    market = {
        "marketId": "m1",
        "eventId": "e1",
        "marketType": "SPREAD",
        "status": "OPEN",
        "strike": "-4.5",
        "fee": {"coefficient": "0.06", "charged": "WHEN_LIVE"},
        "outcomes": [
            {"outcomeId": "fav", "name": "BKN -4.5"},
            {"outcomeId": "dog", "name": "CHA +4.5"},
        ],
    }
    parsed = novig_live.parse_market(market, "OPEN_PREGAME", {"spread": {"4.5"}, "total": set()})
    assert parsed["kind"] == "spread"
    assert parsed["side"] == "BKN"
    assert parsed["number"] == "4.5"
    views = novig_live.contract_views(parsed)
    assert [row["side"] for row in views] == ["BKN"]


def test_moneyline_is_not_a_spread():
    market = {
        "marketId": "m2",
        "eventId": "e1",
        "marketType": "MONEY",
        "status": "OPEN",
        "strike": "0",
        "fee": {"coefficient": "0.06", "charged": "WHEN_LIVE"},
        "outcomes": [
            {"outcomeId": "a", "name": "LAC"},
            {"outcomeId": "b", "name": "SAC"},
        ],
    }
    parsed = novig_live.parse_market(market, "OPEN_PREGAME", {"spread": set(), "total": set()})
    assert parsed["kind"] == "moneyline"
    assert parsed["number"] == ""


def test_over_is_more_than():
    market = {
        "marketId": "m3",
        "eventId": "e1",
        "marketType": "TOTAL",
        "status": "OPEN",
        "strike": "35.5",
        "fee": {"coefficient": "0.06", "charged": "WHEN_LIVE"},
        "outcomes": [
            {"outcomeId": "o", "name": "Over 35.5"},
            {"outcomeId": "u", "name": "Under 35.5"},
        ],
    }
    parsed = novig_live.parse_market(market, "OPEN_PREGAME", {"spread": set(), "total": {"35.5"}})
    views = novig_live.contract_views(parsed)
    assert {row["side"] for row in views} == {"over", "under"}


def test_pregame_fee_is_zero_and_live_fee_uses_the_market_coefficient():
    price = Decimal("0.40")
    assert novig_live.taker_fee(price, "0.06", "WHEN_LIVE", "OPEN_PREGAME") == Decimal("0")
    assert novig_live.taker_fee(price, "0.06", "WHEN_LIVE", "OPEN") == Decimal("0")
    assert novig_live.taker_fee(price, "0.06", "WHEN_LIVE", "OPEN_INGAME") == Decimal("0.01440")
    assert novig_live.taker_fee(price, None, "ALWAYS", "OPEN_INGAME") is None
    assert novig_live.taker_fee(price, "0.06", "", "OPEN_INGAME") is None


def test_official_formula_yes_equals_no_and_docs_examples():
    """docs.novig.com/fees: Fee = c × P × (1−P) × N for one $1 contract (N=1)."""
    c = "0.06"
    live = "OPEN_INGAME"
    # 1 contract @ $0.50 → $0.015; @ $0.30 same as @ $0.70.
    assert novig_live.taker_fee(Decimal("0.50"), c, "WHEN_LIVE", live) == Decimal("0.01500")
    assert novig_live.taker_fee(Decimal("0.30"), c, "WHEN_LIVE", live) == Decimal("0.01260")
    assert novig_live.taker_fee(Decimal("0.70"), c, "WHEN_LIVE", live) == Decimal("0.01260")
    assert novig_live.taker_fee(Decimal("0.10"), c, "WHEN_LIVE", live) == Decimal("0.00540")
    yes_fee = novig_live.taker_fee(Decimal("0.38"), c, "WHEN_LIVE", live)
    no_fee = novig_live.taker_fee(Decimal("0.62"), c, "WHEN_LIVE", live)
    assert yes_fee == no_fee == Decimal("0.01414")
    assert novig_live.taker_fee(Decimal("0.50"), c, "ALWAYS", "OPEN_PREGAME") == Decimal("0.01500")
    assert novig_live.taker_fee(Decimal("0.50"), None, "WHEN_LIVE", live) is None


def test_fee_from_fills_absent_is_uncharged_zero():
    assert novig_live.fee_from_fills([]) is None
    assert novig_live.fee_from_fills(None) is None
    uncharged = [{"qty": 100, "cost": "0.40", "taker": True}]
    assert novig_live.fee_from_fills(uncharged) == Decimal("0")
    charged = [{"qty": 100, "cost": "0.40", "fee": "0.01440", "taker": True}]
    assert novig_live.fee_from_fills(charged) == Decimal("0.01440")


def test_ensure_fee_schedule_does_not_invent_coefficient():
    contract = {"market_id": "", "fee_coefficient": None, "fee_charged": "", "event_status": "OPEN_INGAME"}
    novig_live.ensure_fee_schedule(contract, fetch=False)
    assert contract["fee_coefficient"] is None
    assert novig_live.taker_fee(Decimal("0.40"), contract["fee_coefficient"], contract["fee_charged"], "OPEN_INGAME") is None


def test_tennis_spread_is_kept_without_listed_number():
    market = {
        "marketId": "m-ten",
        "eventId": "e-ten",
        "marketType": "SPREAD",
        "status": "OPEN",
        "strike": "-3.5",
        "fee": {"coefficient": "0.06", "charged": "WHEN_LIVE"},
        "outcomes": [
            {"outcomeId": "fav", "name": "Carlos Alcaraz -3.5"},
            {"outcomeId": "dog", "name": "Jannik Sinner +3.5"},
        ],
    }
    parsed = novig_live.parse_market(market, "OPEN_INGAME", None, "tennis")
    assert parsed is not None
    assert parsed["kind"] == "spread"
    assert parsed["side"] == "Carlos Alcaraz"
    assert parsed["number"] == "3.5"
    football = novig_live.parse_market(market, "OPEN_INGAME", None, "pro football")
    assert football is None


def test_unlisted_spread_number_is_skipped():
    market = {
        "marketId": "m4",
        "eventId": "e1",
        "marketType": "SPREAD",
        "status": "OPEN",
        "strike": "-9.5",
        "fee": {"coefficient": "0.06", "charged": "WHEN_LIVE"},
        "outcomes": [
            {"outcomeId": "fav", "name": "BKN -9.5"},
            {"outcomeId": "dog", "name": "CHA +9.5"},
        ],
    }
    assert novig_live.parse_market(market, "OPEN_PREGAME", {"spread": {"4.5"}, "total": set()}) is None


def test_subscribe_does_not_place():
    message = novig_live.subscribe_message(["m1"], 1)
    assert "place" not in message
    assert message["subscribe"]["markets"] == {"m1": "book"}


if __name__ == "__main__":
    test_ask_is_one_minus_the_other_bid()
    test_zero_size_is_not_an_ask()
    test_spread_keeps_the_minus_side_only()
    test_moneyline_is_not_a_spread()
    test_over_is_more_than()
    test_pregame_fee_is_zero_and_live_fee_uses_the_market_coefficient()
    test_official_formula_yes_equals_no_and_docs_examples()
    test_fee_from_fills_absent_is_uncharged_zero()
    test_ensure_fee_schedule_does_not_invent_coefficient()
    test_tennis_spread_is_kept_without_listed_number()
    test_unlisted_spread_number_is_skipped()
    test_subscribe_does_not_place()
    print("novig tests ok")
