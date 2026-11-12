"""Consideration table: one lock pair + flatten. Aboian primary, Eala second.

Paul wants the intended Poly shop named even when it missed or was never sent.
No network. No secrets. No live orders.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import opportunity_considerations as oc

ROOT = Path(__file__).resolve().parents[1]
ABOIAN = ROOT / "tools" / "fixtures" / "aboian_hardt_flatten_20261030.json"
EALA = ROOT / "tools" / "fixtures" / "eala_shnaider_pohankova_20261030.json"


def _blob(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sent(blob: dict) -> list[dict]:
    return [dict(row, event=row.get("event") or "sent") for row in blob.get("sent") or []]


def test_aboian_kalshi_sold_yes_bought_yes_is_one_flatten_story():
    blob = _blob(ABOIAN)
    ui = blob["kalshi_ui"]
    view = oc.attempt_from_row(blob["consider_row"], _sent(blob))
    leg1, leg2, flatten = view["leg1"], view["leg2"], view["flatten"]
    assert view["game"] == "Aboian vs Hardt"
    assert view["sport"] == "tennis"
    assert view["bet_type"] == "moneyline"
    assert view["type"] == "A lock gap"
    assert view["outcome"] == "one+flatten"
    assert leg1["platform"].lower() == "kalshi"
    assert leg1["side"] == "No"
    assert "Sold Yes 34.38\u00a2" in (leg1.get("ui") or "")
    assert "Limit 36\u00a2" in (leg1.get("ui") or "")
    assert leg1["fill"].startswith("fill 1")
    assert str(leg1.get("fill_px") or "").startswith("0.6400")
    assert "18:49:56" in (leg1.get("send_et") or "")
    assert Decimal(ui["sold_yes_all_in"]) == Decimal("0.3438")
    assert leg2["platform"].lower() == "polymarket"
    assert leg2["side"] == "Yes"
    assert str(leg2.get("limit") or "").startswith("0.370")
    assert leg2["fill"] == "never sent"
    assert not oc._leg_filled(leg2)
    assert flatten["platform"].lower() == "kalshi"
    assert flatten["side"] == "Yes"
    assert "Bought Yes 37.62\u00a2" in (flatten.get("ui") or "")
    assert "Limit 36\u00a2" in (flatten.get("ui") or "")
    assert flatten["fill"].startswith("fill 1")
    assert str(flatten.get("fill_px") or "").startswith("0.3600")
    assert "18:50:01" in (flatten.get("send_et") or "")
    assert flatten["pnl"] == Decimal(ui["round_trip_pnl"]) == Decimal("-0.0324")
    later = [row for row in _sent(blob) if str(row.get("limit_price") or "") == "0.150"]
    assert later
    assert str(leg2.get("limit") or "") != "0.150"
    html = oc._cells(blob["consider_row"], _sent(blob))
    assert "Sold Yes 34.38\u00a2" in html
    assert "Bought Yes 37.62\u00a2" in html
    assert "never sent" in html
    assert "one+flatten" in html
    assert "A lock gap" in html
    assert ">0.150<" not in html
    assert "polymarket" in html.lower()


def test_aboian_poly_37c_was_never_sent():
    blob = _blob(ABOIAN)
    assert blob["poly_37c"]["sent"] is False
    view = oc.attempt_from_row(blob["consider_row"], _sent(blob))
    assert view["leg2"]["platform"].lower() == "polymarket"
    assert view["leg2"]["fill"] == "never sent"
    assert view["leg2"]["sent"] is False
    html = oc._cells(blob["consider_row"], _sent(blob))
    assert "never sent" in html
    assert html.count("never sent") >= 1


def test_eala_same_pattern_poly_miss_then_flatten():
    blob = _blob(EALA)
    ui = blob["kalshi_ui"]
    view = oc.attempt_from_row(blob["consider_row"], _sent(blob))
    leg1, leg2, flatten = view["leg1"], view["leg2"], view["flatten"]
    assert view["game"] == "Eala vs Shnaider"
    assert view["outcome"] == "one+flatten"
    assert view["type"] == "A lock gap"
    assert leg1["platform"].lower() == "kalshi"
    assert leg1["side"] == "No"
    assert "Sold Yes 16.01\u00a2" in (leg1.get("ui") or "")
    assert "Limit 17\u00a2" in (leg1.get("ui") or "")
    assert leg1["fill"].startswith("fill 1")
    assert str(leg1.get("fill_px") or "").startswith("0.8300")
    assert "06:47:18" in (leg1.get("send_et") or "")
    assert Decimal(ui["sold_yes_all_in"]) == Decimal("0.1601")
    assert leg2["platform"].lower() == "polymarket"
    assert leg2["side"] == "Yes"
    assert str(leg2.get("limit") or "").startswith("0.130")
    assert leg2["fill"] == "miss 0"
    assert not oc._leg_filled(leg2)
    assert flatten["platform"].lower() == "kalshi"
    assert flatten["side"] == "Yes"
    assert "Bought Yes 19.04\u00a2" in (flatten.get("ui") or "")
    assert "Limit 18\u00a2" in (flatten.get("ui") or "")
    assert flatten["fill"].startswith("fill 1")
    assert str(flatten.get("fill_px") or "").startswith("0.1800")
    assert "06:47:21" in (flatten.get("send_et") or "")
    assert flatten["pnl"] == Decimal(ui["round_trip_pnl"]) == Decimal("-0.0303")
    html = oc._cells(blob["consider_row"], _sent(blob))
    assert "Sold Yes 16.01\u00a2" in html
    assert "Bought Yes 19.04\u00a2" in html
    assert "miss 0" in html
    assert "one+flatten" in html
    assert "polymarket" in html.lower()


def test_table_headers_are_lock_pair_columns():
    labels = [name for name, _kind in oc.TABLE_HEADERS]
    assert labels[0] == "Game"
    assert "Leg 1 fill?" in labels
    assert "Leg 2 fill?" in labels
    assert "Flatten P&L" in labels
    assert "Outcome" in labels
    assert "Venue return" not in labels
    assert len(labels) == 32


def main() -> None:
    tests = (
        test_aboian_kalshi_sold_yes_bought_yes_is_one_flatten_story,
        test_aboian_poly_37c_was_never_sent,
        test_eala_same_pattern_poly_miss_then_flatten,
        test_table_headers_are_lock_pair_columns,
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
