"""Order ledger: all systems A–E, System column, after-fee all-in."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import order_ledger


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _rows_from(orders: list[dict], io_rows: list[dict] | None = None) -> list[list[str]]:
    folder = Path(tempfile.mkdtemp())
    orders_path = folder / "orders.jsonl"
    io_path = folder / "order_io.jsonl"
    _write_jsonl(orders_path, orders)
    _write_jsonl(io_path, io_rows or [])
    saved = order_ledger.ORDERS, order_ledger.ORDER_IO, order_ledger.SUPERVISOR_LOG
    order_ledger.ORDERS = orders_path
    order_ledger.ORDER_IO = io_path
    order_ledger.SUPERVISOR_LOG = folder / "missing.log"
    try:
        return order_ledger._new_sent_rows([])
    finally:
        order_ledger.ORDERS, order_ledger.ORDER_IO, order_ledger.SUPERVISOR_LOG = saved


def test_attempts_keep_b_off_the_prior_lock_claim():
    rows = [
        {
            "event": "claim",
            "bet_key": "tennis\tjohber\tlock",
            "game": "Johnson vs Berkieta",
            "market_type": "moneyline",
            "side": "Spencer Johnson",
        },
        {
            "event": "sent",
            "bet_key": "tennis\tjohber\tlock",
            "venue": "kalshi",
            "instrument": "KX-JOH",
            "side": "no",
            "limit_price": "0.5700",
            "http_status": 201,
            "order_id": "lock-1",
        },
        {
            "event": "sent",
            "bet_key": "tennis-b\ttennis_foo\tRodriguez Taverna vs Bueno\tkalshi\tGonzalo Bueno\tt0",
            "step": "b-t0",
            "venue": "kalshi",
            "instrument": "KX-BUE",
            "side": "yes",
            "limit_price": "0.6600",
            "http_status": 201,
            "order_id": "b-1",
        },
    ]
    groups = order_ledger._attempts(rows)
    assert len(groups) == 2
    lock_ctx, lock_ev = groups[0]
    b_ctx, b_ev = groups[1]
    assert lock_ctx["_system_label"] == "A Lock gap"
    assert lock_ctx["game"] == "Johnson vs Berkieta"
    assert [item["order_id"] for item in lock_ev if item.get("event") == "sent"] == ["lock-1"]
    assert b_ctx["_system_label"] == "B Tennis crossover"
    assert b_ctx["game"] == "Rodriguez Taverna vs Bueno"
    assert [item["order_id"] for item in b_ev if item.get("event") == "sent"] == ["b-1"]


def test_new_sent_rows_label_a_through_e():
    rows = _rows_from(
        [
            {
                "event": "claim",
                "bet_key": "tennis\tlockkey",
                "game": "Johnson vs Berkieta",
                "market_type": "moneyline",
                "side": "Spencer Johnson",
            },
            {
                "event": "sent",
                "bet_key": "tennis\tlockkey",
                "venue": "kalshi",
                "instrument": "KX-JOH",
                "side": "no",
                "limit_price": "0.5700",
                "http_status": 201,
                "order_id": "a-1",
                "wire": "0.5200",
                "fee": "0.0175",
                "after_fee": "0.5375",
            },
            {
                "event": "filled",
                "bet_key": "tennis\tlockkey",
                "venue": "kalshi",
                "instrument": "KX-JOH",
                "price": "0.5200",
            },
            {
                "event": "sent",
                "bet_key": "tennis-b\ttennis_foo\tRodriguez Taverna vs Bueno\tkalshi\tGonzalo Bueno\tt0",
                "step": "b-t0",
                "venue": "kalshi",
                "instrument": "KX-BUE",
                "side": "yes",
                "limit_price": "0.6600",
                "http_status": 201,
                "order_id": "b-1",
            },
            {
                "event": "sent",
                "bet_key": "cfb-favorite\tcollege_football_untnavy\tNorth Texas\t\t1",
                "system": "cfb_favorite",
                "step": "c-t0",
                "game": "NAVY vs UNT",
                "venue": "kalshi",
                "instrument": "KX-UNT",
                "side": "yes",
                "limit_price": "0.6000",
                "http_status": 201,
                "order_id": "c-1",
            },
            {
                "event": "sent",
                "bet_key": "spread-t0\tcollege_football_misstex\tTexas\t2.5\t1",
                "system": "spread_t0",
                "step": "d-t0",
                "game": "MISS vs TEX",
                "venue": "kalshi",
                "instrument": "KX-TEX",
                "side": "yes",
                "limit_price": "0.5700",
                "http_status": 201,
                "order_id": "d-1",
            },
            {
                "event": "sent",
                "bet_key": "tennis-t0-dog\ttennis_dog\tSpencer Johnson\t\t1",
                "system": "tennis_t0_dog",
                "step": "e-t0",
                "game": "Johnson vs Berkieta",
                "venue": "kalshi",
                "instrument": "KX-DOG",
                "side": "yes",
                "limit_price": "0.4100",
                "http_status": 201,
                "order_id": "e-1",
            },
        ]
    )
    by_id = {cells[order_ledger.COL["Order id"]]: cells for cells in rows}
    assert set(by_id) == {"a-1", "b-1", "c-1", "d-1", "e-1"}
    assert by_id["a-1"][order_ledger.COL["System"]] == "A Lock gap"
    assert by_id["a-1"][order_ledger.COL["Game"]] == "Johnson vs Berkieta"
    assert by_id["a-1"][order_ledger.COL["After-fee (all-in)"]] == "0.5375"
    assert by_id["b-1"][order_ledger.COL["System"]] == "B Tennis crossover"
    assert by_id["b-1"][order_ledger.COL["Game"]] == "Rodriguez Taverna vs Bueno"
    assert by_id["b-1"][order_ledger.COL["Pair limit price"]] == "not sent"
    assert by_id["c-1"][order_ledger.COL["System"]] == "C CFB favorite"
    assert by_id["c-1"][order_ledger.COL["Game"]] == "NAVY vs UNT"
    assert by_id["d-1"][order_ledger.COL["System"]] == "D T0 spreads"
    assert "spread" in by_id["d-1"][order_ledger.COL["Market"]]
    assert by_id["e-1"][order_ledger.COL["System"]] == "E Tennis T0 dog"


def test_after_fee_is_all_in_not_wire_as_zero():
    assert order_ledger._after_fee_cell(True, "0.5200", "0.0175") == "0.5375"
    assert order_ledger._after_fee_cell(True, "0.5200", None) == "fee unknown"
    assert order_ledger._after_fee_cell(False, "0.5200", "0") == ""
    assert order_ledger._fee_cell(True, None) == "fee unknown"
    assert order_ledger._fee_cell(False, "0") == ""


def test_legacy_html_row_inserts_system_column():
    old = [""] * 30
    old[0] = "1"
    old[1] = "Johnson vs Berkieta"
    old[4] = "kalshi"
    old[22] = "Step b-t0, attempt 1."
    got = order_ledger._coerce_existing_row(old)
    assert got[order_ledger.COL["System"]] == "B Tennis crossover"
    assert got[order_ledger.COL["Game"]] == "Johnson vs Berkieta"
    assert got[order_ledger.COL["Venue"]] == "kalshi"
    assert len(got) == order_ledger.COL_COUNT
    shifted = [""] * 31
    shifted[0] = "9"
    shifted[1] = "Trotter vs Young"
    shifted[2] = "moneyline James Kent Trotter"
    shifted[5] = "kalshi"
    fixed = order_ledger._coerce_existing_row(shifted)
    assert fixed[order_ledger.COL["System"]] == "A Lock gap"
    assert fixed[order_ledger.COL["Game"]] == "Trotter vs Young"
    assert len(fixed) == order_ledger.COL_COUNT


if __name__ == "__main__":
    test_attempts_keep_b_off_the_prior_lock_claim()
    test_new_sent_rows_label_a_through_e()
    test_after_fee_is_all_in_not_wire_as_zero()
    test_legacy_html_row_inserts_system_column()
    print("test_order_ledger ok")
