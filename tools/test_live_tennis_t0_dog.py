"""System E gates: unique T0 dog send, 50-50 skip, B-open skip, Poly size, max 2.

E consider sees tennis_rows (same list as B). Does not POST.
Does not start live_strategy_b.py. Does not sell.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders
import live_t0_yes
import live_tennis_t0_dog as e
import prediction_systems as ps


class _FakeScan:
    def __init__(self, sports: dict):
        self._sports = sports

    def load_college(self):
        return list(self._sports.get("college football") or [])

    def load_sports(self):
        return {k: v for k, v in self._sports.items() if k != "college football"}

    def game_codes(self, game):
        return str(game.get("codes") or "xx")

    def tickers_of(self, game):
        return [], []

    SPORT_PREFIX = {}


def _now_start():
    now = live_t0_yes.now_et()
    start = now.replace(second=0, microsecond=0)
    return now, start


def _tennis_row(title="Underdog vs Favorite", start_iso="", sport="tennis"):
    game = {
        "title_kalshi": title,
        "listed_start": start_iso,
        "codes": "undfav",
        "date": str(start_iso)[:10],
    }
    return {
        "key": "tennis_undfav_" + str(start_iso)[:10].replace("-", "_"),
        "sport": sport,
        "game": game,
        "title": title,
        "start": start_iso,
        "listed_start": start_iso,
    }


def _ml_quotes(dog="Underdog", fav="Favorite", dog_ask="0.41", fav_ask="0.61"):
    return [
        {
            "venue": "kalshi",
            "side": dog,
            "team": dog,
            "yes": Decimal(dog_ask),
            "ask": Decimal(dog_ask),
            "kind": "moneyline",
            "number": "",
        },
        {
            "venue": "kalshi",
            "side": fav,
            "team": fav,
            "yes": Decimal(fav_ask),
            "ask": Decimal(fav_ask),
            "kind": "moneyline",
            "number": "",
        },
    ]


def _quotes(dog="Underdog", fav="Favorite", dog_ask="0.41", fav_ask="0.61", venue="kalshi", size=None):
    rows = [
        {"venue": venue, "side": dog, "team": dog, "yes": Decimal(dog_ask), "ask": Decimal(dog_ask)},
        {"venue": venue, "side": fav, "team": fav, "yes": Decimal(fav_ask), "ask": Decimal(fav_ask)},
    ]
    if size is not None:
        rows[0]["yes_size"] = Decimal(str(size))
        rows[0]["spec"] = {"venue": venue, "quote_size": Decimal(str(size)), "yes_size": Decimal(str(size))}
    return rows


def test_dog_041_fav_061_sends_e():
    asks = {"Underdog": Decimal("0.41"), "Favorite": Decimal("0.61")}
    assert ps.pick_dog_primary(asks) == "Underdog"
    plan = e.plan_send(side_asks=asks, quotes=_quotes(), max_open=2, open_n=0)
    assert plan["action"] == "send", plan
    assert plan["dog"] == "Underdog"
    assert plan["ask"] == Decimal("0.41")
    assert plan["venue"] == "kalshi"


def test_both_050_skip():
    asks = {"A": Decimal("0.50"), "B": Decimal("0.50")}
    assert ps.pick_dog_primary(asks) is None
    plan = e.plan_send(side_asks=asks, quotes=_quotes(dog_ask="0.50", fav_ask="0.50"))
    assert plan["action"] == "skip"
    assert "50" in plan["reason"] or "unique" in plan["reason"] or "junk" in plan["reason"]


def test_b_already_open_skip():
    asks = {"Underdog": Decimal("0.41"), "Favorite": Decimal("0.61")}
    b_status = {
        "matches": [
            {"game": "Underdog vs Favorite", "stage": "absorbed", "note": "holding T0 both-Yes"},
        ]
    }
    plan = e.plan_send(
        side_asks=asks,
        quotes=_quotes(),
        title="Underdog vs Favorite",
        b_status=b_status,
    )
    assert plan["action"] == "skip", plan
    assert plan["reason"] == "B already on match"
    t0_sent = {
        "matches": [
            {
                "game": "Underdog vs Favorite",
                "stage": "t0_filled_waiting_50_cross",
                "t0_yes": {"a": {"fill_qty": "1"}},
            }
        ]
    }
    assert e.b_holds_match("Underdog vs Favorite", b_status=t0_sent) is True
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
    assert e.b_holds_match("Underdog vs Favorite", b_status=c_over) is False
    allowed = e.plan_send(
        side_asks=asks,
        quotes=_quotes(),
        title="Underdog vs Favorite",
        b_status=c_over,
    )
    assert allowed["action"] == "send", allowed


def test_poly_size_03_skip():
    asks = {"Underdog": Decimal("0.41"), "Favorite": Decimal("0.61")}
    quotes = _quotes(venue="polymarket", size="0.3")
    plan = e.plan_send(side_asks=asks, quotes=quotes)
    assert plan["action"] == "skip", plan
    assert live_lock_orders.POLY_SIZE_LT_QTY_SKIP in str(plan["reason"])
    spec = {"venue": "polymarket", "quote_size": Decimal("0.3")}
    skip = live_lock_orders.poly_size_lt_qty_skip(spec, rest=False)
    assert skip
    assert "0.3" in skip or "saw=" in skip


def test_max_2_blocks_third():
    asks = {"Underdog": Decimal("0.41"), "Favorite": Decimal("0.61")}
    first = e.plan_send(side_asks=asks, quotes=_quotes(), open_n=0, max_open=2)
    second = e.plan_send(side_asks=asks, quotes=_quotes(), open_n=1, max_open=2)
    third = e.plan_send(side_asks=asks, quotes=_quotes(), open_n=2, max_open=2)
    assert first["action"] == "send"
    assert second["action"] == "send"
    assert third["action"] == "skip"
    assert third["reason"] == "max_open"


def test_junk_dog_le_010_skip():
    asks = {"Junk": Decimal("0.10"), "Favorite": Decimal("0.90")}
    assert ps.pick_dog_primary(asks) is None
    assert ps.in_dog_band(Decimal("0.10")) is False
    assert ps.in_dog_band(Decimal("0.41")) is True


def test_e_skip_010_and_050_send_011_to_049():
    """Exclusive band: 10¢ and 50¢ skip; 11¢ through 49¢ would send at T0."""
    assert ps.in_dog_band(Decimal("0.10")) is False
    assert ps.in_dog_band(Decimal("0.50")) is False
    assert ps.in_dog_band(Decimal("0.11")) is True
    assert ps.in_dog_band(Decimal("0.49")) is True
    lo = e.plan_send(
        side_asks={"Underdog": Decimal("0.10"), "Favorite": Decimal("0.90")},
        quotes=_quotes(dog_ask="0.10", fav_ask="0.90"),
    )
    assert lo["action"] == "skip", lo
    hi = e.plan_send(
        side_asks={"Underdog": Decimal("0.50"), "Favorite": Decimal("0.50")},
        quotes=_quotes(dog_ask="0.50", fav_ask="0.50"),
    )
    assert hi["action"] == "skip", hi
    send_lo = e.plan_send(
        side_asks={"Underdog": Decimal("0.11"), "Favorite": Decimal("0.89")},
        quotes=_quotes(dog_ask="0.11", fav_ask="0.89"),
    )
    assert send_lo["action"] == "send", send_lo
    assert send_lo["ask"] == Decimal("0.11")
    send_hi = e.plan_send(
        side_asks={"Underdog": Decimal("0.49"), "Favorite": Decimal("0.51")},
        quotes=_quotes(dog_ask="0.49", fav_ask="0.51"),
    )
    assert send_hi["action"] == "send", send_hi
    assert send_hi["ask"] == Decimal("0.49")


def test_e_consider_sees_tennis_row_from_tennis_rows():
    """E slate reads tennis_rows (B's list). NFL/CFB queue rows stay off E."""
    _now, start = _now_start()
    tennis = [_tennis_row(start_iso=start.isoformat())]
    nfl = {
        "title_kalshi": "Los Angeles vs Arizona",
        "listed_start": start.isoformat(),
        "codes": "laari",
        "date": start.date().isoformat(),
    }
    cfb = {
        "title_kalshi": "LSU vs Auburn",
        "listed_start": start.isoformat(),
        "codes": "lsuaub",
        "date": start.date().isoformat(),
    }
    scan = _FakeScan({"pro football": [nfl], "college football": [cfb]})
    quotes = _ml_quotes()
    fired = []

    def fake_fire(sid, spec, shot, cfg, log_fn):
        fired.append((sid, spec.get("title"), shot.get("dog"), shot.get("dog_ask")))
        return {"stage": "filled", "note": "test no POST", "last_order": {}}

    with patch("live_game_pollers.tennis_rows", return_value=tennis):
        with patch.object(live_t0_yes, "collect_quotes", return_value=(quotes, [], [], [], [])):
            with patch.object(live_t0_yes, "fire", fake_fire):
                with patch.object(live_t0_yes, "b_holds_match", return_value=False):
                    slate = live_t0_yes.slate_near_t0(scan, "tennis_t0_dog")
                    assert len(slate) == 1, slate
                    assert slate[0]["sport"] == "tennis"
                    assert slate[0]["title"] == "Underdog vs Favorite"
                    titles = {row["title"] for row in slate}
                    assert "Los Angeles vs Arizona" not in titles
                    assert "LSU vs Auburn" not in titles
                    cfg = SimpleNamespace(on=True, max_open=99, stake_usd=Decimal("1"), size=1)
                    status = {"system": "tennis_t0_dog", "matches": [], "skipped": []}
                    with patch.object(live_t0_yes, "open_matches", return_value=[]):
                        with patch.object(live_t0_yes, "rest_e_open_same_dog", return_value=False):
                            live_t0_yes._E_HELD_DOGS.clear()
                            stage = live_t0_yes.consider_game(
                                "tennis_t0_dog", scan, slate[0], status, cfg
                            )
                    assert stage == "filled", (stage, status)
                    assert fired
                    assert fired[0][0] == "tennis_t0_dog"
                    assert fired[0][2] == "Underdog"


def test_e_consider_skips_when_b_holds():
    _now, start = _now_start()
    spec = _tennis_row(start_iso=start.isoformat())
    quotes = _ml_quotes()
    fired = []

    def fake_fire(sid, spec_row, shot, cfg, log_fn):
        fired.append(sid)
        return {"stage": "filled", "note": "should not fire", "last_order": {}}

    with patch.object(live_t0_yes, "collect_quotes", return_value=(quotes, [], [], [], [])):
        with patch.object(live_t0_yes, "fire", fake_fire):
            with patch.object(live_t0_yes, "b_holds_match", return_value=True):
                cfg = SimpleNamespace(on=True, max_open=99, stake_usd=Decimal("1"), size=1)
                status = {"system": "tennis_t0_dog", "matches": [], "skipped": []}
                with patch.object(live_t0_yes, "open_matches", return_value=[]):
                    reason = live_t0_yes.consider_game(
                        "tennis_t0_dog", _FakeScan({}), spec, status, cfg
                    )
                assert reason == "B already on match"
                assert fired == []


def test_e_consider_skips_010_and_050_at_t0():
    _now, start = _now_start()
    spec = _tennis_row(start_iso=start.isoformat())
    cfg = SimpleNamespace(on=True, max_open=99, stake_usd=Decimal("1"), size=1)
    fired = []

    def fake_fire(sid, spec_row, shot, cfg, log_fn):
        fired.append(sid)
        return {"stage": "filled", "note": "should not fire", "last_order": {}}

    with patch.object(live_t0_yes, "fire", fake_fire):
        with patch.object(live_t0_yes, "b_holds_match", return_value=False):
            with patch.object(live_t0_yes, "open_matches", return_value=[]):
                with patch.object(
                    live_t0_yes,
                    "collect_quotes",
                    return_value=(_ml_quotes(dog_ask="0.10", fav_ask="0.90"), [], [], [], []),
                ):
                    status = {"system": "tennis_t0_dog", "matches": [], "skipped": []}
                    reason = live_t0_yes.consider_game(
                        "tennis_t0_dog", _FakeScan({}), spec, status, cfg
                    )
                    assert "0.10" in reason or "unique dog" in reason, reason
                    assert fired == []
                with patch.object(
                    live_t0_yes,
                    "collect_quotes",
                    return_value=(_ml_quotes(dog_ask="0.50", fav_ask="0.50"), [], [], [], []),
                ):
                    status = {"system": "tennis_t0_dog", "matches": [], "skipped": []}
                    reason = live_t0_yes.consider_game(
                        "tennis_t0_dog", _FakeScan({}), spec, status, cfg
                    )
                    assert "0.50" in reason or "unique dog" in reason, reason
                    assert fired == []


def test_e_consider_would_send_011_049_at_t0():
    live_t0_yes._E_HELD_DOGS.clear()
    _now, start = _now_start()
    spec = _tennis_row(start_iso=start.isoformat())
    cfg = SimpleNamespace(on=True, max_open=99, stake_usd=Decimal("1"), size=1)
    fired = []

    def fake_fire(sid, spec_row, shot, cfg, log_fn):
        fired.append(shot.get("dog_ask"))
        return {"stage": "filled", "note": "test no POST", "last_order": {}}

    with patch.object(live_t0_yes, "fire", fake_fire):
        with patch.object(live_t0_yes, "b_holds_match", return_value=False):
            with patch.object(live_t0_yes, "rest_e_open_same_dog", return_value=False):
                with patch.object(live_t0_yes, "open_matches", return_value=[]):
                    with patch.object(
                        live_t0_yes,
                        "collect_quotes",
                        return_value=(_ml_quotes(dog_ask="0.11", fav_ask="0.89"), [], [], [], []),
                    ):
                        live_t0_yes._E_HELD_DOGS.clear()
                        status = {"system": "tennis_t0_dog", "matches": [], "skipped": []}
                        stage = live_t0_yes.consider_game(
                            "tennis_t0_dog", _FakeScan({}), spec, status, cfg
                        )
                        assert stage == "filled", stage
                    with patch.object(
                        live_t0_yes,
                        "collect_quotes",
                        return_value=(_ml_quotes(dog_ask="0.49", fav_ask="0.51"), [], [], [], []),
                    ):
                        live_t0_yes._E_HELD_DOGS.clear()
                        status = {"system": "tennis_t0_dog", "matches": [], "skipped": []}
                        stage = live_t0_yes.consider_game(
                            "tennis_t0_dog", _FakeScan({}), spec, status, cfg
                        )
                        assert stage == "filled", stage
    assert Decimal("0.11") in fired
    assert Decimal("0.49") in fired


def test_e_trusted_clock_waits_for_later_listed():
    occ = datetime(2026, 10, 28, 0, 30, tzinfo=live_t0_yes.ET)
    listed = datetime(2026, 10, 28, 21, 30, tzinfo=live_t0_yes.ET)
    clock, src = live_t0_yes.choose_trusted_t0_clock(occ, listed)
    assert clock == listed
    assert src == "listed/feed"
    now = datetime(2026, 10, 28, 0, 32, tzinfo=live_t0_yes.ET)
    ready, why = live_t0_yes.t0_window(clock, now)
    assert ready is False
    assert why == "before T0"
    near = datetime(2026, 10, 28, 21, 29, 50, tzinfo=live_t0_yes.ET)
    ready, why = live_t0_yes.t0_window(clock, near)
    assert ready is True
    kalshi = [{"occurrence_datetime": occ.isoformat()}]
    clock2, src2 = live_t0_yes.trusted_t0_clock(listed.isoformat(), [], kalshi)
    assert clock2 == listed
    assert src2 == "listed/feed"


def test_e_slate_drops_nontennis_and_far_future():
    _now, start = _now_start()
    later = (start + timedelta(days=2)).isoformat()
    rows = [
        _tennis_row(title="Now Match", start_iso=start.isoformat()),
        _tennis_row(title="Later Match", start_iso=later),
        _tennis_row(title="NFL on tennis list", start_iso=start.isoformat(), sport="pro football"),
    ]
    with patch("live_game_pollers.tennis_rows", return_value=rows):
        slate = live_t0_yes.slate_near_t0(_FakeScan({}), "tennis_t0_dog")
    titles = {row["title"] for row in slate}
    sports = {row["sport"] for row in slate}
    assert "Now Match" in titles
    assert "Later Match" not in titles
    assert "NFL on tennis list" not in titles
    assert sports <= {"tennis"}


def test_tagger_linette_titles_are_same_match():
    a = "Lilli Tagger vs. Magda Linette"
    b = "Magda Linette @ Lilli Tagger Round of 16"
    assert live_t0_yes.same_game(a, b)
    assert live_t0_yes.match_player_set(a) == frozenset({"tagger", "linette"})
    e_status = {
        "matches": [
            {
                "game": b,
                "key": "tennis_01a17d48090279718b1c63cb_2026_10_29",
                "stage": "filled",
                "dog": "Magda Linette",
                "instrument": "aec-wta-liltag-maglin-2026-10-29",
                "last_order": {"fill_qty": "1", "instrument": "aec-wta-liltag-maglin-2026-10-29"},
            }
        ]
    }
    asks = {"Magda Linette": Decimal("0.25"), "Lilli Tagger": Decimal("0.75")}
    quotes = _quotes(dog="Magda Linette", fav="Lilli Tagger", dog_ask="0.25", fav_ask="0.75")
    plan = e.plan_send(side_asks=asks, quotes=quotes, title=a, e_status=e_status)
    assert plan["action"] == "skip", plan
    assert "already filled" in plan["reason"]
    assert "Linette" in plan["reason"]


def test_michelsen_fils_two_platforms_same_dog():
    poly_title = "Alex Michelsen vs. Arthur Fils"
    kalshi_title = "Michelsen vs Fils"
    assert live_t0_yes.same_game(poly_title, kalshi_title)
    e_status = {
        "matches": [
            {
                "game": poly_title,
                "key": "tennis_michelfils_2026_10_29",
                "stage": "filled",
                "dog": "Alex Michelsen",
                "venue": "polymarket",
                "instrument": "aec-atp-alemic-artfil-2026-10-29",
                "last_order": {"fill_qty": "1", "instrument": "aec-atp-alemic-artfil-2026-10-29"},
            }
        ]
    }
    asks = {"Alex Michelsen": Decimal("0.35"), "Arthur Fils": Decimal("0.65")}
    quotes = _quotes(dog="Alex Michelsen", fav="Arthur Fils", dog_ask="0.35", fav_ask="0.65", venue="kalshi")
    plan = e.plan_send(side_asks=asks, quotes=quotes, title=kalshi_title, e_status=e_status)
    assert plan["action"] == "skip", plan
    assert "already filled" in plan["reason"]
    assert live_t0_yes.acquire_e_dog(poly_title, "Alex Michelsen") is True
    assert live_t0_yes.acquire_e_dog(kalshi_title, "Alex Michelsen") is False
    live_t0_yes.release_e_dog(poly_title, "Alex Michelsen")


if __name__ == "__main__":
    test_dog_041_fav_061_sends_e()
    test_both_050_skip()
    test_b_already_open_skip()
    test_poly_size_03_skip()
    test_max_2_blocks_third()
    test_junk_dog_le_010_skip()
    test_e_skip_010_and_050_send_011_to_049()
    test_e_consider_sees_tennis_row_from_tennis_rows()
    test_e_consider_skips_when_b_holds()
    test_e_consider_skips_010_and_050_at_t0()
    test_e_consider_would_send_011_049_at_t0()
    test_e_slate_drops_nontennis_and_far_future()
    test_e_trusted_clock_waits_for_later_listed()
    test_tagger_linette_titles_are_same_match()
    test_michelsen_fils_two_platforms_same_dog()
    print("ok")
