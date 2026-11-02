"""Venue open positions → kitchen tape. No network. No secrets."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_same_direction as ksd  # noqa: E402
import venue_open_miss_ingest as vomi  # noqa: E402
import write_orders_performance as wop  # noqa: E402

GIM = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-GIM"
PEN = "KXATPCHALLENGERMATCH-26NOV01GIMPEN-PEN"


def test_ingest_open_writes_claim_sent_not_orphan_filled():
    tape: list[dict] = []
    positions = [
        {"ticker": GIM, "position_fp": "1.00", "title": "Gima"},
        {"ticker": PEN, "position_fp": "-1.00", "title": "Peniston"},
    ]
    rep = vomi.ingest_open_positions(positions, venue="kalshi", tape=tape, persist=False)
    assert rep["added"] == 2
    assert len(rep["written"]) == 4  # claim+sent × 2
    events = [row["event"] for row in rep["written"]]
    assert events.count("claim") == 2
    assert events.count("sent") == 2
    assert "filled" not in events
    for row in rep["written"]:
        if row["event"] == "sent":
            assert row.get("confirm_known") is True
            assert wop.qty_is_fill(row.get("confirm_qty"))
    # Re-ingest is idempotent against the updated tape.
    tape2 = list(tape) + list(rep["written"])
    again = vomi.ingest_open_positions(positions, venue="kalshi", tape=tape2, persist=False)
    assert again["added"] == 0
    stacks = ksd.find_same_direction_stacks(rep["written"])
    assert stacks
    assert "GIMPEN" in stacks[0]["event"]


def test_claim_sent_clusters_into_dashboard_fill():
    """Regression: orphan filled was dropped; claim+sent must show as a trade."""
    pair = vomi.claim_sent_pair(
        venue="kalshi",
        instrument=GIM,
        side="yes",
        qty=Decimal("1"),
        game="Gima vs Pen",
        when="2026-11-02T10:15:00-05:00",
        kind="open",
    )
    clusters = wop.cluster_lock_attempts(pair)
    assert len(clusters) == 1
    enriched = wop.enrich_cluster(clusters[0], {}, [])
    assert enriched.get("n_fill_legs") == 1
    assert wop.qty_is_fill((enriched.get("fill_legs") or [{}])[0].get("qty"))


def test_promote_orphan_filled_rows():
    orphan = {
        "event": "filled",
        "bet_key": f"venue-open|kalshi|{GIM}|yes",
        "venue": "kalshi",
        "instrument": GIM,
        "outcome": "yes",
        "confirm_qty": "1",
        "confirm_known": True,
        "source": "venue_open_miss_ingest",
        "at": "2026-11-02T10:15:00-05:00",
        "game": "Gima",
    }
    promoted = wop.promote_orphan_venue_filled([orphan])
    assert any(row.get("event") == "claim" for row in promoted)
    assert any(row.get("event") == "sent" for row in promoted)
    clusters = wop.cluster_lock_attempts(promoted)
    assert clusters
    enriched = wop.enrich_cluster(clusters[0], {}, [])
    assert enriched.get("n_fill_legs") == 1


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


def test_kalshi_fills_from_payload():
    rows = vomi._kalshi_fills_from_payload(
        {
            "fills": [
                {
                    "ticker": GIM,
                    "side": "yes",
                    "count_fp": "1.00",
                    "created_time": "2026-11-02T12:00:00Z",
                    "order_id": "abc",
                }
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0]["instrument"] == GIM


def test_complementary_instruments_poly_slugs():
    assert ksd.complementary_instruments("match-foo-GIM", "match-foo-PEN")
    assert not ksd.complementary_instruments("match-foo-GIM", "match-foo-GIM")


if __name__ == "__main__":
    test_ingest_open_writes_claim_sent_not_orphan_filled()
    test_claim_sent_clusters_into_dashboard_fill()
    test_promote_orphan_filled_rows()
    test_open_book_blocks_yes_b_when_no_a_held()
    test_kalshi_rows_from_payload_sign()
    test_kalshi_fills_from_payload()
    test_complementary_instruments_poly_slugs()
    print("test_venue_open_miss_ingest ok")
