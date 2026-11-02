"""Venue open positions → kitchen tape. No network. No secrets."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_same_direction as ksd  # noqa: E402
import venue_open_miss_ingest as vomi  # noqa: E402

GIM = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-GIM"
PEN = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-PEN"


def test_ingest_open_kalshi_yes_no_complementary():
    tape: list[dict] = []
    positions = [
        {"ticker": GIM, "position_fp": "1.00", "title": "Gima"},
        {"ticker": PEN, "position_fp": "-1.00", "title": "Peniston"},
    ]
    rep = vomi.ingest_open_positions(positions, venue="kalshi", tape=tape, persist=False)
    assert rep["added"] == 2
    assert len(rep["written"]) == 2
    sides = {row["instrument"]: row["outcome"] for row in rep["written"]}
    assert sides[GIM] == "yes"
    assert sides[PEN] == "no"
    # Re-ingest is idempotent against the updated tape.
    tape2 = list(tape) + list(rep["written"])
    again = vomi.ingest_open_positions(positions, venue="kalshi", tape=tape2, persist=False)
    assert again["added"] == 0
    stacks = ksd.find_same_direction_stacks(rep["written"])
    assert stacks
    assert "GIMPEN" in stacks[0]["event"]


def test_open_book_blocks_yes_b_when_no_a_held():
    open_rows = [{"instrument": GIM, "outcome": "no", "venue": "kalshi"}]
    new_legs = [{"instrument": PEN, "outcome": "yes", "venue": "kalshi"}]
    bad, why = ksd.open_book_blocks_same_direction(new_legs, open_rows)
    assert bad is True
    assert "same-direction" in why
    # Dual-Yes is Strategy B — not blocked by this gate.
    bad2, _ = ksd.open_book_blocks_same_direction(
        [{"instrument": PEN, "outcome": "yes", "venue": "kalshi"}],
        [{"instrument": GIM, "outcome": "yes", "venue": "kalshi"}],
    )
    assert bad2 is False


def test_kalshi_rows_from_payload_sign():
    rows = vomi._kalshi_rows_from_payload(
        {
            "body": {
                "market_positions": [
                    {"ticker": GIM, "position_fp": "2.00"},
                    {"ticker": PEN, "position_fp": "-1.00"},
                ]
            }
        }
    )
    assert len(rows) == 2
    assert vomi._side_of(rows[0]) == "yes"
    assert vomi._side_of(rows[1]) == "no"


def test_complementary_instruments_poly_slugs():
    assert ksd.complementary_instruments("match-foo-GIM", "match-foo-PEN")
    assert not ksd.complementary_instruments("match-foo-GIM", "match-foo-GIM")


if __name__ == "__main__":
    test_ingest_open_kalshi_yes_no_complementary()
    test_open_book_blocks_yes_b_when_no_a_held()
    test_kalshi_rows_from_payload_sign()
    test_complementary_instruments_poly_slugs()
    print("test_venue_open_miss_ingest ok")
