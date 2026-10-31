"""Eala/Shnaider flatten -3.03c and Pohankova Poly fill 0. No network. No secrets."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import live_pm_settle_reconcile as rec
import settled_pnl_store
import write_orders_performance as w

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "eala_shnaider_pohankova_20261030.json"


def _blob():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _sent(row: dict) -> dict:
    out = dict(row)
    out.setdefault("event", "sent")
    return out


def test_opportunities_table_eala_sold_yes_then_poly_miss_then_bought_yes():
    import opportunity_considerations as table

    blob = _blob()
    html = table._cells(blob["consider_row"], [_sent(row) for row in blob["sent"]])
    assert "Sold Yes 16.01¢" in html
    assert "Bought Yes 19.04¢" in html
    assert "miss 0" in html
    assert "one+flatten" in html
    assert "0.130" in html


def test_kalshi_round_trip_is_minus_3_03_cents():
    blob = _blob()
    ui = blob["kalshi_ui"]
    sold = Decimal(ui["sold_yes_all_in"])
    bought = Decimal(ui["bought_yes_all_in"])
    assert sold - bought == Decimal(ui["round_trip_pnl"])
    assert sold - bought == Decimal("-0.0303")
    no_after = Decimal("1") - sold
    yes_after = bought
    assert no_after == Decimal("0.8399")
    assert yes_after == Decimal("0.1904")
    assert Decimal("1") - (no_after + yes_after) == Decimal("-0.0303")


def test_kalshi_all_in_does_not_double_count_fee():
    cash, fee = rec.kalshi_statement_cash(trade_px="0.1800", fee="0.0104", limit="0.1800", quote="0.1800")
    assert cash == Decimal("0.1800")
    assert fee == Decimal("0.0104")
    assert cash + fee == Decimal("0.1904")
    split, split_fee = rec.kalshi_statement_cash(trade_px="0.1904", fee="0.0104", limit="0.1800")
    assert split == Decimal("0.1800")
    assert split_fee == Decimal("0.0104")
    assert split + split_fee == Decimal("0.1904")


def test_poly_fill_zero_is_not_a_ticket():
    blob = _blob()
    store = {}
    for row in blob["sent"]:
        if str(row.get("venue") or "") != "polymarket":
            continue
        out = rec.apply_row(_sent(row), venue_fill={"qty": "0"}, market={}, store=store)
        assert out["action"] == "missed_send"
        assert row["order_id"] not in store
        assert w.qty_is_fill(row.get("confirm_qty")) is False
        assert w.is_empty_http_fill(200, row.get("confirm_qty")) is True


def test_eala_flatten_books_venue_net_not_two_directionals():
    blob = _blob()
    sent = [_sent(row) for row in blob["sent"]]
    trades = []
    for fill in blob["kalshi_fills"]:
        trades.append(rec._kalshi_trade_row(fill))
    store = {}
    report = rec.reconcile_rows(
        sent,
        trades=trades,
        markets={
            blob["poly_eala_slug"]: blob["poly_eala_market"],
            blob["kalshi_ticker"]: {"venue": "kalshi", "result": "", "status": "active"},
        },
        store=store,
        fetched_slugs=[blob["kalshi_ticker"], blob["poly_eala_slug"], blob["poly_pohankova_slug"]],
    )
    by_id = {row["order_id"]: row for row in report["patches"]}
    assert by_id["DDN15JAG12WK"]["action"] == "missed_send"
    assert by_id["DDN4J8JG12WA"]["action"] == "missed_send"
    assert by_id["DDGKJK1G12VP"]["action"] == "missed_send"
    assert by_id["01a18c6b-cef0-71b6-96e9-466e5a1a4dbb"]["action"] == "flatten_settled"
    assert by_id["01a18c6b-d6c0-7c80-a026-11d74753c8e5"]["action"] == "flatten_settled"
    origin = store["01a18c6b-cef0-71b6-96e9-466e5a1a4dbb"]
    close = store["01a18c6b-d6c0-7c80-a026-11d74753c8e5"]
    assert origin["flatten_pair"] is True
    assert close["flatten_pair"] is True
    assert Decimal(str(origin["wire"])) == Decimal("0.8300")
    assert Decimal(str(origin["fee"])) == Decimal("0.0099")
    assert Decimal(str(origin["after_fee"])) == Decimal("0.8399")
    assert Decimal(str(close["wire"])) == Decimal("0.1800")
    assert Decimal(str(close["fee"])) == Decimal("0.0104")
    assert Decimal(str(close["after_fee"])) == Decimal("0.1904")
    assert Decimal(str(close["flatten_net"])) == Decimal("-0.0303")
    assert Decimal(str(close["pnl"])) == Decimal("-0.0303")
    assert Decimal(str(origin["pnl"])) == Decimal("0.0000")
    assert "DDN15JAG12WK" not in store
    assert "DDGKJK1G12VP" not in store
    # Winner on Poly (Eala lost) must not rewrite flatten into two directional tickets.
    rec.apply_row(
        _sent(blob["sent"][1]),
        venue_fill={"qty": "1", "price": "0.8300", "fee": "0.0099", "side": "no"},
        market={"venue": "kalshi", "result": "no"},
        store=store,
    )
    assert store["01a18c6b-cef0-71b6-96e9-466e5a1a4dbb"]["flatten_pair"] is True
    assert Decimal(str(store["01a18c6b-cef0-71b6-96e9-466e5a1a4dbb"]["pnl"])) == Decimal("0.0000")


def test_held_lock_yes_no_is_not_a_flatten_group():
    """Chin/Kuhar-style both-sides lock is not a flatten unwind."""
    sent = [
        {
            "event": "sent",
            "order_id": "LOCK-YES",
            "venue": "polymarket",
            "instrument": "aec-demo-lock",
            "game": "Demo Lock",
            "side": "yes",
            "step": "hard",
            "http_status": 200,
            "confirm_qty": "1",
            "quote_price": "0.27",
            "limit_price": "0.27",
        },
        {
            "event": "sent",
            "order_id": "LOCK-NO",
            "venue": "polymarket",
            "instrument": "aec-demo-lock",
            "game": "Demo Lock",
            "side": "no",
            "step": "easy",
            "http_status": 200,
            "confirm_qty": "1",
            "quote_price": "0.74",
            "limit_price": "0.26",
        },
    ]
    fills = rec.fills_by_order(
        [
            {"our_order_id": "LOCK-YES", "qty": "1", "price": "0.27", "intent": "ORDER_INTENT_BUY_LONG"},
            {"our_order_id": "LOCK-NO", "qty": "1", "price": "0.26", "intent": "ORDER_INTENT_BUY_SHORT"},
        ]
    )
    assert rec.flatten_groups(sent, fills) == []


def test_stamp_does_not_directional_settle_flatten():
    origin = {
        "order_id": "01a18c6b-cef0-71b6-96e9-466e5a1a4dbb",
        "venue": "kalshi",
        "instrument": "KXWTAMATCH-26OCT29EALSHN-EAL",
        "side": "no",
        "qty": "1",
        "cash": "0.8300",
        "fee": "0.0099",
        "step": "hard",
    }
    close = {
        "order_id": "01a18c6b-d6c0-7c80-a026-11d74753c8e5",
        "venue": "kalshi",
        "instrument": "KXWTAMATCH-26OCT29EALSHN-EAL",
        "side": "yes",
        "qty": "1",
        "cash": "0.1800",
        "fee": "0.0104",
        "step": "flatten",
    }
    cluster = {
        "fill_legs": [origin, close],
        "legs": [origin, close],
        "flatten_filled": True,
        "realized": Decimal("-0.0303"),
        "game": "Eala vs Shnaider",
    }
    w.stamp_ticket_pnl([cluster], [{"ticker": "KXWTAMATCH-26OCT29EALSHN-EAL", "result": "no"}])
    assert origin["ticket_status"] == "flatten"
    assert close["ticket_status"] == "flatten"
    assert Decimal(str(origin["ticket_pnl"])) == Decimal("0")
    assert Decimal(str(close["ticket_pnl"])) == Decimal("-0.0303")
    assert Decimal(str(cluster["realized"])) == Decimal("-0.0303")


def main() -> None:
    tests = (
        test_opportunities_table_eala_sold_yes_then_poly_miss_then_bought_yes,
        test_kalshi_round_trip_is_minus_3_03_cents,
        test_kalshi_all_in_does_not_double_count_fee,
        test_poly_fill_zero_is_not_a_ticket,
        test_eala_flatten_books_venue_net_not_two_directionals,
        test_held_lock_yes_no_is_not_a_flatten_group,
        test_stamp_does_not_directional_settle_flatten,
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
