"""Rebuild of orders_performance.html on confirmed fill / game complete, not on deny.

No network. No secrets. Does not place or sell.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import orders_performance_refresh as refresh
import venue_fill_confirm


def _payload(qty, tape="0"):
    return venue_fill_confirm.attach(
        {"fill_count": str(tape), "status": "executed"},
        {"known": True, "qty": str(qty), "note": "test confirm"},
    )


def _reset(scheduled=None):
    refresh.reset_for_tests()
    refresh.run_rebuild = lambda: scheduled.append("run") or str(refresh.PAGE) if scheduled is not None else ""
    refresh._phone_ntfy = lambda: None
    refresh.DEBOUNCE_SEC = 30.0
    refresh.NTFY_MIN_SEC = 180.0


def test_rebuild_on_confirmed_house_fill():
    _reset()
    assert refresh.should_rebuild_on_fill(_payload("1.00")) is True
    assert refresh.maybe_after_order(_payload("1.00"), status=201) is True


def test_rebuild_on_partial_poly_qty():
    _reset()
    assert refresh.should_rebuild_on_fill(_payload("0.42")) is True
    assert refresh.maybe_after_order(_payload("0.42"), status=201) is True


def test_no_rebuild_on_empty_kalshi_201():
    _reset()
    empty = _payload("0", tape="0.00")
    assert refresh.should_rebuild_on_fill(empty, status=201) is False
    assert refresh.maybe_after_order(empty, status=201) is False


def test_no_rebuild_on_deny():
    _reset()
    assert refresh.should_rebuild_on_fill(None, status=404, denied=True) is False
    assert refresh.maybe_after_order(None, status=404, denied=True) is False
    assert refresh.should_rebuild_on_fill({"error": "insufficient_shard_balance"}, status=404) is False
    assert refresh.maybe_after_order({"error": "insufficient_shard_balance"}, status=404) is False


def test_no_rebuild_on_skip():
    _reset()
    assert refresh.should_rebuild_on_fill(None, status=0, skipped=True) is False
    assert refresh.maybe_after_order(None, status=0, skipped=True) is False
    assert refresh.should_rebuild_on_fill(None, status=0) is False
    assert refresh.maybe_after_order(None, status=0) is False


def test_rebuild_on_game_complete_not_untouched():
    _reset()
    assert refresh.should_rebuild_on_game_complete("closed", we_touched=True) is True
    assert refresh.should_rebuild_on_game_complete("settled", we_touched=True) is True
    assert refresh.should_rebuild_on_game_complete("removed", we_touched=True) is True
    assert refresh.should_rebuild_on_game_complete("void", we_touched=True) is True
    assert refresh.should_rebuild_on_game_complete("closed", we_touched=False) is False
    assert refresh.maybe_after_game_complete("closed", title="A vs B", we_touched=True) is True
    assert refresh.maybe_after_game_complete("closed", title="A vs B", we_touched=True) is False
    assert refresh.maybe_after_game_complete("deny", title="A vs B", we_touched=True) is False


def test_watch_stop_complete_not_miss():
    _reset()
    assert refresh.watch_stop_is_game_complete("market closed (kalshi closed)") is True
    assert refresh.watch_stop_is_game_complete("leftover IOC miss; attempt done") is False
    assert refresh.watch_stop_is_game_complete("remaining ask can never be profitable") is False
    assert refresh.watch_stop_is_game_complete("8:00 AM ET deadline") is False
    watch = {"game": "A vs B", "bet_key": "k", "filled_venue": "kalshi"}
    assert refresh.maybe_after_watch_stop("market closed (kalshi closed)", watch) is True
    assert refresh.maybe_after_watch_stop("leftover IOC miss; attempt done", watch) is False


def test_game_was_touched_from_watch_and_tape():
    watches = [{"game": "Ribecai vs Houkes", "filled_venue": "kalshi", "filled_instrument": "KX"}]
    assert refresh.game_was_touched("Ribecai vs Houkes", watches=watches, matches=[], orders=[]) is True
    assert refresh.game_was_touched("Other Game", watches=watches, matches=[], orders=[]) is False
    orders = [{"event": "filled", "game": "Funk vs Petrov", "confirm_qty": "1"}]
    assert refresh.game_was_touched("Funk vs Petrov", watches=[], matches=[], orders=orders) is True
    empty_sends = [{"event": "sent", "game": "Skip Game", "confirm_qty": "0"}]
    assert refresh.game_was_touched("Skip Game", watches=[], matches=[], orders=empty_sends) is False


def test_b_stage_complete_requires_a_fill():
    _reset()
    held = {
        "game": "A vs B",
        "key": "tennis_a_b",
        "stage": "postponed",
        "t0_yes": {"a": {"filled": True, "fill_qty": "1"}},
    }
    assert refresh.b_match_touched(held) is True
    assert refresh.maybe_after_b_stage(held, "waiting_cross", "postponed") is True
    bare = {"game": "C vs D", "key": "tennis_c_d", "stage": "abandoned", "t0_yes": {"a": {}}}
    assert refresh.b_match_touched(bare) is False
    assert refresh.maybe_after_b_stage(bare, "waiting_t0", "abandoned") is False


def test_schedule_does_not_block_and_coalesces():
    scheduled = []
    _reset(scheduled)
    t0 = time.perf_counter()
    assert refresh.maybe_after_order(_payload("1"), status=201) is True
    assert refresh.maybe_after_order(_payload("1"), status=201) is True
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5
    assert scheduled == []
    refresh.flush_for_test()
    assert scheduled == ["run"]


def test_flatten_close_rebuilds_not_miss():
    _reset()
    assert refresh.maybe_after_flatten("A vs B", "k", filled=True) is True
    assert refresh.maybe_after_flatten("A vs B", "k", filled=False) is False


def test_settled_poly_is_close_empty_open_poly_is_not():
    import open_count_sync as ocs

    _reset()
    held = {
        "key": "tennis_abdoguidot_2026_10_25",
        "game": "Karim vs Guidotti",
        "stage": "waiting_cross",
        "venue": "polymarket",
        "instrument": "aec-itfme-karabd-margui-2026-10-25",
        "last_order": {"fill_qty": "1", "http": 200},
        "t0_yes": {
            "a": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket", "fill_qty": "1"},
            "b": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket", "fill_qty": "1"},
        },
    }
    open_snap = ocs.empty_snapshot()
    open_snap["poly_ok"] = True
    open_snap["poly"] = []
    open_snap["kalshi_ok"] = True
    open_snap["poly_markets"] = {
        "aec-itfme-karabd-margui-2026-10-25": {
            "venue": "polymarket",
            "state": "MARKET_STATE_OPEN",
            "expired": False,
        }
    }
    open_item = ocs.classify_match("tennis_crossover", held, open_snap)
    assert open_item["real"] is True
    assert refresh.classified_is_venue_close(open_item, snapshot=open_snap) is False
    assert refresh.maybe_after_classified(open_item, snapshot=open_snap) is False

    closed_snap = ocs.empty_snapshot()
    closed_snap["poly_ok"] = True
    closed_snap["poly"] = []
    closed_snap["kalshi_ok"] = True
    closed_snap["poly_markets"] = {
        "aec-itfme-karabd-margui-2026-10-25": {
            "venue": "polymarket",
            "state": "MARKET_STATE_EXPIRED",
            "expired": True,
            "settlementPx": "1.00",
        }
    }
    closed_item = ocs.classify_match("tennis_crossover", held, closed_snap)
    assert closed_item["real"] is False
    assert refresh.classified_is_venue_close(closed_item, snapshot=closed_snap) is True
    assert refresh.maybe_after_classified(closed_item, snapshot=closed_snap) is True
    assert refresh.maybe_after_classified(closed_item, snapshot=closed_snap) is False


def test_cd_filled_settles():
    import open_count_sync as ocs
    import live_t0_yes

    _reset()
    status = {
        "system": "cfb_favorite",
        "matches": [
            {
                "key": "college_football_untnavy_2026_10_24",
                "game": "NAVY vs UNT",
                "stage": "filled",
                "venue": "kalshi",
                "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT",
                "last_order": {"fill_qty": "1", "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT", "venue": "kalshi"},
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    snap["kalshi_markets"] = {
        "KXNCAAFGAME-26OCT24UNTNAVY-UNT": {
            "venue": "kalshi",
            "status": "settled",
            "result": "yes",
        }
    }
    n = live_t0_yes.note_settled_holds("cfb_favorite", status, snapshot=snap)
    assert n == 1
    assert status["matches"][0]["stage"] == "settled"


def test_note_snapshot_closes_debounces_five_systems():
    import open_count_sync as ocs

    _reset()
    held = {
        "key": "college_football_untnavy_2026_10_24",
        "game": "NAVY vs UNT",
        "stage": "filled",
        "venue": "kalshi",
        "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT",
        "last_order": {"fill_qty": "1", "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT", "venue": "kalshi"},
    }
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    snap["kalshi_markets"] = {
        "KXNCAAFGAME-26OCT24UNTNAVY-UNT": {"venue": "kalshi", "status": "settled", "result": "yes"}
    }
    watches = {
        "cfb_favorite": {"matches": [dict(held)]},
        "spread_t0": {"matches": [dict(held, stage="filled")]},
        "tennis_crossover": {"matches": []},
        "tennis_t0_dog": {"matches": []},
    }
    n = refresh.note_snapshot_closes(snap, watches=watches)
    assert n >= 1
    n2 = refresh.note_snapshot_closes(snap, watches=watches)
    assert n2 == 0


def test_spawn_exit_zero_is_success():
    """A generator exit of 0 must count as rebuilt, not `returncode or 1` failure."""
    _reset()
    class _Proc:
        returncode = 0

    logs = []
    saved_run = refresh.win_hidden.run
    saved_log = refresh._log
    refresh.win_hidden.run = lambda *a, **k: _Proc()
    refresh._log = logs.append
    try:
        path = refresh._spawn_generator()
        assert path == str(refresh.PAGE)
        assert any("rebuilt" in str(row) for row in logs)
        assert not any("exit" in str(row) for row in logs)
        _Proc.returncode = 1
        path = refresh._spawn_generator()
        assert path == ""
        assert any("exit 1" in str(row) for row in logs)
    finally:
        refresh.win_hidden.run = saved_run
        refresh._log = saved_log


def test_ntfy_debounced_after_rebuild():
    pings = []
    n = {"i": 0}
    page = Path(__file__).resolve().parent / "_tmp_orders_perf_ntfy.html"
    page.write_text("one", encoding="utf-8")
    _reset()
    refresh._phone_ntfy = lambda: pings.append("ping")
    refresh.NTFY_MIN_SEC = 60.0
    saved_page = refresh.PAGE
    refresh.PAGE = page

    def fake_run():
        n["i"] += 1
        page.write_text(f"page-{n['i']}", encoding="utf-8")
        return str(page)

    refresh.run_rebuild = fake_run
    try:
        refresh._run_once()
        refresh._run_once()
        assert n["i"] == 2
        assert pings == ["ping"]
    finally:
        refresh.PAGE = saved_page
        try:
            page.unlink()
        except OSError:
            pass


def main() -> None:
    test_rebuild_on_confirmed_house_fill()
    test_rebuild_on_partial_poly_qty()
    test_no_rebuild_on_empty_kalshi_201()
    test_no_rebuild_on_deny()
    test_no_rebuild_on_skip()
    test_rebuild_on_game_complete_not_untouched()
    test_watch_stop_complete_not_miss()
    test_game_was_touched_from_watch_and_tape()
    test_b_stage_complete_requires_a_fill()
    test_flatten_close_rebuilds_not_miss()
    test_settled_poly_is_close_empty_open_poly_is_not()
    test_cd_filled_settles()
    test_note_snapshot_closes_debounces_five_systems()
    test_spawn_exit_zero_is_success()
    test_schedule_does_not_block_and_coalesces()
    test_ntfy_debounced_after_rebuild()
    refresh.reset_for_tests()
    print("test_orders_performance_refresh ok")


if __name__ == "__main__":
    main()
