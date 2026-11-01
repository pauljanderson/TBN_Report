"""Merged tennis poller: one process, four sockets, A lifted. No orders."""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers as lgp
import live_quote_mux
import price_memory
from test_live_game_pollers import Scan

ET = ZoneInfo("America/New_York")


def test_four_socket_hosts():
    hosts = live_quote_mux.socket_host_list()
    assert len(hosts) == 4
    assert len(set(hosts)) == 4
    assert live_quote_mux.WS_HOSTS["kalshi"] == "external-api-ws.kalshi.com"
    assert live_quote_mux.WS_HOSTS["gemini"] == "ws.gemini.com"
    assert live_quote_mux.WS_HOSTS["polymarket"] == "api.polymarket.us"
    assert live_quote_mux.WS_HOSTS["novig"] == "api.novig.com"


def test_one_process_many_games_subscribe_unsubscribe():
    mux = live_quote_mux.SharedStreams(lambda *_a, **_k: None, lambda _m: None)
    cmds1 = mux.plan_set_game("tennis_a", kalshi={"KA": {"ticker": "KA"}}, gemini={"GA": {"s": "GA"}})
    cmds2 = mux.plan_set_game("tennis_b", kalshi={"KB": {"ticker": "KB"}}, polymarket={"slug-b": {"slug": "slug-b"}})
    assert set(mux.kalshi) == {"KA", "KB"}
    assert mux.games_for("kalshi", "KA") == {"tennis_a"}
    assert mux.games_for("kalshi", "KB") == {"tennis_b"}
    assert any(venue == "kalshi" and op == "subscribe" and "KA" in ids for venue, op, ids in cmds1)
    assert any(venue == "kalshi" and op == "subscribe" and "KB" in ids for venue, op, ids in cmds2)
    drop = mux.plan_drop_game("tennis_a")
    assert "KA" not in mux.kalshi
    assert "KB" in mux.kalshi
    assert any(venue == "kalshi" and op == "unsubscribe" and "KA" in ids for venue, op, ids in drop)
    assert mux.by_game.keys() == {"tennis_b"}


def test_tomorrow_not_subscribed():
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
    mux = live_quote_mux.SharedStreams(lambda *_a, **_k: None, lambda _m: None)
    for row in rows:
        mux.plan_set_game(row["key"], kalshi={"KXATPMATCH-26OCT29ABCVYZ": {}})
    assert mux.kalshi == {}
    assert mux.by_game == {}


def test_live_window_still_five_minutes():
    assert lgp.TENNIS_PRE_START_MIN == 5
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
    mux = live_quote_mux.SharedStreams(lambda *_a, **_k: None, lambda _m: None)
    mux.plan_set_game(rows[0]["key"], kalshi={"KXATPMATCH-26OCT28NOWABC": {}})
    assert "KXATPMATCH-26OCT28NOWABC" in mux.kalshi


def test_a_send_not_imported_into_poller():
    mux_src = (ROOT / "tools" / "live_quote_mux.py").read_text(encoding="utf-8")
    assert "import live_lock_orders" not in mux_src
    assert "execute_locks" not in mux_src
    poll_src = inspect.getsource(lgp.poll_all)
    after_src = inspect.getsource(lgp._after_quotes)
    assert "execute_locks" not in poll_src
    assert "execute_locks" not in after_src
    assert "live_lock_orders" not in poll_src
    sender = (ROOT / "tools" / "live_lock_sender.py").read_text(encoding="utf-8")
    assert "execute_locks" in sender
    assert "live_lock_orders" in sender


def test_no_poll_one_spawn_for_tennis():
    merged = " ".join(lgp.command_for_merged())
    assert "--poll-all" in merged
    assert "--poll-one" not in merged
    src = inspect.getsource(lgp.supervise)
    assert "spawn_merged" in src
    assert "spawn_lock_sender" in src
    assert "spawn(row" not in src
    assert "--poll-all" in inspect.getsource(lgp.spawn_merged) or "--poll-all" in inspect.getsource(lgp.command_for_merged)


def test_b_can_read_price_poller_wrote():
    folder = Path(tempfile.mkdtemp(prefix="pm_b_read_"))
    saved = {
        "RAW": price_memory.RAW,
        "LAST": price_memory.LAST,
        "LAST_DIR": price_memory.LAST_DIR,
        "HISTORY_DIR": price_memory.HISTORY_DIR,
        "CSV_DIR": price_memory.CSV_DIR,
        "HISTORY": price_memory.HISTORY,
        "cache": dict(price_memory._legacy_last_cache),
    }
    price_memory.RAW = folder
    price_memory.LAST = folder / "price_last.json"
    price_memory.LAST_DIR = folder / "price_last_games"
    price_memory.HISTORY_DIR = folder / "price_memory"
    price_memory.CSV_DIR = folder / "price_memory" / "csv"
    price_memory.HISTORY = folder / "price_memory.jsonl"
    price_memory._legacy_last_cache["mtime"] = None
    price_memory._legacy_last_cache["data"] = None
    seen = datetime(2026, 10, 28, 16, 40, 0, tzinfo=ET)
    game = "Poller vs Reader"
    canned = [price_memory.quote_row(
        "tennis", game, "moneyline", "Poller", "", "Polymarket", "yes",
        Decimal("0.42"), seen, None,
    )]
    try:
        with patch.object(price_memory, "quotes_from_book", return_value=[]):
            with patch.object(price_memory, "quotes_from_polymarket", return_value=canned):
                with patch.object(price_memory, "quotes_from_novig", return_value=[]):
                    n = price_memory.remember_books(
                        "tennis", game, seen, polymarket_contracts=[{"slug": "x"}],
                    )
        assert n >= 1
        last = price_memory.load_last_game("tennis", game)
        assert last
        sport_last = price_memory.load_last_sport("tennis")
        recs = [row for row in sport_last.values() if isinstance(row, dict)]
        assert recs
        assert any(str(row.get("price") or "").startswith("0.42") for row in recs)
        assert not price_memory.LAST.exists() or price_memory.LAST.stat().st_size < 1_000_000
        path = price_memory.game_last_path("tennis", game)
        assert path.is_file()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload
    finally:
        price_memory.RAW = saved["RAW"]
        price_memory.LAST = saved["LAST"]
        price_memory.LAST_DIR = saved["LAST_DIR"]
        price_memory.HISTORY_DIR = saved["HISTORY_DIR"]
        price_memory.CSV_DIR = saved["CSV_DIR"]
        price_memory.HISTORY = saved["HISTORY"]
        price_memory._legacy_last_cache.clear()
        price_memory._legacy_last_cache.update(saved["cache"])


def test_classify_poll_all_is_not_supervisor():
    import prediction_job_control as jc

    rows = [
        {"pid": 1, "parent": 0, "started": "", "cmd": "python -u tools/live_game_pollers.py"},
        {"pid": 2, "parent": 1, "started": "", "cmd": "python -u tools/live_game_pollers.py --poll-all"},
        {"pid": 3, "parent": 1, "started": "", "cmd": "python -u tools/live_lock_sender.py"},
        {"pid": 4, "parent": 1, "started": "", "cmd": "python -u tools/live_game_pollers.py --poll-one tennis_x"},
        {"pid": 5, "parent": 0, "started": "", "cmd": "python -u tools/live_strategy_b.py"},
    ]
    jobs = jc.classify(rows)
    assert [r["pid"] for r in jobs["supervisor"]] == [1]
    assert [r["pid"] for r in jobs["poll_all"]] == [2]
    assert [r["pid"] for r in jobs["lock_sender"]] == [3]
    assert [r["pid"] for r in jobs["children"]] == [4]
    assert [r["pid"] for r in jobs["strategy_b"]] == [5]


if __name__ == "__main__":
    test_four_socket_hosts()
    test_one_process_many_games_subscribe_unsubscribe()
    test_tomorrow_not_subscribed()
    test_live_window_still_five_minutes()
    test_a_send_not_imported_into_poller()
    test_no_poll_one_spawn_for_tennis()
    test_b_can_read_price_poller_wrote()
    test_classify_poll_all_is_not_supervisor()
    print("ok")
