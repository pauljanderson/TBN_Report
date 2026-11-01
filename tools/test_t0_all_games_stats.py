"""T0 all-game path metrics. Does not place orders. Does not start Strategy B."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import t0_all_games_stats as t0

ET = ZoneInfo("America/New_York")
T0_TS = int(datetime(2026, 10, 24, 12, 0, tzinfo=ET).timestamp())


def test_favorite_stays_above_50():
    ticks = [(T0_TS + 60 * i, 0.62 + i * 0.01) for i in range(1, 6)]
    got = t0.analyze_favorite_path(0.61, T0_TS, ticks, T0_TS + 600)
    assert got["empty"] is False
    assert got["stay_above"] is True
    assert got["dipped"] is False
    assert got["recovered"] is False


def test_favorite_dips_then_recovers():
    ticks = [
        (T0_TS + 60, 0.55),
        (T0_TS + 120, 0.48),
        (T0_TS + 180, 0.44),
        (T0_TS + 240, 0.53),
    ]
    got = t0.analyze_favorite_path(0.72, T0_TS, ticks, T0_TS + 300)
    assert got["stay_above"] is False
    assert got["dipped"] is True
    assert got["recovered"] is True
    assert got["minutes_le50"] > 0


def test_empty_path_is_not_stay_above():
    got = t0.analyze_favorite_path(0.80, T0_TS, [], T0_TS + 60)
    assert got["empty"] is True
    assert got["stay_above"] is False
    assert got["path_status"] == "no_post_t0_path"


def test_stay_above_then_settle_win():
    ticks = [(T0_TS + 60 * i, 0.62 + i * 0.05) for i in range(1, 8)]
    got = t0.analyze_favorite_path(0.61, T0_TS, ticks, T0_TS + 600, fav_won=True)
    assert got["stay_above"] is True
    assert got["dipped"] is False
    assert got["stay_above_but_lost"] is False


def test_last_tick_080_settle_lose_is_not_stay_above():
    ticks = [(T0_TS + 30, 0.82), (T0_TS + 90, 0.80)]
    got = t0.analyze_favorite_path(0.85, T0_TS, ticks, T0_TS + 120, fav_won=False)
    assert got["stay_above"] is False
    assert got["stay_above_but_lost"] is True
    assert got["missing_crash"] is True
    assert got["path_status"] == "path_incomplete"
    assert got["raw_never_le50"] is True


def test_dog_one_cross_and_hold():
    ticks = [
        (T0_TS + 30, 0.41),
        (T0_TS + 90, 0.49),
        (T0_TS + 120, 0.51),
        (T0_TS + 180, 0.58),
        (T0_TS + 240, 0.66),
    ]
    got = t0.classify_dog_cross(0.38, T0_TS, ticks)
    assert got["kind"] == "one_cross_hold"
    assert got["n_cross"] == 1
    assert got["excluded"] is False
    assert got["minutes_to_first"] == 2.0


def test_dog_cross_then_fail():
    ticks = [
        (T0_TS + 60, 0.52),
        (T0_TS + 120, 0.47),
        (T0_TS + 180, 0.44),
    ]
    got = t0.classify_dog_cross(0.40, T0_TS, ticks)
    assert got["kind"] == "cross_then_fail"
    assert got["n_cross"] == 1


def test_dog_never_crosses():
    ticks = [(T0_TS + 60, 0.42), (T0_TS + 120, 0.45), (T0_TS + 180, 0.49)]
    got = t0.classify_dog_cross(0.39, T0_TS, ticks)
    assert got["kind"] == "never_cross"
    assert got["n_cross"] == 0


def test_dog_multi_cross():
    ticks = [
        (T0_TS + 60, 0.51),
        (T0_TS + 120, 0.47),
        (T0_TS + 180, 0.53),
    ]
    got = t0.classify_dog_cross(0.40, T0_TS, ticks)
    assert got["kind"] == "multi_cross"
    assert got["n_cross"] == 2


def test_dog_already_at_or_above_50_excluded():
    got = t0.classify_dog_cross(0.50, T0_TS, [(T0_TS + 60, 0.61)])
    assert got["excluded"] is True
    assert got["kind"] == "already_ge_50"
    got2 = t0.classify_dog_cross(0.55, T0_TS, [(T0_TS + 60, 0.40)])
    assert got2["excluded"] is True


def test_from_below_needs_prior_at_or_under_50():
    # T0 dog 0.40, first tick already 0.51 is still a from-below cross (T0 is the prior).
    got = t0.classify_dog_cross(0.40, T0_TS, [(T0_TS + 10, 0.51)])
    assert got["kind"] == "one_cross_hold"
    # Equal to 50 is not a cross; next tick 0.51 is.
    got2 = t0.classify_dog_cross(0.40, T0_TS, [(T0_TS + 10, 0.50), (T0_TS + 20, 0.51)])
    assert got2["kind"] == "one_cross_hold"
    assert got2["n_cross"] == 1


def test_bucket_win_labels():
    assert t0.bucket_of(0.91) == ">90"
    assert t0.bucket_of(0.90) == "80-89"
    assert t0.bucket_of(0.80) == "80-89"
    assert t0.bucket_of(0.799) == "70-79"
    assert t0.bucket_of(0.50) == "50-50"
    assert t0.bucket_of(0.501) == "50-59"
    assert t0.bucket_of(None) == "missing T0"


def test_t0_two_sided_last_pre_clock():
    clock = T0_TS
    yes_a = [(clock - 30, 0.41), (clock + 10, 0.44)]
    yes_b = [(clock - 20, 0.61), (clock + 10, 0.58)]
    a, b, ts, label = t0.assign_t0_prices(yes_a, yes_b, clock)
    assert a == 0.41
    assert b == 0.61
    assert ts == clock - 20
    assert "last two-sided" in label


def test_listed_odd_seconds_not_trusted():
    listed = datetime(2026, 10, 24, 12, 0, 40, tzinfo=ET)
    clock, src, skip = t0.pick_trusted_clock(None, listed, [(T0_TS, 0.4)], [(T0_TS, 0.6)])
    assert clock is None
    assert skip == "no_trusted_clock"


def test_occurrence_odd_seconds_is_trusted():
    occ = datetime(2026, 10, 24, 12, 0, 51, tzinfo=ET)
    clock, src, skip = t0.pick_trusted_clock(occ, None, [(T0_TS + 120, 0.4)], [(T0_TS + 120, 0.6)])
    assert clock == occ
    assert src == "occurrence"
    assert skip == ""


def test_one_sided_absorbing_before_clock_is_hidden():
    clock = T0_TS
    yes_a = [(clock - 120, 0.97), (clock - 60, 0.99), (clock + 10, 0.99)]
    hidden = t0.clock_hides_match(yes_a, [], clock)
    assert hidden is True
    live = [(clock - 60, 0.62), (clock + 10, 0.58)]
    assert t0.clock_hides_match(live, [], clock) is False


def test_scheduled_listed_is_trusted():
    listed = datetime(2026, 10, 24, 12, 0, 0, tzinfo=ET)
    clock, src, skip = t0.pick_trusted_clock(None, listed, [(T0_TS + 5, 0.4)], [(T0_TS + 5, 0.6)])
    assert src == "listed/feed"
    assert skip == ""
    assert clock == listed


def test_rebuild_due_when_stamp_missing():
    saved = t0.REBUILD_STAMP
    try:
        t0.REBUILD_STAMP = Path(tempfile.mkdtemp()) / "missing.json"
        assert t0._rebuild_due() is True
    finally:
        t0.REBUILD_STAMP = saved


def test_rebuild_due_respects_two_hours():
    saved = t0.REBUILD_STAMP
    folder = Path(tempfile.mkdtemp())
    stamp = folder / "t0_all_games_stats_rebuild.json"
    try:
        t0.REBUILD_STAMP = stamp
        fresh = t0.now_et() - timedelta(minutes=30)
        stamp.write_text(json.dumps({"written_at": fresh.isoformat()}), encoding="utf-8")
        assert t0._rebuild_due() is False
        old = t0.now_et() - timedelta(hours=3)
        stamp.write_text(json.dumps({"written_at": old.isoformat()}), encoding="utf-8")
        assert t0._rebuild_due() is True
    finally:
        t0.REBUILD_STAMP = saved


def test_supervisor_hook_present():
    text = (Path(t0.ROOT) / "tools" / "live_game_pollers.py").read_text(encoding="utf-8")
    assert "t0_all_games_stats" in text
    assert "maybe_rebuild" in text
    control = (Path(t0.ROOT) / "tools" / "prediction_job_control.py").read_text(encoding="utf-8")
    assert "t0_all_games_stats.html" in control
    assert "t0_all_games_stats.maybe_rebuild" in control


if __name__ == "__main__":
    test_favorite_stays_above_50()
    test_favorite_dips_then_recovers()
    test_empty_path_is_not_stay_above()
    test_stay_above_then_settle_win()
    test_last_tick_080_settle_lose_is_not_stay_above()
    test_dog_one_cross_and_hold()
    test_dog_cross_then_fail()
    test_dog_never_crosses()
    test_dog_multi_cross()
    test_dog_already_at_or_above_50_excluded()
    test_from_below_needs_prior_at_or_under_50()
    test_bucket_win_labels()
    test_t0_two_sided_last_pre_clock()
    test_listed_odd_seconds_not_trusted()
    test_occurrence_odd_seconds_is_trusted()
    test_one_sided_absorbing_before_clock_is_hidden()
    test_scheduled_listed_is_trusted()
    test_rebuild_due_when_stamp_missing()
    test_rebuild_due_respects_two_hours()
    test_supervisor_hook_present()
    print("ok")
