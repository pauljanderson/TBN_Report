"""Strategy B D=25 helpers. Does not place orders. Does not touch orders_stopped.json."""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from unittest.mock import patch

import live_lock_orders
import live_strategy_b
import live_t0_yes
import novig_live
import orders_performance_refresh
import polymarket_us_live
import venue_fill_confirm

orders_performance_refresh.run_rebuild = lambda: ""

ET = ZoneInfo("America/New_York")
_TAPE: list[dict] = []


def _stub_tape(row):
    _TAPE.append(dict(row))


live_lock_orders.record_research_row = _stub_tape


def test_extra_pair_stays_25c_lock():
    spec = {"venue": "kalshi", "instrument": "KX-TEST", "outcome": "yes"}
    zero = {"venue": "", "instrument": "X", "outcome": "yes"}
    assert live_strategy_b.extra_pair_net_ok(
        Decimal("0.52"), Decimal("0"), Decimal("0.22"), zero
    )
    assert not live_strategy_b.extra_pair_net_ok(
        Decimal("0.52"), Decimal("0"), Decimal("0.24"), zero
    )
    assert live_strategy_b.fav_target(Decimal("0.52")) == Decimal("0.23")
    assert live_strategy_b.fav_target(Decimal("0.60")) == Decimal("0.15")
    # Documented Kalshi taker fee on the 0.23 target already exceeds 1 − D.
    assert not live_strategy_b.extra_pair_net_ok(
        Decimal("0.52"), Decimal("0"), Decimal("0.23"), spec
    )


def test_clockless_t0_not_fired_live():
    now = datetime(2026, 10, 21, 16, 37, tzinfo=ET)
    pair = {
        "t0_a": 0.40,
        "t0_b": 0.61,
        "t0_ts": int(now.timestamp()),
        "actual_start": "",
        "t0_label": "first competitive two-sided Yes",
        "yes_a": [(int(now.timestamp()) - i, 0.40) for i in range(4)],
        "yes_b": [(int(now.timestamp()) - i, 0.61) for i in range(4)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False
    assert "trusted clock" in why


def test_t0_misses_stale_trusted_start():
    now = datetime(2026, 10, 21, 16, 35, tzinfo=ET)
    start = datetime(2026, 10, 21, 15, 10, tzinfo=ET)
    pair = {
        "t0_a": 0.35,
        "t0_b": 0.66,
        "t0_ts": int(now.timestamp()),
        "actual_start": start.isoformat(),
        "t0_label": "mixed pre-start + first in-game (occurrence)",
        "yes_a": [(int(now.timestamp()), 0.35)],
        "yes_b": [(int(now.timestamp()), 0.66)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False
    assert "missed T0 window" in why


def test_t0_waits_for_trusted_start():
    now = datetime(2026, 10, 21, 16, 0, tzinfo=ET)
    pair = {
        "t0_a": 0.36,
        "t0_b": 0.65,
        "t0_ts": int(now.timestamp()),
        "actual_start": (now + timedelta(minutes=10)).isoformat(),
        "t0_label": "last two-sided Yes <= occurrence",
        "yes_a": [(int(now.timestamp()), 0.36)],
        "yes_b": [(int(now.timestamp()), 0.65)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False
    assert "waiting trusted actual start" in why


def test_c_band_and_yes_band():
    assert live_strategy_b.C_HI == Decimal("1.05")
    assert live_strategy_b.T0_C_OVER_SKIP == "t0_allin_c_over_105"
    assert live_strategy_b.CROSS_ALLIN_OVER == "cross_allin_c_over_105"
    assert live_strategy_b.in_c_band(Decimal("1.05"))
    assert live_strategy_b.in_c_band(Decimal("1.02"))
    assert live_strategy_b.in_c_band(Decimal("0.90"))
    assert live_strategy_b.in_c_band(Decimal("0.94"))
    assert live_strategy_b.in_c_band(Decimal("0.99"))
    assert not live_strategy_b.in_c_band(Decimal("1.06"))
    assert not live_strategy_b.in_c_band(Decimal("1.21"))
    assert live_strategy_b.in_yes_band(Decimal("0.36"))
    assert not live_strategy_b.in_yes_band(Decimal("0.10"))
    assert live_strategy_b.is_absorbing(Decimal("0.05"))
    assert live_strategy_b.is_absorbing(Decimal("0.95"))
    assert live_strategy_b.should_stack_t0(Decimal("0.99"))
    assert not live_strategy_b.should_stack_t0(Decimal("1.00"))
    assert not live_strategy_b.should_stack_t0(Decimal("1.01"))


def test_one_leg_miss_is_missed_yes_not_opponent_no():
    saved = live_strategy_b._phone_b_note
    live_strategy_b._phone_b_note = lambda *args, **kwargs: None
    match = {
        "key": "tennis_goffin",
        "game": "Goffin vs Opponent",
        "venue": "kalshi",
        "fav_player": "Favorite",
        "dog_player": "Goffin",
        "t0_yes": {
            "a": {"player": "Goffin", "price": "0.36", "filled": False, "instrument": "A"},
            "b": {"player": "Favorite", "price": "0.65", "filled": False, "instrument": "B"},
        },
    }
    results = {
        "a": {
            "filled": True,
            "pay": "0.36",
            "fill_px": "0.36",
            "fill_fee": "0",
            "fill_qty": "1",
            "status": 201,
            "order_id": "1",
            "sent_at": "2026-10-21T16:00:00-04:00",
            "note": "",
        },
        "b": {
            "filled": False,
            "pay": "0.65",
            "fill_qty": "0",
            "status": 200,
            "order_id": "",
            "sent_at": "2026-10-21T16:00:00-04:00",
            "note": "ioc miss",
        },
    }
    saved_flat = live_strategy_b.flatten_t0_leg
    live_strategy_b.flatten_t0_leg = lambda *_a, **_k: {"filled": False, "note": "flatten miss"}
    try:
        live_strategy_b.mark_t0_results(match, results)
        assert match["stage"] == "one_leg_miss"
        assert match["one_leg_miss"] == "Favorite"
        assert "opponent No" in match["note"] or "Goffin" in match["note"]
        assert "Yes" in match["note"]
    finally:
        live_strategy_b._phone_b_note = saved
        live_strategy_b.flatten_t0_leg = saved_flat


def test_lock_bot_skip_reads_b_state_file():
    folder = Path(tempfile.mkdtemp())
    path = folder / "strategy_b_watch.json"
    path.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "game": "Smith vs Purcell",
                        "stage": "t0_filled_waiting_50_cross",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    saved = live_lock_orders.STRATEGY_B_STATE
    live_lock_orders.STRATEGY_B_STATE = path
    try:
        assert live_lock_orders.strategy_b_blocks_lock("tennis", "Smith vs Purcell") is True
        assert live_lock_orders.strategy_b_blocks_lock("tennis", "Other vs Match") is False
        assert live_lock_orders.strategy_b_blocks_lock("pro football", "Smith vs Purcell") is False
    finally:
        live_lock_orders.STRATEGY_B_STATE = saved


def test_lock_bot_skip_absorbed_b():
    """Absorbed still holds T0 both-Yes; lock must not hunt the same title."""
    assert "absorbed" in live_lock_orders._STRATEGY_B_OPEN
    folder = Path(tempfile.mkdtemp())
    path = folder / "strategy_b_watch.json"
    path.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "game": "Moutet vs Paul",
                        "stage": "absorbed",
                        "note": "absorbed before 50c cross; holding T0 both-Yes",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    saved = live_lock_orders.STRATEGY_B_STATE
    live_lock_orders.STRATEGY_B_STATE = path
    try:
        assert live_lock_orders.strategy_b_blocks_lock("tennis", "Moutet vs Paul") is True
        assert live_lock_orders.strategy_b_blocks_lock("tennis", "Other vs Match") is False
    finally:
        live_lock_orders.STRATEGY_B_STATE = saved


def test_send_blocked_strategy_b_ignores_latch():
    assert live_lock_orders._send_blocked({"_strategy_b": True}) == ""


def _cross_match():
    return {
        "key": "tennis_taverna",
        "game": "Rodriguez Taverna vs Bueno",
        "venue": "kalshi",
        "stage": "t0_filled_waiting_50_cross",
        "fav_player": "Bueno",
        "dog_player": "Rodriguez Taverna",
        "t0_yes": {
            "a": {"player": "Rodriguez Taverna", "price": "0.35", "filled": True, "instrument": "A"},
            "b": {"player": "Bueno", "price": "0.66", "filled": True, "instrument": "B"},
        },
        "last_quotes": {},
    }


def _recheck_dog_fav(dog_ask, fav_ask, dog="Rodriguez Taverna", fav="Bueno"):
    def _fn(spec, *a, **k):
        player = str(spec.get("player") or "")
        if player == fav:
            return Decimal(str(fav_ask)), "book"
        return Decimal(str(dog_ask)), "book"

    return _fn


def test_cross_send_once_does_not_retry_miss():
    match = _cross_match()
    sent = []
    saved_latest = live_strategy_b.latest_yes
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.latest_yes = lambda *_a, **_k: Decimal("0.52")
    live_strategy_b.recheck_yes = _recheck_dog_fav("0.52", "0.48")
    live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append(1) or {
        "filled": False,
        "posted": True,
        "fill_qty": "0",
        "pay": "0.52",
        "status": 201,
        "sent_at": "2026-10-21T16:50:00-04:00",
        "order_id": "x",
        "note": "ioc miss",
    }
    try:
        live_strategy_b.maybe_cross(match)
        live_strategy_b.maybe_cross(match)
        assert sent == [1]
        assert match.get("cross_need_reset") is True
        assert match["stage"] == "t0_filled_waiting_50_cross"
    finally:
        live_strategy_b.latest_yes = saved_latest
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_leftover_partial_is_not_a_retry_miss():
    match = {
        "key": "tennis_santos",
        "game": "Santos vs Malla",
        "venue": "polymarket",
        "stage": "one_leg_miss",
        "one_leg_miss": "Malla",
        "fav_player": "Santos",
        "dog_player": "Malla",
        "t0_yes": {
            "a": {"player": "Santos", "price": "0.62", "filled": True, "instrument": "S"},
            "b": {"player": "Malla", "price": "0.39", "filled": False, "instrument": "M"},
        },
        "last_quotes": {},
    }
    sent = []
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = lambda *_a, **_k: (Decimal("0.53"), "book")
    live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append(1) or {
        "filled": False,
        "posted": True,
        "fill_qty": "0.62",
        "payload": {"status": "cancelled", "filledQuantity": "0.62"},
        "pay": "0.53",
        "fill_px": "0.53",
        "fill_fee": "0.02",
        "status": 201,
        "sent_at": "2026-10-21T16:37:45-04:00",
        "order_id": "p",
        "note": "partial",
    }
    try:
        live_strategy_b.maybe_one_leg_yes(match)
        live_strategy_b.maybe_one_leg_yes(match)
        assert sent == [1]
        assert match.get("leftover_ioc_sent") is True
        assert match["stage"] == "one_leg_miss"
        assert "partial" in match["note"]
        assert match["t0_yes"]["b"]["fill_qty"] == "0.62"
        assert match["t0_yes"]["b"]["filled"] is not True
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_poly_size_019_fok_does_not_send_or_open():
    spec = {
        "venue": "polymarket",
        "instrument": "aec-utr-guaale-bralac-2026-10-24",
        "intent": "ORDER_INTENT_BUY_LONG",
        "quote_size": "0.19",
        "quote_source": "book",
    }
    posted = []

    def fake_send(_built):
        posted.append(1)
        return 200, {"id": "x", "cumQuantity": "1"}, "ok"

    def fake_fetch(s, **_k):
        live_lock_orders._attach_quote_size(s, "0.19", overwrite=True)
        return Decimal("0.48"), "book"

    saved_send = live_lock_orders._send
    saved_fetch = live_lock_orders.fetch_book_ask
    live_lock_orders._send = fake_send
    live_lock_orders.fetch_book_ask = fake_fetch
    try:
        result = live_strategy_b.send_yes_ioc(spec, Decimal("0.48"), "t0", "k")
    finally:
        live_lock_orders._send = saved_send
        live_lock_orders.fetch_book_ask = saved_fetch
    assert posted == []
    assert result["filled"] is False
    assert result["posted"] is False
    assert live_lock_orders.POLY_SIZE_LT_QTY_SKIP in str(result.get("note") or "")


def test_poly_size_ge_1_fok_fill_opens_one():
    spec = {
        "venue": "polymarket",
        "instrument": "aec-test",
        "intent": "ORDER_INTENT_BUY_LONG",
        "quote_size": "5",
        "quote_source": "book",
    }
    posted = []

    def fake_send(built):
        posted.append(built.get("body", {}).get("tif"))
        payload = {"id": "oid-fok-1", "cumQuantity": 1, "state": "ORDER_STATE_FILLED"}
        return 200, payload, "filled"

    def fake_fetch(s, **_k):
        live_lock_orders._attach_quote_size(s, "5", overwrite=True)
        return Decimal("0.48"), "book"

    saved_send = live_lock_orders._send
    saved_fetch = live_lock_orders.fetch_book_ask
    saved_funds = live_lock_orders._funds_block
    saved_append = live_lock_orders._append
    live_lock_orders._send = fake_send
    live_lock_orders.fetch_book_ask = fake_fetch
    live_lock_orders._funds_block = lambda _spec: ""
    live_lock_orders._append = lambda _row: None
    try:
        result = live_strategy_b.send_yes_ioc(spec, Decimal("0.48"), "t0", "k")
    finally:
        live_lock_orders._send = saved_send
        live_lock_orders.fetch_book_ask = saved_fetch
        live_lock_orders._funds_block = saved_funds
        live_lock_orders._append = saved_append
    assert posted == ["TIME_IN_FORCE_FILL_OR_KILL"]
    assert result["filled"] is True
    assert result["posted"] is True
    assert Decimal(str(result.get("fill_qty") or 0)) >= Decimal("1")


def test_poly_cross_partial_does_not_flatten_as_one():
    match = _cross_match()
    match["venue"] = "polymarket"
    match["t0_yes"]["a"]["venue"] = "polymarket"
    match["t0_yes"]["b"]["venue"] = "polymarket"
    flattened = []
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    saved_flat = live_strategy_b.flatten_extra_leg
    live_strategy_b.recheck_yes = _recheck_dog_fav("0.52", "0.48")
    live_strategy_b.send_yes_ioc = lambda spec, *a, **k: {
        "filled": False,
        "posted": True,
        "fill_qty": "0.19",
        "pay": "0.52",
        "fill_px": "0.52",
        "fill_fee": "0.02",
        "status": 200,
        "sent_at": "2026-10-24T16:50:00-04:00",
        "order_id": "partial",
        "note": "partial",
        "spec": spec,
    }
    live_strategy_b.flatten_extra_leg = lambda *a, **k: flattened.append(1) or {"filled": False}
    try:
        live_strategy_b.maybe_cross(match)
        assert flattened == []
        assert match.get("extra_stuck") is True
        assert "not flattening" in match["note"]
        assert match.get("cross_ioc_sent") is False
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send
        live_strategy_b.flatten_extra_leg = saved_flat


def test_guajardo_brain_leftover_empty_confirm_is_partial():
    """Guajardo leftover-yes: empty activities must not look like an IOC miss."""
    tape = {
        "id": "D9ZCT3CG11KJ",
        "marketSlug": "aec-utr-guaale-bralac-2026-10-24",
        "executions": [
            {
                "order": {
                    "id": "D9ZCT3CG11KJ",
                    "cumQuantity": 0.19,
                    "leavesQuantity": 0.81,
                    "state": "ORDER_STATE_PARTIALLY_FILLED",
                    "avgPx": {"value": "0.4800"},
                    "marketSlug": "aec-utr-guaale-bralac-2026-10-24",
                }
            }
        ],
    }
    empty = {"activities": [], "eof": True}
    with patch.object(polymarket_us_live, "get_activities", return_value=(200, json.dumps(empty))):
        confirm = venue_fill_confirm.confirm_order(
            "polymarket",
            tape,
            {
                "venue": "polymarket",
                "instrument": "aec-utr-guaale-bralac-2026-10-24",
                "outcome": "yes",
            },
            tries=1,
            sleep_sec=0,
        )
    payload = venue_fill_confirm.attach(tape, confirm)
    qty = live_lock_orders.filled_contracts(payload)
    assert qty == Decimal("0.19")
    result = {
        "filled": qty >= live_strategy_b.SIZE,
        "posted": True,
        "payload": payload,
        "fill_qty": live_strategy_b._money(qty),
        "pay": "0.480",
        "status": 200,
    }
    assert live_strategy_b._ticket_qty(result) == Decimal("0.19")
    assert result["filled"] is False
    match = {
        "key": "tennis_guajarbrain_2026_10_24",
        "game": "Alexander Guajardo vs. Lachlan Brain",
        "venue": "polymarket",
        "stage": "one_leg_miss",
        "one_leg_miss": "Guajardo, Alexander",
        "fav_player": "Brain, Lachlan",
        "dog_player": "Guajardo, Alexander",
        "t0_yes": {
            "a": {"player": "Guajardo, Alexander", "price": "0.47", "filled": False, "instrument": "aec-utr-guaale-bralac-2026-10-24"},
            "b": {"player": "Brain, Lachlan", "price": "0.54", "filled": True, "instrument": "aec-utr-guaale-bralac-2026-10-24"},
        },
        "last_quotes": {},
    }
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = lambda *_a, **_k: (Decimal("0.48"), "book")
    live_strategy_b.send_yes_ioc = lambda *_a, **_k: result
    try:
        live_strategy_b.maybe_one_leg_yes(match)
        assert match.get("leftover_ioc_sent") is True
        assert match["stage"] == "one_leg_miss"
        assert "partial" in match["note"]
        assert "IOC miss" not in match["note"]
        assert match["t0_yes"]["a"]["filled"] is not True
        assert match["t0_yes"]["a"]["fill_qty"] == "0.19"
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_watch_cadence_is_continuous_tick():
    assert live_strategy_b.TICK_SEC <= 1
    assert "continuous" in live_strategy_b.WATCH_CADENCE
    assert live_lock_orders.WATCH_TICK_SEC <= 1
    assert live_lock_orders.WATCH_MODE == "continuous_quote"


def test_strategy_b_has_no_job_deadline():
    friday = datetime(2026, 10, 23, 8, 0, 0, tzinfo=ET)
    assert live_strategy_b.past_job_deadline() is False
    assert live_strategy_b.past_job_deadline(friday) is False
    assert live_strategy_b.job_deadline_iso() is None
    assert live_strategy_b.MAX_OPEN_B_MATCHES >= 1


def test_tape_resume_is_not_a_live_t0_clock():
    now = datetime(2026, 10, 21, 16, 35, tzinfo=ET)
    pair = {
        "t0_a": 0.35,
        "t0_b": 0.66,
        "t0_ts": int(now.timestamp()),
        "actual_start": now.isoformat(),
        "actual_source": "tape resume after last >=60min gap",
        "t0_label": "last two-sided Yes <= tape resume after last >=60min gap",
        "yes_a": [(int(now.timestamp()), 0.35)],
        "yes_b": [(int(now.timestamp()), 0.66)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False
    assert "trusted clock" in why


def test_listed_hides_inplay_two_sided_moving():
    now = datetime(2026, 10, 21, 16, 0, tzinfo=ET)
    listed = datetime(2026, 10, 21, 16, 2, tzinfo=ET)
    listed_ts = int(listed.timestamp())
    pair = {
        "t0_a": 0.36,
        "t0_b": 0.65,
        "t0_ts": listed_ts - 600,
        "listed_dt": listed,
        "listed_start": listed.isoformat(),
        "actual_start": listed.isoformat(),
        "actual_source": "listed/feed",
        "t0_label": "last two-sided Yes <= listed/feed",
        "yes_a": [(listed_ts - 900, 0.40), (listed_ts - 600, 0.36)],
        "yes_b": [(listed_ts - 900, 0.61), (listed_ts - 600, 0.65)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False
    assert "trusted clock" in why


def test_odd_second_listed_is_not_a_live_t0_clock():
    """Polymarket gameStartTime 23:12:40Z is a feed stamp, not court time (Wolff/Webb)."""
    now = datetime(2026, 10, 21, 19, 12, 40, tzinfo=ET)
    listed = datetime(2026, 10, 21, 19, 12, 40, tzinfo=ET)
    listed_ts = int(listed.timestamp())
    pair = {
        "t0_a": 0.86,
        "t0_b": 0.15,
        "t0_ts": listed_ts,
        "listed_dt": listed,
        "listed_start": listed.isoformat(),
        "actual_start": listed.isoformat(),
        "actual_source": "listed/feed",
        "t0_label": "last two-sided Yes <= listed/feed",
        "yes_a": [(listed_ts, 0.86)],
        "yes_b": [(listed_ts, 0.15)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False
    assert "feed stamp" in why


def test_scheduled_listed_still_fires_t0():
    now = datetime(2026, 10, 21, 15, 10, 20, tzinfo=ET)
    listed = datetime(2026, 10, 21, 15, 10, 0, tzinfo=ET)
    listed_ts = int(listed.timestamp())
    pair = {
        "t0_a": 0.36,
        "t0_b": 0.65,
        "t0_ts": listed_ts,
        "listed_dt": listed,
        "listed_start": listed.isoformat(),
        "actual_start": listed.isoformat(),
        "actual_source": "listed/feed",
        "t0_label": "last two-sided Yes <= listed/feed",
        "yes_a": [(listed_ts, 0.36)],
        "yes_b": [(listed_ts, 0.65)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is True


def test_odd_second_occurrence_still_trusted():
    now = datetime(2026, 10, 21, 15, 10, 40, tzinfo=ET)
    occ = datetime(2026, 10, 21, 15, 10, 40, tzinfo=ET)
    occ_ts = int(occ.timestamp())
    pair = {
        "t0_a": 0.36,
        "t0_b": 0.65,
        "t0_ts": occ_ts,
        "occ_dt": occ,
        "occurrence": occ.isoformat(),
        "actual_start": occ.isoformat(),
        "actual_source": "occurrence",
        "t0_label": "last two-sided Yes <= occurrence",
        "yes_a": [(occ_ts, 0.36)],
        "yes_b": [(occ_ts, 0.65)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is True


def test_absorbing_rejects_t0():
    now = datetime(2026, 10, 21, 16, 0, tzinfo=ET)
    start = datetime(2026, 10, 21, 15, 59, tzinfo=ET)
    pair = {
        "t0_a": 0.36,
        "t0_b": 0.65,
        "t0_ts": int(start.timestamp()),
        "actual_start": start.isoformat(),
        "t0_label": "mixed pre-start + first in-game (occurrence)",
        "yes_a": [(int(now.timestamp()), 0.05)],
        "yes_b": [(int(now.timestamp()), 0.95)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False
    assert "absorbing" in why


def test_extras_cross_ready_no_backfill_then_next_upcross():
    match = {"cross_need_reset": True}
    ok, why = live_strategy_b.extras_cross_ready(match, Decimal("0.55"))
    assert ok is False
    assert "no backfill" in why
    ok, why = live_strategy_b.extras_cross_ready(match, Decimal("0.39"))
    assert ok is False
    assert match["cross_need_reset"] is False
    ok, why = live_strategy_b.extras_cross_ready(match, Decimal("0.51"))
    assert ok is True


def test_waiting_cross_occupies_open_slot():
    assert "waiting_cross" in live_strategy_b.OPEN_STAGES
    assert "waiting_cross" in live_lock_orders._STRATEGY_B_OPEN
    assert "fav_gtc_resting" in live_strategy_b.OPEN_STAGES
    assert "fav_gtc_resting" in live_lock_orders._STRATEGY_B_OPEN


def test_postponed_not_counted_open():
    data = {
        "matches": [
            {"game": "Rodriguez Taverna vs Bueno", "stage": "postponed"},
            {"game": "Vivian Wolff vs. Stefani Webb", "stage": "postponed"},
            {"game": "Other vs Match", "stage": "waiting_cross"},
            {"game": "Done vs Game", "stage": "done"},
            {"game": "Abs vs Orb", "stage": "absorbed"},
            {"game": "Left vs Slate", "stage": "abandoned"},
        ]
    }
    open_rows = [
        row
        for row in data["matches"]
        if str(row.get("stage") or "") in live_strategy_b.OPEN_STAGES
    ]
    assert [row["game"] for row in open_rows] == ["Other vs Match"]
    assert "postponed" not in live_strategy_b.OPEN_STAGES
    assert live_strategy_b.POSTPONED_STAGE in live_strategy_b.DONE_STAGES


def test_sus_period_is_postponed():
    why = live_strategy_b.postponed_reason(
        original_start=datetime(2026, 10, 21, 15, 10, tzinfo=ET),
        payloads=({"period": "SUS", "startTime": "2026-10-21T19:10:00Z"},),
    )
    assert why == "period=SUS"


def test_start_moved_next_et_day_is_postponed():
    original = datetime(2026, 10, 21, 19, 12, 40, tzinfo=ET)
    why = live_strategy_b.postponed_reason(
        original_start=original,
        payloads=({"startTime": "2026-10-22T17:00:00Z", "period": ""},),
    )
    assert why is not None
    assert "2026-10-22" in why


def test_odd_second_same_day_is_not_postponed_by_clock():
    original = datetime(2026, 10, 21, 19, 12, 40, tzinfo=ET)
    why = live_strategy_b.postponed_reason(
        original_start=original,
        payloads=({"startTime": "2026-10-21T23:12:40Z", "status": "MARKET_STATUS_OPEN"},),
    )
    assert why is None


def test_closed_without_settlement_is_postponed():
    why = live_strategy_b.postponed_reason(
        original_start=datetime(2026, 10, 21, 15, 10, tzinfo=ET),
        payloads=({"status": "closed", "result": ""},),
    )
    assert why == "closed without settlement"


def test_active_empty_result_is_not_postponed():
    why = live_strategy_b.postponed_reason(
        original_start=datetime(2026, 10, 21, 15, 10, tzinfo=ET),
        payloads=({"status": "active", "result": "", "occurrence_datetime": "2026-10-21T19:10:00Z"},),
    )
    assert why is None


def test_post_period_is_postponed():
    """Live Polymarket tennis catalog uses period=POST (not ppt)."""
    why = live_strategy_b.postponed_reason(
        original_start=datetime(2026, 10, 21, 9, 36, tzinfo=ET),
        payloads=(
            {
                "title": "Beatrise Zeltina vs. Ane Mintegi Del Olmo",
                "period": "POST",
                "startTime": "2026-10-21T13:36:34Z",
                "live": False,
                "ended": False,
                "score": "3-6, 6-4, 3-5",
                "eventState": {"period": "POST", "live": False},
                "markets": [{"status": "MARKET_STATUS_OPEN", "ep3Status": "OPEN"}],
            },
        ),
    )
    assert why == "period=POST"


def test_taverna_live_shape_sus_not_kalshi_active():
    """Taverna: Kalshi still active; rain-suspend is Polymarket period=SUS."""
    kalshi = {
        "kalshi_events": [
            {
                "contracts": [
                    {
                        "ticker": "KXATPCHALLENGERMATCH-26OCT21RODBUE-ROD",
                        "status": "active",
                        "result": "",
                        "occurrence_datetime": "2026-10-21T19:10:00Z",
                        "yes_ask_dollars": "0.5700",
                    }
                ]
            }
        ]
    }
    poly = {
        "title": "Santiago Rodriguez Taverna vs. Gonzalo Bueno",
        "period": "SUS",
        "startTime": "2026-10-21T19:10:00Z",
        "startDate": "2026-10-21T19:10:00Z",
        "live": True,
        "ended": False,
        "closed": False,
        "score": "6-7(12-14), 6-4, 1-1",
        "eventState": {"period": "SUS", "live": True, "ended": False, "score": "6-7(12-14), 6-4, 1-1"},
        "markets": [
            {
                "slug": "aec-atp-santav-gonbue-2026-10-21",
                "status": "MARKET_STATUS_OPEN",
                "ep3Status": "OPEN",
                "gameStartTime": "2026-10-21T19:10:00Z",
                "closed": False,
            }
        ],
    }
    original = datetime(2026, 10, 21, 15, 10, tzinfo=ET)
    assert live_strategy_b.postponed_reason(original_start=original, payloads=(kalshi,)) is None
    why = live_strategy_b.postponed_reason(original_start=original, payloads=(kalshi, poly))
    assert why == "period=SUS"


def test_wolff_live_shape_start_moved_thu_1pm():
    """Wolff Polymarket startTime/startDate/gameStartTime moved to Thu 1pm ET."""
    poly = {
        "title": "Vivian Wolff vs. Stefani Webb",
        "slug": "itfwo-vivwol-steweb-2026-10-21",
        "startTime": "2026-10-22T17:00:00Z",
        "startDate": "2026-10-22T17:00:00Z",
        "period": "",
        "live": False,
        "ended": False,
        "closed": False,
        "score": "0-0",
        "eventState": {"period": "", "live": False, "ended": False, "score": "0-0"},
        "markets": [
            {
                "slug": "aec-itfwo-vivwol-steweb-2026-10-21",
                "status": "MARKET_STATUS_OPEN",
                "ep3Status": "OPEN",
                "gameStartTime": "2026-10-22T17:00:00Z",
                "startDate": "2026-10-21T01:00:43Z",
                "closed": False,
            }
        ],
    }
    original = datetime(2026, 10, 21, 19, 12, 40, tzinfo=ET)
    why = live_strategy_b.postponed_reason(original_start=original, payloads=(poly,))
    assert why is not None
    assert "2026-10-22" in why


def test_kalshi_occurrence_moved_next_et_day():
    why = live_strategy_b.postponed_reason(
        original_start=datetime(2026, 10, 21, 15, 10, tzinfo=ET),
        payloads=(
            {
                "contracts": [
                    {
                        "status": "active",
                        "result": "",
                        "occurrence_datetime": "2026-10-22T17:00:00Z",
                    }
                ]
            },
        ),
    )
    assert why is not None
    assert "occurrence moved" in why
    assert "2026-10-22" in why


def test_novig_delayed_is_postponed():
    why = live_strategy_b.postponed_reason(
        original_start=datetime(2026, 10, 21, 15, 10, tzinfo=ET),
        payloads=({"status": "DELAYED", "startTime": "2026-10-21T19:10:00-04:00"},),
    )
    assert why == "status=DELAYED"
    why = live_strategy_b.postponed_reason(
        original_start=datetime(2026, 10, 21, 15, 10, tzinfo=ET),
        payloads=({"event_status": "SUSPENDED"},),
    )
    assert why == "event_status=SUSPENDED"


def test_novig_canceled_and_s1_are_not_postponed():
    original = datetime(2026, 10, 21, 15, 10, tzinfo=ET)
    assert live_strategy_b.postponed_reason(
        original_start=original,
        payloads=({"status": "CANCELED", "description": "Lui Maxted @ Alastair Gray"},),
    ) is None
    assert live_strategy_b.postponed_reason(
        original_start=original,
        payloads=({"period": "S1", "startTime": "2026-10-21T19:10:00Z", "live": True},),
    ) is None
    assert live_strategy_b.postponed_reason(
        original_start=original,
        payloads=({"period": "NS", "startTime": "2026-10-21T19:10:00Z", "live": False},),
    ) is None


def test_gemini_start_moved_when_event_has_contracts():
    why = live_strategy_b.postponed_reason(
        original_start=datetime(2026, 10, 21, 15, 10, tzinfo=ET),
        payloads=(
            {
                "status": "active",
                "startTime": "2026-10-22T17:00:00.000Z",
                "contracts": [{"status": "active"}],
            },
        ),
    )
    assert why is not None
    assert "2026-10-22" in why


def test_process_open_does_not_send_on_postponed():
    sent = []
    match = _cross_match()
    match["stage"] = "postponed"
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append(1) or {"filled": False}
    try:
        live_strategy_b.process_open(match)
        live_strategy_b.maybe_cross(match)
        assert sent == []
        assert match["stage"] == "postponed"
    finally:
        live_strategy_b.send_yes_ioc = saved_send


def test_cross_ioc_miss_does_not_retry_same_ask():
    match = _cross_match()
    match["stage"] = "waiting_cross"
    sent = []
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = _recheck_dog_fav("0.52", "0.48")
    live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append(1) or {
        "filled": False,
        "posted": True,
        "fill_qty": "0",
        "pay": "0.52",
        "status": 201,
        "sent_at": "2026-10-21T16:50:00-04:00",
        "order_id": "x",
        "note": "ioc miss",
    }
    try:
        live_strategy_b.maybe_cross(match)
        live_strategy_b.maybe_cross(match)
        assert sent == [1]
        assert match.get("cross_need_reset") is True
        assert "leftover-retry" in match["note"]
        assert match["stage"] == "waiting_cross"
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_b_can_select_novig_as_yes_venue():
    view = {
        "yes": Decimal("0.36"),
        "ident": "m-novig-1",
        "buy_yes_outcome": "oid-a",
        "buy_no_outcome": "oid-b",
        "label": "Alice",
        "fee_coefficient": "0.02",
        "fee_charged": "TAKER",
        "event_status": "OPEN_PREGAME",
    }
    spec = live_strategy_b._yes_spec_from_view("novig", view, "Alice")
    assert spec is not None
    assert spec["venue"] == "novig"
    assert spec["instrument"] == "m-novig-1"
    assert spec["outcome"] == "yes"
    assert spec["outcome_id"] == "oid-a"
    assert spec["yes_outcome_id"] == "oid-a"
    assert spec["no_outcome_id"] == "oid-b"
    assert live_strategy_b.SIZE == Decimal("1")
    assert "novig" in live_strategy_b.VENUE_ORDER

    class DummyScan:
        def load_views(self, _events, _venue):
            return []

    saved_fetch = live_strategy_b._fetch_events
    saved_live = novig_live.orders_live
    live_strategy_b._fetch_events = lambda *_a, **_k: {
        "kalshi_events": [],
        "gemini_events": [],
        "polymarket": [],
        "novig_markets": [
            {
                "market_id": "m-novig-1",
                "kind": "moneyline",
                "side": "Alice",
                "other_side": "Bob",
                "yes_outcome": "oid-a",
                "no_outcome": "oid-b",
                "yes_ask": Decimal("0.36"),
                "no_ask": Decimal("0.65"),
                "ask_size": Decimal("5"),
                "no_ask_size": Decimal("5"),
                "fee_coefficient": "0.02",
                "fee_charged": "TAKER",
                "event_status": "OPEN_PREGAME",
            }
        ],
        "occurrence": None,
    }
    novig_live.orders_live = lambda: True
    try:
        books = live_strategy_b.moneyline_yes_books(
            DummyScan(),
            {"title": "Alice vs Bob", "key": "t-novig", "game": {}},
        )
        novig_books = [row for row in books if row.get("venue") == "novig"]
        assert len(novig_books) == 1
        players = novig_books[0]["players"]
        assert {row["player"] for row in players} == {"Alice", "Bob"}
        assert all(row["outcome_id"] for row in players)
        picked = live_strategy_b.pick_t0_book(books)
        assert picked is None  # fee_charged TAKER is unknown; skip Novig T0
        for row in players:
            row["fee_charged"] = "ALWAYS"
        picked = live_strategy_b.pick_t0_book(books)
        assert picked is not None
        assert picked["venue"] == "novig"
    finally:
        live_strategy_b._fetch_events = saved_fetch
        novig_live.orders_live = saved_live


def test_b_still_one_contract_and_two_match_cap():
    assert live_strategy_b.SIZE == Decimal("1")
    assert live_strategy_b.MAX_OPEN_B_MATCHES >= 1
    assert live_strategy_b.T0_STACK_CAP == 10
    assert live_strategy_b.D == Decimal("0.25")


def test_b_novig_send_uses_venue_confirm():
    saved_send = live_lock_orders._send
    saved_funds = live_lock_orders._funds_block
    saved_confirm = live_lock_orders.confirm_venue_after_order
    saved_live = novig_live.orders_live
    novig_live.orders_live = lambda: True
    live_lock_orders._funds_block = lambda _built: ""
    confirm_calls = []

    def fake_confirm(spec, status, payload):
        confirm_calls.append((str(spec.get("venue") or ""), status))
        return {
            "known": True,
            "qty": "1",
            "note": "novig fills GET qty 1",
            "mismatch": False,
            "venue": "novig",
            "endpoint": "GET /v3/portfolio/fills",
        }

    def fake_send(spec):
        payload = {"orderId": "n1", "status": "FILLED", "tif": "IOC"}
        payload = live_lock_orders._with_venue_confirm(spec, 201, payload)
        return 201, payload, "ok"

    live_lock_orders.confirm_venue_after_order = fake_confirm
    live_lock_orders._send = fake_send
    spec = {
        "venue": "novig",
        "instrument": "m-novig-1",
        "outcome": "yes",
        "outcome_id": "oid-a",
        "yes_outcome_id": "oid-a",
        "no_outcome_id": "oid-b",
        "pay": "0.36",
    }
    try:
        result = live_strategy_b.send_yes_ioc(
            spec, Decimal("0.36"), "b-t0", "tennis-b\tnovig-test", log_fn=lambda *_a, **_k: None
        )
        assert confirm_calls == [("novig", 201)]
        assert result["confirm_known"] is True
        assert result["confirm_qty"] == "1"
        assert result["filled"] is True
        assert result["fill_qty"] == "1"
    finally:
        live_lock_orders._send = saved_send
        live_lock_orders._funds_block = saved_funds
        live_lock_orders.confirm_venue_after_order = saved_confirm
        novig_live.orders_live = saved_live


def test_b_novig_low_balance_named_deny():
    saved_funds = live_lock_orders._funds_block
    saved_live = novig_live.orders_live
    novig_live.orders_live = lambda: True
    live_lock_orders._funds_block = lambda _built: "venue=novig cost=0.40 balance=0"
    spec = {
        "venue": "novig",
        "instrument": "m-novig-1",
        "outcome": "yes",
        "outcome_id": "oid-a",
        "pay": "0.40",
    }
    try:
        result = live_strategy_b.send_yes_ioc(
            spec, Decimal("0.40"), "b-t0", "tennis-b\tnovig-bal", log_fn=lambda *_a, **_k: None
        )
        assert result["posted"] is False
        assert result["filled"] is False
        assert "Novig balance too low" in str(result.get("note") or "")
        assert "$0" in str(result.get("note") or "")
    finally:
        live_lock_orders._funds_block = saved_funds
        novig_live.orders_live = saved_live


def test_b_novig_flatten_uses_opposite_outcome_id():
    filled = {
        "venue": "novig",
        "instrument": "m-novig-1",
        "outcome": "yes",
        "outcome_id": "oid-a",
        "yes_outcome_id": "oid-a",
        "no_outcome_id": "oid-b",
        "_strategy_b": True,
    }
    flat = live_lock_orders._flatten_spec(filled)
    assert flat is not None
    assert flat["outcome"] == "no"
    assert flat["outcome_id"] == "oid-b"
    match = {
        "key": "t",
        "game": "Alice vs Bob",
        "venue": "novig",
        "t0_yes": {
            "a": {
                "player": "Alice",
                "price": "0.36",
                "instrument": "m-novig-1",
                "venue": "novig",
                "outcome_id": "oid-a",
                "yes_outcome_id": "oid-a",
                "no_outcome_id": "oid-b",
            }
        },
    }
    spec = live_strategy_b._player_spec(match, "a")
    assert spec["outcome_id"] == "oid-a"
    assert spec["no_outcome_id"] == "oid-b"


def test_b_novig_all_in_uses_documented_coefficient():
    spec = {
        "venue": "novig",
        "fee_coefficient": "0.06",
        "fee_charged": "WHEN_LIVE",
        "event_status": "OPEN_INGAME",
    }
    novig_fee = Decimal("0.01414")
    all_in = live_strategy_b.t0_all_in_from_asks(spec, Decimal("0.38"), spec, Decimal("0.62"))
    assert all_in == Decimal("0.38") + Decimal("0.62") + novig_fee + novig_fee
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.38"), Decimal("0.62"), spec_a=spec, spec_b=spec
    )
    assert ok is True, why
    missing = {"venue": "novig"}
    assert live_strategy_b.t0_all_in_from_asks(missing, Decimal("0.50"), missing, Decimal("0.51")) is None


def test_t0_ready_multi_does_not_call_fee_unknown():
    """venue=multi is not a shop. All-in uses per-leg specs, not a fake multi fee."""
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.40"), Decimal("0.55"), venue="multi"
    )
    assert ok is True, why
    assert "unknown" not in why
    novig_spec = {
        "venue": "novig",
        "fee_coefficient": "0.06",
        "fee_charged": "WHEN_LIVE",
        "event_status": "OPEN_PREGAME",
        "player": "A",
    }
    kalshi_spec = {"venue": "kalshi", "player": "B"}
    now = datetime(2026, 10, 30, 22, 0, 0, tzinfo=ET)
    pair = {
        "t0_a": 0.40,
        "t0_b": 0.55,
        "t0_ts": int(now.timestamp()),
        "actual_start": now.isoformat(),
        "occ_dt": now,
        "venue": "multi",
        "spec_a": novig_spec,
        "spec_b": kalshi_spec,
        "yes_a": [(int(now.timestamp()), 0.40)],
        "yes_b": [(int(now.timestamp()), 0.55)],
    }
    ready, why = live_strategy_b.t0_ready(pair, now)
    assert "unknown" not in why
    assert live_strategy_b.T0_C_OVER_SKIP not in why
    ready, why = live_strategy_b.t0_ready(
        {
            "t0_a": 0.40,
            "t0_b": 0.55,
            "t0_ts": int(now.timestamp()),
            "venue": "novig",
            "spec_a": novig_spec,
            "spec_b": novig_spec,
        },
        now,
    )
    assert live_strategy_b.T0_C_OVER_SKIP not in why


def test_pick_skips_novig_without_schedule_keeps_kalshi():
    """Cheapest Novig wire without a fee is not the pair. Kalshi with a formula is."""
    saved_live = novig_live.orders_live
    novig_live.orders_live = lambda: True
    try:
        books = [
            {
                "venue": "novig",
                "title": "A vs B",
                "players": [
                    {"player": "A", "pay": Decimal("0.38"), "venue": "novig", "instrument": "n-a"},
                    {"player": "B", "pay": Decimal("0.50"), "venue": "novig", "instrument": "n-b"},
                ],
            },
            {
                "venue": "kalshi",
                "title": "A vs B",
                "players": [
                    {"player": "A", "pay": Decimal("0.40"), "venue": "kalshi", "instrument": "k-a"},
                    {"player": "B", "pay": Decimal("0.52"), "venue": "kalshi", "instrument": "k-b"},
                ],
            },
        ]
        picked = live_strategy_b.pick_t0_book(books)
        assert picked is not None
        assert all(row.get("venue") == "kalshi" for row in picked["players"])
        only_novig = live_strategy_b.pick_t0_book([books[0]])
        assert only_novig is None
        for row in books[0]["players"]:
            row["fee_coefficient"] = "0.06"
            row["fee_charged"] = "WHEN_LIVE"
            row["event_status"] = "OPEN_PREGAME"
        priced = live_strategy_b.pick_t0_book([books[0]])
        assert priced is not None
        assert all(row.get("venue") == "novig" for row in priced["players"])
    finally:
        novig_live.orders_live = saved_live


def _filled_leg(pay, fill_px, oid="1"):
    return {
        "filled": True,
        "pay": pay,
        "fill_px": fill_px,
        "fill_fee": "0.02",
        "fill_qty": "1",
        "status": 200,
        "order_id": oid,
        "sent_at": "2026-10-23T05:03:24-04:00",
        "note": "",
    }


def test_poly_short_fill_px_does_not_invert_fav_dog():
    """Trungelliti/Dodig 23 Oct 2026: BUY_SHORT fill_px 0.41 is not Yes Dodig 0.61."""
    match = {
        "key": "tennis_trudod",
        "game": "Marco Trungelliti vs. Matej Dodig",
        "venue": "polymarket",
        "stage": "waiting_t0",
        "fav_player": "Matej Dodig",
        "dog_player": "Marco Trungelliti",
        "t0_yes": {
            "a": {
                "player": "Marco Trungelliti",
                "price": "0.410",
                "filled": False,
                "instrument": "aec-atp-martru-matdod-2026-10-23",
                "intent": "ORDER_INTENT_BUY_LONG",
            },
            "b": {
                "player": "Matej Dodig",
                "price": "0.610",
                "filled": False,
                "instrument": "aec-atp-martru-matdod-2026-10-23",
                "intent": "ORDER_INTENT_BUY_SHORT",
            },
        },
    }
    live_strategy_b.mark_t0_results(
        match,
        {
            "a": _filled_leg("0.410", "0.41", "D93BC89011N2"),
            "b": _filled_leg("0.610", "0.41", "D93BDNCG11TB"),
        },
    )
    assert match["fav_player"] == "Matej Dodig"
    assert match["dog_player"] == "Marco Trungelliti"
    assert match["c"] == "1.02"
    assert match["stage"] == "waiting_cross"
    assert match.get("cross_need_reset") is not True
    assert "waiting for underdog" in match["note"]


def _trungelliti_t0_match():
    return {
        "key": "tennis_trudod",
        "game": "Marco Trungelliti vs. Matej Dodig",
        "venue": "polymarket",
        "stage": "waiting_t0",
        "fav_player": "Marco Trungelliti",
        "dog_player": "Matej Dodig",
        "t0_yes": {
            "a": {
                "player": "Marco Trungelliti",
                "price": "0.41",
                "yes_ask": "0.41",
                "filled": False,
                "instrument": "aec-atp-martru-matdod-2026-10-23",
                "intent": "ORDER_INTENT_BUY_LONG",
                "venue": "polymarket",
            },
            "b": {
                "player": "Matej Dodig",
                "price": "0.61",
                "yes_ask": "0.61",
                "filled": False,
                "instrument": "aec-atp-martru-matdod-2026-10-23",
                "intent": "ORDER_INTENT_BUY_SHORT",
                "venue": "polymarket",
            },
        },
    }


def test_trungelliti_replay_dog_is_trungelliti_no_immediate_dodig_cross():
    """T0 0.41/0.61, Poly fees 0.43/0.63, BUY_SHORT Dodig fill_px 0.41 must not invert."""
    match = _trungelliti_t0_match()
    live_strategy_b.mark_t0_results(
        match,
        {
            "a": {
                **_filled_leg("0.41", "0.41", "D93BC89011N2"),
                "fill_fee": "0.02",
            },
            "b": {
                **_filled_leg("0.41", "0.41", "D93BDNCG11TB"),
                "fill_fee": "0.02",
            },
        },
    )
    assert match["fav_player"] == "Matej Dodig"
    assert match["dog_player"] == "Marco Trungelliti"
    assert match["c"] == "1.02"
    assert match["stage"] == "waiting_cross"
    assert match.get("cross_need_reset") is not True
    assert (match.get("t0_yes") or {}).get("b", {}).get("yes_ask") == "0.61"
    assert (match.get("t0_yes") or {}).get("b", {}).get("fill_px") == "0.41"

    sent = []
    asks = {"Marco Trungelliti": Decimal("0.41"), "Matej Dodig": Decimal("0.61")}

    def fake_recheck(spec, *a, **k):
        player = str(spec.get("player") or "")
        return asks.get(player, Decimal("0.41")), "book"

    def fake_send(spec, pay, step, bet_key, log_fn=None):
        player = str(spec.get("player") or "")
        sent.append({"player": player, "pay": str(pay), "step": step})
        return {
            "filled": True,
            "posted": True,
            "fill_qty": "1",
            "pay": str(pay),
            "fill_px": str(pay),
            "fill_fee": "0.02",
            "status": 200,
            "sent_at": "2026-10-23T05:19:31-04:00",
            "order_id": "cross-trung",
            "note": "",
        }

    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    saved_gtc = live_strategy_b.send_yes_gtc
    saved_poll = live_strategy_b.poll_fav_gtc_fill
    saved_latest = live_strategy_b.latest_yes
    saved_net = live_strategy_b.extra_pair_net_ok
    def fake_gtc(spec, pay, step, bet_key, log_fn=None):
        player = str(spec.get("player") or "")
        sent.append({"player": player, "pay": str(pay), "step": step, "kind": "gtc"})
        return {
            "filled": False,
            "posted": True,
            "fill_qty": "0",
            "pay": str(pay),
            "status": 201,
            "sent_at": "2026-10-23T05:19:32-04:00",
            "order_id": "gtc-dodig",
            "note": "resting",
            "resting": True,
            "tif": "good_till_canceled",
            "payload": {"status": "resting", "order_id": "gtc-dodig", "remaining_count": "1"},
        }

    live_strategy_b.recheck_yes = fake_recheck
    live_strategy_b.send_yes_ioc = fake_send
    live_strategy_b.send_yes_gtc = fake_gtc
    live_strategy_b.poll_fav_gtc_fill = lambda _m: False
    live_strategy_b.latest_yes = lambda game, venue, player: asks.get(player)
    live_strategy_b.extra_pair_net_ok = lambda *a, **k: True
    try:
        live_strategy_b.process_open(match)
        assert sent == []
        assert match["dog_player"] == "Marco Trungelliti"
        assert match["stage"] == "waiting_cross"

        asks["Marco Trungelliti"] = Decimal("0.52")
        live_strategy_b.process_open(match)
        assert sent == []
        assert live_strategy_b.CROSS_FAV_NOT_BELOW in (match.get("note") or "")

        asks["Matej Dodig"] = Decimal("0.51")
        live_strategy_b.process_open(match)
        assert sent == []
        assert live_strategy_b.CROSS_ALLIN_OVER in (match.get("note") or "")

        asks["Matej Dodig"] = Decimal("0.48")
        live_strategy_b.process_open(match)
        assert sent == [
            {"player": "Marco Trungelliti", "pay": "0.52", "step": "b-cross"},
            {"player": "Matej Dodig", "pay": "0.23", "step": "b-fav", "kind": "gtc"},
        ]
        assert match["stage"] == "fav_gtc_resting"
        assert match["cross_player"] == "Marco Trungelliti"
        assert match["fav_target"] == "0.23"
        assert live_strategy_b.fav_target(Decimal("0.52")) == Decimal("0.23")

        asks["Matej Dodig"] = Decimal("0.24")
        live_strategy_b.process_open(match)
        assert sent == [
            {"player": "Marco Trungelliti", "pay": "0.52", "step": "b-cross"},
            {"player": "Matej Dodig", "pay": "0.23", "step": "b-fav", "kind": "gtc"},
        ]

        asks["Matej Dodig"] = Decimal("0.23")
        live_strategy_b.process_open(match)
        assert sent[-1] == {"player": "Matej Dodig", "pay": "0.23", "step": "b-fav", "kind": "gtc"}
        assert match["stage"] == "fav_gtc_resting"
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send
        live_strategy_b.send_yes_gtc = saved_gtc
        live_strategy_b.poll_fav_gtc_fill = saved_poll
        live_strategy_b.latest_yes = saved_latest
        live_strategy_b.extra_pair_net_ok = saved_net


def test_false_favorite_cross_is_rewound_so_dog_can_still_fire():
    match = _trungelliti_t0_match()
    match["stage"] = "waiting_fav_dip"
    match["fav_player"] = "Marco Trungelliti"
    match["dog_player"] = "Matej Dodig"
    match["cross_fill"] = "0.61"
    match["cross_player"] = "Matej Dodig"
    match["fav_target"] = "0.14"
    match["t0_yes"]["a"]["filled"] = True
    match["t0_yes"]["b"]["filled"] = True
    sent = []
    asks = {"Marco Trungelliti": Decimal("0.52"), "Matej Dodig": Decimal("0.48")}
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    saved_latest = live_strategy_b.latest_yes
    live_strategy_b.recheck_yes = lambda spec, *a, **k: (asks.get(str(spec.get("player") or "")), "book")
    live_strategy_b.send_yes_ioc = lambda spec, pay, step, bet_key, log_fn=None: sent.append(
        str(spec.get("player") or "")
    ) or {
        "filled": True,
        "posted": True,
        "fill_qty": "1",
        "pay": str(pay),
        "fill_px": str(pay),
        "status": 200,
        "sent_at": "2026-10-23T05:19:31-04:00",
        "order_id": "x",
        "note": "",
    }
    live_strategy_b.latest_yes = lambda game, venue, player: asks.get(player)
    try:
        live_strategy_b.process_open(match)
        assert match["dog_player"] == "Marco Trungelliti"
        assert match["fav_player"] == "Matej Dodig"
        assert sent == ["Marco Trungelliti"]
        assert match["stage"] == "waiting_fav_dip"
        assert match["fav_target"] == "0.23"
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send
        live_strategy_b.latest_yes = saved_latest


def test_t0_dog_already_above_50_does_not_arm_immediate_cross():
    match = {
        "key": "tennis_tie",
        "game": "A vs B",
        "venue": "kalshi",
        "stage": "waiting_t0",
        "t0_yes": {
            "a": {"player": "A", "price": "0.51", "filled": False, "instrument": "A"},
            "b": {"player": "B", "price": "0.55", "filled": False, "instrument": "B"},
        },
    }
    live_strategy_b.mark_t0_results(
        match,
        {"a": _filled_leg("0.51", "0.51"), "b": _filled_leg("0.55", "0.55")},
    )
    assert match["fav_player"] == "B"
    assert match["dog_player"] == "A"
    assert match.get("cross_need_reset") is True
    sent = []
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = lambda *_a, **_k: (Decimal("0.51"), "book")
    live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append(1) or {
        "filled": True,
        "posted": True,
        "fill_qty": "1",
        "pay": "0.51",
        "fill_px": "0.51",
        "status": 201,
        "sent_at": "2026-10-23T05:03:51-04:00",
        "order_id": "x",
        "note": "",
    }
    try:
        live_strategy_b.maybe_cross(match)
        assert sent == []
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def _t0_match(pa, pb, venue="kalshi", fee_coefficient=None):
    return {
        "key": "tennis_t0_under_one",
        "game": "A vs B",
        "venue": venue,
        "stage": "waiting_t0",
        "t0_yes": {
            "a": {
                "player": "A",
                "price": str(pa),
                "yes_ask": str(pa),
                "filled": False,
                "instrument": "IA",
                "venue": venue,
                "fee_coefficient": fee_coefficient,
            },
            "b": {
                "player": "B",
                "price": str(pb),
                "yes_ask": str(pb),
                "filled": False,
                "instrument": "IB",
                "venue": venue,
                "fee_coefficient": fee_coefficient,
            },
        },
    }


def _run_fire_t0(match, pa, pb, fill_fee="0", quote_size="5"):
    sent = []
    _TAPE.clear()
    live_strategy_b._tape_seen.clear()
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    saved_funds = live_strategy_b._t0_pair_funds_block
    live_strategy_b._t0_pair_funds_block = lambda *_a, **_k: ""

    def fake_recheck(spec):
        live_lock_orders._attach_quote_size(spec, quote_size)
        player = str(spec.get("player") or "")
        pay = pa if player == "A" else pb
        return Decimal(str(pay)), "book"

    def fake_send(spec, pay, step, bet_key, log_fn=None):
        sent.append(step)
        return {
            "filled": True,
            "posted": True,
            "fill_qty": "1",
            "pay": str(pay),
            "fill_px": str(pay),
            "fill_fee": fill_fee,
            "status": 201,
            "sent_at": "2026-10-24T13:00:00-04:00",
            "order_id": f"ord{len(sent)}",
            "note": "",
            "confirm_known": True,
            "confirm_qty": "1",
        }

    live_strategy_b.recheck_yes = fake_recheck
    live_strategy_b.send_yes_ioc = fake_send
    try:
        live_strategy_b.fire_t0(match)
        return sent
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send
        live_strategy_b._t0_pair_funds_block = saved_funds


def test_c_090_sends():
    assert live_strategy_b.pick_t0_book(
        [
            {
                "venue": "kalshi",
                "players": [
                    {"pay": Decimal("0.40"), "player": "A"},
                    {"pay": Decimal("0.50"), "player": "B"},
                ],
            }
        ]
    ) is not None
    saved_cap = live_strategy_b.T0_STACK_CAP
    live_strategy_b.T0_STACK_CAP = 1
    try:
        match = _t0_match("0.40", "0.50")
        sent = _run_fire_t0(match, "0.40", "0.50")
        assert sent == ["b-t0", "b-t0"] or sent.count("b-t0") == 2
        assert match["stage"] == "waiting_cross"
        assert int(match.get("t0_stack_n") or 0) == 1
        t0_rows = [row for row in _TAPE if row.get("event") == "t0"]
        assert t0_rows
        snap = t0_rows[-1]
        assert snap.get("action") == "send"
        assert str(snap.get("yes_a") or "") in {"0.4", "0.40"}
        assert str(snap.get("yes_b") or "") in {"0.5", "0.50"}
        assert snap.get("all_in_c")
    finally:
        live_strategy_b.T0_STACK_CAP = saved_cap


def test_c_099_stacks():
    saved_cap = live_strategy_b.T0_STACK_CAP
    live_strategy_b.T0_STACK_CAP = 2
    try:
        match = _t0_match("0.40", "0.48")
        sent = _run_fire_t0(match, "0.40", "0.48", fill_fee="0")
        assert sent.count("b-t0") == 2
        assert sent.count("b-t0-s2") == 2
        assert int(match.get("t0_stack_n") or 0) == 2
        assert match["stage"] == "waiting_cross"
        assert match["stage"] in live_strategy_b.OPEN_STAGES
    finally:
        live_strategy_b.T0_STACK_CAP = saved_cap


def test_c_101_does_not_stack():
    match = _t0_match("0.50", "0.51")
    sent = _run_fire_t0(match, "0.50", "0.51", fill_fee="0")
    assert sent.count("b-t0") == 2
    assert not any("t0-s" in step for step in sent)
    assert int(match.get("t0_stack_n") or 0) == 1
    assert "all-in" in str(match.get("t0_stack_stop") or "")


def test_c_121_skip():
    assert live_strategy_b.pick_t0_book(
        [
            {
                "venue": "kalshi",
                "players": [
                    {"pay": Decimal("0.60"), "player": "A"},
                    {"pay": Decimal("0.61"), "player": "B"},
                ],
            }
        ]
    ) is None
    match = _t0_match("0.60", "0.61")
    sent = _run_fire_t0(match, "0.60", "0.61")
    assert sent == []
    assert match["stage"] == "abandoned"
    assert live_strategy_b.T0_C_OVER_SKIP in str(match.get("note") or "")
    assert match.get("skip_reason") == live_strategy_b.T0_C_OVER_SKIP
    t0_rows = [row for row in _TAPE if row.get("event") == "t0"]
    assert t0_rows
    snap = t0_rows[-1]
    assert snap.get("action") == "skip"
    assert str(snap.get("yes_a") or "") in {"0.6", "0.60"}
    assert str(snap.get("yes_b") or "") == "0.61"
    assert snap.get("all_in_c")


def _book(pa, pb, venue="kalshi", fee_coefficient=None):
    players = [
        {"pay": Decimal(str(pa)), "player": "A", "venue": venue},
        {"pay": Decimal(str(pb)), "player": "B", "venue": venue},
    ]
    if fee_coefficient is not None:
        for row in players:
            row["fee_coefficient"] = fee_coefficient
    return {"venue": venue, "players": players}


def _all_in(pa, pb, venue="kalshi", fee_coefficient=None):
    spec = {"venue": venue, "fee_coefficient": fee_coefficient}
    return live_strategy_b.t0_all_in_from_asks(spec, Decimal(str(pa)), spec, Decimal(str(pb)))


def test_t0_allin_c_hi_105_paul_cases():
    """Paul: 0.47+0.54 all-in ~1.03 send; 0.81+0.29 all-in >1.05 skip;
    wire 1.02 all-in ≤1.05 send (Broady-like); wire 1.01 that fees push over 1.05 skip.
    """
    skip_token = live_strategy_b.T0_C_OVER_SKIP
    assert skip_token == "t0_allin_c_over_105"

    kalshi_103 = _all_in("0.47", "0.54", "kalshi")
    assert kalshi_103 is not None
    assert Decimal("1.03") <= kalshi_103 <= Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.47"), Decimal("0.54"), venue="kalshi"
    )
    assert ok is True, why

    namigata = _all_in("0.81", "0.29", "kalshi")
    assert namigata is not None and namigata > Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.81"), Decimal("0.29"), venue="kalshi"
    )
    assert ok is False and skip_token in why
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.81"), Decimal("0.29"), venue="polymarket"
    )
    assert ok is False and skip_token in why

    # Broady-like: overnight wire C_HI=1.01 would skip 1.02. All-in 1.04 ≤ 1.05 sends.
    # (Actual Broady Poly 0.68+0.34 is 1.02/1.06 and still skips — fees over 1.05.)
    broady_like = _all_in("0.89", "0.13", "polymarket")
    assert broady_like is not None
    assert broady_like == Decimal("1.02") + Decimal("0.01") + Decimal("0.01")
    assert broady_like <= Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.89"), Decimal("0.13"), venue="polymarket"
    )
    assert ok is True, why
    assert live_strategy_b.pick_t0_book([_book("0.89", "0.13", venue="polymarket")]) is not None

    broady_poly = _all_in("0.68", "0.34", "polymarket")
    assert broady_poly is not None and broady_poly > Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.68"), Decimal("0.34"), venue="polymarket"
    )
    assert ok is False and skip_token in why

    # Wire 1.01 Poly 0.50+0.51: theta 0.0695 all-in 1.05 on the cap, send.
    wire_101_poly = _all_in("0.50", "0.51", "polymarket")
    assert wire_101_poly == Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.50"), Decimal("0.51"), venue="polymarket"
    )
    assert ok is True, why

    # Wire 1.01 that fees push over 1.05: Gemini rounds each mid-price fee up a cent,
    # so 0.50+0.51 stays 1.05 (send). A documented skip is Poly 0.50+0.52 (1.02+0.04=1.06)
    # or Novig with no schedule. Prove the gate is all-in, not overnight wire 1.01:
    # 0.50+0.51 Kalshi still sends; Novig 0.50+0.51 fee-unknown skips.
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.50"), Decimal("0.51"), venue="kalshi"
    )
    assert ok is True, why
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.50"), Decimal("0.51"), venue="novig"
    )
    assert ok is False and skip_token in why and "unknown" in why

    gemini_101 = _all_in("0.50", "0.51", "gemini")
    assert gemini_101 == Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.50"), Decimal("0.51"), venue="gemini"
    )
    assert ok is True, why

    # Fees push over 1.05 on a 1.01-class book: Poly 0.47+0.54 is 1.05 send (on cap);
    # Poly 0.47+0.55 is wire 1.02 / all-in 1.06 skip. Gemini 0.50+0.52 same.
    poly_101 = _all_in("0.47", "0.54", "polymarket")
    assert poly_101 == Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.47"), Decimal("0.54"), venue="polymarket"
    )
    assert ok is True, why
    poly_over = _all_in("0.47", "0.55", "polymarket")
    assert poly_over is not None and poly_over > Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.47"), Decimal("0.55"), venue="polymarket"
    )
    assert ok is False and skip_token in why

    gemini_over = _all_in("0.50", "0.52", "gemini")
    assert gemini_over is not None and gemini_over > Decimal("1.05")
    ok, why = live_strategy_b.t0_yes_asks_send_ok(
        Decimal("0.50"), Decimal("0.52"), venue="gemini"
    )
    assert ok is False and skip_token in why

    assert live_strategy_b.pick_t0_book([_book("0.81", "0.57")]) is None
    assert live_strategy_b.pick_t0_book([_book("0.81", "0.29")]) is None
    assert live_strategy_b.pick_t0_book([_book("0.47", "0.54")]) is not None
    assert live_strategy_b.pick_t0_book([_book("0.47", "0.55")]) is None
    assert live_strategy_b.pick_t0_book([_book("0.47", "0.55", venue="polymarket")]) is None

    ready, why = live_strategy_b.t0_ready(
        {"t0_a": 0.81, "t0_b": 0.29, "t0_ts": 1, "venue": "kalshi"}
    )
    assert ready is False and skip_token in why
    ready, why = live_strategy_b.t0_ready(
        {"t0_a": 0.47, "t0_b": 0.54, "t0_ts": 1, "venue": "kalshi"}
    )
    assert ready is False and skip_token not in why  # clock, not C
    ready, why = live_strategy_b.t0_ready(
        {"t0_a": 0.89, "t0_b": 0.13, "t0_ts": 1, "venue": "polymarket"}
    )
    assert ready is False and skip_token not in why
    ready, why = live_strategy_b.t0_ready(
        {"t0_a": 0.47, "t0_b": 0.55, "t0_ts": 1, "venue": "polymarket"}
    )
    assert ready is False and skip_token in why

    saved_cap = live_strategy_b.T0_STACK_CAP
    live_strategy_b.T0_STACK_CAP = 1
    try:
        match = _t0_match("0.81", "0.29")
        assert _run_fire_t0(match, "0.81", "0.29") == []
        assert match["stage"] == "abandoned" and match.get("skip_reason") == skip_token

        match = _t0_match("0.47", "0.54")
        sent = _run_fire_t0(match, "0.47", "0.54")
        assert sent.count("b-t0") == 2
        assert match["stage"] == "waiting_cross"
        assert match.get("skip_reason") != skip_token

        match = _t0_match("0.89", "0.13", venue="polymarket", fee_coefficient="0.0695")
        sent = _run_fire_t0(match, "0.89", "0.13")
        assert sent.count("b-t0") == 2
        assert match.get("skip_reason") != skip_token

        match = _t0_match("0.50", "0.51", venue="polymarket", fee_coefficient="0.0695")
        sent = _run_fire_t0(match, "0.50", "0.51")
        assert sent.count("b-t0") == 2

        match = _t0_match("0.47", "0.55", venue="polymarket", fee_coefficient="0.0695")
        assert _run_fire_t0(match, "0.47", "0.55") == []
        assert match["stage"] == "abandoned" and match.get("skip_reason") == skip_token

        match = _t0_match("0.50", "0.51", venue="novig")
        assert _run_fire_t0(match, "0.50", "0.51") == []
        assert match["stage"] == "abandoned" and match.get("skip_reason") == skip_token
    finally:
        live_strategy_b.T0_STACK_CAP = saved_cap


def test_buy_short_fill_does_not_make_101_stack():
    match = _t0_match("0.47", "0.54", venue="polymarket", fee_coefficient="0.0695")
    match["t0_yes"]["a"].update(
        {"fill_px": "0.47", "fill_fee": "0.02", "intent": "ORDER_INTENT_BUY_LONG", "filled": True}
    )
    match["t0_yes"]["b"].update(
        {"fill_px": "0.46", "fill_fee": "0.02", "intent": "ORDER_INTENT_BUY_SHORT", "filled": True}
    )
    all_in = live_strategy_b.t0_fill_all_in(match)
    assert all_in is not None
    assert all_in >= Decimal("1")
    assert not live_strategy_b.should_stack_t0(all_in)


def test_fees_turn_099_wire_into_all_in_no_stack():
    match = _t0_match("0.49", "0.50", venue="polymarket", fee_coefficient="0.0695")
    sent = _run_fire_t0(match, "0.49", "0.50", fill_fee="0.02")
    assert sent.count("b-t0") == 2
    assert not any("t0-s" in step for step in sent)
    all_in = live_strategy_b.t0_fill_all_in(match)
    assert all_in is not None and all_in >= Decimal("1")
    assert not live_strategy_b.should_stack_t0(all_in)


def test_cross_fav_below_dog_paul_cases():
    token = live_strategy_b.CROSS_FAV_NOT_BELOW
    assert token == "cross_fav_not_below_dog"
    assert live_strategy_b.cross_fav_below_dog(Decimal("0.81"), Decimal("0.81")) == (
        False,
        token,
    )
    ok, why = live_strategy_b.cross_fav_below_dog(Decimal("0.51"), Decimal("0.52"))
    assert ok is True
    assert live_strategy_b.cross_fav_below_dog(Decimal("0.52"), Decimal("0.52")) == (
        False,
        token,
    )
    ok, why = live_strategy_b.cross_fav_below_dog(Decimal("0.48"), Decimal("0.52"))
    assert ok is True


def _patel_cross_match():
    return {
        "key": "tennis_patelkamboj_2026_10_25",
        "game": "Parv Patel vs. Udit Kamboj",
        "venue": "polymarket",
        "stage": "t0_filled_waiting_50_cross",
        "fav_player": "Kamboj, Udit",
        "dog_player": "Patel, Parv",
        "t0_fav_player": "Kamboj, Udit",
        "t0_dog_player": "Patel, Parv",
        "t0_yes": {
            "a": {
                "player": "Patel, Parv",
                "price": "0.23",
                "yes_ask": "0.23",
                "filled": True,
                "instrument": "aec-utr-patpar-kamudi-2026-10-25",
                "venue": "polymarket",
                "intent": "ORDER_INTENT_BUY_LONG",
            },
            "b": {
                "player": "Kamboj, Udit",
                "price": "0.8",
                "yes_ask": "0.8",
                "filled": True,
                "instrument": "aec-utr-patpar-kamudi-2026-10-25",
                "venue": "polymarket",
                "intent": "ORDER_INTENT_BUY_SHORT",
            },
        },
        "last_quotes": {},
    }


def _run_cross_asks(match, dog_ask, fav_ask, dog, fav):
    sent = []
    _TAPE.clear()
    live_strategy_b._tape_seen.clear()
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = _recheck_dog_fav(dog_ask, fav_ask, dog=dog, fav=fav)

    def fake_send(spec, pay, step, bet_key, log_fn=None):
        sent.append({"player": str(spec.get("player") or ""), "pay": str(pay), "step": step})
        return {
            "filled": True,
            "posted": True,
            "fill_qty": "1",
            "pay": str(pay),
            "fill_px": str(pay),
            "fill_fee": "0.01",
            "status": 200,
            "sent_at": "2026-10-24T23:37:44-04:00",
            "order_id": "x",
            "note": "",
        }

    live_strategy_b.send_yes_ioc = fake_send
    try:
        live_strategy_b.maybe_cross(match)
        return sent
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_cross_fav_not_below_dog_skips_and_sends():
    token = live_strategy_b.CROSS_FAV_NOT_BELOW
    dog, fav = "Patel, Parv", "Kamboj, Udit"

    skip_equal = _patel_cross_match()
    assert _run_cross_asks(skip_equal, "0.81", "0.81", dog, fav) == []
    assert token in (skip_equal.get("note") or "")
    assert skip_equal.get("cross_ioc_sent") is not True
    assert skip_equal["stage"] == "t0_filled_waiting_50_cross"

    skip_51 = _patel_cross_match()
    assert _run_cross_asks(skip_51, "0.52", "0.51", dog, fav) == []
    assert live_strategy_b.CROSS_ALLIN_OVER in (skip_51.get("note") or "")
    assert skip_51.get("cross_ioc_sent") is not True
    assert skip_51["stage"] == "t0_filled_waiting_50_cross"

    skip_tie = _patel_cross_match()
    assert _run_cross_asks(skip_tie, "0.52", "0.52", dog, fav) == []
    assert token in (skip_tie.get("note") or "")

    send_48 = _patel_cross_match()
    assert _run_cross_asks(send_48, "0.52", "0.48", dog, fav) == [
        {"player": dog, "pay": "0.52", "step": "b-cross"}
    ]


def test_cross_allin_c_105_paul_cases():
    """AND: fav Yes < dog Yes, and all-in C (asks + documented taker fees) <= 1.05.

    Patel 0.80+0.81 fails both. dog 0.52 + fav 0.48 all-in ~1.03 send.
    dog 0.52 + fav 0.51 fav is below but all-in >1.05 skip.
    dog 0.70 + fav 0.40 fav below but all-in >1.05 skip. No extra, no dip.
    """
    token = live_strategy_b.CROSS_ALLIN_OVER
    fav_token = live_strategy_b.CROSS_FAV_NOT_BELOW
    assert token == "cross_allin_c_over_105"
    dog, fav = "Patel, Parv", "Kamboj, Udit"
    spec = {"venue": "polymarket", "fee_coefficient": "0.0695"}

    patel = _all_in("0.80", "0.81", "polymarket")
    assert patel is not None and patel > Decimal("1.05")
    ok, why = live_strategy_b.cross_fav_below_dog(Decimal("0.81"), Decimal("0.80"))
    assert ok is False and why == fav_token
    ok, why = live_strategy_b.cross_allin_c_ok(spec, Decimal("0.80"), spec, Decimal("0.81"))
    assert ok is False and token in why
    skip_patel = _patel_cross_match()
    assert _run_cross_asks(skip_patel, "0.80", "0.81", dog, fav) == []
    assert fav_token in (skip_patel.get("note") or "")
    assert skip_patel.get("cross_ioc_sent") is not True
    assert skip_patel["stage"] == "t0_filled_waiting_50_cross"

    send_48 = _all_in("0.52", "0.48", "kalshi")
    assert send_48 is not None
    assert Decimal("1.02") <= send_48 <= Decimal("1.05")
    ok, why = live_strategy_b.cross_fav_below_dog(Decimal("0.48"), Decimal("0.52"))
    assert ok is True
    ok, why = live_strategy_b.cross_allin_c_ok(
        {"venue": "kalshi"}, Decimal("0.52"), {"venue": "kalshi"}, Decimal("0.48")
    )
    assert ok is True, why
    match_48 = _patel_cross_match()
    assert _run_cross_asks(match_48, "0.52", "0.48", dog, fav) == [
        {"player": dog, "pay": "0.52", "step": "b-cross"}
    ]
    assert match_48["stage"] == "waiting_fav_dip"
    assert match_48.get("cross_fill") == "0.52"

    skip_51 = _all_in("0.52", "0.51", "polymarket")
    assert skip_51 is not None and skip_51 > Decimal("1.05")
    ok, why = live_strategy_b.cross_fav_below_dog(Decimal("0.51"), Decimal("0.52"))
    assert ok is True
    ok, why = live_strategy_b.cross_allin_c_ok(spec, Decimal("0.52"), spec, Decimal("0.51"))
    assert ok is False and token in why
    match_51 = _patel_cross_match()
    assert _run_cross_asks(match_51, "0.52", "0.51", dog, fav) == []
    assert token in (match_51.get("note") or "")
    assert match_51.get("cross_ioc_sent") is not True
    assert match_51["stage"] == "t0_filled_waiting_50_cross"
    assert match_51.get("extra_stuck") is not True

    skip_70 = _all_in("0.70", "0.40", "polymarket")
    assert skip_70 is not None and skip_70 > Decimal("1.05")
    ok, why = live_strategy_b.cross_fav_below_dog(Decimal("0.40"), Decimal("0.70"))
    assert ok is True
    ok, why = live_strategy_b.cross_allin_c_ok(spec, Decimal("0.70"), spec, Decimal("0.40"))
    assert ok is False and token in why
    match_70 = _patel_cross_match()
    assert _run_cross_asks(match_70, "0.70", "0.40", dog, fav) == []
    assert token in (match_70.get("note") or "")
    assert match_70.get("cross_ioc_sent") is not True
    assert match_70["stage"] == "t0_filled_waiting_50_cross"
    assert match_70.get("extra_stuck") is not True

    kalshi_51 = _all_in("0.52", "0.51", "kalshi")
    assert kalshi_51 is not None and kalshi_51 > Decimal("1.05")
    ok, why = live_strategy_b.cross_allin_c_ok(
        {"venue": "kalshi"}, Decimal("0.52"), {"venue": "kalshi"}, Decimal("0.51")
    )
    assert ok is False and token in why
    ok, why = live_strategy_b.cross_allin_c_ok(
        {"venue": "novig"}, Decimal("0.52"), {"venue": "novig"}, Decimal("0.48")
    )
    assert ok is False and token in why and "unknown" in why


def test_patel_1137_replay_skips_fav_still_above_dog():
    """Tape 23:37:44 ET: dog Patel 0.80, fav Kamboj 0.81. New gate skips."""
    match = _patel_cross_match()
    sent = _run_cross_asks(match, "0.80", "0.81", "Patel, Parv", "Kamboj, Udit")
    assert sent == []
    assert live_strategy_b.CROSS_FAV_NOT_BELOW in (match.get("note") or "")
    assert match.get("cross_ioc_sent") is not True
    assert match["stage"] == "t0_filled_waiting_50_cross"
    assert (match.get("last_quotes") or {}).get("Patel, Parv", {}).get("ask") == "0.8"
    assert (match.get("last_quotes") or {}).get("Kamboj, Udit", {}).get("ask") == "0.81"
    cross_rows = [row for row in _TAPE if row.get("event") == "cross"]
    assert cross_rows
    snap = cross_rows[-1]
    assert snap.get("action") == "skip"
    assert str(snap.get("dog_yes") or "") in {"0.8", "0.80"}
    assert str(snap.get("fav_yes") or "") == "0.81"


def test_no_second_strategy_b_helper():
    import inspect
    import prediction_job_control

    ensure_src = inspect.getsource(prediction_job_control.ensure_strategy_b)
    assert 'if jobs.get("strategy_b")' in ensure_src
    assert "return False" in ensure_src
    reload_doc = inspect.getdoc(prediction_job_control.reload_strategy_b) or ""
    assert "poller" in reload_doc.lower()
    reload_src = inspect.getsource(prediction_job_control.reload_strategy_b)
    assert "_stop_pids" in reload_src
    assert "STRATEGY_B_SCRIPT" in reload_src
    assert "SUPERVISOR_SCRIPT" not in reload_src


def _shimizu_cross_match():
    return {
        "key": "tennis_shimizhsu_2026_10_27",
        "game": "Yuta Shimizu vs. Yu Hsiou Hsu",
        "venue": "polymarket",
        "stage": "t0_filled_waiting_50_cross",
        "fav_player": "Yu-Hsiou Hsu",
        "dog_player": "Yuta Shimizu",
        "t0_fav_player": "Yu-Hsiou Hsu",
        "t0_dog_player": "Yuta Shimizu",
        "t0_yes": {
            "a": {
                "player": "Yuta Shimizu",
                "price": "0.46",
                "yes_ask": "0.46",
                "filled": True,
                "instrument": "aec-atp-yutshi-yuhhsu-2026-10-27",
                "venue": "polymarket",
                "fee_coefficient": "0.0695",
            },
            "b": {
                "player": "Yu-Hsiou Hsu",
                "price": "0.55",
                "yes_ask": "0.55",
                "filled": True,
                "instrument": "aec-atp-yutshi-yuhhsu-2026-10-27",
                "venue": "polymarket",
                "fee_coefficient": "0.0695",
            },
        },
        "last_quotes": {},
    }


def test_t0_arm_budget_shrinks_when_waiting_cross():
    waiting = {"matches": [{"stage": "waiting_cross", "game": "Yuta Shimizu vs. Yu Hsiou Hsu"}]}
    idle = {"matches": [{"stage": "done", "game": "other"}]}
    assert live_strategy_b.t0_arm_budget_sec(waiting) == live_strategy_b.T0_ARM_BUDGET_WHEN_CROSS_SEC
    assert live_strategy_b.t0_arm_budget_sec(waiting) <= 0.25
    assert live_strategy_b.t0_arm_budget_sec(idle) == live_strategy_b.T0_ARM_BUDGET_SEC
    assert live_strategy_b.TICK_SEC <= 1
    assert live_strategy_b.CROSS_IDLE_SEC <= 0.1
    assert "continuous" in live_strategy_b.WATCH_CADENCE
    assert "memory" in live_strategy_b.WATCH_CADENCE


def test_extra_stuck_poly_partial_does_not_block_settle():
    """A 0.02 FOK leftover is extra_stuck, not an armed 50-cross. Settle hook still runs."""
    match = _shimizu_cross_match()
    match["extra_stuck"] = True
    match["last_order"] = {"id": "DC9R5HV011TB", "fill_qty": "0.02", "http": 200}
    status = {"matches": [match]}
    assert live_strategy_b.open_cross_matches(status) == []
    assert live_strategy_b.t0_arm_budget_sec(status) == live_strategy_b.T0_ARM_BUDGET_SEC
    order = []

    def rec(name, result=None):
        def _fn(*_a, **_k):
            order.append(name)
            return result
        return _fn

    saved = {
        "caps": live_strategy_b.live_b_caps,
        "load": live_strategy_b.load_status,
        "save": live_strategy_b.save_status,
        "pump": live_strategy_b._pump_ticks,
        "merge": live_strategy_b._merge_price_last,
        "slate": live_strategy_b.tennis_slate,
        "scan": live_strategy_b._scan_mod,
        "try_t0": live_strategy_b.try_t0,
        "process": live_strategy_b.process_open,
        "arm": live_strategy_b._arm_new_matches,
        "cluster": live_strategy_b.cluster_counts,
        "postponed": live_strategy_b.live_postponed_reason,
        "settle": live_strategy_b.note_settled_holds,
        "open": live_strategy_b.open_matches,
    }
    live_strategy_b.live_b_caps = lambda: (True, 4)
    live_strategy_b.load_status = lambda *a, **k: status
    live_strategy_b.save_status = rec("save")
    live_strategy_b._pump_ticks = rec("pump")
    live_strategy_b._merge_price_last = rec("merge")
    live_strategy_b.tennis_slate = rec("tennis_slate", [])
    live_strategy_b._scan_mod = rec("scan", object())
    live_strategy_b.try_t0 = rec("try_t0", "no T0 yet")
    live_strategy_b.process_open = rec("process_open")
    live_strategy_b._arm_new_matches = rec("arm_new")
    live_strategy_b.cluster_counts = lambda *_a, **_k: {}
    live_strategy_b.live_postponed_reason = lambda *_a, **_k: ""
    live_strategy_b.note_settled_holds = rec("settle")
    live_strategy_b.open_matches = lambda *_a, **_k: [match]
    try:
        live_strategy_b.tick()
        assert "settle" in order
    finally:
        for name, fn in saved.items():
            setattr(
                live_strategy_b,
                {
                    "caps": "live_b_caps",
                    "load": "load_status",
                    "save": "save_status",
                    "pump": "_pump_ticks",
                    "merge": "_merge_price_last",
                    "slate": "tennis_slate",
                    "scan": "_scan_mod",
                    "try_t0": "try_t0",
                    "process": "process_open",
                    "arm": "_arm_new_matches",
                    "cluster": "cluster_counts",
                    "postponed": "live_postponed_reason",
                    "settle": "note_settled_holds",
                    "open": "open_matches",
                }[name],
                fn,
            )


def test_shimizu_memory_052_sends_immediately_not_180s():
    """First 50¢ memory tick (00:23:57 0.52) must REST+send now, not 180s later."""
    match = _shimizu_cross_match()
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yuta Shimizu", "0.52")
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yu-Hsiou Hsu", "0.49")
    sent = []
    rest = []
    sleeps = []

    def fake_recheck(spec, *a, **k):
        rest.append({"player": spec.get("player"), "pace": k.get("pace", "missing")})
        player = str(spec.get("player") or "")
        if "Hsu" in player:
            return Decimal("0.49"), "book"
        return Decimal("0.52"), "book"

    def fake_send(spec, pay, step, bet_key, log_fn=None):
        sent.append({"player": spec.get("player"), "pay": str(pay), "step": step})
        return {
            "filled": True,
            "posted": True,
            "fill_qty": "1",
            "pay": str(pay),
            "fill_px": str(pay),
            "fill_fee": "0.02",
            "status": 200,
            "sent_at": "2026-10-28T00:23:57.500-04:00",
            "order_id": "shim-cross",
            "note": "",
        }

    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = fake_recheck
    live_strategy_b.send_yes_ioc = fake_send
    try:
        with patch("time.sleep", side_effect=lambda sec: sleeps.append(float(sec))):
            live_strategy_b.maybe_cross(match)
        assert sent == [{"player": "Yuta Shimizu", "pay": "0.52", "step": "b-cross"}]
        assert rest and all(row.get("pace") is False for row in rest)
        assert not any(sec >= 180 for sec in sleeps)
        assert match.get("cross_ioc_sent") is True
        assert match.get("cross_player") == "Yuta Shimizu"
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_shimizu_memory_049_does_not_send_or_rest():
    match = _shimizu_cross_match()
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yuta Shimizu", "0.49")
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yu-Hsiou Hsu", "0.52")
    sent = []
    rest = []
    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = lambda *a, **k: rest.append(1) or (Decimal("0.52"), "book")
    live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append(1) or {"filled": False}
    try:
        live_strategy_b.maybe_cross(match)
        assert sent == []
        assert rest == []
        assert match.get("cross_ioc_sent") is not True
        assert str(match.get("stage") or "") == "t0_filled_waiting_50_cross"
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_shimizu_cross_does_not_double_send():
    match = _shimizu_cross_match()
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yuta Shimizu", "0.52")
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yu-Hsiou Hsu", "0.49")
    sent = []

    def fake_recheck(spec, *a, **k):
        player = str(spec.get("player") or "")
        if "Hsu" in player:
            return Decimal("0.49"), "book"
        return Decimal("0.52"), "book"

    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = fake_recheck
    live_strategy_b.send_yes_ioc = lambda spec, pay, step, bet_key, log_fn=None: sent.append(step) or {
        "filled": True,
        "posted": True,
        "fill_qty": "1",
        "pay": str(pay),
        "fill_px": str(pay),
        "fill_fee": "0.02",
        "status": 200,
        "sent_at": "2026-10-28T00:23:57.500-04:00",
        "order_id": "shim-cross",
        "note": "",
    }
    try:
        live_strategy_b.maybe_cross(match)
        live_strategy_b.maybe_cross(match)
        live_strategy_b.process_open(match)
        assert sent == ["b-cross"]
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_maybe_cross_is_not_only_once_per_long_tick():
    """Gate: 50-cross pump is tick_cross_only every 50ms, not maybe_cross once per TICK_SEC."""
    loop_src = inspect.getsource(live_strategy_b.loop)
    tick_src = inspect.getsource(live_strategy_b.tick)
    cross_src = inspect.getsource(live_strategy_b.tick_cross_only)
    arm_src = inspect.getsource(live_strategy_b._arm_new_matches)
    assert "tick_cross_only" in loop_src
    assert "CROSS_IDLE_SEC" in loop_src
    assert live_strategy_b.CROSS_IDLE_SEC <= 0.1
    assert live_strategy_b.TICK_SEC <= 1
    assert live_strategy_b.T0_ARM_BUDGET_WHEN_CROSS_SEC <= 0.25
    assert "_process_hot_opens" in cross_src
    assert "try_t0" not in cross_src
    assert "tennis_slate" not in cross_src
    assert "_arm_new_matches" not in cross_src
    assert tick_src.find("_process_hot_opens") < tick_src.find("tennis_slate")
    assert tick_src.find("_process_hot_opens") < tick_src.find("_arm_new_matches")
    assert tick_src.find("_process_hot_opens") < tick_src.find("try_t0")
    assert arm_src.find("_process_hot_opens") > 0
    assert "try_t0" in arm_src


def test_t0_hunt_does_not_run_before_50_cross_watches():
    """While a 50-cross is armed, process_open/maybe_cross runs before slate walk / try_t0."""
    order = []
    match = _shimizu_cross_match()
    status = {"matches": [match], "queued": [], "skipped": []}

    def rec(name, result=None):
        def _fn(*_a, **_k):
            order.append(name)
            return result
        return _fn

    saved = {
        "caps": live_strategy_b.live_b_caps,
        "load": live_strategy_b.load_status,
        "save": live_strategy_b.save_status,
        "pump": live_strategy_b._pump_ticks,
        "merge": live_strategy_b._merge_price_last,
        "slate": live_strategy_b.tennis_slate,
        "scan": live_strategy_b._scan_mod,
        "try_t0": live_strategy_b.try_t0,
        "process": live_strategy_b.process_open,
        "arm": live_strategy_b._arm_new_matches,
        "cluster": live_strategy_b.cluster_counts,
        "postponed": live_strategy_b.live_postponed_reason,
        "settle": live_strategy_b.note_settled_holds,
        "open": live_strategy_b.open_matches,
    }
    live_strategy_b.live_b_caps = lambda: (True, 4)
    live_strategy_b.load_status = lambda *a, **k: status
    live_strategy_b.save_status = rec("save")
    live_strategy_b._pump_ticks = rec("pump")
    live_strategy_b._merge_price_last = rec("merge")
    live_strategy_b.tennis_slate = rec(
        "tennis_slate",
        [{"title": "Other vs Foo", "key": "other", "listed_start": ""}],
    )
    live_strategy_b._scan_mod = rec("scan", object())
    live_strategy_b.try_t0 = rec("try_t0", "no T0 yet")
    live_strategy_b.process_open = rec("process_open")
    live_strategy_b.cluster_counts = lambda *_a, **_k: {}
    live_strategy_b.live_postponed_reason = lambda *_a, **_k: ""
    live_strategy_b.note_settled_holds = rec("settle")
    live_strategy_b.open_matches = lambda *_a, **_k: [match]

    def fake_arm(*_a, **_k):
        order.append("arm_new")
        live_strategy_b.try_t0(object(), {"title": "Other vs Foo"}, status)

    live_strategy_b._arm_new_matches = fake_arm
    try:
        live_strategy_b.tick()
        assert "process_open" in order
        assert "tennis_slate" in order
        assert "arm_new" in order
        assert "try_t0" in order
        assert order.index("process_open") < order.index("tennis_slate")
        assert order.index("process_open") < order.index("arm_new")
        assert order.index("process_open") < order.index("try_t0")
        assert "settle" not in order
    finally:
        for name, fn in saved.items():
            setattr(
                live_strategy_b,
                {
                    "caps": "live_b_caps",
                    "load": "load_status",
                    "save": "save_status",
                    "pump": "_pump_ticks",
                    "merge": "_merge_price_last",
                    "slate": "tennis_slate",
                    "scan": "_scan_mod",
                    "try_t0": "try_t0",
                    "process": "process_open",
                    "arm": "_arm_new_matches",
                    "cluster": "cluster_counts",
                    "postponed": "live_postponed_reason",
                    "settle": "note_settled_holds",
                    "open": "open_matches",
                }[name],
                fn,
            )


def test_tick_cross_only_does_not_walk_t0_slate():
    order = []
    match = _shimizu_cross_match()
    status = {"matches": [match], "queued": [], "skipped": []}
    saved = {
        "caps": live_strategy_b.live_b_caps,
        "load": live_strategy_b.load_status,
        "save": live_strategy_b.save_status,
        "pump": live_strategy_b._pump_ticks,
        "merge": live_strategy_b._merge_price_last,
        "slate": live_strategy_b.tennis_slate,
        "try_t0": live_strategy_b.try_t0,
        "process": live_strategy_b.process_open,
        "arm": live_strategy_b._arm_new_matches,
    }
    live_strategy_b.live_b_caps = lambda: (True, 4)
    live_strategy_b.load_status = lambda *a, **k: status
    live_strategy_b.save_status = lambda *_a, **_k: order.append("save")
    live_strategy_b._pump_ticks = lambda: order.append("pump")
    live_strategy_b._merge_price_last = lambda: order.append("merge")
    live_strategy_b.tennis_slate = lambda: order.append("tennis_slate") or []
    live_strategy_b.try_t0 = lambda *_a, **_k: order.append("try_t0") or "no T0 yet"
    live_strategy_b.process_open = lambda *_a, **_k: order.append("process_open")
    live_strategy_b._arm_new_matches = lambda *_a, **_k: order.append("arm_new")
    try:
        out = live_strategy_b.tick_cross_only(status)
        assert out is status
        assert "process_open" in order
        assert "try_t0" not in order
        assert "tennis_slate" not in order
        assert "arm_new" not in order
    finally:
        live_strategy_b.live_b_caps = saved["caps"]
        live_strategy_b.load_status = saved["load"]
        live_strategy_b.save_status = saved["save"]
        live_strategy_b._pump_ticks = saved["pump"]
        live_strategy_b._merge_price_last = saved["merge"]
        live_strategy_b.tennis_slate = saved["slate"]
        live_strategy_b.try_t0 = saved["try_t0"]
        live_strategy_b.process_open = saved["process"]
        live_strategy_b._arm_new_matches = saved["arm"]


def _hsu_after_cross(fill="0.60", fav_ask="0.38", venue="polymarket"):
    match = _shimizu_cross_match()
    match["stage"] = "waiting_fav_dip"
    match["cross_fill"] = fill
    match["cross_fee"] = "0"
    match["cross_ioc_sent"] = True
    match["cross_player"] = "Yuta Shimizu"
    match["fav_target"] = str(live_strategy_b.fav_target(Decimal(fill)))
    match["venue"] = venue
    match["t0_yes"]["a"]["venue"] = venue
    match["t0_yes"]["b"]["venue"] = venue
    return match, Decimal(str(fav_ask))


def test_hsu_gtc_rests_at_15c_after_60c_cross():
    """Shimizu fill 0.60 → Hsu GTC at 0.15, not cross−25¢, even if min print is 38¢."""
    match, ask = _hsu_after_cross("0.60", "0.38")
    sent = []
    cancelled = []

    def fake_gtc(spec, pay, step, bet_key, log_fn=None):
        sent.append({"player": spec.get("player"), "pay": str(pay), "step": step, "tif": "gtc"})
        return {
            "filled": False,
            "posted": True,
            "fill_qty": "0",
            "pay": str(pay),
            "status": 200,
            "order_id": "hsu-gtc",
            "note": "resting",
            "resting": True,
            "tif": live_lock_orders.POLY_TIF_GTC,
            "payload": {"id": "hsu-gtc", "state": "ORDER_STATE_OPEN", "leavesQuantity": "1"},
        }

    saved_recheck = live_strategy_b.recheck_yes
    saved_ioc = live_strategy_b.send_yes_ioc
    saved_gtc = live_strategy_b.send_yes_gtc
    saved_poll = live_strategy_b.poll_fav_gtc_fill
    saved_net = live_strategy_b.extra_pair_net_ok
    saved_cancel = live_lock_orders._cancel
    live_strategy_b.recheck_yes = lambda spec, *a, **k: (ask, "book")
    live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append({"kind": "ioc"}) or {"filled": False}
    live_strategy_b.send_yes_gtc = fake_gtc
    live_strategy_b.poll_fav_gtc_fill = lambda _m: False
    live_strategy_b.extra_pair_net_ok = lambda *a, **k: True
    live_lock_orders._cancel = lambda *a, **k: cancelled.append(1) or (200, "cancelled")
    try:
        live_strategy_b.maybe_fav_dip(match)
        live_strategy_b.maybe_fav_dip(match)
        live_strategy_b.process_open(match)
        assert sent == [
            {
                "player": "Yu-Hsiou Hsu",
                "pay": "0.15",
                "step": "b-fav",
                "tif": "gtc",
            }
        ]
        assert live_strategy_b.fav_target(Decimal("0.60")) == Decimal("0.15")
        assert match["stage"] == "fav_gtc_resting"
        assert match.get("fav_ioc_sent") is True
        assert match.get("fav_gtc_sent") is True
        assert cancelled == []
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_ioc
        live_strategy_b.send_yes_gtc = saved_gtc
        live_strategy_b.poll_fav_gtc_fill = saved_poll
        live_strategy_b.extra_pair_net_ok = saved_net
        live_lock_orders._cancel = saved_cancel


def test_fav_already_at_target_uses_ioc_not_gtc():
    match, ask = _hsu_after_cross("0.60", "0.15")
    sent = []
    saved_recheck = live_strategy_b.recheck_yes
    saved_ioc = live_strategy_b.send_yes_ioc
    saved_gtc = live_strategy_b.send_yes_gtc
    saved_net = live_strategy_b.extra_pair_net_ok
    live_strategy_b.recheck_yes = lambda spec, *a, **k: (ask, "book")
    live_strategy_b.send_yes_ioc = lambda spec, pay, step, bet_key, log_fn=None: sent.append(
        {"kind": "ioc", "pay": str(pay), "step": step}
    ) or {
        "filled": True,
        "posted": True,
        "fill_qty": "1",
        "pay": str(pay),
        "fill_px": str(pay),
        "fill_fee": "0",
        "status": 200,
        "order_id": "hsu-ioc",
        "note": "",
        "payload": {"id": "hsu-ioc", "cumQuantity": "1"},
    }
    live_strategy_b.send_yes_gtc = lambda *a, **k: sent.append({"kind": "gtc"}) or {"filled": False}
    live_strategy_b.extra_pair_net_ok = lambda *a, **k: True
    try:
        live_strategy_b.maybe_fav_dip(match)
        assert sent == [{"kind": "ioc", "pay": "0.15", "step": "b-fav"}]
        assert match["stage"] == "done"
        assert match.get("fav_fill") == "0.15"
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_ioc
        live_strategy_b.send_yes_gtc = saved_gtc
        live_strategy_b.extra_pair_net_ok = saved_net


def test_gtc_not_rested_when_extra_pair_net_fails():
    match, ask = _hsu_after_cross("0.60", "0.38")
    sent = []
    saved_recheck = live_strategy_b.recheck_yes
    saved_gtc = live_strategy_b.send_yes_gtc
    saved_net = live_strategy_b.extra_pair_net_ok
    live_strategy_b.recheck_yes = lambda spec, *a, **k: (ask, "book")
    live_strategy_b.send_yes_gtc = lambda *a, **k: sent.append(1) or {"filled": False}
    live_strategy_b.extra_pair_net_ok = lambda *a, **k: False
    try:
        live_strategy_b.maybe_fav_dip(match)
        assert sent == []
        assert match["stage"] == "waiting_fav_dip"
        assert "not rested" in (match.get("note") or "")
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_gtc = saved_gtc
        live_strategy_b.extra_pair_net_ok = saved_net


def test_absorb_cancels_resting_fav_gtc():
    match, ask = _hsu_after_cross("0.60", "0.95")
    match["stage"] = "fav_gtc_resting"
    match["fav_gtc_sent"] = True
    match["fav_ioc_sent"] = True
    match["fav_gtc_order_id"] = "hsu-gtc"
    match["fav_gtc_spec"] = {"venue": "polymarket", "instrument": "aec-atp-yutshi-yuhhsu-2026-10-27"}
    match["fav_gtc_payload"] = {"id": "hsu-gtc", "state": "open"}
    cancelled = []
    saved_cancel = live_lock_orders._cancel
    saved_latest = live_strategy_b.latest_yes
    live_lock_orders._cancel = lambda spec, payload: cancelled.append(
        (spec.get("venue"), live_lock_orders._order_id(payload))
    ) or (200, "cancelled")
    live_strategy_b.latest_yes = lambda game, venue, player: Decimal("0.95")
    try:
        live_strategy_b.process_open(match)
        assert match["stage"] == "absorbed"
        assert cancelled == [("polymarket", "hsu-gtc")]
        assert match.get("fav_gtc_cancelled") is True
    finally:
        live_lock_orders._cancel = saved_cancel
        live_strategy_b.latest_yes = saved_latest


def test_poly_fav_gtc_tif_is_not_fok():
    spec = {
        "venue": "polymarket",
        "instrument": "aec-atp-yutshi-yuhhsu-2026-10-27",
        "intent": "ORDER_INTENT_BUY_LONG",
        "quote_size": "5",
        "quote_source": "book",
        "player": "Yu-Hsiou Hsu",
    }
    posted = []
    cancelled = []

    def fake_send(built):
        posted.append(built.get("body", {}).get("tif"))
        assert built.get("_tif") == "gtc"
        payload = {
            "id": "oid-gtc-1",
            "state": "ORDER_STATE_OPEN",
            "leavesQuantity": "1",
            "cumQuantity": "0",
        }
        return 200, payload, "resting"

    saved_send = live_lock_orders._send
    saved_funds = live_lock_orders._funds_block
    saved_append = live_lock_orders._append
    saved_cancel = live_lock_orders._cancel
    live_lock_orders._send = fake_send
    live_lock_orders._funds_block = lambda _spec: ""
    live_lock_orders._append = lambda _row: None
    live_lock_orders._cancel = lambda *a, **k: cancelled.append(1) or (200, "cancelled")
    try:
        result = live_strategy_b.send_yes_gtc(spec, Decimal("0.15"), "b-fav", "k")
    finally:
        live_lock_orders._send = saved_send
        live_lock_orders._funds_block = saved_funds
        live_lock_orders._append = saved_append
        live_lock_orders._cancel = saved_cancel
    assert posted == [live_lock_orders.POLY_TIF_GTC]
    assert posted != [live_lock_orders.POLY_TIF_FOK]
    assert result["posted"] is True
    assert result["filled"] is False
    assert cancelled == []
    assert live_lock_orders.POLY_TIF_GTC != live_lock_orders.POLY_TIF_FOK


def test_venue_gtc_tif_strings():
    assert live_strategy_b.venue_gtc_tif("kalshi") == ("time_in_force", "good_till_canceled")
    assert live_strategy_b.venue_gtc_tif("gemini") == ("timeInForce", "good-til-cancel")
    assert live_strategy_b.venue_gtc_tif("polymarket")[1] == live_lock_orders.POLY_TIF_GTC
    assert live_strategy_b.venue_gtc_tif("novig") == ("tif", "GTC")
    assert live_strategy_b.venue_gtc_tif("unknown") is None
    built = {
        "venue": "kalshi",
        "body": {"time_in_force": "immediate_or_cancel", "ticker": "X"},
    }
    ok, tif = live_strategy_b.apply_gtc_body(built)
    assert ok is True
    assert tif == "good_till_canceled"
    assert built["body"]["time_in_force"] == "good_till_canceled"
    poly = {
        "venue": "polymarket",
        "body": {"tif": live_lock_orders.POLY_TIF_FOK, "synchronousExecution": True},
    }
    ok, tif = live_strategy_b.apply_gtc_body(poly)
    assert ok is True
    assert tif == live_lock_orders.POLY_TIF_GTC
    assert poly["body"]["tif"] != live_lock_orders.POLY_TIF_FOK
    assert poly["body"]["synchronousExecution"] is False
    gem = {"venue": "gemini", "body": {"timeInForce": "immediate-or-cancel", "makerOrCancel": True}}
    ok, tif = live_strategy_b.apply_gtc_body(gem)
    assert ok is True
    assert gem["body"]["timeInForce"] == "good-til-cancel"
    assert gem["body"]["makerOrCancel"] is False
    nov = {"venue": "novig", "body": {"tif": "IOC"}}
    ok, tif = live_strategy_b.apply_gtc_body(nov)
    assert ok is True
    assert nov["body"]["tif"] == "GTC"
    assert live_lock_orders._is_gtc_spec(nov) is True
    skip = {"venue": "blank-shop", "body": {}}
    ok, why = live_strategy_b.apply_gtc_body(skip)
    assert ok is False
    assert "gtc_unsupported" in why


def test_hours_away_listed_does_not_t0_on_early_occurrence():
    """Parks vs Birrell: occurrence 00:30, listed 21:30, send at 00:32 must not T0."""
    now = datetime(2026, 10, 28, 0, 32, tzinfo=ET)
    occ = datetime(2026, 10, 28, 0, 30, tzinfo=ET)
    listed = datetime(2026, 10, 28, 21, 30, tzinfo=ET)
    pair = {
        "t0_a": 0.40,
        "t0_b": 0.61,
        "t0_ts": int(occ.timestamp()),
        "occ_dt": occ,
        "occurrence": occ.isoformat(),
        "listed_dt": listed,
        "listed_start": listed.isoformat(),
        "actual_start": occ.isoformat(),
        "actual_source": "occurrence",
        "t0_label": "mixed pre-start + first in-game (occurrence)",
        "yes_a": [(int(occ.timestamp()), 0.40)],
        "yes_b": [(int(occ.timestamp()), 0.61)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False, why
    assert "waiting trusted actual start" in why
    clock, src = live_strategy_b.live_trusted_clock(pair, now)
    assert clock == listed
    assert src == "listed/feed"


def test_t0_fires_within_15s_of_later_listed():
    now = datetime(2026, 10, 28, 21, 29, 50, tzinfo=ET)
    occ = datetime(2026, 10, 28, 0, 30, tzinfo=ET)
    listed = datetime(2026, 10, 28, 21, 30, tzinfo=ET)
    pair = {
        "t0_a": 0.40,
        "t0_b": 0.61,
        "t0_ts": int(listed.timestamp()),
        "occ_dt": occ,
        "occurrence": occ.isoformat(),
        "listed_dt": listed,
        "listed_start": listed.isoformat(),
        "actual_start": listed.isoformat(),
        "actual_source": "listed/feed",
        "t0_label": "last two-sided Yes <= listed/feed",
        "yes_a": [(int(listed.timestamp()), 0.40)],
        "yes_b": [(int(listed.timestamp()), 0.61)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is True, why
    too_early = datetime(2026, 10, 28, 21, 29, 40, tzinfo=ET)
    ok, why = live_strategy_b.t0_ready(pair, too_early)
    assert ok is False
    assert "waiting trusted actual start" in why


def test_liu_colby_next_day_live_start_does_not_t0():
    """Listed 14:00 28 Oct, live start next day 16:20 — T0 at 14:03 must wait."""
    now = datetime(2026, 10, 28, 14, 3, tzinfo=ET)
    listed = datetime(2026, 10, 28, 14, 0, tzinfo=ET)
    live = datetime(2026, 10, 29, 16, 20, tzinfo=ET)
    pair = {
        "t0_a": 0.46,
        "t0_b": 0.45,
        "t0_ts": int(listed.timestamp()),
        "listed_dt": listed,
        "listed_start": listed.isoformat(),
        "live_dt": live,
        "live_start": live.isoformat(),
        "t0_label": "mixed pre-start + first in-game (listed/feed)",
        "yes_a": [(int(listed.timestamp()), 0.46)],
        "yes_b": [(int(listed.timestamp()), 0.45)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False, why
    assert "waiting trusted actual start" in why
    clock, src = live_strategy_b.live_trusted_clock(pair, now)
    assert clock == live
    assert "next day" in src
    clock2, src2 = live_t0_yes.choose_trusted_t0_clock(None, listed, live)
    assert clock2 == live
    assert src2 == "live start (next day)"


def test_cross_refuses_hours_before_trusted_t0():
    match = _shimizu_cross_match()
    listed = datetime(2026, 10, 29, 16, 20, tzinfo=ET)
    match["listed_start"] = listed.isoformat()
    now = datetime(2026, 10, 29, 13, 50, tzinfo=ET)
    with patch.object(live_strategy_b, "_poly_event_snapshot", return_value={}), patch.object(
        live_strategy_b, "now_et", return_value=now
    ):
        ok, why = live_strategy_b.extras_cross_clock_ok(match, now)
        assert ok is False
        assert live_strategy_b.CROSS_BEFORE_START in why
        sent = []
        saved_send = live_strategy_b.send_yes_ioc
        live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append(a) or {"filled": False}
        try:
            live_strategy_b.maybe_cross(match)
            assert sent == []
            assert live_strategy_b.CROSS_BEFORE_START in str(match.get("note") or "")
        finally:
            live_strategy_b.send_yes_ioc = saved_send


def test_cheapest_legs_picks_poly_60_and_kalshi_39():
    """Birrell 0.61 Kalshi vs 0.60 Poly; opponent 0.40 Poly vs 0.39 Kalshi."""
    books = [
        {
            "venue": "kalshi",
            "title": "Parks vs Birrell",
            "players": [
                {"player": "Alycia Parks", "pay": Decimal("0.39"), "venue": "kalshi", "instrument": "PAR"},
                {"player": "Kimberly Birrell", "pay": Decimal("0.61"), "venue": "kalshi", "instrument": "BIR"},
            ],
        },
        {
            "venue": "polymarket",
            "title": "Parks vs Birrell",
            "players": [
                {
                    "player": "Alycia Parks",
                    "pay": Decimal("0.40"),
                    "venue": "polymarket",
                    "instrument": "poly-parks",
                    "intent": "ORDER_INTENT_BUY_LONG",
                    "fee_coefficient": "0.0695",
                },
                {
                    "player": "Kimberly Birrell",
                    "pay": Decimal("0.60"),
                    "venue": "polymarket",
                    "instrument": "poly-birrell",
                    "intent": "ORDER_INTENT_BUY_LONG",
                    "fee_coefficient": "0.0695",
                },
            ],
        },
    ]
    picked = live_strategy_b.pick_cheapest_legs(books)
    assert picked is not None
    players = {live_strategy_b._player_id(row["player"]): row for row in picked["players"]}
    assert players["birrell"]["venue"] == "polymarket"
    assert players["birrell"]["pay"] == Decimal("0.60")
    assert players["parks"]["venue"] == "kalshi"
    assert players["parks"]["pay"] == Decimal("0.39")
    same = live_strategy_b.pick_t0_book([books[0]])
    assert same is not None
    assert all(row.get("venue") == "kalshi" for row in same["players"])


def test_cheapest_legs_poly_dog_kalshi_fav_beats_both_novig():
    """Cheapest Yes per player across shops. Both-Novig is not forced."""
    saved_live = novig_live.orders_live
    novig_live.orders_live = lambda: True
    novig = {
        "venue": "novig",
        "title": "Podoroska vs Monnet",
        "players": [
            {
                "player": "Nadia Podoroska",
                "pay": Decimal("0.55"),
                "venue": "novig",
                "instrument": "NV-POD",
                "fee_coefficient": "0.06",
                "fee_charged": "ALWAYS",
                "event_status": "OPEN_INGAME",
            },
            {
                "player": "Carole Monnet",
                "pay": Decimal("0.50"),
                "venue": "novig",
                "instrument": "NV-MON",
                "fee_coefficient": "0.06",
                "fee_charged": "ALWAYS",
                "event_status": "OPEN_INGAME",
            },
        ],
    }
    books = [
        novig,
        {
            "venue": "polymarket",
            "title": "Podoroska vs Monnet",
            "players": [
                {
                    "player": "Nadia Podoroska",
                    "pay": Decimal("0.48"),
                    "venue": "polymarket",
                    "instrument": "poly-pod",
                    "intent": "ORDER_INTENT_BUY_LONG",
                    "fee_coefficient": "0.0695",
                },
                {
                    "player": "Carole Monnet",
                    "pay": Decimal("0.52"),
                    "venue": "polymarket",
                    "instrument": "poly-mon",
                    "intent": "ORDER_INTENT_BUY_LONG",
                    "fee_coefficient": "0.0695",
                },
            ],
        },
        {
            "venue": "kalshi",
            "title": "Podoroska vs Monnet",
            "players": [
                {"player": "Nadia Podoroska", "pay": Decimal("0.54"), "venue": "kalshi", "instrument": "K-POD"},
                {"player": "Carole Monnet", "pay": Decimal("0.45"), "venue": "kalshi", "instrument": "K-MON"},
            ],
        },
    ]
    try:
        ranked = live_strategy_b.rank_cheapest_legs(books)
        assert ranked is not None
        players = {live_strategy_b._player_id(row["player"]): row for row in ranked["players"]}
        assert players["podoroska"]["venue"] == "polymarket"
        assert players["podoroska"]["pay"] == Decimal("0.48")
        assert players["monnet"]["venue"] == "kalshi"
        assert players["monnet"]["pay"] == Decimal("0.45")
        assert ranked["venue"] == "multi"
        picked = live_strategy_b.pick_cheapest_legs(books)
        assert picked is not None
        assert picked["venue"] == "multi"
        same = live_strategy_b.pick_cheapest_legs([novig])
        assert same is None
        novig_ranked = live_strategy_b.rank_cheapest_legs([novig])
        assert novig_ranked is not None
        assert all(row.get("venue") == "novig" for row in novig_ranked["players"])
    finally:
        novig_live.orders_live = saved_live


def test_t0_grace_thirty_minutes_holds_c_and_d():
    assert live_strategy_b.T0_GRACE_SEC == 1800
    assert live_strategy_b.t0_grace_minutes() == 30
    assert live_strategy_b.C_HI == Decimal("1.05")
    assert live_strategy_b.D == Decimal("0.25")
    assert live_t0_yes.T0_GRACE_SEC == 300


def test_t0_ready_at_29_min_still_in_window():
    listed = datetime(2026, 10, 31, 10, 0, 0, tzinfo=ET)
    now = listed + timedelta(minutes=29)
    pair = {
        "t0_a": 0.40,
        "t0_b": 0.61,
        "t0_ts": int(listed.timestamp()),
        "listed_dt": listed,
        "listed_start": listed.isoformat(),
        "actual_start": listed.isoformat(),
        "actual_source": "listed/feed",
        "t0_label": "last two-sided Yes <= listed/feed",
        "yes_a": [(int(listed.timestamp()), 0.40)],
        "yes_b": [(int(listed.timestamp()), 0.61)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is True, why


def test_t0_ready_at_31_min_missed_window():
    listed = datetime(2026, 10, 31, 10, 0, 0, tzinfo=ET)
    now = listed + timedelta(minutes=31)
    pair = {
        "t0_a": 0.40,
        "t0_b": 0.61,
        "t0_ts": int(listed.timestamp()),
        "listed_dt": listed,
        "listed_start": listed.isoformat(),
        "actual_start": listed.isoformat(),
        "actual_source": "listed/feed",
        "t0_label": "last two-sided Yes <= listed/feed",
        "yes_a": [(int(listed.timestamp()), 0.40)],
        "yes_b": [(int(listed.timestamp()), 0.61)],
    }
    ok, why = live_strategy_b.t0_ready(pair, now)
    assert ok is False
    assert "missed T0 window" in why


def test_prepare_book_rests_all_shops_not_memory_winners():
    src = inspect.getsource(live_strategy_b._prepare_book)
    assert "venues=mem_venues" not in src
    assert "moneyline_yes_books(scan, spec)" in src
    assert "rank_cheapest_legs" in src


def test_cross_uses_cheapest_dog_platform():
    match = _shimizu_cross_match()
    match["shop"] = {
        "shimizu": {
            "polymarket": dict(match["t0_yes"]["a"]),
            "kalshi": {
                "player": "Yuta Shimizu",
                "venue": "kalshi",
                "instrument": "KX-SHIM",
                "pay": "0.53",
            },
        },
        "hsu": {
            "polymarket": dict(match["t0_yes"]["b"]),
            "kalshi": {
                "player": "Yu-Hsiou Hsu",
                "venue": "kalshi",
                "instrument": "KX-HSU",
                "pay": "0.48",
            },
        },
    }
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yuta Shimizu", "0.52")
    live_strategy_b.remember_live_yes(match["game"], "kalshi", "Yuta Shimizu", "0.53")
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yu-Hsiou Hsu", "0.49")
    live_strategy_b.remember_live_yes(match["game"], "kalshi", "Yu-Hsiou Hsu", "0.48")
    sent = []

    def fake_recheck(spec, *a, **k):
        venue = str(spec.get("venue") or "")
        player = str(spec.get("player") or "")
        if "Shimizu" in player:
            return Decimal("0.52") if venue == "polymarket" else Decimal("0.53"), "book"
        return Decimal("0.49") if venue == "polymarket" else Decimal("0.48"), "book"

    saved_recheck = live_strategy_b.recheck_yes
    saved_send = live_strategy_b.send_yes_ioc
    live_strategy_b.recheck_yes = fake_recheck
    live_strategy_b.send_yes_ioc = lambda spec, pay, step, bet_key, log_fn=None: sent.append(
        {"venue": spec.get("venue"), "player": spec.get("player"), "pay": str(pay)}
    ) or {
        "filled": True,
        "posted": True,
        "fill_qty": "1",
        "pay": str(pay),
        "fill_px": str(pay),
        "fill_fee": "0.02",
        "status": 200,
        "sent_at": "2026-10-28T00:23:57.500-04:00",
        "order_id": "shim-cross",
        "note": "",
    }
    try:
        live_strategy_b.maybe_cross(match)
        assert sent == [{"venue": "polymarket", "player": "Yuta Shimizu", "pay": "0.52"}]
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_send


def test_dip_gtc_rests_on_cheapest_fav_platform():
    match, _ask = _hsu_after_cross("0.60", "0.38", venue="polymarket")
    match["shop"] = {
        "hsu": {
            "polymarket": dict(match["t0_yes"]["b"]),
            "kalshi": {
                "player": "Yu-Hsiou Hsu",
                "venue": "kalshi",
                "instrument": "KX-HSU",
                "pay": "0.37",
            },
        }
    }
    live_strategy_b.remember_live_yes(match["game"], "polymarket", "Yu-Hsiou Hsu", "0.38")
    live_strategy_b.remember_live_yes(match["game"], "kalshi", "Yu-Hsiou Hsu", "0.37")
    sent = []

    def fake_gtc(spec, pay, step, bet_key, log_fn=None):
        sent.append({"venue": spec.get("venue"), "player": spec.get("player"), "pay": str(pay)})
        return {
            "filled": False,
            "posted": True,
            "fill_qty": "0",
            "pay": str(pay),
            "status": 200,
            "order_id": "hsu-gtc-k",
            "note": "resting",
            "resting": True,
            "tif": "good_till_canceled",
            "payload": {"order_id": "hsu-gtc-k", "status": "resting"},
        }

    saved_recheck = live_strategy_b.recheck_yes
    saved_ioc = live_strategy_b.send_yes_ioc
    saved_gtc = live_strategy_b.send_yes_gtc
    saved_poll = live_strategy_b.poll_fav_gtc_fill
    saved_net = live_strategy_b.extra_pair_net_ok
    live_strategy_b.recheck_yes = lambda spec, *a, **k: (
        Decimal("0.37") if str(spec.get("venue") or "") == "kalshi" else Decimal("0.38"),
        "book",
    )
    live_strategy_b.send_yes_ioc = lambda *a, **k: sent.append({"kind": "ioc"}) or {"filled": False}
    live_strategy_b.send_yes_gtc = fake_gtc
    live_strategy_b.poll_fav_gtc_fill = lambda _m: False
    live_strategy_b.extra_pair_net_ok = lambda *a, **k: True
    try:
        live_strategy_b.maybe_fav_dip(match)
        live_strategy_b.maybe_fav_dip(match)
        assert sent == [{"venue": "kalshi", "player": "Yu-Hsiou Hsu", "pay": "0.15"}]
        assert match.get("fav_gtc_sent") is True
    finally:
        live_strategy_b.recheck_yes = saved_recheck
        live_strategy_b.send_yes_ioc = saved_ioc
        live_strategy_b.send_yes_gtc = saved_gtc
        live_strategy_b.poll_fav_gtc_fill = saved_poll
        live_strategy_b.extra_pair_net_ok = saved_net
    ioc = live_lock_orders.kalshi_order_body("T", "yes", Decimal("0.15"), "cid")
    assert ioc["time_in_force"] == "immediate_or_cancel"
    fok = live_lock_orders.polymarket_order_body("s", "ORDER_INTENT_BUY_LONG", Decimal("0.15"))
    assert fok["tif"] == live_lock_orders.POLY_TIF_FOK
    gem_ioc = live_lock_orders.gemini_order_payload("sym", "yes", Decimal("0.15"))
    assert gem_ioc["timeInForce"] == "immediate-or-cancel"
    nov_ioc = novig_live.order_body("oid", Decimal("0.15"), "cid")
    assert nov_ioc["tif"] == "IOC"


if __name__ == "__main__":
    test_extra_pair_stays_25c_lock()
    test_clockless_t0_not_fired_live()
    test_t0_misses_stale_trusted_start()
    test_t0_waits_for_trusted_start()
    test_c_band_and_yes_band()
    test_one_leg_miss_is_missed_yes_not_opponent_no()
    test_lock_bot_skip_reads_b_state_file()
    test_lock_bot_skip_absorbed_b()
    test_send_blocked_strategy_b_ignores_latch()
    test_cross_send_once_does_not_retry_miss()
    test_tape_resume_is_not_a_live_t0_clock()
    test_listed_hides_inplay_two_sided_moving()
    test_odd_second_listed_is_not_a_live_t0_clock()
    test_scheduled_listed_still_fires_t0()
    test_odd_second_occurrence_still_trusted()
    test_absorbing_rejects_t0()
    test_extras_cross_ready_no_backfill_then_next_upcross()
    test_waiting_cross_occupies_open_slot()
    test_postponed_not_counted_open()
    test_sus_period_is_postponed()
    test_start_moved_next_et_day_is_postponed()
    test_odd_second_same_day_is_not_postponed_by_clock()
    test_closed_without_settlement_is_postponed()
    test_active_empty_result_is_not_postponed()
    test_post_period_is_postponed()
    test_taverna_live_shape_sus_not_kalshi_active()
    test_wolff_live_shape_start_moved_thu_1pm()
    test_kalshi_occurrence_moved_next_et_day()
    test_novig_delayed_is_postponed()
    test_novig_canceled_and_s1_are_not_postponed()
    test_gemini_start_moved_when_event_has_contracts()
    test_process_open_does_not_send_on_postponed()
    test_cross_ioc_miss_does_not_retry_same_ask()
    test_leftover_partial_is_not_a_retry_miss()
    test_poly_size_019_fok_does_not_send_or_open()
    test_poly_size_ge_1_fok_fill_opens_one()
    test_poly_cross_partial_does_not_flatten_as_one()
    test_guajardo_brain_leftover_empty_confirm_is_partial()
    test_watch_cadence_is_continuous_tick()
    test_strategy_b_has_no_job_deadline()
    test_b_can_select_novig_as_yes_venue()
    test_b_still_one_contract_and_two_match_cap()
    test_b_novig_send_uses_venue_confirm()
    test_b_novig_low_balance_named_deny()
    test_b_novig_flatten_uses_opposite_outcome_id()
    test_b_novig_all_in_uses_documented_coefficient()
    test_t0_ready_multi_does_not_call_fee_unknown()
    test_pick_skips_novig_without_schedule_keeps_kalshi()
    test_poly_short_fill_px_does_not_invert_fav_dog()
    test_trungelliti_replay_dog_is_trungelliti_no_immediate_dodig_cross()
    test_false_favorite_cross_is_rewound_so_dog_can_still_fire()
    test_t0_dog_already_above_50_does_not_arm_immediate_cross()
    test_c_090_sends()
    test_c_099_stacks()
    test_c_101_does_not_stack()
    test_c_121_skip()
    test_t0_allin_c_hi_105_paul_cases()
    test_buy_short_fill_does_not_make_101_stack()
    test_fees_turn_099_wire_into_all_in_no_stack()
    test_cross_fav_below_dog_paul_cases()
    test_cross_fav_not_below_dog_skips_and_sends()
    test_cross_allin_c_105_paul_cases()
    test_patel_1137_replay_skips_fav_still_above_dog()
    test_no_second_strategy_b_helper()
    test_t0_arm_budget_shrinks_when_waiting_cross()
    test_extra_stuck_poly_partial_does_not_block_settle()
    test_shimizu_memory_052_sends_immediately_not_180s()
    test_shimizu_memory_049_does_not_send_or_rest()
    test_shimizu_cross_does_not_double_send()
    test_maybe_cross_is_not_only_once_per_long_tick()
    test_t0_hunt_does_not_run_before_50_cross_watches()
    test_tick_cross_only_does_not_walk_t0_slate()
    test_hsu_gtc_rests_at_15c_after_60c_cross()
    test_fav_already_at_target_uses_ioc_not_gtc()
    test_gtc_not_rested_when_extra_pair_net_fails()
    test_absorb_cancels_resting_fav_gtc()
    test_poly_fav_gtc_tif_is_not_fok()
    test_venue_gtc_tif_strings()
    test_hours_away_listed_does_not_t0_on_early_occurrence()
    test_t0_fires_within_15s_of_later_listed()
    test_liu_colby_next_day_live_start_does_not_t0()
    test_cross_refuses_hours_before_trusted_t0()
    test_cheapest_legs_picks_poly_60_and_kalshi_39()
    test_cheapest_legs_poly_dog_kalshi_fav_beats_both_novig()
    test_t0_grace_thirty_minutes_holds_c_and_d()
    test_t0_ready_at_29_min_still_in_window()
    test_t0_ready_at_31_min_missed_window()
    test_prepare_book_rests_all_shops_not_memory_winners()
    test_cross_uses_cheapest_dog_platform()
    test_dip_gtc_rests_on_cheapest_fav_platform()
    print("ok")
