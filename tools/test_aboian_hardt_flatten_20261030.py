"""Aboian vs Hardt: Kalshi flatten is real; Poly fill 0 is not a ticket. No network."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import live_pm_settle_reconcile as rec
import open_count_sync as ocs
import opportunity_considerations as oc
import write_orders_performance as w

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "aboian_hardt_flatten_20261030.json"


def _blob():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _sent(row: dict) -> dict:
    out = dict(row)
    out.setdefault("event", "sent")
    return out


def test_opportunities_table_aboian_is_kalshi_no_poly_never_sent_flatten_yes():
    import opportunity_considerations as table

    blob = _blob()
    html = table._cells(blob["consider_row"], [_sent(row) for row in blob["sent"]])
    assert "Sold Yes 34.38¢" in html
    assert "Bought Yes 37.62¢" in html
    assert "never sent" in html
    assert "one+flatten" in html
    assert "polymarket" in html.lower()
    assert "kalshi" in html.lower()


def test_venues_label_is_kalshi_only_not_poly_hold():
    row = _blob()["consider_row"]
    label = oc.venues_label(row)
    low = label.lower()
    assert "kalshi" in low
    assert "no kalshi" in low
    assert "sold yes = buy no" in low
    assert "yes polymarket" not in low
    assert "polymarket" not in low
    assert "no position remains" in low
    assert oc.filled_venues_of(row) == ["kalshi"]
    n, patched = oc.strike_flatten_hold(row)
    assert patched["filled_venues"] == "kalshi"
    assert patched["hold_now"] == "none"
    assert n >= 0


def test_venues_label_fill_zero_lists_no_platform():
    row = {
        "yes_venue": "kalshi",
        "no_venue": "polymarket",
        "decision": "sent",
        "reason": "Hard miss abort. polymarket HTTP 200 fill 0 no message",
        "venue_return": "polymarket HTTP 200 fill 0 no message; confirm polymarket activities GET empty.",
    }
    label = oc.venues_label(row).lower()
    assert "confirm qty 0" in label
    assert "yes kalshi" not in label
    assert "no polymarket" not in label
    assert "yes polymarket" not in label


def test_poly_fill_zero_is_not_a_ticket():
    blob = _blob()
    poly = next(row for row in blob["sent"] if row["venue"] == "polymarket")
    assert w.qty_is_fill(poly.get("confirm_qty")) is False
    assert w.is_empty_http_fill(200, poly.get("confirm_qty")) is True
    store = {}
    out = rec.apply_row(_sent(poly), venue_fill={"qty": "0"}, market={}, store=store)
    assert out["action"] == "missed_send"
    assert poly["order_id"] not in store


def test_kalshi_flatten_is_venue_net_not_open():
    blob = _blob()
    no_leg = {
        "qty": 1,
        "side": "no",
        "player": "Valerio Aboian",
        "cash": "0.6400",
        "fee": "0.0162",
        "venue": "kalshi",
        "instrument": blob["kalshi_ticker"],
        "order_id": "01a18f01-6620-7739-9256-98228e5a511a",
        "step": "hard",
        "posted": True,
        "has_io": True,
        "http": 201,
        "http_line": "kalshi HTTP 201 fill 1.00 fill_count 1.00",
    }
    yes_leg = {
        "qty": 1,
        "side": "yes",
        "player": "Valerio Aboian",
        "cash": "0.3600",
        "fee": "0.0162",
        "venue": "kalshi",
        "instrument": blob["kalshi_ticker"],
        "order_id": "01a18f01-71d8-7e02-9c09-08d28b0572cb",
        "step": "flatten",
        "posted": True,
        "has_io": True,
        "http": 201,
        "http_line": "flatten kalshi HTTP 201 fill 1.00 fill_count 1.00",
    }
    cluster = {
        "is_b": False,
        "b_t0_both": False,
        "complementary": True,
        "game": blob["game"],
        "fill_legs": [no_leg, yes_leg],
        "legs": [no_leg, yes_leg],
        "n_fill_legs": 2,
        "flatten_filled": True,
        "market_final": False,
        "venue_live": False,
        "notes": [],
    }
    scored = w.score_cluster(cluster, [], {"kalshi": {}, "polymarket": {}}, {})
    assert scored.get("venue_live") is False
    assert scored.get("open_legs") in {0, None} or Decimal(str(scored.get("open_legs") or 0)) == 0
    assert w.cluster_is_settled(scored) is True
    extra = w.extra_open_from_unsettled([scored], [])
    assert extra == []


def test_b_t0_flatten_cannot_stay_open_without_position():
    slug = "aec-itfme-lucliu-ryacol-2026-10-28"
    yes_leg = {
        "qty": 1, "side": "yes", "player": "LUCCA LIU", "cash": "0.46", "fee": "0.02",
        "venue": "polymarket", "instrument": slug, "order_id": "LIU-YES", "step": "b-t0",
        "posted": True, "has_io": True, "http": 200, "http_line": "polymarket HTTP 200 fill 1",
    }
    no_leg = {
        "qty": 1, "side": "no", "player": "Ryan Colby", "cash": "0.45", "fee": "0.01",
        "venue": "polymarket", "instrument": slug, "order_id": "COLBY-NO", "step": "flatten",
        "posted": True, "has_io": True, "http": 200, "http_line": "flatten polymarket HTTP 200 fill 1",
    }
    cluster = {
        "is_b": True,
        "b_t0_both": True,
        "complementary": True,
        "game": "LUCCA LIU vs. Ryan Colby",
        "fill_legs": [yes_leg, no_leg],
        "legs": [yes_leg, no_leg],
        "n_fill_legs": 2,
        "flatten_filled": True,
        "market_final": False,
        "venue_live": False,
        "notes": [],
    }
    scored = w.score_cluster(cluster, [], {"kalshi": {}, "polymarket": {}}, {})
    assert scored.get("venue_live") is False
    extra = w.extra_open_from_unsettled([scored], [])
    assert extra == []


def test_classify_full_flatten_empty_book_is_not_open():
    status_row = {
        "key": "tennis_liucolby_2026_10_28",
        "game": "LUCCA LIU vs. Ryan Colby",
        "stage": "waiting_cross",
        "venue": "polymarket",
        "instrument": "aec-itfme-lucliu-ryacol-2026-10-28",
        "last_order": {"fill_qty": "1", "http": 200, "time": "2026-10-28T14:03:11-04:00"},
        "t0_yes": {
            "a": {
                "player": "LUCCA LIU",
                "flattened": True,
                "instrument": "aec-itfme-lucliu-ryacol-2026-10-28",
                "venue": "polymarket",
            },
            "b": {
                "player": "Ryan Colby",
                "filled": True,
                "instrument": "aec-itfme-lucliu-ryacol-2026-10-28",
                "venue": "polymarket",
            },
        },
    }
    snap = ocs.empty_snapshot()
    snap["poly_ok"] = True
    snap["poly"] = []
    snap["kalshi_ok"] = True
    item = ocs.classify_match("tennis_crossover", status_row, snap)
    assert item["real"] is False
    assert "flatten" in str(item.get("why") or "").lower()


def test_http_ok_fill_zero_cannot_be_open_or_settled():
    poly = {
        "qty": 0,
        "side": "yes",
        "player": "Nick Hardt",
        "cash": "0.150",
        "fee": "0.01",
        "venue": "polymarket",
        "instrument": "aec-atp-valabo-nichar-2026-10-30",
        "order_id": "DDZK92R012VC",
        "step": "hard",
        "posted": True,
        "has_io": True,
        "http": 200,
        "http_line": "polymarket HTTP 200 fill 0 no message",
    }
    cluster = {
        "game": "Aboian vs Hardt",
        "fill_legs": [],
        "legs": [poly],
        "n_fill_legs": 0,
        "flatten_filled": False,
        "posted": True,
        "notes": [],
    }
    scored = w.score_cluster(cluster, [], {"kalshi": {}, "polymarket": {}}, {})
    assert scored.get("venue_live") is not True
    assert scored.get("n_fill_legs") in {0, None} or int(scored.get("n_fill_legs") or 0) == 0
    assert w.hold_class_of(scored) in {w.HOLD_NEVER, w.HOLD_UNKNOWN, w.HOLD_FLATTEN}
    extra = w.extra_open_from_unsettled([scored], [])
    assert extra == []


def main() -> None:
    tests = (
        test_opportunities_table_aboian_is_kalshi_no_poly_never_sent_flatten_yes,
        test_venues_label_is_kalshi_only_not_poly_hold,
        test_venues_label_fill_zero_lists_no_platform,
        test_poly_fill_zero_is_not_a_ticket,
        test_kalshi_flatten_is_venue_net_not_open,
        test_b_t0_flatten_cannot_stay_open_without_position,
        test_classify_full_flatten_empty_book_is_not_open,
        test_http_ok_fill_zero_cannot_be_open_or_settled,
    )
    failed = 0
    for fn in tests:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception as exc:
            failed += 1
            print("FAIL", fn.__name__, type(exc).__name__, exc)
    if failed:
        raise SystemExit(1)
    print("ok")


if __name__ == "__main__":
    main()
