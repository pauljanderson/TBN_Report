"""Moreno vs Herrera 28 Oct 2026: venue settle + 0.3 leftover. No network. No secrets."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import live_lock_orders
import open_count_sync
import settled_pnl_store
import write_orders_performance as w

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "moreno_herrera_poly_20261028.json"
SLUG = "aec-utr-morale-cartho-2026-10-28"
ONE = Decimal("1")


def _blob():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_official_and_venue_moreno_won():
    blob = _blob()
    assert blob["official_winner"] == "Alejandro Moreno"
    assert blob["poly_settlement"]["settlementPx"] == "1.0000"
    assert blob["poly_settlement"]["result"] == "yes"
    fields = open_count_sync._poly_payload_fields(blob["poly_book"])
    assert settled_pnl_store.result_from_market(fields) == "yes"
    assert settled_pnl_store.result_from_market(blob["poly_settlement"]) == "yes"


def test_t0_partial_0_3_is_ledger_fill_not_house_one():
    blob = _blob()
    t0 = blob["legs"]["t0_moreno"]
    qty = Decimal(str(t0["qty"]))
    assert qty == Decimal("0.3")
    assert w.qty_is_fill(qty) is True
    assert w.qty_is_house_fill(qty) is False
    assert w.flatten_marks_house_one(qty, Decimal("1")) is True
    assert w.is_empty_http_fill(200, qty) is False


def test_flatten_refuses_house_one_on_0_3():
    out = live_lock_orders.flatten_filled_leg(
        lambda *_a, **_k: None,
        "tennis-b\ttest\tMoreno vs Herrera\tpolymarket\tMoreno\tflatten",
        "Alejandro Moreno vs. Thomas Cardona Herrera",
        {
            "venue": "polymarket",
            "instrument": SLUG,
            "outcome": "yes",
            "fill_qty": "0.3",
        },
    )
    assert out.get("posted") is False
    assert "not flattening as 1" in str(out.get("note") or "")


def test_herrera_short_cash_is_0_16_not_yes_wire_0_84():
    blob = _blob()
    her = blob["legs"]["t0_herrera"]
    assert her["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert Decimal(str(her["cash"])) == Decimal("0.16")
    assert Decimal(str(her["yes_wire"])) == Decimal("0.84")


def test_four_bets_venue_true_pnl():
    """Moreno won. 0.3 LONG + flatten LONG win; Herrera SHORT loses. Net +0.005 with fees."""
    settlements = [
        {
            "ticker": SLUG,
            "result": "yes",
            "settlementPx": "1.0000",
            "source": "live_market_get",
            "venue": "polymarket",
            "status": "MARKET_STATE_EXPIRED",
            "expired": True,
        }
    ]
    t0_m = {
        "order_id": "DCFF2ZM011N2",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "0.3",
        "cash": "0.8500",
        "fee": "0",
        "player": "Moreno, Alejandro",
    }
    t0_h = {
        "order_id": "DCFF326G11R3",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "no",
        "qty": "1",
        "cash": "0.1600",
        "fee": "0.0100",
        "player": "Cardona Herrera, Thomas",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
    }
    flat = {
        "order_id": "DCFGAH0011N2",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "1",
        "cash": "0.8600",
        "fee": "0.0100",
        "player": "Moreno, Alejandro",
        "step": "flatten",
    }
    st_m, pnl_m = w.ticket_settled_pnl(t0_m, settlements, "Alejandro Moreno")
    st_h, pnl_h = w.ticket_settled_pnl(t0_h, settlements, "Alejandro Moreno")
    st_f, pnl_f = w.ticket_settled_pnl(flat, settlements, "Alejandro Moreno")
    assert st_m == "win"
    assert pnl_m == Decimal("0.0450")
    assert st_h == "lose"
    assert pnl_h == Decimal("-0.1700")
    assert st_f == "win"
    assert pnl_f == Decimal("0.1300")
    assert pnl_m + pnl_h + pnl_f == Decimal("0.0050")
    cluster = {
        "game": "Alejandro Moreno vs. Thomas Cardona Herrera",
        "sport": "tennis",
        "fill_legs": [t0_m, t0_h, flat],
        "n_fill_legs": 3,
        "complementary": True,
        "flatten_filled": True,
        "watch": {"stage": "postponed", "postponed_reason": "closed without settlement"},
        "notes": ["postponed closed without settlement", "B stage postponed"],
    }
    scored = w.score_cluster(cluster, settlements, {"kalshi": {}, "polymarket": {}}, w.market_index_of(settlements))
    assert scored.get("postponed") is False
    assert scored.get("venue_paid") is True
    assert w.cluster_is_settled(scored) is True
    assert scored.get("realized") == Decimal("0.0050")
    hits = w.scan_postponed_but_settled(
        [{**cluster, "postponed": True}],
        settlements,
    )
    assert hits


def test_missed_send_qty_zero_is_not_a_ticket():
    settlements = [{"ticker": SLUG, "result": "yes", "settlementPx": "1.0000", "venue": "polymarket"}]
    miss = {
        "order_id": "TEST-MISS-NOT-LIVE",
        "venue": "polymarket",
        "instrument": SLUG,
        "side": "yes",
        "qty": "0",
        "cash": "0.85",
        "fee": "0",
        "http": 200,
    }
    assert w.qty_is_fill(miss["qty"]) is False
    w.stamp_ticket_pnl(
        [{"postponed": False, "fill_legs": [], "legs": [miss], "void": False}],
        settlements,
    )
    assert miss.get("ticket_status") not in {"win", "lose"}


def main() -> None:
    tests = (
        test_official_and_venue_moreno_won,
        test_t0_partial_0_3_is_ledger_fill_not_house_one,
        test_flatten_refuses_house_one_on_0_3,
        test_herrera_short_cash_is_0_16_not_yes_wire_0_84,
        test_four_bets_venue_true_pnl,
        test_missed_send_qty_zero_is_not_a_ticket,
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
    print("test_moreno_herrera_poly_autopsy ok")


if __name__ == "__main__":
    main()
