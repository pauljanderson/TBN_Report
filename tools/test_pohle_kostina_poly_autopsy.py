"""Venue-truth locks for Pohle/Kostina 28 Oct 2026. No network. No secrets."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import open_count_sync
import settled_pnl_store
import venue_fill_confirm
import write_orders_performance as w
from order_ledger import polymarket_fill

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "pohle_kostina_poly_20261028.json"
SLUG = "aec-itfwo-vicpoh-arikos-2026-10-28"
ONE = Decimal("1")


def _blob():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _fill(order_id: str) -> dict:
    for row in _blob()["fills"]:
        if row["order_id"] == order_id:
            return row
    raise AssertionError(order_id)


def test_poly_book_settlement_px_one_is_yes():
    """Pohle won. Yes Pohle settles at $1."""
    book = _blob()["poly_book"]
    assert _blob()["itf_winner"] == "Victoria Pohle"
    fields = open_count_sync._poly_payload_fields(book)
    assert fields["result"] == "yes"
    assert settled_pnl_store.result_from_market(fields) == "yes"
    assert settled_pnl_store.result_from_market(book["marketData"]["stats"]) == "yes"


def test_kostina_t0_short_cash_is_spread_0_48_not_avgpX_0_52():
    """BUY_SHORT: avgPx 0.52 is Yes-wire; cash paid is commissionSpreadPx 0.48."""
    row = _fill("DCCXJ77G11MV")
    poly = polymarket_fill(row["response"], quote=row["quote_price"], pay=row["quote_price"])
    assert poly["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert Decimal(str(poly["avg"])) == Decimal("0.5200")
    assert Decimal(str(poly["spread"])) == Decimal("0.4800")
    assert Decimal(str(poly["cash"])) == Decimal("0.4800")
    cash, fee, qty = w.fill_cash_fee(
        {
            "venue": "polymarket",
            "side": "no",
            "limit_price": "0.520",
            "quote_price": "0.48",
        },
        {"request": row["request"], "response": row["response"]},
    )
    assert qty == ONE
    assert fee == Decimal("0.0100")
    assert cash == Decimal("0.4800")


def test_kostina_cross_short_cash_is_spread_not_yes_wire():
    """09:57 cross: avg 0.48 Yes-wire, spread 0.52 house. Quote 0.53."""
    row = _fill("DCEJABR011N2")
    poly = polymarket_fill(row["response"], quote=row["quote_price"], pay=row["quote_price"])
    assert Decimal(str(poly["avg"])) == Decimal("0.4800")
    assert Decimal(str(poly["spread"])) == Decimal("0.5200")
    assert Decimal(str(poly["cash"])) == Decimal("0.5200")
    cash, fee, qty = w.fill_cash_fee(
        {
            "venue": "polymarket",
            "side": "no",
            "limit_price": "0.470",
            "quote_price": "0.53",
        },
        {"request": row["request"], "response": row["response"]},
    )
    assert qty == ONE
    assert fee == Decimal("0.0200")
    assert cash == Decimal("0.5200")


def test_pohle_won_kostina_yes_tickets_lose():
    """Ticker Yes (settlementPx 1): Pohle LONG wins; three Kostina shorts lose."""
    settlements = [{"ticker": SLUG, "result": "yes", "settlementPx": "1.0000", "venue": "polymarket"}]
    pohle = {
        "order_id": "TEST-POHLE-T0-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "1",
        "cash": "0.5300",
        "fee": "0.0200",
        "player": "Victoria Pohle",
    }
    t0 = {
        "order_id": "TEST-KOSTINA-T0-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.4800",
        "fee": "0.0100",
        "player": "Arina Kostina",
    }
    c1 = {
        "order_id": "TEST-KOSTINA-C1-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.5300",
        "fee": "0.0200",
        "player": "Arina Kostina",
    }
    c2 = {
        "order_id": "TEST-KOSTINA-C2-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.5200",
        "fee": "0.0200",
        "player": "Arina Kostina",
    }
    st, pnl = w.ticket_settled_pnl(pohle, settlements, "")
    assert st == "win"
    assert pnl == Decimal("0.4500")
    st, pnl = w.ticket_settled_pnl(t0, settlements, "")
    assert st == "lose"
    assert pnl == Decimal("-0.4900")
    st, pnl = w.ticket_settled_pnl(c1, settlements, "")
    assert st == "lose"
    assert pnl == Decimal("-0.5500")
    st, pnl = w.ticket_settled_pnl(c2, settlements, "")
    assert st == "lose"
    assert pnl == Decimal("-0.5400")
    assert (
        Decimal("0.4500")
        + Decimal("-0.4900")
        + Decimal("-0.5500")
        + Decimal("-0.5400")
        == Decimal("-1.1300")
    )


def test_wrong_ticker_no_would_invert_winner():
    """Stored ticker result=no is how the kitchen paid three Kostina wins."""
    settlements = [{"ticker": SLUG, "result": "no", "settlementPx": "0", "venue": "polymarket"}]
    pohle = {
        "order_id": "TEST-POHLE-INV-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "1",
        "cash": "0.5300",
        "fee": "0.0200",
    }
    kostina = {
        "order_id": "TEST-KOSTINA-INV-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.4800",
        "fee": "0.0200",
    }
    st_p, pnl_p = w.ticket_settled_pnl(pohle, settlements, "")
    st_k, pnl_k = w.ticket_settled_pnl(kostina, settlements, "")
    assert st_p == "lose" and pnl_p == Decimal("-0.5500")
    assert st_k == "win" and pnl_k == Decimal("0.5000")
    book = open_count_sync._poly_payload_fields(_blob()["poly_book"])
    assert book["result"] == "yes"
    assert book["result"] != settlements[0]["result"]


def test_house_cash_nickel_does_not_keep_yes_wire():
    """0.48 quote vs 0.52 avg is not 'close enough' to keep Yes-wire."""
    cash = venue_fill_confirm.poly_house_cash(
        avg="0.5200",
        spread="0.4800",
        quote="0.48",
        intent="ORDER_INTENT_BUY_SHORT",
    )
    assert cash == Decimal("0.4800")
    cash2 = venue_fill_confirm.poly_house_cash(
        avg="0.4800",
        spread="0.5200",
        quote="0.53",
        intent="ORDER_INTENT_BUY_SHORT",
    )
    assert cash2 == Decimal("0.5200")


def main() -> None:
    tests = (
        test_poly_book_settlement_px_one_is_yes,
        test_kostina_t0_short_cash_is_spread_0_48_not_avgpX_0_52,
        test_kostina_cross_short_cash_is_spread_not_yes_wire,
        test_pohle_won_kostina_yes_tickets_lose,
        test_wrong_ticker_no_would_invert_winner,
        test_house_cash_nickel_does_not_keep_yes_wire,
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
        raise SystemExit(f"{failed} failed")
    print("test_pohle_kostina_poly_autopsy ok")


if __name__ == "__main__":
    main()
