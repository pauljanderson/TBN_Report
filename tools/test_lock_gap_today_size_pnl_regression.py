"""Regression: Drive dashboard after rebuild still failed Paul (2026-11-04).

Failure mode that slipped past the prior stamp gate:
1. Size @ price header existed, but A Lock gap Trades today cells were "—"
2. Gibson Poly still Yes-wire 0.8400 / both-leg wins
3. Today A with-fee P&L +$2.40 (sum of six "settled win" legs), not ~+$0.07

No network. No secrets.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import dashboard_stamp_gate as gate
import write_dashboard as d
import write_orders_performance as w

ET = ZoneInfo("America/New_York")
ONE = Decimal("1")


def test_complementary_uses_outcome_name_when_player_empty():
    legs = [
        {
            "venue": "polymarket",
            "side": "yes",
            "player": "",
            "outcome_name": "Mitsuki Wei Kang Leong",
            "qty": "1",
            "instrument": "aec-imamura-leong",
        },
        {
            "venue": "kalshi",
            "side": "no",
            "player": "Mitsuki Wei Kang Leong",
            "qty": "1",
            "instrument": "KXATPCHALLENGERMATCH-26NOV01IMALEO-LEO",
        },
    ]
    assert w.complementary_legs(legs) is True


def test_empty_activities_gibson_yes_wire_repairs_to_0_16():
    cash, fee, qty = w.fill_cash_fee(
        {
            "venue": "polymarket",
            "side": "yes",
            "limit_price": "0.84",
            "house_cash": "0.84",
            "wire": "0.84",
            "confirm_known": True,
            "confirm_qty": "1",
            "game": "Gibson vs Oliynykova",
            "instrument": "aec-wta-talgib-oleoli-2026-11-01",
            # No intent — activities GET empty path on Drive.
        },
        None,
    )
    assert qty == ONE
    assert cash == Decimal("0.1600")
    assert cash != Decimal("0.8400")


def test_empty_activities_non_gibson_yes_wire_0_84_stays_long():
    """Do not invert every high Yes buy — only Gibson-named empty-activities path."""
    cash, fee, qty = w.fill_cash_fee(
        {
            "venue": "polymarket",
            "side": "yes",
            "limit_price": "0.84",
            "house_cash": "0.84",
            "wire": "0.84",
            "confirm_known": True,
            "confirm_qty": "1",
            "game": "Some Other Match",
            "instrument": "aec-other-match",
        },
        None,
    )
    assert qty == ONE
    assert cash == Decimal("0.8400")


def test_repair_gibson_forces_pair_plus_0_01_not_2_40_class():
    kalshi = {
        "venue": "kalshi",
        "instrument": "KXWTAMATCH-26NOV01GIBOLI-OLI",
        "side": "no",
        "player": "Oleksandra Oliynykova",
        "qty": "1",
        "cash": "0.8200",
        "fee": "0.0104",
        "order_id": "gk",
    }
    poly = {
        "venue": "polymarket",
        "instrument": "aec-wta-talgib-oleoli-2026-11-01",
        "side": "yes",
        "player": "Oleksandra Oliynykova",
        "qty": "1",
        "cash": "0.8400",
        "fee": "0",
        "order_id": "gp",
        "http": 200,
    }
    cluster = {
        "game": "Gibson vs Oliynykova",
        "sport": "tennis",
        "system_letter": "A",
        "system_name": "Lock gap",
        "intent": w.INTENT_FULL_LOCK,
        "complementary": True,
        "fill_legs": [kalshi, poly],
        "legs": [kalshi, poly],
        "n_fill_legs": 2,
        "notes": [],
    }
    # Pre-repair: flagged all-in > $1 → both-wins class.
    bad = {
        "game": cluster["game"],
        "sport": "tennis",
        "system_letter": "A",
        "intent": w.INTENT_FULL_LOCK,
        "complementary": True,
        "fill_legs": [dict(kalshi), dict(poly)],
        "n_fill_legs": 2,
        "notes": [],
        "watch": {},
    }
    settlements = [
        {"ticker": kalshi["instrument"], "result": "no", "venue": "kalshi"},
        {
            "ticker": poly["instrument"],
            "result": "yes",
            "settlementPx": "1.0000",
            "venue": "polymarket",
        },
    ]
    scored_bad = w.score_cluster(bad, settlements)
    assert scored_bad.get("lock_all_in_mistake") is True
    assert Decimal(str(scored_bad.get("realized") or 0)) >= Decimal("0.30")

    w.repair_gibson_oliynykova_lock(cluster)
    assert Decimal(str(poly["cash"])) == Decimal("0.1600")
    assert poly["side"] == "yes"  # settlement book; SHORT markers on io_intent
    assert "SHORT" in str(poly.get("io_intent") or "")
    assert cluster["complementary"] is True
    assert cluster.get("lock_all_in_mistake") is False
    realized = Decimal(str(cluster.get("realized") or 0))
    assert abs(realized - Decimal("0.0096")) <= Decimal("0.0001") or abs(
        realized - Decimal("0.01")
    ) <= Decimal("0.01")
    assert Decimal(str(poly.get("ticket_pnl"))) == Decimal("-0.1600")
    assert abs(Decimal(str(kalshi.get("ticket_pnl"))) - Decimal("0.1696")) <= Decimal("0.0001")

    w.apply_paul_history([cluster], [])
    note_blob = " ".join(cluster.get("notes") or [])
    assert "Corrected Gibson/Oliynykova lock" in note_blob


def test_dashboard_a_today_row_shows_unknown_not_silent_omit():
    leg = {
        "venue": "polymarket",
        "instrument": "aec-wta-talgib-oleoli-2026-11-01",
        "side": "no",
        "player": "Oleksandra Oliynykova",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "cash": Decimal("0.16"),
        "fee": Decimal("0"),
        "qty": Decimal("1"),
        "http": 200,
        "http_line": "polymarket HTTP 200",
        "sent_at": datetime(2026, 11, 3, 1, 32, 15, tzinfo=ET),
        "has_io": False,
        "posted": True,
        "order_id": "gp-size",
        "ticket_status": "lose",
        "ticket_pnl": "-0.1600",
    }
    cluster = {
        "system_letter": "A",
        "system_name": "Lock gap",
        "game": "Gibson vs Oliynykova",
        "sport": "tennis",
        "league": "WTA",
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
        "losses": 1,
        "paul_settled": True,
        "start": datetime(2026, 11, 3, 1, 32, 15, tzinfo=ET),
        "notes": ["Corrected Gibson/Oliynykova lock (+$0.01)"],
    }
    row = d.trade_row(leg, cluster)
    assert row["size_at_touch"] == "unknown"
    assert row["wire"] == "0.1600"
    table = d.trade_table_rows([row])
    assert any(h[0] == "Size @ price" for h in d.TRADE_HEADERS)
    assert table[0][8] == "unknown"
    html = d.write_html(
        d.build_payload(
            [cluster],
            [],
            systems=[{"letter": "A", "on": "on", "pid": "1", "alive": True}],
        )
    )
    assert "Size @ price" in html
    assert "unknown" in html
    assert "Today with-fee P&L" in html or "today with-fee" in html.lower()
    assert "Inception with-fee P&L" in html or "NOT today" in html
    assert "0.8400" not in html


def test_three_lock_today_pnl_not_2_40_after_gibson_repair():
    """Imamura lock + Gibson repaired + Teichmann lock-ish → not the $2.40 KPI."""
    from copy import deepcopy

    def _leg(**kw):
        base = {
            "qty": "1",
            "fee": "0",
            "http": 200,
            "posted": True,
            "has_io": True,
            "sent_at": datetime(2026, 11, 3, 1, 20, tzinfo=ET),
        }
        base.update(kw)
        return base

    gibson_k = _leg(
        venue="kalshi",
        instrument="KXWTAMATCH-26NOV01GIBOLI-OLI",
        side="no",
        player="Oleksandra Oliynykova",
        cash="0.8200",
        fee="0.0104",
        order_id="gk",
    )
    gibson_p = _leg(
        venue="polymarket",
        instrument="aec-wta-talgib-oleoli-2026-11-01",
        side="yes",
        player="Oleksandra Oliynykova",
        cash="0.8400",
        order_id="gp",
    )
    ima_k = _leg(
        venue="kalshi",
        instrument="KXATPCHALLENGERMATCH-26NOV01IMALEO-LEO",
        side="no",
        player="Mitsuki Wei Kang Leong",
        cash="0.4500",
        fee="0.0174",
        order_id="ik",
    )
    ima_p = _leg(
        venue="polymarket",
        instrument="aec-imamura-leong",
        side="yes",
        player="",
        outcome_name="Mitsuki Wei Kang Leong",
        cash="0.4800",
        order_id="ip",
    )
    tei_k = _leg(
        venue="kalshi",
        instrument="KXWTAMATCH-26NOV03TEIGAR-GAR",
        side="yes",
        player="Joanna Garland",
        cash="0.6400",
        fee="0.0162",
        order_id="tk",
    )
    tei_p = _leg(
        venue="polymarket",
        instrument="aec-teichmann-garland",
        side="no",
        player="Joanna Garland",
        cash="0.3300",
        order_id="tp",
    )

    def _cluster(game, legs):
        return {
            "game": game,
            "sport": "tennis",
            "system_letter": "A",
            "system_name": "Lock gap",
            "intent": w.INTENT_FULL_LOCK,
            "complementary": w.complementary_legs(legs),
            "fill_legs": legs,
            "legs": legs,
            "n_fill_legs": 2,
            "notes": [],
            "watch": {},
            "start": datetime(2026, 11, 3, 1, 20, tzinfo=ET),
        }

    clusters = [
        _cluster("Gibson vs Oliynykova", [gibson_k, gibson_p]),
        _cluster("Imamura vs Leong", [ima_k, ima_p]),
        _cluster("Teichmann vs Garland", [tei_k, tei_p]),
    ]
    settlements = [
        {"ticker": gibson_k["instrument"], "result": "no", "venue": "kalshi"},
        {
            "ticker": gibson_p["instrument"],
            "result": "no",
            "settlementPx": "0.0000",
            "venue": "polymarket",
        },
        {"ticker": ima_k["instrument"], "result": "no", "venue": "kalshi"},
        {
            "ticker": ima_p["instrument"],
            "result": "yes",
            "settlementPx": "1.0000",
            "venue": "polymarket",
        },
        {"ticker": tei_k["instrument"], "result": "yes", "venue": "kalshi"},
        {
            "ticker": tei_p["instrument"],
            "result": "no",
            "settlementPx": "0.0000",
            "venue": "polymarket",
        },
    ]
    scored = [w.score_cluster(deepcopy(c), settlements) for c in clusters]
    w.apply_paul_history(scored, [])
    w.restrict_realized(scored, settlements)
    w.stamp_ticket_pnl(scored, settlements)

    total = sum((Decimal(str(c.get("realized") or 0)) for c in scored), Decimal("0"))
    assert abs(total - Decimal("2.40")) > Decimal("0.50")
    assert total < Decimal("1.00")
    gibson = next(c for c in scored if "gibson" in str(c.get("game") or "").lower())
    assert abs(Decimal(str(gibson.get("realized") or 0)) - Decimal("0.01")) <= Decimal("0.02")
    # Size @ price column present on flattened today rows.
    rows = d.flatten_trades(scored)
    assert rows
    assert all((r.get("size_at_touch") or "unknown") not in {"", "—"} for r in rows)


if __name__ == "__main__":
    test_complementary_uses_outcome_name_when_player_empty()
    test_empty_activities_gibson_yes_wire_repairs_to_0_16()
    test_empty_activities_non_gibson_yes_wire_0_84_stays_long()
    test_repair_gibson_forces_pair_plus_0_01_not_2_40_class()
    test_dashboard_a_today_row_shows_unknown_not_silent_omit()
    test_three_lock_today_pnl_not_2_40_after_gibson_repair()
    print("test_lock_gap_today_size_pnl_regression ok")
