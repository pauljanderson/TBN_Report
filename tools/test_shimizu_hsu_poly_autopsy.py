"""Venue-truth locks for Shimizu/Hsu 28 Oct 2026. No network. No secrets.

These assert Polymarket fill + settlement as recorded. They fail today
until house cash and ticker result match the venue. Do not patch send
or settlement money in this job.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import open_count_sync
import order_types
import settled_pnl_store
import write_dashboard as d
import write_orders_performance as w
from order_ledger import polymarket_fill

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "shimizu_hsu_poly_20261028.json"
SLUG = "aec-atp-yutshi-yuhhsu-2026-10-27"
ONE = Decimal("1")


def _blob():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _fill(name: str) -> dict:
    for row in _blob()["fills"]:
        if row["player"] == name and row["step"] == "b-t0":
            return row
        if name == "cross" and row["step"] == "b-cross":
            return row
    raise AssertionError(name)


def test_poly_book_settlement_px_zero_is_no():
    """Hsu won. Yes Shimizu settles at $0. Dict settlementPx must parse."""
    book = _blob()["poly_book"]
    assert _blob()["atp_winner"] == "Yu-Hsiou Hsu"
    fields = open_count_sync._poly_payload_fields(book)
    assert fields["result"] == "no"
    assert settled_pnl_store.result_from_market(fields) == "no"
    assert settled_pnl_store.result_from_market(book["marketData"]["stats"]) == "no"


def test_hsu_buy_short_cash_is_spread_0_55_not_avgpX_0_45():
    """Poly BUY_SHORT: avgPx 0.45 is Yes-wire; cash paid is commissionSpreadPx 0.55."""
    hsu = _fill("Yu-Hsiou Hsu")
    poly = polymarket_fill(hsu["response"])
    assert poly["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert Decimal(str(poly["avg"])) == Decimal("0.4500")
    assert Decimal(str(poly["fee"])) == Decimal("0.0100")
    assert Decimal(str(poly["cash"])) == Decimal("0.5500")
    sent = {
        "venue": "polymarket",
        "side": "no",
        "limit_price": "0.450",
        "quote_price": "0.55",
    }
    io_row = {"request": hsu["request"], "response": hsu["response"]}
    cash, fee, qty = w.fill_cash_fee(sent, io_row)
    assert qty == ONE
    assert fee == Decimal("0.0100")
    assert cash == Decimal("0.5500")


def test_hsu_won_shimizu_yes_tickets_lose():
    """Ticker No (settlementPx 0): both Shimizu Yes lose; Hsu BUY_SHORT wins."""
    settlements = [{"ticker": SLUG, "result": "no", "venue": "polymarket"}]
    shim = {
        "order_id": "TEST-SHIMIZU-T0-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "1",
        "cash": "0.4600",
        "fee": "0.0200",
        "player": "Yuta Shimizu",
    }
    hsu = {
        "order_id": "TEST-HSU-T0-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.5500",
        "fee": "0.0100",
        "player": "Yu-Hsiou Hsu",
    }
    cross = {
        "order_id": "TEST-SHIMIZU-CROSS-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "1",
        "cash": "0.6000",
        "fee": "0.0200",
        "player": "Yuta Shimizu",
    }
    st, pnl = w.ticket_settled_pnl(shim, settlements, "")
    assert st == "lose"
    assert pnl == Decimal("-0.4800")
    st, pnl = w.ticket_settled_pnl(hsu, settlements, "")
    assert st == "win"
    assert pnl == Decimal("0.4400")
    st, pnl = w.ticket_settled_pnl(cross, settlements, "")
    assert st == "lose"
    assert pnl == Decimal("-0.6200")
    assert Decimal("-0.4800") + Decimal("0.4400") + Decimal("-0.6200") == Decimal("-0.6600")


def test_wrong_ticker_yes_would_invert_winner():
    """Stored ticker result=yes is how the dashboard showed two Shimizu wins."""
    settlements = [{"ticker": SLUG, "result": "yes", "venue": "polymarket"}]
    shim = {
        "order_id": "TEST-SHIMIZU-INV-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "1",
        "cash": "0.4600",
        "fee": "0.0200",
    }
    hsu = {
        "order_id": "TEST-HSU-INV-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.4500",
        "fee": "0.0100",
    }
    st_s, pnl_s = w.ticket_settled_pnl(shim, settlements, "")
    st_h, pnl_h = w.ticket_settled_pnl(hsu, settlements, "")
    assert st_s == "win" and pnl_s == Decimal("0.5200")
    assert st_h == "lose" and pnl_h == Decimal("-0.4600")
    assert st_s != "lose"
    assert _blob()["atp_winner"] == "Yu-Hsiou Hsu"
    book = open_count_sync._poly_payload_fields(_blob()["poly_book"])
    assert book["result"] == "no"
    assert book["result"] != settlements[0]["result"]


def test_type_column_uses_quote_not_short_wire():
    """Hsu quote 0.55 is B T0 hi; Shimizu 0.46 is low; 0.63 send is crossover."""
    slug = SLUG
    shim = {
        "venue": "polymarket",
        "instrument": slug,
        "side": "yes",
        "player": "Yuta Shimizu",
        "step": "b-t0",
        "quote_price": "0.46",
        "cash": "0.4600",
        "limit": "0.460",
        "qty": 1,
        "has_io": True,
        "http": 200,
        "order_id": "test-shim-t0",
    }
    hsu = {
        "venue": "polymarket",
        "instrument": slug,
        "side": "no",
        "player": "Yu-Hsiou Hsu",
        "step": "b-t0",
        "quote_price": "0.55",
        "cash": "0.4500",
        "limit": "0.450",
        "qty": 1,
        "has_io": True,
        "http": 200,
        "order_id": "test-hsu-t0",
    }
    cross = {
        "venue": "polymarket",
        "instrument": slug,
        "side": "yes",
        "player": "Yuta Shimizu",
        "step": "b-cross",
        "quote_price": "0.63",
        "cash": "0.6000",
        "limit": "0.630",
        "qty": 1,
        "has_io": True,
        "http": 200,
        "order_id": "test-shim-cross",
    }
    cluster = {
        "system_letter": "B",
        "game": "Yuta Shimizu vs. Yu Hsiou Hsu",
        "is_b": True,
        "legs": [shim, hsu, cross],
        "fill_legs": [shim, hsu, cross],
    }
    assert order_types.from_leg(hsu, cluster) == order_types.TYPE_B_HI
    assert order_types.from_leg(shim, cluster) == order_types.TYPE_B_LO
    assert order_types.from_leg(cross, cluster) == order_types.TYPE_B_CROSS
    row = d.trade_row(hsu, cluster)
    assert row["order_type"] == order_types.TYPE_B_HI
    html = d.write_html(
        d.build_payload(
            [cluster],
            [],
            systems=[{"letter": "B", "on": "on", "pid": "2", "alive": True}],
        )
    )
    assert ">Type<" in html
    assert order_types.TYPE_B_HI in html
    assert "What you asked" not in html


def main() -> None:
    tests = (
        test_poly_book_settlement_px_zero_is_no,
        test_hsu_buy_short_cash_is_spread_0_55_not_avgpX_0_45,
        test_hsu_won_shimizu_yes_tickets_lose,
        test_wrong_ticker_yes_would_invert_winner,
        test_type_column_uses_quote_not_short_wire,
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
        raise SystemExit(f"{failed} failed (venue truth; production money not patched)")
    print("test_shimizu_hsu_poly_autopsy ok")


if __name__ == "__main__":
    main()
