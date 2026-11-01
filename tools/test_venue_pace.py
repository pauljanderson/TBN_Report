"""HTTP budget: in-flight cap, skipped ticks, send-path reserved seat.

Does not place orders. Does not print secrets.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import venue_pace
from prediction_paths import RAW_DIR


def _setup():
    folder = Path(tempfile.mkdtemp())
    venue_pace.reset_for_tests(folder)
    saved_interval = dict(venue_pace.INTERVAL)
    for name in list(venue_pace.INTERVAL):
        venue_pace.INTERVAL[name] = 0.0
    return folder, saved_interval


def _teardown(saved_interval):
    venue_pace.INTERVAL.update(saved_interval)
    venue_pace.RAW = RAW_DIR


def test_caps_documented():
    assert venue_pace.IN_FLIGHT_CAP == venue_pace.INFLIGHT_CAP
    assert venue_pace.IN_FLIGHT_CAP["kalshi"] == 4
    assert venue_pace.IN_FLIGHT_CAP["gemini"] == 2
    assert venue_pace.IN_FLIGHT_CAP["novig"] == 2
    assert venue_pace.IN_FLIGHT_CAP["polymarket"] == 8
    assert venue_pace.SEND_RESERVED["kalshi"] == 1
    assert venue_pace.background_limit("kalshi") == 3
    assert venue_pace.background_limit("gemini") == 1
    assert venue_pace.background_limit("novig") == 1
    assert venue_pace.background_limit("polymarket") == 7


def test_background_skips_when_cap_full():
    folder, saved = _setup()
    try:
        limit = venue_pace.background_limit("kalshi")
        with venue_pace.hold_inflight("kalshi"):
            with venue_pace.hold_inflight("kalshi"):
                with venue_pace.hold_inflight("kalshi"):
                    snap = venue_pace.health_snapshot()["venues"]["kalshi"]
                    assert snap["in_flight"] == limit, snap
                    assert venue_pace.wait_turn("kalshi") is False
                    after = venue_pace.health_snapshot()["venues"]["kalshi"]
                    assert after["skipped_ticks"] == 1, after
                    assert after["in_flight"] == limit
    finally:
        _teardown(saved)


def test_send_path_uses_reserved_slot():
    folder, saved = _setup()
    try:
        with venue_pace.hold_inflight("kalshi"):
            with venue_pace.hold_inflight("kalshi"):
                with venue_pace.hold_inflight("kalshi"):
                    assert venue_pace.wait_turn("kalshi") is False
                    assert venue_pace.wait_turn("kalshi", priority=venue_pace.PRIORITY_SEND) is True
                    assert venue_pace.wait_turn("kalshi", priority=True) is True
                    snap = venue_pace.health_snapshot()["venues"]["kalshi"]
                    assert snap["send_granted"] >= 2, snap
                    assert snap["skipped_ticks"] >= 1
    finally:
        _teardown(saved)


def test_skip_count_persists():
    folder, saved = _setup()
    try:
        with venue_pace.hold_inflight("gemini"):
            assert venue_pace.wait_turn("gemini") is False
            assert venue_pace.wait_turn("gemini") is False
        row = venue_pace._read_health("gemini")
        assert int(row.get("skipped_ticks") or 0) == 2, row
        path = folder / "pace_gemini.health.json"
        assert path.is_file()
        combined = folder / "venue_pace_health.json"
        assert combined.is_file()
    finally:
        _teardown(saved)


def test_health_snapshot_has_job_status_fields():
    folder, saved = _setup()
    try:
        venue_pace.wait_turn("novig")
        snap = venue_pace.health_snapshot()
        row = snap["venues"]["novig"]
        for key in (
            "label",
            "interval_s",
            "cap",
            "in_flight",
            "skipped_ticks",
            "lock_wait_ms",
            "lock_wait_ms_ewma",
            "reserved",
        ):
            assert key in row, key
        assert row["label"] == "Novig"
        assert snap["venues"]["polymarket"]["label"] == "Polymarket US"
    finally:
        _teardown(saved)


def main() -> int:
    test_caps_documented()
    test_background_skips_when_cap_full()
    test_send_path_uses_reserved_slot()
    test_skip_count_persists()
    test_health_snapshot_has_job_status_fields()
    print("test_venue_pace: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
