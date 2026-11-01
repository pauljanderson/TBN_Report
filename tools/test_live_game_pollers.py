"""In-match quote collection gates. No network and no orders."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers as lgp


class Scan:
    def tickers_of(self, game):
        kalshi = game.get("kalshi") or {}
        gem = game.get("gemini") or {}
        k = [t for t in (kalshi.get("game"),) if t]
        g = [t for t in (gem.get("moneyline"),) if t]
        return k, g

    def game_codes(self, game):
        kalshi = game.get("kalshi") or {}
        ticker = str(kalshi.get("game") or "")
        if ticker:
            tail = ticker.split("-")[-1]
            match = re.search(r"\d{2}[A-Z]{3}\d{2}(?:\d{4})?([A-Z].+)$", tail)
            if match:
                return match.group(1).lower()
            return tail.lower()
        teams = game.get("codes") or []
        return "".join(str(part) for part in teams).lower()


def test_twin_key_unchanged():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT18WAWLAN",
            "slug": "aec-atp-stawaw-marlan-2026-10-18",
            "title": "Wawrinka vs Landaluce",
            "date": "2026-10-18",
            "startTime": (now - lgp.timedelta(minutes=10)).isoformat(),
        }],
        novig_games=[],
    )
    assert len(rows) == 1
    assert rows[0]["key"] == "tennis_wawlan_2026_10_18"
    assert rows[0]["game"]["kalshi"]["game"] == "KXATPMATCH-26OCT18WAWLAN"
    assert rows[0]["game"]["polymarket_markets"][0]["slug"].startswith("aec-atp")


def test_kalshi_only_without_polymarket_twin():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXWTAMATCH-26OCT21SWISAB",
            "slug": "",
            "title": "Swiatek vs Sabalenka",
            "date": now.date().isoformat(),
        }],
        novig_games=[],
    )
    assert len(rows) == 1
    assert rows[0]["sport"] == "tennis"
    assert "swiatek" in rows[0]["title"].lower() or "swiatek" in rows[0]["key"]
    assert lgp.has_quote_venues(rows[0]["game"], scan)


def test_polymarket_only_without_kalshi():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "",
            "slug": "aec-atp-onlypoly-2026-10-21",
            "title": "Pacheco Mendez vs Rodriguez Taverna",
            "date": now.date().isoformat(),
            "long_name": "Pacheco Mendez",
            "short_name": "Rodriguez Taverna",
            "startTime": (now - lgp.timedelta(minutes=10)).isoformat(),
        }],
        novig_games=[],
    )
    assert len(rows) == 1
    game = rows[0]["game"]
    assert not game.get("kalshi", {}).get("game")
    assert game["polymarket_markets"][0]["slug"] == "aec-atp-onlypoly-2026-10-21"
    assert lgp.has_quote_venues(game, scan)


def test_novig_only_dedupes_against_twin():
    scan = Scan()
    now = lgp.now_et()
    start = (now - lgp.timedelta(minutes=8)).isoformat()
    today = now.date().isoformat()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT18WAWLAN",
            "slug": "aec-atp-stawaw-marlan-2026-10-18",
            "title": "Wawrinka vs Landaluce",
            "date": today,
            "startTime": start,
        }],
        novig_games=[{
            "title": "Stan Wawrinka vs Martin Landaluce",
            "date": today,
            "event_id": "nv-waw",
            "novig_markets": [{"market_id": "m1", "kind": "moneyline"}],
            "startTime": start,
        }],
    )
    assert len(rows) == 1
    assert rows[0]["key"].startswith("tennis_wawlan_")


def test_novig_only_is_kept():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[],
        novig_games=[{
            "title": "Alice vs Bob",
            "date": now.date().isoformat(),
            "event_id": "nv-alicebob",
            "novig_markets": [{"market_id": "m9", "kind": "moneyline"}],
            "status": "OPEN_INGAME",
            "startTime": (now - lgp.timedelta(minutes=15)).isoformat(),
        }],
    )
    assert len(rows) == 1
    assert lgp.has_quote_venues(rows[0]["game"], scan)
    assert rows[0]["game"]["novig_markets"][0]["market_id"] == "m9"


def test_football_kalshi_only_is_enough():
    scan = Scan()
    game = {"kalshi": {"game": "KXNFLGAME-26OCT23NECHI"}, "gemini": {}, "date": "2026-10-23"}
    assert lgp.has_quote_venues(game, scan)
    empty = {"kalshi": {}, "gemini": {}, "date": "2026-10-23"}
    assert not lgp.has_quote_venues(empty, scan)


def test_unmatched_future_polymarket_is_not_spawned():
    scan = Scan()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "",
            "slug": "aec-atp-later-2026-10-22",
            "title": "Future vs Player",
            "date": "2026-10-22",
            "startTime": "2026-10-22T18:00:00-04:00",
        }],
        novig_games=[],
    )
    assert rows == []


def test_unmatched_live_polymarket_is_spawned():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "",
            "slug": "aec-atp-live-now",
            "title": "Liveone vs Livetwo",
            "date": now.date().isoformat(),
            "startTime": (now - lgp.timedelta(minutes=20)).isoformat(),
        }],
        novig_games=[],
    )
    assert len(rows) == 1
    assert rows[0]["game"]["polymarket_markets"][0]["slug"] == "aec-atp-live-now"


def test_identity_ignores_first_name_order():
    left = lgp.tennis_identity("Wawrinka vs Landaluce", "2026-10-18")
    right = lgp.tennis_identity("Martin Landaluce vs Stan Wawrinka", "2026-10-18")
    assert left and left == right


def test_supervisor_leftover_tick_has_no_clock_cutoff():
    import inspect

    src = inspect.getsource(lgp.supervise)
    assert "WATCH_DEADLINE" not in src
    assert "8:00 AM" not in src
    assert "spawn_lock_sender" in src
    assert "tick_one_leg_watch" not in src
    sender = (ROOT / "tools" / "live_lock_sender.py").read_text(encoding="utf-8")
    assert "ensure_watch_ticker" in sender
    assert "execute_locks" in sender
    assert lgp.job_deadline_iso() is None
    assert lgp.past_job_deadline() is False


def test_pollers_have_no_job_deadline():
    from datetime import datetime

    friday = datetime(2026, 10, 23, 8, 0, 0, tzinfo=lgp.ET)
    assert lgp.past_job_deadline() is False
    assert lgp.past_job_deadline(friday) is False
    assert lgp.job_deadline_iso() is None
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT18WAWLAN",
            "slug": "aec-atp-stawaw-marlan-2026-10-18",
            "title": "Wawrinka vs Landaluce",
            "date": now.date().isoformat(),
        }],
        novig_games=[],
    )
    assert rows
    assert lgp.job_deadline_iso() is None


def test_new_pollers_hide_windows_on_nt():
    import os
    import subprocess

    import win_hidden

    flags = lgp.poller_creationflags()
    info = win_hidden.startupinfo()
    if os.name == "nt":
        assert flags & subprocess.CREATE_NO_WINDOW
        assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
        assert not (flags & win_hidden.DETACHED_PROCESS)
        assert not (flags & win_hidden.CREATE_NEW_CONSOLE)
        assert info is not None
        assert info.wShowWindow == win_hidden.SW_HIDE
    else:
        assert flags == 0
        assert info is None


def test_pre_start_window_is_five_minutes():
    assert lgp.TENNIS_PRE_START_MIN == 5
    assert lgp.TENNIS_NEVER_LIVE_MIN == 30


def test_tomorrow_twin_is_not_spawned():
    scan = Scan()
    now = lgp.now_et()
    tomorrow = now + lgp.timedelta(days=1)
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT29ABCVYZ",
            "slug": "aec-atp-tomorrow-twin",
            "title": "Tomorrow vs Twin",
            "date": tomorrow.date().isoformat(),
            "startTime": tomorrow.replace(hour=14, minute=0, second=0, microsecond=0).isoformat(),
        }],
        novig_games=[],
    )
    assert rows == []
    assert lgp.tennis_collect_now(
        {
            "event_ticker": "KXATPMATCH-26OCT29ABCVYZ",
            "slug": "aec-atp-tomorrow-twin",
            "date": tomorrow.date().isoformat(),
            "startTime": tomorrow.replace(hour=14, minute=0, second=0, microsecond=0).isoformat(),
        },
        True,
        now,
    ) is False


def test_in_window_twin_is_spawned():
    scan = Scan()
    now = lgp.now_et()
    start = now + lgp.timedelta(minutes=3)
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT28NOWABC",
            "slug": "aec-atp-in-window-twin",
            "title": "Inwindow vs Twin",
            "date": now.date().isoformat(),
            "startTime": start.isoformat(),
        }],
        novig_games=[],
    )
    assert len(rows) == 1
    assert rows[0]["live_until"]
    assert lgp.tennis_collect_now(rows[0]["game"]["polymarket_markets"][0], True, now) is True


def test_too_early_today_twin_is_not_spawned():
    scan = Scan()
    now = lgp.now_et()
    start = now + lgp.timedelta(hours=3)
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT28LATERX",
            "slug": "aec-atp-later-today",
            "title": "Later vs Today",
            "date": now.date().isoformat(),
            "startTime": start.isoformat(),
        }],
        novig_games=[],
    )
    assert rows == []


def test_settled_match_is_not_spawned():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT28POSTXY",
            "slug": "aec-atp-settled",
            "title": "Settled vs Match",
            "date": now.date().isoformat(),
            "startTime": (now - lgp.timedelta(minutes=10)).isoformat(),
            "period": "POST",
        }],
        novig_games=[],
    )
    assert rows == []


def test_never_live_after_30min_is_not_spawned():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT28NEVERX",
            "slug": "aec-atp-never-live",
            "title": "Never vs Live",
            "date": now.date().isoformat(),
            "startTime": (now - lgp.timedelta(minutes=45)).isoformat(),
        }],
        novig_games=[],
    )
    assert rows == []


def test_in_play_after_30min_is_spawned():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT28LIVEAB",
            "slug": "aec-atp-still-live",
            "title": "Still vs Live",
            "date": now.date().isoformat(),
            "startTime": (now - lgp.timedelta(minutes=45)).isoformat(),
            "period": "S2",
            "status": "OPEN_INGAME",
        }],
        novig_games=[],
    )
    assert len(rows) == 1


def test_worker_exits_after_settle_or_tomorrow():
    now = lgp.now_et()
    tomorrow = now + lgp.timedelta(days=1)
    end = tomorrow + lgp.timedelta(hours=5)
    tomorrow_spec = {
        "sport": "tennis",
        "start": tomorrow.isoformat(),
        "listed_start": tomorrow.isoformat(),
        "game": {
            "date": tomorrow.date().isoformat(),
            "startTime": tomorrow.isoformat(),
            "kalshi": {"game": "KXATPMATCH-26OCT29ABCVYZ"},
        },
        "supervisor_pid": 0,
    }
    assert lgp._worker_should_stop(tomorrow_spec, end) is True
    settled_spec = {
        "sport": "tennis",
        "start": (now - lgp.timedelta(minutes=10)).isoformat(),
        "game": {
            "date": now.date().isoformat(),
            "startTime": (now - lgp.timedelta(minutes=10)).isoformat(),
            "period": "POST",
            "kalshi": {"game": "KXATPMATCH-26OCT28POSTXY"},
        },
        "supervisor_pid": 0,
    }
    assert lgp._worker_should_stop(settled_spec, now + lgp.timedelta(hours=5)) is True
    live_spec = {
        "sport": "tennis",
        "start": (now - lgp.timedelta(minutes=3)).isoformat(),
        "game": {
            "date": now.date().isoformat(),
            "startTime": (now - lgp.timedelta(minutes=3)).isoformat(),
            "kalshi": {"game": "KXATPMATCH-26OCT28NOWABC"},
        },
        "supervisor_pid": 0,
    }
    assert lgp._worker_should_stop(live_spec, now + lgp.timedelta(hours=5)) is False


def test_tracked_terminate_kills_adopted_pid():
    killed = []
    saved_kill = lgp.kill_pid
    saved_alive = lgp.pid_alive
    lgp.pid_alive = lambda pid: pid == 4242
    lgp.kill_pid = lambda pid: killed.append(pid)
    try:
        lgp.Tracked(4242, None).terminate()
    finally:
        lgp.kill_pid = saved_kill
        lgp.pid_alive = saved_alive
    assert killed == [4242]


def test_reap_idle_pollers_kills_keys_not_live():
    killed = []
    saved_running = lgp.running_poller_pids
    saved_kill = lgp.kill_pid
    lgp.running_poller_pids = lambda: {"tennis_tomorrow": 99, "tennis_live": 100}
    lgp.kill_pid = lambda pid: killed.append(pid)
    try:
        children = {}
        already = lgp.reap_idle_pollers(children, {"tennis_live"}, me=1)
    finally:
        lgp.running_poller_pids = saved_running
        lgp.kill_pid = saved_kill
    assert already["tennis_live"] == 100
    assert set(killed) == {99, 100}


def test_tennis_spread_siblings_keep_moneyline():
    k, g = lgp.expand_sibling_tickers(
        ["KXATPMATCH-26OCT30PAUALC"],
        [],
        "tennis",
    )
    assert k[0] == "KXATPMATCH-26OCT30PAUALC"
    assert "KXATPGSPREAD-26OCT30PAUALC" in k
    assert "KXATPSSPREAD-26OCT30PAUALC" in k
    from price_memory import market_type_from

    assert market_type_from("KXATPMATCH-26OCT30PAUALC") == "moneyline"
    assert market_type_from("KXATPGSPREAD-26OCT30PAUALC") == "spread"


def test_tennis_row_attaches_spread_ticker_and_poly_spread():
    scan = Scan()
    now = lgp.now_et()
    rows = lgp.tennis_rows(
        scan,
        matches=[{
            "event_ticker": "KXATPMATCH-26OCT30PAUALC",
            "slug": "aec-atp-tompau-caralc-2026-10-30",
            "title": "Paul vs Alcaraz",
            "date": now.date().isoformat(),
            "kind": "moneyline",
            "spread_ticker": "KXATPGSPREAD-26OCT30PAUALC",
            "spread_tickers": ["KXATPGSPREAD-26OCT30PAUALC", "KXATPSSPREAD-26OCT30PAUALC"],
            "spread_markets": [{
                "slug": "aec-atp-tompau-caralc-2026-10-30-spread-3pt5",
                "kind": "spread",
                "number": "3.5",
                "long_name": "Alcaraz",
                "short_name": "Paul",
            }],
            "startTime": (now - lgp.timedelta(minutes=10)).isoformat(),
        }],
        novig_games=[],
    )
    assert len(rows) == 1
    game = rows[0]["game"]
    assert game["kalshi"]["game"] == "KXATPMATCH-26OCT30PAUALC"
    assert game["kalshi"]["spread"] == "KXATPGSPREAD-26OCT30PAUALC"
    slugs = [row.get("slug") for row in game["polymarket_markets"]]
    assert slugs[0].startswith("aec-atp-tompau-caralc")
    assert any(row.get("kind") == "spread" for row in game["polymarket_markets"])
    k, _g = lgp.tickers_for_quotes(game, scan, "tennis")
    assert "KXATPMATCH-26OCT30PAUALC" in k
    assert "KXATPGSPREAD-26OCT30PAUALC" in k


def test_price_memory_keeps_tennis_spread_quotes():
    from decimal import Decimal

    from price_memory import quotes_from_polymarket, quotes_from_novig

    seen = lgp.now_et()
    poly = quotes_from_polymarket([{
        "kind": "spread",
        "number": "3.5",
        "long_name": "Alcaraz",
        "short_name": "Paul",
        "yes_ask": Decimal("0.31"),
        "ask_size": Decimal("1"),
        "yes_bid": Decimal("0.29"),
        "bid_size": Decimal("1"),
        "slug": "aec-spread",
    }], "tennis", "Paul vs Alcaraz", seen, {})
    assert any(row["market_type"] == "spread" and row["pay"] == "yes" for row in poly)
    novig = quotes_from_novig([{
        "kind": "spread",
        "number": "3.5",
        "side": "Alcaraz",
        "other_side": "",
        "yes_ask": Decimal("0.28"),
        "ask_size": Decimal("1"),
        "no_ask": Decimal("0.74"),
        "no_ask_size": Decimal("1"),
        "yes_outcome": "fav",
        "no_outcome": "dog",
        "market_id": "m-ten",
        "event_status": "OPEN_INGAME",
        "fee_coefficient": "0.06",
        "fee_charged": "WHEN_LIVE",
        "orders": {},
    }], "tennis", "Paul vs Alcaraz", seen, {})
    assert any(row["market_type"] == "spread" and row["pay"] == "yes" for row in novig)


def test_poly_two_way_moneyline_still_skips_spread():
    import polymarket_us_live as poly

    spread = {
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD",
        "marketType": "spread",
        "sportsMarketType": "full_game_spread",
        "line": 3.5,
        "slug": "aec-atp-spread",
        "marketSides": [
            {"long": True, "description": "Alcaraz"},
            {"long": False, "description": "Paul"},
        ],
    }
    assert poly.two_way_moneyline(spread) is None
    parsed = poly.two_way_spread(spread)
    assert parsed is not None
    assert parsed["kind"] == "spread"
    assert parsed["number"] == "3.5"


def test_supervise_reaps_idle_pollers():
    import inspect

    src = inspect.getsource(lgp.supervise)
    assert "reap_idle_pollers" in src
    assert "CREATE_NEW_CONSOLE" not in src


if __name__ == "__main__":
    test_twin_key_unchanged()
    test_kalshi_only_without_polymarket_twin()
    test_polymarket_only_without_kalshi()
    test_novig_only_dedupes_against_twin()
    test_novig_only_is_kept()
    test_football_kalshi_only_is_enough()
    test_unmatched_future_polymarket_is_not_spawned()
    test_unmatched_live_polymarket_is_spawned()
    test_identity_ignores_first_name_order()
    test_supervisor_leftover_tick_has_no_clock_cutoff()
    test_pollers_have_no_job_deadline()
    test_new_pollers_hide_windows_on_nt()
    test_pre_start_window_is_five_minutes()
    test_tomorrow_twin_is_not_spawned()
    test_in_window_twin_is_spawned()
    test_too_early_today_twin_is_not_spawned()
    test_settled_match_is_not_spawned()
    test_never_live_after_30min_is_not_spawned()
    test_in_play_after_30min_is_spawned()
    test_worker_exits_after_settle_or_tomorrow()
    test_tracked_terminate_kills_adopted_pid()
    test_reap_idle_pollers_kills_keys_not_live()
    test_tennis_spread_siblings_keep_moneyline()
    test_tennis_row_attaches_spread_ticker_and_poly_spread()
    test_price_memory_keeps_tennis_spread_quotes()
    test_poly_two_way_moneyline_still_skips_spread()
    test_supervise_reaps_idle_pollers()
    print("ok")
