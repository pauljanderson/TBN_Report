"""Size @ price = book depth at the wire we got (ask_size / quote_size).

Paul follow-up after Gibson lock-gap fix: today trade rows must show how much
was sitting at the fill price. Prefer tape ask_size/quote_size; else order_io;
market volume_fp/liquidity only as labeled fallback.

No network. No secrets.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import write_dashboard as d
import write_orders_performance as w

ET = ZoneInfo("America/New_York")


def test_size_at_touch_prefers_ask_size_over_market_volume():
    value, source = w.size_at_touch_of(
        {"ask_size": "12", "volume_fp": "900", "side": "yes"},
    )
    assert value == "12.0000"
    assert source == "ask_size"
    cell = w.size_at_touch_cell({"ask_size": "12", "volume_fp": "900"})
    assert cell == "12.0000"
    assert "mkt" not in cell


def test_size_at_touch_falls_back_to_order_io_quote_size():
    value, source = w.size_at_touch_of(
        {"side": "no"},
        {"quote_size": "3.5", "volume": "1000"},
    )
    assert value == "3.5000"
    assert source == "quote_size"


def test_size_at_touch_market_volume_is_labeled_not_touch():
    cell = w.size_at_touch_cell({"volume_fp": "500"})
    assert cell.startswith("500")
    assert "mkt, not touch" in cell
    assert w.size_at_touch_cell({}) == "unknown"
    assert w.size_at_touch_cell({"size_at_touch": "—"}) == "unknown"


def test_dashboard_today_row_shows_size_at_price():
    leg = {
        "venue": "kalshi",
        "instrument": "KXTEST",
        "side": "no",
        "player": "Gibson",
        "cash": Decimal("0.82"),
        "fee": Decimal("0.0104"),
        "qty": Decimal("1"),
        "http": 200,
        "http_line": "HTTP 200",
        "sent_at": datetime(2026, 11, 3, 12, 0, tzinfo=ET),
        "has_io": True,
        "posted": True,
        "ask_size": "8",
        "order_id": "size-touch-1",
    }
    cluster = {
        "system_letter": "A",
        "system_name": "Lock gap",
        "game": "Gibson vs Oliynykova",
        "sport": "tennis",
        "league": "WTA",
        "side": "Gibson",
        "legs": [leg],
        "fill_legs": [leg],
        "n_fill_legs": 1,
        "realized": Decimal("0.01"),
        "open_cost": Decimal("0"),
        "open_legs": 0,
        "venue_live": False,
        "postponed": False,
        "void": False,
        "venue_paid": True,
        "market_final": True,
        "settled_legs": 1,
        "wins": 1,
        "start": datetime(2026, 11, 3, 12, 0, tzinfo=ET),
    }
    row = d.trade_row(leg, cluster)
    assert row["size_at_touch"] == "8.0000"
    assert row["size_at_touch_source"] == "ask_size"
    table = d.trade_table_rows([row])
    assert table[0][8] == "8.0000"  # Size @ price column
    html = d.write_html(
        d.build_payload(
            [cluster],
            [],
            systems=[{"letter": "A", "on": "on", "pid": "1", "alive": True}],
        )
    )
    assert "Size @ price" in html
    assert "ask_size" in html


def test_ledger_row_includes_size_at_price():
    leg = {
        "venue": "polymarket",
        "side": "no",
        "qty": Decimal("1"),
        "cash": Decimal("0.16"),
        "fee": Decimal("0"),
        "limit": Decimal("0.16"),
        "http_line": "HTTP 200",
        "ask_size": "4",
        "quote_size": "4",
        "size_at_touch": "4.0000",
        "size_at_touch_source": "ask_size",
    }
    cluster = {
        "system_letter": "A",
        "system_name": "Lock gap",
        "system_role": "lock",
        "game": "Gibson vs Oliynykova",
        "sport": "tennis",
        "league": "WTA",
        "market": "moneyline",
        "side": "Gibson",
        "number": "",
        "intent": w.INTENT_FULL_LOCK,
        "leftover_flag": "no",
        "hold_class": "resolved",
        "start": datetime(2026, 11, 3, 12, 0, tzinfo=ET),
        "n_attempts": 1,
        "legs": [leg],
        "fill_legs": [leg],
        "n_fill_legs": 1,
        "realized": Decimal("0.01"),
        "result": "settled",
        "notes": [],
        "complementary": True,
        "b_t0_both": False,
    }
    cells = w.ledger_row(cluster)
    # Fill qty, Fill prices, Size @ price are consecutive.
    assert "1.0000" in cells and "4.0000" in cells
    qty_idx = cells.index("1.0000")
    assert cells[qty_idx + 1] == "0.1600"
    assert cells[qty_idx + 2] == "4.0000"


if __name__ == "__main__":
    test_size_at_touch_prefers_ask_size_over_market_volume()
    test_size_at_touch_falls_back_to_order_io_quote_size()
    test_size_at_touch_market_volume_is_labeled_not_touch()
    test_dashboard_today_row_shows_size_at_price()
    test_ledger_row_includes_size_at_price()
    print("ok")
