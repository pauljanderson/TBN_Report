"""Venue-true settle reconciler. No network. No secrets. No second B."""
from __future__ import annotations

from decimal import Decimal

import live_pm_settle_reconcile as rec
import settled_pnl_store
import write_orders_performance as w

SLUG = "aec-itfme-chiduh-arylak-2026-10-28"
MARKET_NO = {
    "venue": "polymarket",
    "settlementPx": "0.0000",
    "result": "no",
    "state": "MARKET_STATE_EXPIRED",
}


def _sent(**kwargs):
    row = {
        "event": "sent",
        "venue": "polymarket",
        "instrument": SLUG,
        "game": "Chirag Duhan vs. Aryan Lakshmanan",
        "http_status": 200,
        "confirm_qty": "0",
        "tape_qty": "0",
        "side": "no",
        "quote_price": "0.52",
        "limit_price": "0.48",
    }
    row.update(kwargs)
    return row


def test_confirm_zero_is_never_a_won_ticket():
    store = {
        "DC9FDBMG11N6": {
            "order_id": "DC9FDBMG11N6",
            "qty": "0",
            "status": "win",
            "pnl": "0.50",
        }
    }
    sent = _sent(order_id="DC9FDBMG11N6", confirm_qty="0")
    out = rec.apply_row(sent, venue_fill={"qty": "0"}, market=MARKET_NO, store=store)
    assert out["action"] == "clear_false_win"
    assert "DC9FDBMG11N6" not in store
    miss = rec.apply_row(
        _sent(order_id="GHOST0"),
        venue_fill=None,
        market=MARKET_NO,
        store=store,
    )
    assert miss["action"] == "missed_send"
    assert w.qty_is_fill("0") is False
    assert w.is_empty_http_fill(200, "0") is True


def test_qty_0_02_is_real_fill_not_house_one():
    store = {}
    sent = _sent(
        order_id="DC9R5HV011TB",
        confirm_qty="0.02",
        tape_qty="0.02",
        quote_price="0.52",
        limit_price="0.48",
        side="no",
    )
    fill = {
        "qty": Decimal("0.02"),
        "price": Decimal("0.4800"),
        "intent": "ORDER_INTENT_BUY_SHORT",
        "fee": Decimal("0"),
    }
    out = rec.apply_row(sent, venue_fill=fill, market=MARKET_NO, store=store)
    assert out["action"] == "settled"
    assert out["house"] == "tiny"
    row = store["DC9R5HV011TB"]
    assert Decimal(str(row["qty"])) == Decimal("0.0200")
    assert Decimal(str(row["qty"])) < 1
    assert w.qty_is_fill(row["qty"]) is True
    assert w.qty_is_house_fill(row["qty"]) is False
    assert Decimal(str(row["wire"])) == Decimal("0.4800")
    assert Decimal(str(row["pnl"])) == Decimal("0.0104")
    assert row["status"] == "win"


def test_t0_both_yes_pnl_matches_poly_house_cash():
    store = {}
    duhan = _sent(
        order_id="DC8MDRS011R3",
        confirm_qty="1",
        side="yes",
        quote_price="0.73",
        limit_price="0.730",
        game="Chirag Duhan vs. Aryan Lakshmanan",
    )
    lak = _sent(
        order_id="DC8MDY5011TB",
        confirm_qty="1",
        side="no",
        quote_price="0.28",
        limit_price="0.720",
    )
    rec.apply_row(
        duhan,
        venue_fill={"qty": "1", "price": "0.7300", "intent": "ORDER_INTENT_BUY_LONG", "fee": "0.01"},
        market=MARKET_NO,
        store=store,
    )
    rec.apply_row(
        lak,
        venue_fill={"qty": "1", "price": "0.7200", "intent": "ORDER_INTENT_BUY_SHORT", "fee": "0.01"},
        market=MARKET_NO,
        store=store,
    )
    assert store["DC8MDRS011R3"]["status"] == "lose"
    assert Decimal(str(store["DC8MDRS011R3"]["pnl"])) == Decimal("-0.7400")
    assert store["DC8MDY5011TB"]["status"] == "win"
    assert Decimal(str(store["DC8MDY5011TB"]["wire"])) == Decimal("0.2800")
    assert Decimal(str(store["DC8MDY5011TB"]["pnl"])) == Decimal("0.7100")


def test_fills_by_order_sums_executions_not_house_one():
    trades = [
        {"our_order_id": "DC9R5HV011TB", "qty": "0.0200", "price": {"value": "0.4800"}},
        {"our_order_id": "DC8MDRS011R3", "qty": "0.8400", "price": {"value": "0.7300"}},
        {"our_order_id": "DC8MDRS011R3", "qty": "0.0300", "price": {"value": "0.7300"}},
        {"our_order_id": "DC8MDRS011R3", "qty": "0.0300", "price": {"value": "0.7300"}},
        {"our_order_id": "DC8MDRS011R3", "qty": "0.1000", "price": {"value": "0.7300"}},
    ]
    by_id = rec.fills_by_order(trades)
    assert by_id["DC9R5HV011TB"]["qty"] == Decimal("0.0200")
    assert by_id["DC8MDRS011R3"]["qty"] == Decimal("1.0000")
    assert "DC9FDBMG11N6" not in by_id


def test_reconcile_rows_maps_kitchen_to_poly():
    sent = [
        _sent(order_id="DC9R5HV011TB", confirm_qty="0.02", tape_qty="0.02"),
        _sent(order_id="DC9FDBMG11N6", confirm_qty="0"),
        _sent(
            order_id="DC8MDRS011R3",
            confirm_qty="1",
            side="yes",
            quote_price="0.73",
            limit_price="0.73",
        ),
        _sent(
            order_id="DC8MDY5011TB",
            confirm_qty="1",
            side="no",
            quote_price="0.28",
            limit_price="0.72",
        ),
    ]
    trades = [
        {"our_order_id": "DC9R5HV011TB", "qty": "0.0200", "price": {"value": "0.4800"}, "intent": "ORDER_INTENT_BUY_SHORT", "slug": SLUG},
        {"our_order_id": "DC8MDRS011R3", "qty": "1.0000", "price": {"value": "0.7300"}, "intent": "ORDER_INTENT_BUY_LONG", "fee": "0.01", "slug": SLUG},
        {"our_order_id": "DC8MDY5011TB", "qty": "1.0000", "price": {"value": "0.7200"}, "intent": "ORDER_INTENT_BUY_SHORT", "fee": "0.01", "slug": SLUG},
    ]
    store = {}
    report = rec.reconcile_rows(
        sent,
        trades=trades,
        markets={SLUG: MARKET_NO, SLUG.lower(): MARKET_NO},
        store=store,
    )
    by_id = {row["order_id"]: row for row in report["patches"]}
    assert by_id["DC9FDBMG11N6"]["action"] == "missed_send"
    assert by_id["DC9R5HV011TB"]["action"] == "settled"
    assert Decimal(str(store["DC9R5HV011TB"]["qty"])) == Decimal("0.0200")
    assert Decimal(str(store["DC9R5HV011TB"]["wire"])) == Decimal("0.4800")
    assert "DC9FDBMG11N6" not in store


def test_unfetched_slug_is_not_cleared():
    store = {
        "KEEP1": {"order_id": "KEEP1", "qty": "1", "status": "win", "pnl": "0.50"},
    }
    sent = [_sent(order_id="KEEP1", confirm_qty="1", instrument="aec-other-slug")]
    report = rec.reconcile_rows(
        sent,
        trades=[{"our_order_id": "DC9R5HV011TB", "qty": "0.02", "slug": SLUG}],
        markets={},
        store=store,
        fetched_slugs=[SLUG],
    )
    assert store["KEEP1"]["status"] == "win"
    assert all(row.get("order_id") != "KEEP1" for row in report["changed"])


def test_ensure_settle_reconcile_never_starts_second():
    import prediction_job_control as jc

    jobs = {
        "settle_reconcile": [{"pid": 77, "cmd": "python -u tools/live_pm_settle_reconcile.py"}],
        "strategy_b": [{"pid": 44, "cmd": "python -u tools/live_strategy_b.py"}],
        "supervisor": [],
        "scan": [],
        "children": [],
        "poll_all": [],
        "lock_sender": [],
        "cfb_favorite": [],
        "spread_t0": [],
        "tennis_t0_dog": [],
    }
    spawned = []
    saved = jc._spawn
    jc._spawn = lambda *a, **k: spawned.append(a)
    try:
        assert jc.ensure_settle_reconcile(jobs) is False
        assert spawned == []
    finally:
        jc._spawn = saved


def test_chin_kuhar_yes_wire_quote_uses_venue_debit():
    """Kuhar BUY_SHORT: kitchen Yes-ask 0.74, Poly TRADE 0.26. Winner is Kuhar (Yes Chin = 0)."""
    import json
    from pathlib import Path

    import venue_fill_confirm

    slug = "aec-itfme-johchi-matkuh-2026-10-28"
    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "chin_kuhar_poly_20261028.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["official_winner"] == "Matt Kuhar"
    assert fixture["poly_settlement"]["settlementPx"] == "0.0000"
    assert fixture["poly_settlement"]["result"] == "no"
    assert venue_fill_confirm.poly_house_cash(
        avg="0.2600",
        spread="0.7400",
        quote="0.74",
        api_limit="0.26",
        intent="ORDER_INTENT_BUY_SHORT",
    ) == Decimal("0.2600")
    market = {
        "venue": "polymarket",
        "settlementPx": "0.0000",
        "result": "no",
        "state": "MARKET_STATE_EXPIRED",
    }
    store = {}
    chin = _sent(
        order_id="DCCWHAK011MM",
        confirm_qty="1",
        side="yes",
        quote_price="0.27",
        limit_price="0.270",
        instrument=slug,
        game="John Chin vs. Matt Kuhar",
    )
    kuhar = _sent(
        order_id="DCCWHE2G11M3",
        confirm_qty="1",
        side="no",
        quote_price="0.74",
        limit_price="0.260",
        instrument=slug,
        game="John Chin vs. Matt Kuhar",
    )
    rec.apply_row(
        chin,
        venue_fill={"qty": "1", "price": "0.2700", "intent": "ORDER_INTENT_BUY_LONG", "fee": "0.01"},
        market=market,
        store=store,
    )
    rec.apply_row(
        kuhar,
        venue_fill={"qty": "1", "price": "0.2600", "intent": "ORDER_INTENT_BUY_SHORT", "fee": "0.01"},
        market=market,
        store=store,
    )
    assert store["DCCWHAK011MM"]["status"] == "lose"
    assert Decimal(str(store["DCCWHAK011MM"]["pnl"])) == Decimal("-0.2800")
    assert store["DCCWHE2G11M3"]["status"] == "win"
    assert Decimal(str(store["DCCWHE2G11M3"]["wire"])) == Decimal("0.2600")
    assert Decimal(str(store["DCCWHE2G11M3"]["pnl"])) == Decimal("0.7300")
    by_id = rec.fills_by_order(fixture["trades"])
    assert by_id["DCCWHAK011MM"]["qty"] == Decimal("1.0000")
    assert by_id["DCCWHE2G11M3"]["qty"] == Decimal("1.0000")
    kitchen_kuhar = Decimal("0.2500")
    assert Decimal(str(store["DCCWHE2G11M3"]["pnl"])) - kitchen_kuhar == Decimal("0.4800")


def test_classify_picks_up_reconcile_process():
    import prediction_job_control as jc

    rows = [
        {
            "pid": 99,
            "parent": 1,
            "started": "2026-10-29 15:20:00",
            "cmd": "python -u tools/live_pm_settle_reconcile.py",
        },
        {
            "pid": 44,
            "parent": 1,
            "started": "2026-10-29 15:20:00",
            "cmd": "python -u tools/live_strategy_b.py",
        },
    ]
    jobs = jc.classify(rows)
    assert len(jobs["settle_reconcile"]) == 1
    assert jobs["settle_reconcile"][0]["pid"] == 99
    assert len(jobs["strategy_b"]) == 1


def main() -> None:
    tests = (
        test_confirm_zero_is_never_a_won_ticket,
        test_qty_0_02_is_real_fill_not_house_one,
        test_t0_both_yes_pnl_matches_poly_house_cash,
        test_fills_by_order_sums_executions_not_house_one,
        test_reconcile_rows_maps_kitchen_to_poly,
        test_unfetched_slug_is_not_cleared,
        test_chin_kuhar_yes_wire_quote_uses_venue_debit,
        test_ensure_settle_reconcile_never_starts_second,
        test_classify_picks_up_reconcile_process,
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
