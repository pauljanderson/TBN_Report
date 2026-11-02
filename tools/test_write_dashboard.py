"""Dashboard scoreboard: fill vs miss vs lost bet, SVG charts, one sort script.

No network. No secrets. Does not place or sell. Does not start Strategy B.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import write_dashboard as d

ET = ZoneInfo("America/New_York")


def _cluster(**kwargs):
    row = {
        "system_letter": "B",
        "system_name": "Tennis crossover",
        "game": "Hong vs Wu",
        "sport": "tennis",
        "league": "ATP",
        "side": "Hong",
        "legs": [],
        "fill_legs": [],
        "n_fill_legs": 0,
        "realized": Decimal("0"),
        "open_cost": Decimal("0"),
        "open_legs": 0,
        "venue_live": False,
        "postponed": False,
        "void": False,
        "start": datetime(2026, 10, 27, 8, 0, tzinfo=ET),
    }
    row.update(kwargs)
    return row


def _leg(**kwargs):
    row = {
        "venue": "polymarket",
        "instrument": "slug",
        "side": "yes",
        "player": "Hong",
        "cash": Decimal("0.18"),
        "fee": Decimal("0.01"),
        "qty": Decimal("1"),
        "http": 200,
        "http_line": "HTTP 200",
        "sent_at": datetime(2026, 10, 27, 8, 1, tzinfo=ET),
        "has_io": True,
        "posted": True,
    }
    row.update(kwargs)
    return row


def test_fill_vs_miss_vs_lost_not_mixed():
    filled = _cluster(
        n_fill_legs=1,
        fill_legs=[_leg()],
        legs=[_leg()],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("0.81"),
        wins=1,
    )
    miss = _cluster(
        game="Missed vs Ghost",
        system_letter="A",
        n_fill_legs=0,
        legs=[_leg(qty=Decimal("0"), cash=None, fee=None, http=201, http_line="HTTP 201 fill_count 0")],
        fill_legs=[],
    )
    lost = _cluster(
        game="Lost vs Bet",
        system_letter="C",
        n_fill_legs=1,
        fill_legs=[_leg(player="Troy")],
        legs=[_leg(player="Troy")],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("-0.44"),
        losses=1,
    )
    rows = d.flatten_trades([filled, miss, lost])
    by_game = {row["game"]: row for row in rows}
    assert by_game["Hong vs Wu"]["filled"] == "yes"
    assert "qty > 0" in by_game["Hong vs Wu"]["filled_label"]
    assert by_game["Hong vs Wu"]["failure"] == ""
    assert by_game["Missed vs Ghost"]["filled"] == "no"
    assert "missed send" in by_game["Missed vs Ghost"]["failure"]
    assert by_game["Missed vs Ghost"]["outcome"] == "missed send"
    assert "lost bet" in by_game["Lost vs Bet"]["failure"]
    assert by_game["Lost vs Bet"]["filled"] == "yes"


def test_html_has_svg_sortable_no_ask_plain():
    filled = _cluster(
        n_fill_legs=1,
        fill_legs=[_leg()],
        legs=[_leg()],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("0.20"),
        wins=1,
    )
    miss = _cluster(
        game="Ghost 201",
        system_letter="A",
        n_fill_legs=0,
        legs=[_leg(qty=Decimal("0"), http=201, http_line="HTTP 201", cash=None, fee=None)],
    )
    postponed = _cluster(
        game="Llanes vs Del Pino",
        system_letter="B",
        n_fill_legs=1,
        fill_legs=[_leg(player="Llanes")],
        legs=[_leg(player="Llanes")],
        postponed=True,
        venue_live=True,
        open_legs=1,
        open_cost=Decimal("0.18"),
        realized=Decimal("0"),
    )
    open_rows = [{
        "system": "B",
        "game": "Llanes vs Del Pino",
        "sport": "tennis",
        "players": "Llanes vs Del Pino",
        "bet_for": "Yes Llanes",
        "venue": "polymarket",
        "confirmed": "1",
        "exposure": "0.19",
        "postponed": "yes",
        "source": "job_status Positions overlay",
    }]
    systems = [
        {"letter": "A", "name": "Lock gap (cap 0.99)", "on": "on", "stake": "4", "max_open": "3", "open": "0", "pid": "1", "alive": True, "last": "ok"},
        {"letter": "B", "name": "Tennis crossover", "on": "on", "stake": "4", "max_open": "4", "open": "1", "pid": "2", "alive": True, "last": "ok"},
        {"letter": "C", "name": "College football favorite", "on": "on", "stake": "4", "max_open": "4", "open": "0", "pid": "3", "alive": True, "last": "ok"},
        {"letter": "D", "name": "T0 spreads (on except NFL)", "on": "on", "stake": "4", "max_open": "4", "open": "0", "pid": "4", "alive": True, "last": "ok"},
        {"letter": "E", "name": "Tennis T0 dog", "on": "on", "stake": "1", "max_open": "2", "open": "0", "pid": "5", "alive": True, "last": "ok"},
    ]
    payload = d.build_payload([filled, miss, postponed], open_rows, systems=systems)
    html = d.write_html(payload)
    assert "What you asked" not in html
    assert "In plain English" not in html
    assert "hard time understanding what trades were made" not in html
    assert "This is the scoreboard" not in html
    assert "D on except NFL" in html
    assert "lock.net_max" in html
    assert "postponed" in html.lower()
    assert 'class="sortable"' in html
    assert "sortable-th" in html
    assert "<svg" in html
    assert 'data-window-btn="today"' in html
    assert html.count("<script>") == 1 or (
        html.count("<script>") == 2 and "cacheBustUrl" in html
    )
    assert "SORTABLE_TABLE_SCRIPT" not in html
    assert html.count("function sortTable") == 1
    assert "Did not start a second B" in html
    assert "viewport" in html
    assert "Swipe sideways" in html
    assert "Previous" in html
    assert "Next" in html
    assert 'aria-label="Dashboard day"' in html
    payload["prev_href"] = "dashboard_20261028.html"
    payload["next_href"] = ""
    html_nav = d.write_html(payload)
    assert 'href="dashboard_20261028.html"' in html_nav
    assert "What you asked" not in html_nav


def test_one_fill_is_win_xor_loss_not_both():
    yas_t0 = _leg(
        player="Dayana Yastremska wins",
        cash=Decimal("0.46"),
        fee=Decimal("0.0174"),
        order_id="01a17bf2-bca0-76a2-8f0a-415c540b5ea6",
        sent_at=datetime(2026, 10, 27, 1, 59, 51, tzinfo=ET),
        ticket_status="win",
        ticket_pnl="0.5226",
        step="b-t0",
        venue="kalshi",
        instrument="KXWTAMATCH-26OCT26YASVOL-YAS",
    )
    vol_t0 = _leg(
        player="Katie Volynets wins",
        cash=Decimal("0.56"),
        fee=Decimal("0.0173"),
        order_id="01a17bf2-8208-73a7-8b40-276df04918be",
        sent_at=datetime(2026, 10, 27, 1, 59, 51, tzinfo=ET),
        ticket_status="lose",
        ticket_pnl="-0.5773",
        step="b-t0",
        venue="kalshi",
        instrument="KXWTAMATCH-26OCT26YASVOL-VOL",
    )
    cross = _leg(
        player="Dayana Yastremska wins",
        cash=Decimal("0.55"),
        fee=Decimal("0.0174"),
        order_id="01a17c08-f808-72d5-b9b9-210693c8a94f",
        sent_at=datetime(2026, 10, 27, 2, 24, 52, tzinfo=ET),
        ticket_status="win",
        ticket_pnl="0.4326",
        step="b-cross",
        venue="kalshi",
        instrument="KXWTAMATCH-26OCT26YASVOL-YAS",
    )
    t0 = _cluster(
        game="Yastremska vs Volynets",
        n_fill_legs=2,
        fill_legs=[yas_t0, vol_t0],
        legs=[yas_t0, vol_t0, cross],
        venue_paid=True,
        market_final=True,
        settled_legs=2,
        realized=Decimal("-0.0547"),
        losses=1,
        wins=1,
    )
    extra = _cluster(
        game="Yastremska vs Volynets",
        n_fill_legs=1,
        fill_legs=[cross],
        legs=[cross],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("0.5226"),
        wins=1,
    )
    rows = d.flatten_trades([t0, extra])
    assert len(rows) == 3
    by_oid = {row["order_id"]: row for row in rows}
    assert len(by_oid) == 3
    yas = by_oid["01a17bf2-bca0-76a2-8f0a-415c540b5ea6"]
    vol = by_oid["01a17bf2-8208-73a7-8b40-276df04918be"]
    xrow = by_oid["01a17c08-f808-72d5-b9b9-210693c8a94f"]
    assert yas["outcome"] == "settled win"
    assert yas["failure"] == ""
    assert vol["outcome"] == "settled loss"
    assert "lost bet" in vol["failure"]
    assert xrow["outcome"] == "settled win"
    assert xrow["failure"] == ""
    assert xrow["wire"] == "0.5500"
    outcomes = {(row["order_id"], row["outcome"]) for row in rows}
    assert ("01a17c08-f808-72d5-b9b9-210693c8a94f", "settled loss") not in outcomes
    assert yas["outcome"] != "settled loss"


def test_ticket_pnl_beats_cluster_unknown():
    leg = _leg(
        order_id="priced-1",
        ticket_status="win",
        ticket_pnl="0.5100",
    )
    cluster = _cluster(
        n_fill_legs=1,
        fill_legs=[leg],
        legs=[leg],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        status_unknown=True,
        realized=Decimal("0"),
    )
    row = d.trade_row(leg, cluster)
    assert row["outcome"] == "settled win"
    assert row["pnl"].startswith("+")
    html = d.write_html(d.build_payload([cluster], [], systems=[{"letter": "B", "on": "on", "pid": "2", "alive": True}]))
    assert "What you asked" not in html
    assert "In plain English" not in html


def test_poly_partial_is_fill_not_missed_send():
    leg = _leg(qty=Decimal("0.3"), cash=Decimal("0.85"), fee=Decimal("0"), http=200, player="Moreno")
    cluster = _cluster(
        game="Alejandro Moreno vs. Thomas Cardona Herrera",
        n_fill_legs=1,
        fill_legs=[leg],
        legs=[leg],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("0.045"),
        wins=1,
    )
    row = d.trade_row(leg, cluster)
    assert row["outcome"] != "missed send"
    assert "qty > 0" in row["filled_label"]
    assert row["filled"] == "yes"


def test_missed_send_is_not_won_or_lost():
    miss = _leg(qty=Decimal("0"), cash=None, fee=None, http=200, http_line="HTTP 200 confirm 0")
    cluster = _cluster(
        game="Ghost confirm 0",
        n_fill_legs=0,
        fill_legs=[],
        legs=[miss],
        venue_paid=True,
        market_final=True,
        realized=Decimal("0.30"),
        wins=1,
    )
    row = d.trade_row(miss, cluster)
    assert row["outcome"] == "missed send"
    assert row["outcome"] not in {"settled win", "settled loss"}
    assert "missed send" in row["failure"]


def test_a_off_one_leg_copy():
    systems = [{"letter": "A", "on": "off", "pid": "1"}]
    note = d.a_status_note(systems, latch_on=True)
    assert "A Lock gap is off" in note
    assert "B–E stay on" in note or "stay on" in note


def test_empty_poly_open_kept_in_open_table():
    open_rows = [{
        "system": "B",
        "game": "Namigata leftover",
        "players": "Namigata",
        "bet_for": "Yes Namigata",
        "venue": "polymarket",
        "confirmed": "0.32",
        "exposure": "0.18",
        "postponed": "no",
        "source": "job_status Positions overlay",
    }]
    html = d.write_html(d.build_payload([], open_rows, systems=[{"letter": "B", "on": "on", "pid": "9", "alive": True}]))
    assert "Namigata" in html
    assert "Positions overlay" in html
    assert ">Type<" in html
    assert "Who $1 pays" in html
    assert "What you asked" not in html


def test_open_counts_follow_overlay_not_stale_cluster_flags():
    filled = _cluster(
        n_fill_legs=1,
        fill_legs=[_leg()],
        legs=[_leg()],
        venue_paid=False,
        venue_live=True,
        open_legs=1,
        open_cost=Decimal("0.19"),
        game="Hong vs Wu",
    )
    open_rows = [{
        "system": "B",
        "game": "Hong vs Wu",
        "exposure": "0.19",
        "postponed": "no",
    }]
    payload = d.build_payload([filled], open_rows, systems=[{"letter": "B", "on": "on", "pid": "2", "alive": True}])
    assert payload["today"]["n_open_today_fills"] == 1
    assert payload["today"]["n_open_overlay"] == 1
    assert payload["inception"]["n_open_overlay"] == 1
    ghost_open_cluster = d.build_payload(
        [filled],
        [],
        systems=[{"letter": "B", "on": "on", "pid": "2", "alive": True}],
    )
    assert ghost_open_cluster["today"]["n_open_today_fills"] == 0
    assert ghost_open_cluster["inception"]["n_open_overlay"] == 0


def test_opposite_poly_t0_keeps_own_wire_and_stays_open():
    slug = "aec-itfwo-moemiy-arivar-2026-10-28"
    yes_leg = _leg(
        player="Moeka Miyata",
        side="yes",
        cash=Decimal("0.37"),
        fee=Decimal("0.02"),
        order_id="DC4BN1VG11N2",
        instrument=slug,
        step="b-t0",
    )
    no_leg = _leg(
        player="Arina Varaksina",
        side="no",
        cash=Decimal("0.36"),
        fee=Decimal("0.02"),
        order_id="DC4BN4J011MC",
        instrument=slug,
        step="b-t0",
    )
    cluster = _cluster(
        game="Moeka Miyata vs. Arina Varaksina",
        b_t0_both=True,
        complementary=True,
        venue_live=True,
        market_final=False,
        venue_paid=False,
        flatten_filled=False,
        settled_legs=0,
        n_fill_legs=2,
        fill_legs=[yes_leg, no_leg],
        legs=[yes_leg, no_leg],
        open_legs=2,
        open_cost=Decimal("0.77"),
    )
    rows = {row["order_id"]: row for row in d.flatten_trades([cluster])}
    assert rows["DC4BN1VG11N2"]["wire"] == "0.3700"
    assert rows["DC4BN4J011MC"]["wire"] == "0.3600"
    assert rows["DC4BN1VG11N2"]["after_fee"] == "0.3900"
    assert rows["DC4BN4J011MC"]["after_fee"] == "0.3800"
    assert rows["DC4BN1VG11N2"]["side"] == "Yes Moeka Miyata"
    assert rows["DC4BN4J011MC"]["side"] == "Yes Arina Varaksina"
    assert not rows["DC4BN4J011MC"]["side"].lower().startswith("no ")
    assert rows["DC4BN1VG11N2"]["outcome"] == "open"
    assert rows["DC4BN4J011MC"]["outcome"] == "open"
    assert "settled" not in rows["DC4BN1VG11N2"]["outcome"]


def test_e_poly_short_yes_player_and_leftover_type():
    romano = _leg(
        player="Filippo Romano",
        side="no",
        io_intent="ORDER_INTENT_BUY_SHORT",
        outcome_name="Clement Tabur",
        instrument="aec-tabur-romano",
        step="e-t0",
        order_id="DCEA1H9G11N6",
        cash=Decimal("0.29"),
    )
    e_cluster = _cluster(
        system_letter="E",
        system_name="Tennis T0 dog",
        game="Clement Tabur vs. Filippo Romano",
        sport="tennis",
        kind="tennis_t0_dog",
        n_fill_legs=1,
        fill_legs=[romano],
        legs=[romano],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("0.70"),
        wins=1,
    )
    humbert = _leg(
        player="Ugo Humbert",
        side="no",
        io_intent="ORDER_INTENT_BUY_SHORT",
        outcome_name="Novak Djokovic",
        instrument="aec-djokovic-humbert",
        step="e-t0",
        order_id="DCF5J93G11MM",
        cash=Decimal("0.30"),
        fee=Decimal("0.01"),
    )
    djok = _leg(
        player="Ugo Humbert",
        side="yes",
        io_intent="ORDER_INTENT_BUY_LONG",
        outcome_name="Novak Djokovic",
        instrument="aec-djokovic-humbert",
        step="watch",
        order_id="DCFWP54G11TB",
        cash=Decimal("0.55"),
        fee=Decimal("0.02"),
    )
    leftover_cluster = _cluster(
        system_letter="E",
        system_name="Tennis T0 dog",
        game="Novak Djokovic vs. Ugo Humbert",
        sport="tennis",
        kind="tennis_t0_dog",
        n_fill_legs=2,
        fill_legs=[humbert, djok],
        legs=[humbert, djok],
        venue_paid=True,
        market_final=True,
        settled_legs=2,
        realized=Decimal("0.12"),
    )
    sele = _leg(
        player="Oksana Selekhmeteva",
        side="no",
        io_intent="ORDER_INTENT_BUY_SHORT",
        instrument="aec-yaneva-sele",
        step="e-t0",
        order_id="DCFK7M0G11MM",
        cash=Decimal("0.40"),
    )
    sele_cluster = _cluster(
        system_letter="E",
        kind="tennis_t0_dog",
        game="Elizara Yaneva vs. Oksana Selekhmeteva",
        sport="tennis",
        n_fill_legs=1,
        fill_legs=[sele],
        legs=[sele],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("-0.42"),
        losses=1,
    )
    musetti = _leg(
        venue="kalshi",
        player="Lorenzo Musetti",
        side="no",
        instrument="KXATPMATCH-26OCT28MUSTIA-MUS",
        step="watch",
        order_id="01a182f3-52f8-72fc-aac8-f260aa203891",
        cash=Decimal("0.51"),
    )
    musetti_cluster = _cluster(
        system_letter="E",
        kind="tennis_t0_dog",
        game="Lorenzo Musetti vs. Frances Tiafoe",
        sport="tennis",
        n_fill_legs=1,
        fill_legs=[musetti],
        legs=[musetti],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("-0.53"),
        losses=1,
    )
    rows = {row["order_id"]: row for row in d.flatten_trades([e_cluster, leftover_cluster, sele_cluster, musetti_cluster])}
    assert rows["DCEA1H9G11N6"]["side"] == "Yes Filippo Romano"
    assert rows["DCF5J93G11MM"]["side"] == "Yes Ugo Humbert"
    assert rows["DCFK7M0G11MM"]["side"] == "Yes Oksana Selekhmeteva"
    assert rows["DCFWP54G11TB"]["side"] == "Yes Novak Djokovic"
    assert rows["01a182f3-52f8-72fc-aac8-f260aa203891"]["side"] == "No Lorenzo Musetti"
    assert rows["DCFWP54G11TB"]["order_type"] == "leftover / hedge"
    assert rows["DCFWP54G11TB"]["system_name"] == "A leftover"
    assert "E Tennis T0 dog" not in rows["DCFWP54G11TB"]["system_name"]
    assert "E Tennis T0 dog" not in rows["DCFWP54G11TB"]["order_type"]
    assert rows["01a182f3-52f8-72fc-aac8-f260aa203891"]["order_type"] == "leftover / hedge"
    assert rows["01a182f3-52f8-72fc-aac8-f260aa203891"]["system_name"] == "A leftover"
    assert rows["DCEA1H9G11N6"]["order_type"] != "leftover / hedge"
    html = d.write_html(d.build_payload(
        [e_cluster, leftover_cluster, sele_cluster, musetti_cluster],
        [],
        systems=[{"letter": "E", "on": "on", "pid": "5", "alive": True}],
    ))
    assert "What you asked" not in html
    assert "In plain English" not in html
    assert "Yes Filippo Romano" in html
    assert "Yes Ugo Humbert" in html
    assert "Yes Oksana Selekhmeteva" in html
    assert "leftover / hedge" in html
    assert "A leftover" in html
    assert "Leftover-watch" in html


def test_stats_for_roi_and_table_headers():
    filled = _cluster(
        n_fill_legs=1,
        fill_legs=[_leg(cash=Decimal("0.50"), fee=Decimal("0.01"))],
        legs=[_leg(cash=Decimal("0.50"), fee=Decimal("0.01"))],
        venue_paid=True,
        market_final=True,
        settled_legs=1,
        realized=Decimal("0.49"),
        wins=1,
    )
    rows = d.flatten_trades([filled])
    stats = d.stats_for(rows, [filled], [])
    assert stats["invested"] == Decimal("0.51")
    assert stats["roi"] == Decimal("0.49") / Decimal("0.51") * Decimal(100)
    assert stats["by"]["B"]["invested"] == Decimal("0.51")
    assert stats["by"]["B"]["roi"] == stats["roi"]
    table = d.by_system_today_table(stats)
    assert "ROI %" in table
    assert "+96.1%" in table
    assert table.index("With-fee P&amp;L") < table.index("ROI %")
    kpi = d.kpi_strip(stats)
    assert ">ROI<" in kpi
    assert "+96.1%" in kpi
    revived = d._revive_stats({
        "pnl": "0.49",
        "invested": "0.51",
        "by": {"B": {"sent": 1, "filled": 1, "missed": 0, "open": 0, "settled": 1, "pnl": "0.49", "invested": "0.51"}},
        "pnl_by": {"B": "0.49"},
        "invested_by": {"B": "0.51"},
    })
    assert revived["invested"] == Decimal("0.51")
    assert revived["roi"] == Decimal("0.49") / Decimal("0.51") * Decimal(100)
    assert revived["by"]["B"]["roi"] == revived["roi"]
    empty = d.stats_for([], [], [])
    assert empty["invested"] == Decimal("0")
    assert empty["roi"] is None
    assert d.by_system_today_table(empty).count("—") >= 1


def main() -> None:
    test_fill_vs_miss_vs_lost_not_mixed()
    test_html_has_svg_sortable_no_ask_plain()
    test_one_fill_is_win_xor_loss_not_both()
    test_ticket_pnl_beats_cluster_unknown()
    test_poly_partial_is_fill_not_missed_send()
    test_missed_send_is_not_won_or_lost()
    test_a_off_one_leg_copy()
    test_empty_poly_open_kept_in_open_table()
    test_open_counts_follow_overlay_not_stale_cluster_flags()
    test_opposite_poly_t0_keeps_own_wire_and_stays_open()
    test_e_poly_short_yes_player_and_leftover_type()
    test_stats_for_roi_and_table_headers()
    html = d.write_html(d.build_payload([], [], systems=[{"letter": "B", "on": "on", "pid": "2", "alive": True}]))
    assert ">Type<" in html
    print("test_write_dashboard ok")


if __name__ == "__main__":
    main()
