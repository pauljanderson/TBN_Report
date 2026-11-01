"""TEN/CIN 29.5 team total vs game total must not send. True team lock still matches.

No orders. No secrets. No second B.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"))

import overnight_scan as ov
import live_lock_orders
import novig_live
import opportunity_considerations as oc
import price_memory
from test_live_lock_orders import Scan, _pair

KALSHI_TEAM = "KXNFLTEAMTOTAL-26NOV01TENCIN-CIN30"
KALSHI_GAME = "KXNFLTOTAL-26NOV01TENCIN-30"
NOVIG_GAME = "01a178fd-2f52-71a3-93b5-4c671fd27ff8"
GAME = {"codes": ["TEN", "CIN"], "teams": ["TEN", "CIN"]}
TITLE = "Tennessee vs Cincinnati Pro Football"


def _kalshi_raw(ticker: str, title: str, yes="0.53", no="0.49") -> dict:
    return {
        "ticker": ticker,
        "title": title,
        "yes_sub_title": title,
        "yes_ask_dollars": yes,
        "no_ask_dollars": no,
        "yes_ask_size_fp": "2",
        "no_ask_size_fp": "10",
        "status": "active",
        "floor_strike": "29.5",
    }


def _view(kind: str, side: str, number: str, code: str, ident: str, yes="0.53", no="0.09", label="") -> dict:
    return {
        "kind": kind,
        "side": side,
        "number": number,
        "code": code,
        "yes": Decimal(yes),
        "no": Decimal(no),
        "yes_size": Decimal("2"),
        "no_size": Decimal("10"),
        "label": label or side,
        "ident": ident,
        "status": "open",
        "no_flipped_yes_bid": False,
        "no_reject": "",
        "sell_yes": None,
        "yes_bid": None,
        "buy_no": Decimal(no),
    }


def test_ticker_kind_team_total_before_total():
    assert ov.market_type_from_ticker(KALSHI_TEAM) == "team_total"
    assert ov.market_type_from_ticker(KALSHI_GAME) == "total"
    assert price_memory.market_type_from(KALSHI_TEAM) == "team_total"
    assert price_memory.market_type_from(KALSHI_GAME) == "total"
    assert not price_memory.same_settlement(KALSHI_TEAM, KALSHI_GAME)
    assert "team_total" in price_memory.settlement_mismatch_reason("total", KALSHI_TEAM)


def test_contract_view_keeps_team_total():
    raw = _kalshi_raw(KALSHI_TEAM, "Cincinnati over 29.5 points scored")
    view = ov.contract_view(raw, "team_total", "kalshi")
    assert view is not None
    assert view["kind"] == "team_total"
    assert view["code"] == "CIN"
    assert str(view["number"]) == "29.5"
    parsed = ov.parse_side("Cincinnati over 29.5 points scored", None, "29.5")
    assert parsed[0] == "team_total"
    game = ov.parse_side("Over 29.5", None, "29.5")
    assert game[0] == "total"


def test_tencin_fixture_must_not_pair():
    kalshi = [
        _view(
            "team_total",
            "over",
            "29.5",
            "CIN",
            KALSHI_TEAM,
            yes="0.53",
            no="0.49",
            label="Cincinnati over 29.5 points scored",
        )
    ]
    novig = [
        _view("total", "over", "29.5", "", NOVIG_GAME, yes="0.91", no="0.09", label="over"),
        _view("total", "under", "29.5", "", NOVIG_GAME, yes="0.09", no="0.91", label="under"),
    ]
    # Even the old mis-kind (both labeled total) must fail ident TEAMTOTAL vs game.
    mis = [
        _view(
            "total",
            "over",
            "29.5",
            "",
            KALSHI_TEAM,
            yes="0.53",
            no="0.49",
            label="Cincinnati over 29.5 points scored",
        )
    ]
    cands = novig_live._pair_rows(ov, GAME, "kalshi", kalshi, "novig", novig)
    assert cands == []
    cands_mis = novig_live._pair_rows(ov, GAME, "kalshi", mis, "novig", novig)
    assert cands_mis == []
    gemini_game = [_view("total", "over", "29.5", "", "NFL-2611011300-TEN-CIN-T", yes="0.91", no="0.09")]
    assert ov.pair_contracts(kalshi, gemini_game, ov.alias_map(GAME)) == []
    assert ov.pair_contracts(mis, gemini_game, ov.alias_map(GAME)) == []


def test_true_team_total_over_under_still_matches():
    kalshi = [
        _view(
            "team_total",
            "over",
            "29.5",
            "CIN",
            KALSHI_TEAM,
            yes="0.53",
            no="0.49",
            label="Cincinnati over 29.5 points scored",
        )
    ]
    novig = [
        _view(
            "team_total",
            "over",
            "29.5",
            "CIN",
            "novig-cin-tt-29-5",
            yes="0.50",
            no="0.48",
            label="CIN over",
        )
    ]
    cands = novig_live._pair_rows(ov, GAME, "kalshi", kalshi, "novig", novig)
    assert cands, "same team, same line, team total Over vs Under/No must still lock"
    nets = [ov.d(c.get("gross")) for c in cands]
    assert Decimal("1.01") in nets  # 0.53 + 0.48
    for cand in cands:
        assert cand.get("market_type") == "team_total"
        yes_v = cand.get("yes_venue")
        no_v = cand.get("no_venue")
        assert {yes_v, no_v} == {"kalshi", "novig"}


def test_qualifies_and_recheck_see_bet_type():
    cand = _pair(
        market_type="total",
        side="Cincinnati over 29.5 points scored",
        number="29.5",
        yes_venue="kalshi",
        no_venue="novig",
        yes_price="0.53",
        no_price="0.09",
        yes_size="2",
        no_size="966",
        kalshi_ticker=KALSHI_TEAM,
        novig_market=NOVIG_GAME,
    )
    ok, why = live_lock_orders.qualifies(Scan(), cand, TITLE, GAME)
    assert ok is False
    assert "settlement" in why
    first = live_lock_orders._leg_spec(cand, "yes")
    assert first is not None
    assert first.get("market_type") == "total"
    assert first.get("instrument") == KALSHI_TEAM
    ok_legs, why_legs = live_lock_orders.same_settlement_legs(
        first,
        {"venue": "novig", "instrument": NOVIG_GAME, "market_type": "total"},
    )
    assert ok_legs is False
    assert "team_total" in why_legs
    true_lock = _pair(
        market_type="team_total",
        side="Cincinnati over 29.5 points scored",
        number="29.5",
        kalshi_ticker=KALSHI_TEAM,
        gemini_symbol="NFL-2611011300-TEN-CIN-TT",
    )
    ok2, why2 = live_lock_orders.same_settlement_candidate(true_lock)
    assert ok2 is True, why2


def test_opportunities_labels_not_a_lock():
    row = {
        "market_type": "total",
        "side": "Cincinnati over 29.5 points scored",
        "number": "29.5",
        "kalshi_ticker": KALSHI_TEAM,
        "decision": "sent",
        "source": "websocket",
    }
    assert oc.consideration_not_a_lock(row) is True
    assert oc._attempt_type(row) == "not a lock (two directional)"
    good = {
        "market_type": "team_total",
        "side": "Cincinnati over 29.5 points scored",
        "kalshi_ticker": KALSHI_TEAM,
        "decision": "sent",
    }
    assert oc.consideration_not_a_lock(good) is False
    assert oc._attempt_type(good) == "A lock gap"


if __name__ == "__main__":
    test_ticker_kind_team_total_before_total()
    test_contract_view_keeps_team_total()
    test_tencin_fixture_must_not_pair()
    test_true_team_total_over_under_still_matches()
    test_qualifies_and_recheck_see_bet_type()
    test_opportunities_labels_not_a_lock()
    print("ok")
