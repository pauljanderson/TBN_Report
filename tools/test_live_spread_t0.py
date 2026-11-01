"""D skips NFL / pro football while gathering T0 spread data.

Does not place orders. Does not start live_strategy_b.py. Does not sell.
Does not turn D off globally. CFB and other sports stay on.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import live_t0_yes
from live_spread_t0 import SID
from live_t0_yes import D_SKIP_NFL_TOKEN, is_nfl_sport


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


def test_is_nfl_sport_aliases():
    assert is_nfl_sport("pro football")
    assert is_nfl_sport("NFL")
    assert is_nfl_sport("  Pro Football ")
    assert not is_nfl_sport("college football")
    assert not is_nfl_sport("tennis")
    assert not is_nfl_sport("pro baseball")


def test_consider_skips_nfl_leaves_filled():
    logged = []
    saved = live_t0_yes.log
    live_t0_yes.log = lambda sid, msg: logged.append((sid, msg))
    cfg = SimpleNamespace(on=True, max_open=4, stake_usd=1, size=1)
    try:
        status = live_t0_yes.empty_status("spread_t0")
        reason = live_t0_yes.consider_game(
            "spread_t0",
            _FakeScan({}),
            {
                "sport": "pro football",
                "title": "Los Angeles vs Arizona",
                "key": "nfl_laari",
                "game": {},
            },
            status,
            cfg,
        )
        assert reason == D_SKIP_NFL_TOKEN
        assert any(D_SKIP_NFL_TOKEN in msg for _, msg in logged)
        status["matches"] = [{
            "key": "nfl_filled",
            "game": "Cincinnati vs Baltimore",
            "stage": "filled",
            "sport": "pro football",
        }]
        filled = live_t0_yes.consider_game(
            "spread_t0",
            _FakeScan({}),
            {
                "sport": "pro football",
                "title": "Cincinnati vs Baltimore",
                "key": "nfl_filled",
                "game": {},
            },
            status,
            cfg,
        )
        assert filled == "filled"
        waiting = {
            "key": "nfl_wait",
            "game": "Dallas vs Green Bay",
            "stage": "waiting_t0",
            "sport": "pro football",
        }
        status["matches"] = [waiting]
        skip_wait = live_t0_yes.consider_game(
            "spread_t0",
            _FakeScan({}),
            {
                "sport": "pro football",
                "title": "Dallas vs Green Bay",
                "key": "nfl_wait",
                "game": {},
            },
            status,
            cfg,
        )
        assert skip_wait == D_SKIP_NFL_TOKEN
        assert waiting["stage"] == "skipped"
        assert waiting["note"] == D_SKIP_NFL_TOKEN
    finally:
        live_t0_yes.log = saved


def test_slate_skips_nfl_keeps_cfb_and_other():
    logged = []
    saved_log = live_t0_yes.log
    saved_skip = live_t0_yes._last_d_nfl_skip
    live_t0_yes.log = lambda sid, msg: logged.append((sid, msg))
    live_t0_yes._last_d_nfl_skip = ()
    now = live_t0_yes.now_et()
    start = now.isoformat()
    scan = _FakeScan({
        "college football": [{
            "title_kalshi": "LSU vs Auburn",
            "listed_start": start,
            "codes": "lsuaub",
            "date": "2026-10-25",
        }],
        "pro football": [{
            "title_kalshi": "Los Angeles vs Arizona",
            "listed_start": start,
            "codes": "laari",
            "date": "2026-10-25",
        }],
        "pro baseball": [{
            "title_kalshi": "Yankees vs Red Sox",
            "listed_start": start,
            "codes": "nyybos",
            "date": "2026-10-25",
        }],
    })
    try:
        d_rows = live_t0_yes.slate_near_t0(scan, "spread_t0")
        sports = {row["sport"] for row in d_rows}
        titles = {row["title"] for row in d_rows}
        assert "pro football" not in sports
        assert "Los Angeles vs Arizona" not in titles
        assert "college football" in sports
        assert "pro baseball" in sports
        assert any(D_SKIP_NFL_TOKEN in msg for _, msg in logged)
        c_rows = live_t0_yes.slate_near_t0(scan, "cfb_favorite")
        assert {row["sport"] for row in c_rows} == {"college football"}
    finally:
        live_t0_yes.log = saved_log
        live_t0_yes._last_d_nfl_skip = saved_skip


def test_sid_is_spread_t0():
    assert SID == "spread_t0"
    text = (live_t0_yes.ROOT / "tools" / "live_spread_t0.py").read_text(encoding="utf-8")
    assert "d_skip_nfl_gathering" in text
    assert "systems.json D stays on" in text


def test_far_future_nfl_is_not_on_slate():
    logged = []
    saved_log = live_t0_yes.log
    saved_skip = live_t0_yes._last_d_nfl_skip
    live_t0_yes.log = lambda sid, msg: logged.append((sid, msg))
    live_t0_yes._last_d_nfl_skip = ()
    later = (live_t0_yes.now_et() + timedelta(days=2)).isoformat()
    scan = _FakeScan({
        "pro football": [{
            "title_kalshi": "Future Bowl",
            "listed_start": later,
            "codes": "fut",
            "date": "2026-11-01",
        }],
    })
    try:
        rows = live_t0_yes.slate_near_t0(scan, "spread_t0")
        assert rows == []
        assert not any("Future Bowl" in msg for _, msg in logged)
    finally:
        live_t0_yes.log = saved_log
        live_t0_yes._last_d_nfl_skip = saved_skip


if __name__ == "__main__":
    test_is_nfl_sport_aliases()
    test_consider_skips_nfl_leaves_filled()
    test_slate_skips_nfl_keeps_cfb_and_other()
    test_sid_is_spread_t0()
    test_far_future_nfl_is_not_on_slate()
    print("ok")
