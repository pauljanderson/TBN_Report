"""Leftover filled legs on job_status when orders are stopped.

Does not place orders. Does not touch the live orders_stopped.json latch.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import order_ledger
import prediction_job_control


def test_wawrinka_lists_each_filled_leftover():
    folder = Path(tempfile.mkdtemp())
    orders = folder / "orders.jsonl"
    io_path = folder / "order_io.jsonl"
    watch_path = folder / "one_leg_watch.json"
    orders.write_text(
        json.dumps({
            "event": "claim",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
            "sport": "tennis",
            "game": "Wawrinka vs Landaluce",
            "market_type": "moneyline",
            "side": "Martin Landaluce",
            "compared_at": "2026-10-21T08:59:52.613-04:00",
        }) + "\n" + json.dumps({
            "event": "sent",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
            "venue": "kalshi",
            "instrument": "KXATPMATCH-26OCT18WAWLAN-LAN",
            "side": "no",
            "limit_price": "0.3100",
            "http_status": "pending",
            "note": "request sent",
            "order_id": "",
            "sent_at": "2026-10-21T08:59:52.630-04:00",
            "attempt": 1,
        }) + "\n" + json.dumps({
            "event": "sent",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:LAN\t\tpolymarket\tkalshi",
            "venue": "polymarket",
            "instrument": "aec-atp-stawaw-marlan-2026-10-18",
            "side": "no",
            "limit_price": "0.750",
            "http_status": 200,
            "note": "no message",
            "order_id": "D7XH7B9010JB",
            "sent_at": "2026-10-21T08:59:52.630-04:00",
            "attempt": 1,
        }) + "\n" + json.dumps({
            "event": "claim",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:WAW\t\tpolymarket\tkalshi",
            "sport": "tennis",
            "game": "Wawrinka vs Landaluce",
            "market_type": "moneyline",
            "side": "Stan Wawrinka",
            "compared_at": "2026-10-21T09:30:44.905-04:00",
        }) + "\n" + json.dumps({
            "event": "sent",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:WAW\t\tpolymarket\tkalshi",
            "venue": "kalshi",
            "instrument": "KXATPMATCH-26OCT18WAWLAN-WAW",
            "side": "no",
            "limit_price": "0.7600",
            "http_status": 201,
            "order_id": "01a15ea8-2fb8-7465-b90a-41d908aa2aed",
            "sent_at": "2026-10-21T09:30:44.919-04:00",
            "attempt": 1,
        }) + "\n" + json.dumps({
            "event": "sent",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:WAW\t\tpolymarket\tkalshi",
            "venue": "polymarket",
            "instrument": "aec-atp-stawaw-marlan-2026-10-18",
            "side": "yes",
            "limit_price": "0.700",
            "http_status": 200,
            "order_id": "D7XZBDNG10JE",
            "sent_at": "2026-10-21T09:30:44.919-04:00",
            "attempt": 1,
        }) + "\n" + json.dumps({
            "event": "filled",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:WAW\t\tpolymarket\tkalshi",
            "venue": "polymarket",
            "instrument": "aec-atp-stawaw-marlan-2026-10-18",
            "side": "yes",
            "size": "1",
            "price": "0.7000",
        }) + "\n" + json.dumps({
            "event": "one_leg",
            "bet_key": "tennis\twawlan\t2026-10-18\tmoneyline\tcode:WAW\t\tpolymarket\tkalshi",
            "venue": "polymarket",
            "instrument": "aec-atp-stawaw-marlan-2026-10-18",
            "side": "yes",
            "size": "1",
            "price": "0.7000",
            "second_venue": "kalshi",
            "second_http": 0,
        }) + "\n",
        encoding="utf-8",
    )
    io_path.write_text(
        json.dumps({
            "timestamp": "2026-10-21T08:59:52-04:00",
            "venue": "kalshi",
            "kind": "order",
            "request": {"ticker": "KXATPMATCH-26OCT18WAWLAN-LAN", "side": "ask", "price": "0.3100"},
            "http_status": 201,
            "response": {
                "average_fee_paid": "0.0158",
                "average_fill_price": "0.3400",
                "fill_count": "1.00",
                "order_id": "01a15e8b-ed58-7562-84a7-9115332799fa",
                "remaining_count": "0.00",
            },
        }) + "\n" + json.dumps({
            "timestamp": "2026-10-21T08:59:53-04:00",
            "venue": "polymarket",
            "kind": "order",
            "request": {"marketSlug": "aec-atp-stawaw-marlan-2026-10-18", "intent": "ORDER_INTENT_BUY_SHORT"},
            "http_status": 200,
            "response": {
                "id": "D7XH7B9010JB",
                "executions": [{"lastShares": "0.0000", "order": {"state": "ORDER_STATE_EXPIRED", "cumQuantity": 0}}],
            },
        }) + "\n" + json.dumps({
            "timestamp": "2026-10-21T09:30:45-04:00",
            "venue": "kalshi",
            "kind": "order",
            "request": {"ticker": "KXATPMATCH-26OCT18WAWLAN-WAW", "side": "ask", "price": "0.7600"},
            "http_status": 201,
            "response": {
                "fill_count": "0.00",
                "order_id": "01a15ea8-2fb8-7465-b90a-41d908aa2aed",
                "remaining_count": "0.00",
            },
        }) + "\n",
        encoding="utf-8",
    )
    watch_path.write_text(
        json.dumps({
            "sport": "tennis",
            "game": "Wawrinka vs Landaluce",
            "claim_side": "Stan Wawrinka",
            "filled_venue": "polymarket",
            "filled_instrument": "aec-atp-stawaw-marlan-2026-10-18",
            "filled_side": "yes",
            "fill_px": "0.700",
            "started_at": "2026-10-21T09:31:02.556-04:00",
            "stopped": True,
        }),
        encoding="utf-8",
    )
    saved_orders = order_ledger.ORDERS, order_ledger.ORDER_IO
    saved_watch = prediction_job_control.ONE_LEG_WATCH
    order_ledger.ORDERS = orders
    order_ledger.ORDER_IO = io_path
    prediction_job_control.ONE_LEG_WATCH = watch_path
    try:
        watch = prediction_job_control._load_watch(watch_path)
        legs = prediction_job_control.leftover_filled_legs(
            True, "2026-10-21T09:31:25-04:00", watch=watch
        )
        html = prediction_job_control._filled_legs_html({
            "latch_on": True,
            "latch_text": "set - one leg filled and the other missed - 2026-10-21T09:31:25-04:00",
            "filled_legs": legs,
        })
    finally:
        order_ledger.ORDERS, order_ledger.ORDER_IO = saved_orders
        prediction_job_control.ONE_LEG_WATCH = saved_watch
    assert len(legs) == 2, legs
    kalshi = next(row for row in legs if row["venue"] == "kalshi")
    poly = next(row for row in legs if row["venue"] == "polymarket")
    assert kalshi["sport"] == "tennis"
    assert kalshi["game"] == "Wawrinka vs Landaluce"
    assert kalshi["bet"] == "No Martin Landaluce"
    assert kalshi["fill"] == "$0.66"
    assert kalshi["time_et"].startswith("2026-10-21 08:59")
    assert poly["bet"] == "Yes Stan Wawrinka"
    assert poly["fill"] == "$0.70"
    assert poly["time_et"].startswith("2026-10-21 09:30")
    assert "No Martin Landaluce" in html
    assert "Yes Stan Wawrinka" in html
    assert "What you asked" not in html
    assert "In plain English" not in html
    assert prediction_job_control.leftover_filled_legs(False) == []


def test_leftover_watch_unwraps_watches_list():
    wrapper = {
        "watches": [
            {
                "game": "Goffin vs Opponent",
                "filled_venue": "kalshi",
                "filled_side": "yes",
                "started_at": "2026-10-21T16:00:00-04:00",
                "stopped": False,
            },
            {
                "game": "Wawrinka vs Landaluce",
                "filled_venue": "polymarket",
                "filled_side": "yes",
                "started_at": "2026-10-21T16:05:00-04:00",
                "stopped": False,
            },
        ]
    }
    text = prediction_job_control.leftover_watch_text(wrapper)
    assert "unknown game" not in text, text
    assert "Goffin vs Opponent" in text
    assert "Wawrinka vs Landaluce" in text
    dummy_top = {
        "game": "",
        "bet_key": "wrapper",
        "filled_venue": "",
        "watches": wrapper["watches"],
    }
    text2 = prediction_job_control.leftover_watch_text(dummy_top)
    assert "unknown game" not in text2, text2
    assert "Goffin vs Opponent" in text2
    legs = prediction_job_control.leftover_filled_legs(True, "2026-10-21T16:10:00-04:00", watch=wrapper)
    games = {row.get("game") for row in legs}
    assert "Goffin vs Opponent" in games or "Wawrinka vs Landaluce" in games


def test_strategy_b_status_html_has_no_ask_block():
    html = prediction_job_control._strategy_b_html(
        {
            "strategy_b": {"pid": 1, "started": "2026-10-21 16:00:00"},
            "strategy_b_extra": [],
            "strategy_b_log": "strategy b start",
            "strategy_b_state": {
                "enabled": True,
                "max_open_b_matches": 1,
                "currently_open": 1,
                "cluster_15m": 2,
                "cluster_60m": 5,
                "cluster_note": "2 tennis start(s) in the next 15 minutes",
                "updated_at": "2026-10-21T16:00:00-04:00",
                "matches": [
                    {
                        "game": "Smith vs Purcell",
                        "venue": "kalshi",
                        "stage": "t0_filled_waiting_50_cross",
                        "fav_target": "",
                        "t0_yes": {
                            "a": {"player": "Smith", "price": "0.34", "filled": True},
                            "b": {"player": "Purcell", "price": "0.67", "filled": True},
                        },
                        "last_order": {
                            "id": "abc",
                            "time": "2026-10-21T16:01:00-04:00",
                            "http": 201,
                            "fill_qty": "1",
                        },
                        "last_quotes": {"Smith": {"ask": "0.52"}},
                    }
                ],
            },
        }
    )
    assert "What you asked" not in html
    assert "In plain English" not in html
    assert "Tennis crossover" in html
    assert "max_open_b_matches" in html
    assert "Smith vs Purcell" in html
    assert "T0 filled waiting 50-cross" in html
    assert 'class="sortable"' in html
    assert "Tennis starts next 15 minutes" in html


def test_last_skip_text_uses_live_send_line():
    folder = Path(tempfile.mkdtemp())
    path = folder / "lock_last_skip.json"
    path.write_text(
        json.dumps({
            "event": "skip",
            "reason": "net 0.97 is above 0.95",
            "game": "Some Game",
            "at": "2026-10-21T20:00:00-04:00",
        }),
        encoding="utf-8",
    )
    import live_lock_orders

    text = prediction_job_control.last_skip_text(path)
    line = live_lock_orders.send_line()
    # 0.97 is at or under live NET_MAX, so rewrite_send_line_copy must not
    # claim it is above the send line.
    assert "net 0.97 is above 0.95" in text
    assert f"net 0.97 is above {line}" not in text
    assert prediction_job_control._send_line_text() == line
    hair_path = folder / "lock_last_skip_hair.json"
    hair_path.write_text(
        json.dumps({
            "event": "skip",
            "reason": "net 0.99001 is above 0.97",
            "game": "Some Game",
            "at": "2026-10-21T20:00:00-04:00",
        }),
        encoding="utf-8",
    )
    hair_text = prediction_job_control.last_skip_text(hair_path)
    assert "0.99001" in hair_text
    assert f"net 0.99001 is above {line}" in hair_text


def test_systems_open_now_is_count_not_fraction():
    html = prediction_job_control._systems_html(
        {
            "systems": [
                {
                    "letter": "A",
                    "name": "Lock gap",
                    "on": "on",
                    "stake": "1",
                    "size": "1",
                    "max_open": "3",
                    "open": "0 / 3",
                    "pid": "1",
                    "last": "-",
                },
                {
                    "letter": "B",
                    "name": "Tennis crossover",
                    "on": "on",
                    "stake": "1",
                    "size": "1",
                    "max_open": "4",
                    "open": "2",
                    "pid": "2",
                    "last": "-",
                },
            ]
        }
    )
    import re

    row_a = re.search(r"<tr><td>A</td>.*?</tr>", html)
    assert row_a, html
    cells = re.findall(r"<td>(.*?)</td>", row_a.group(0))
    assert cells[5] == "3"
    assert cells[6] == "0"
    assert "0/3" not in cells[6]
    assert "0 / 3" not in cells[6]
    assert prediction_job_control._open_now_cell("0/3") == "0"
    assert prediction_job_control._open_now_cell("0 / 3") == "0"
    assert prediction_job_control._open_now_cell("2") == "2"


def test_systems_html_documents_lock_net_max():
    html = prediction_job_control._systems_html({"systems": []})
    line = prediction_job_control._send_line_text()
    assert f"--lock-net-max {line}" in html
    assert "--lock-gap" in html
    assert "--lock on --lock-max 3 --lock-stake 1" in html
    assert "does not change the send cap" in html
    assert f"A send cap is <strong>{line}</strong>" in html


def test_status_page_shows_updated_stamp_at_top():
    folder = Path(tempfile.mkdtemp())
    saved = prediction_job_control.STATUS_PAGE
    prediction_job_control.STATUS_PAGE = folder / "job_status.html"
    snap = {
        "supervisor": None,
        "scan": None,
        "children": [],
        "intended": [],
        "poller_compare": [],
        "consoles": {},
        "strategy_b": None,
        "strategy_b_extra": [],
        "strategy_b_log": "",
        "strategy_b_state": {},
        "latch_on": False,
        "latch_text": "not set",
        "watch_text": "no file",
        "send_line": "0.97",
        "lock_open": "0",
        "last_skip_text": "none",
        "filled_legs": [],
        "supervisor_log": "",
        "scan_log": "",
        "deadline_text": "The 8 AM collection deadline is gone. Paul's bats start/stop. Max open locks 3 / Strategy B matches 2 remain the cap.",
        "checked": "2026-10-22 12:12:00 ET",
    }
    try:
        prediction_job_control.write_page(snap)
        page = prediction_job_control.STATUS_PAGE.read_text(encoding="utf-8")
    finally:
        prediction_job_control.STATUS_PAGE = saved
    stamp = "Updated 2026-10-22 12:12:00 ET"
    h1 = page.index("<h1>Prediction job status</h1>")
    stamp_at = page.index(stamp)
    table_at = page.index('<table class="status">')
    assert stamp_at > h1
    assert stamp_at < table_at
    assert "(Eastern Time)" in page[stamp_at : stamp_at + 80]
    assert ">Checked</th>" in page
    assert page.count("2026-10-22 12:12:00 ET") >= 2
    assert "<h2>HTTP budget</h2>" in page
    assert "Kalshi" in page
    assert "In-flight / cap" in page
    assert "Skipped ticks" in page
    assert ">HTTP budget</th>" in page
    assert "What you asked" not in page
    assert "In plain English" not in page
    assert "<h2>What to double-click</h2>" in page
    assert "run_prediction_start.bat" in page
    assert "run_prediction_restart.bat" in page


def test_start_not_blocked_by_old_collection_clock():
    friday = datetime(2026, 10, 23, 8, 0, 0, tzinfo=prediction_job_control.ET)
    ok, note = prediction_job_control.deadline_ok(friday)
    assert ok is True
    assert "Refusing" not in note
    assert "8 AM collection deadline is gone" in note
    assert "Paul's bats start/stop" in note
    assert not hasattr(prediction_job_control, "DEADLINE_STAMP")
    assert not hasattr(prediction_job_control, "ensure_deadline_for_start")
    assert not hasattr(prediction_job_control, "extend_deadline_until_future")
    assert not hasattr(prediction_job_control, "live_deadline")


def test_start_after_friday_8am_still_spawns():
    spawned = []
    saved_spawn = prediction_job_control._spawn
    prediction_job_control._spawn = lambda *a, **k: spawned.append((a, k))
    try:
        code = prediction_job_control.start_missing(
            {
                "supervisor": [],
                "scan": [],
                "children": [],
                "strategy_b": [],
            }
        )
    finally:
        prediction_job_control._spawn = saved_spawn
    assert code == 0
    assert len(spawned) >= 3


def test_status_page_says_bats_control_start():
    folder = Path(tempfile.mkdtemp())
    saved = prediction_job_control.STATUS_PAGE
    prediction_job_control.STATUS_PAGE = folder / "job_status.html"
    snap = {
        "supervisor": None,
        "scan": None,
        "children": [],
        "intended": [],
        "poller_compare": [],
        "consoles": {},
        "strategy_b": None,
        "strategy_b_extra": [],
        "strategy_b_log": "",
        "strategy_b_state": {},
        "latch_on": False,
        "latch_text": "not set",
        "watch_text": "no file",
        "send_line": "0.97",
        "lock_open": "0",
        "last_skip_text": "none",
        "filled_legs": [],
        "supervisor_log": "",
        "scan_log": "",
        "deadline_text": "The 8 AM collection deadline is gone. Paul's bats start/stop. Max open locks 3 / Strategy B matches 2 remain the cap.",
        "checked": "2026-10-22 23:30:00 ET",
    }
    try:
        prediction_job_control.write_page(snap)
        page = prediction_job_control.STATUS_PAGE.read_text(encoding="utf-8")
    finally:
        prediction_job_control.STATUS_PAGE = saved
    assert "8 AM collection deadline is gone" in page
    assert "bats start/stop" in page
    assert "Max open locks 3" in page
    assert "Strategy B matches 2" in page
    assert "Updated 2026-10-22 23:30:00 ET" in page
    assert ">Checked</th>" in page
    assert "adds 12 hours" not in page
    assert "live_deadline.json" not in page
    assert "8:00 AM ET on 2026-10-23" not in page
    assert "What you asked" not in page
    assert "In plain English" not in page
    assert "<h2>What to double-click</h2>" in page


def test_overnight_scan_has_no_collection_deadline():
    text = prediction_job_control.SCAN_SCRIPT.read_text(encoding="utf-8")
    assert "DEADLINE = None" in text
    assert "datetime(2026, 10, 22, 8, 0, 0" not in text
    assert "datetime(2026, 10, 23, 8, 0, 0" not in text
    assert "def keep_running()" in text
    assert "timedelta(hours=12)" not in text


def test_spawn_always_hides_console():
    called = []

    class Fake:
        pass

    def fake_popen(*args, **kwargs):
        called.append((args, kwargs))
        return Fake()

    saved = prediction_job_control.win_hidden.popen
    prediction_job_control.win_hidden.popen = fake_popen
    folder = Path(tempfile.mkdtemp())
    log_path = folder / "console.log"
    try:
        prediction_job_control._spawn(folder / "job.py", log_path)
    finally:
        prediction_job_control.win_hidden.popen = saved
    assert called
    kwargs = called[0][1]
    assert kwargs.get("new_group") is True
    assert kwargs.get("stdout") is not None


def test_reload_one_lock_supervisor_leaves_b_c_d_e():
    stopped = []
    started = []
    live = {
        "supervisor": [{"pid": 11}],
        "children": [{"pid": 22}],
        "scan": [{"pid": 33}],
        "strategy_b": [{"pid": 44}],
        "cfb_favorite": [{"pid": 55}],
        "spread_t0": [{"pid": 66}],
        "tennis_t0_dog": [{"pid": 77}],
    }

    def fake_classify(_rows=None):
        if stopped:
            return {
                "supervisor": [],
                "children": [],
                "scan": [{"pid": 33}],
                "strategy_b": [{"pid": 44}],
                "cfb_favorite": [{"pid": 55}],
                "spread_t0": [{"pid": 66}],
                "tennis_t0_dog": [{"pid": 77}],
            }
        return live

    saved = (
        prediction_job_control.classify,
        prediction_job_control._ps_rows,
        prediction_job_control._stop_pids,
        prediction_job_control.start_missing,
    )
    prediction_job_control.classify = fake_classify
    prediction_job_control._ps_rows = lambda: []
    prediction_job_control._stop_pids = lambda pids: stopped.extend(pids)
    prediction_job_control.start_missing = lambda jobs=None: started.append(jobs) or 0
    saved_sleep = prediction_job_control.time.sleep
    prediction_job_control.time.sleep = lambda *_a, **_k: None
    try:
        info = prediction_job_control.reload_one_lock_supervisor()
    finally:
        (
            prediction_job_control.classify,
            prediction_job_control._ps_rows,
            prediction_job_control._stop_pids,
            prediction_job_control.start_missing,
        ) = saved
        prediction_job_control.time.sleep = saved_sleep
    assert set(stopped) == {11, 22}
    for pid in (33, 44, 55, 66, 77):
        assert pid not in stopped
    assert started and started[0]["strategy_b"][0]["pid"] == 44
    assert info["strategy_b"] == [44]
    assert info["scan"] == [33]
    assert info["tennis_t0_dog"] == [77]


def test_restart_lock_leaves_strategy_b():
    stopped = []
    started = []
    live = {
        "supervisor": [{"pid": 11}],
        "children": [{"pid": 22}],
        "scan": [{"pid": 33}],
        "strategy_b": [{"pid": 44}],
    }

    def fake_classify(_rows):
        if stopped:
            return {
                "supervisor": [],
                "children": [],
                "scan": [],
                "strategy_b": [{"pid": 44}],
            }
        return live

    saved = (
        prediction_job_control.classify,
        prediction_job_control._ps_rows,
        prediction_job_control._stop_pids,
        prediction_job_control.start_missing,
    )
    prediction_job_control.classify = fake_classify
    prediction_job_control._ps_rows = lambda: []
    prediction_job_control._stop_pids = lambda pids: stopped.extend(pids)
    prediction_job_control.start_missing = lambda jobs=None: started.append(jobs) or 0
    try:
        code = prediction_job_control.restart_lock()
    finally:
        (
            prediction_job_control.classify,
            prediction_job_control._ps_rows,
            prediction_job_control._stop_pids,
            prediction_job_control.start_missing,
        ) = saved
    assert code == 0
    assert 44 not in stopped
    assert set(stopped) == {11, 22, 33}
    assert started and started[0]["strategy_b"][0]["pid"] == 44


def test_poller_pid_compare_flags_missing_and_extra():
    intended = [
        {"key": "tennis_abc_2026_10_21", "pid": 11, "sport": "tennis", "game": "A vs B"},
        {"key": "tennis_def_2026_10_21", "pid": 22, "sport": "tennis", "game": "D vs E"},
    ]
    children = [
        {
            "pid": 11,
            "parent": 1,
            "started": "2026-10-21 11:36:02",
            "cmd": "python -u tools/live_game_pollers.py --poll-one tennis_abc_2026_10_21",
        },
        {
            "pid": 99,
            "parent": 1,
            "started": "2026-10-21 11:36:03",
            "cmd": "python -u tools/live_game_pollers.py --poll-one tennis_xyz_2026_10_21",
        },
    ]
    rows = prediction_job_control.poller_pid_compare(intended, children)
    by_key = {row["key"]: row for row in rows}
    assert by_key["tennis_abc_2026_10_21"]["status"] == "match"
    assert by_key["tennis_def_2026_10_21"]["status"] == "missing process"
    assert by_key["tennis_xyz_2026_10_21"]["status"] == "extra process"
    html = prediction_job_control._poller_compare_html({"poller_compare": rows})
    assert "Intended vs actual python poller PIDs" in html
    assert "class=\"sortable\"" in html
    assert "tennis_abc_2026_10_21" in html


def test_d_on_except_nfl_caption():
    src = Path(prediction_job_control.__file__).read_text(encoding="utf-8")
    assert "D on except NFL" in src
    assert "d_skip_nfl_gathering" in src
    html = prediction_job_control._systems_html({"systems": []})
    assert "D on except NFL" in html
    nfl = prediction_job_control._nfl_catalog_html({"children": []})
    assert "D on except NFL" in nfl
    assert "d_skip_nfl_gathering" in nfl


if __name__ == "__main__":
    test_d_on_except_nfl_caption()
    test_wawrinka_lists_each_filled_leftover()
    test_leftover_watch_unwraps_watches_list()
    test_strategy_b_status_html_has_no_ask_block()
    test_last_skip_text_uses_live_send_line()
    test_systems_open_now_is_count_not_fraction()
    test_systems_html_documents_lock_net_max()
    test_status_page_shows_updated_stamp_at_top()
    test_start_not_blocked_by_old_collection_clock()
    test_start_after_friday_8am_still_spawns()
    test_status_page_says_bats_control_start()
    test_overnight_scan_has_no_collection_deadline()
    test_poller_pid_compare_flags_missing_and_extra()
    test_spawn_always_hides_console()
    test_restart_lock_leaves_strategy_b()
    test_reload_one_lock_supervisor_leaves_b_c_d_e()
    print("ok")
