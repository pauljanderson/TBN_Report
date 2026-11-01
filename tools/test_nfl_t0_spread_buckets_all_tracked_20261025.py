"""Synthetic tests for all-tracked NFL T0 spreads.

Does not place orders. Does not start live_strategy_b.py. Does not print secrets.
Does not write sports_queue. Does not change live D. Does not read the fill ledger.
"""
from __future__ import annotations

from pathlib import Path

from nfl_t0_spread_buckets_all_tracked_20261025 import (
    PAGE,
    PENDING_HEADERS,
    STATUS_RANK,
    SUNDAY_GAME_HEADERS,
    SUNDAY_WINDOW_HEADERS,
    T0_PRICE_HEADERS,
    TICKET_HEADERS,
    TODAY_ET,
    YES_AB_GLOSSARY,
    book_status,
    catalog_has_spread,
    catalog_title,
    d_missed_1pm,
    game_status,
    inventory_games,
    is_today_slate,
    kickoff_window_label,
    overlay_catalog_starts,
    path_is_no_post,
    play_state,
    short_team_name,
    sunday_game_rows,
    sunday_games,
    sunday_window_rows,
    t0_price_row,
    yes_no_view,
)
from nfl_t0_spread_buckets_20261025 import pick_one_per_game, pick_primary_line


ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tools" / "nfl_t0_spread_buckets_all_tracked_20261025.py"


def test_yes_a_b_glossary_is_not_yes_plus_no():
    assert "not Yes plus No of one contract" in YES_AB_GLOSSARY
    assert "sorted by team name" in YES_AB_GLOSSARY
    assert "middle" in YES_AB_GLOSSARY.lower()
    text = GEN.read_text(encoding="utf-8")
    assert "Glossary — T0 Yes A / T0 Yes B" in text
    assert "Indiana/Michigan-style same-line" in text
    assert "Cover Yes team 1" in text
    assert "T0 fav Yes" in text
    assert "T0 fav No" in text
    assert "A/B are two teams" in text
    assert "Adding 0.41 + 0.50 = 0.91 is not a 0.91" in text
    assert "spread_two_yes_not_a_lock" in text
    labels = [h[0] for h in T0_PRICE_HEADERS]
    assert "T0 Yes A" not in labels
    assert "T0 Yes B" not in labels
    assert "Cover Yes team 1" in labels
    assert "Cover Yes team 2" in labels
    assert "Team 1" in labels
    assert "Team 2" in labels
    assert "T0 fav Yes" in labels
    assert "T0 fav No" in labels
    assert "Fav Yes+No (same contract)" in labels
    for headers in (T0_PRICE_HEADERS, TICKET_HEADERS, PENDING_HEADERS):
        names = [h[0] for h in headers]
        assert "T0 Yes A" not in names
        assert "T0 Yes B" not in names


def test_yes_no_view_arizona_la_is_not_a_lock():
    book = {
        "fav": "b",
        "fav_name": "Los Angeles",
        "side_a": "Arizona",
        "side_b": "Los Angeles",
        "number": "1.5",
        "t0_a": 0.41,
        "t0_b": 0.50,
        "t0_fav": 0.50,
        "game": "Arizona vs Los Angeles",
        "venue": "Kalshi",
        "two_sided": True,
        "settled": True,
        "fav_won": True,
        "t0_source": "test",
    }
    view = yes_no_view(book)
    assert view["market"] == "Los Angeles wins by >1.5"
    assert view["t0_yes"] == 0.50
    assert abs(view["t0_no"] - 0.50) < 1e-9
    assert view["no_src"] == "1 − Yes"
    assert abs(view["yes_no"] - 1.00) < 1e-9
    assert view["other_name"] == "Arizona"
    assert view["other_yes"] == 0.41
    assert view["team1"] == "Arizona"
    assert view["team2"] == "Los Angeles"
    assert view["team1_yes"] == 0.41
    assert view["team2_yes"] == 0.50
    two_team_yes = view["team1_yes"] + view["team2_yes"]
    assert abs(two_team_yes - 0.91) < 1e-9
    assert abs(view["yes_no"] - two_team_yes) > 0.05
    live = dict(book, t0_no=0.52)
    live_view = yes_no_view(live)
    assert live_view["no_src"] == "live No ask"
    assert abs(live_view["t0_no"] - 0.52) < 1e-9
    row = t0_price_row(book)
    joined = " ".join(row)
    assert "Los Angeles wins by &gt;1.5" in joined
    assert "Arizona" in joined
    assert "0.410" in joined
    assert "0.500" in joined
    assert short_team_name("Arizona wins by more than 1.5 points") == "Arizona"
    assert short_team_name("Los Angeles R wins by over 1.5 points") == "Los Angeles R"


def test_new_page_is_not_the_old_four_row_file():
    assert PAGE.name == "nfl_t0_spread_buckets_all_tracked_20261025.html"
    text = GEN.read_text(encoding="utf-8")
    assert "orders.jsonl" in text
    assert "Does not read orders.jsonl" in text or "Did not read" in text
    assert "open(orders" not in text
    assert "ORDERS" not in text
    assert "system=spread_t0" in text
    assert "FILLED" in text
    assert "not read orders.jsonl / FILLED / system=spread_t0" in text.lower() or (
        "Does not read orders.jsonl / FILLED / system=spread_t0" in text
    )


def test_catalog_spread_sibling():
    assert catalog_has_spread({
        "title_kalshi": "Cincinnati vs Baltimore",
        "kalshi": {"game": "KXNFLGAME-X", "spread": "KXNFLSPREAD-X"},
        "gemini": {"spread": "NFL-S"},
    })
    assert not catalog_has_spread({
        "title_kalshi": "Cincinnati vs Baltimore",
        "kalshi": {"game": "KXNFLGAME-X"},
        "gemini": {"moneyline": "NFL-M"},
    })
    assert catalog_title({"codes": ["CIN", "BAL"]}) == "CIN vs BAL"


def test_game_status_does_not_drop_clock_hid_games():
    hid = {
        "sport": "pro football",
        "kind": "spread",
        "game": "Dallas vs Green Bay",
        "game_n": "dallas vs green bay",
        "skip": "clock_hides_match",
        "two_sided": True,
        "t0_a": None,
        "t0_b": None,
        "t0_ts": None,
        "listed_raw": "2026-10-19T20:20:00-04:00",
    }
    got = game_status([hid])
    assert got["in_pnl"] is False
    assert got["status"] == "clock hid match"
    assert got["n_books"] == 1


def test_game_status_prefers_settled_unique_fav():
    hid = {
        "sport": "pro football",
        "kind": "spread",
        "game": "Baltimore vs Cleveland",
        "game_n": "baltimore vs cleveland",
        "skip": "clock_hides_match",
        "two_sided": True,
        "number": "14.5",
    }
    good = {
        "sport": "pro football",
        "kind": "spread",
        "game": "Baltimore vs Cleveland",
        "game_n": "baltimore vs cleveland",
        "skip": "",
        "two_sided": True,
        "t0_a": 0.73,
        "t0_b": 0.29,
        "t0_ts": 1,
        "t0_fav": 0.73,
        "fav": "a",
        "settled": True,
        "void": False,
        "venue": "Gemini",
        "number": "2.5",
        "fav_path": {"empty": False, "path_status": "complete", "n_post": 12},
    }
    got = game_status([hid, good])
    assert got["in_pnl"] is True
    assert got["status"] == "settled unique-fav T0"
    assert STATUS_RANK[got["status"]] == 0


def test_one_sided_and_no_clock_and_unsettled():
    one = {
        "game": "A vs B",
        "game_n": "a vs b",
        "skip": "",
        "two_sided": False,
        "t0_a": 0.62,
        "t0_b": None,
        "t0_ts": 1,
        "t0_fav": 0.62,
        "fav": "a",
        "settled": True,
        "venue": "Kalshi",
    }
    assert book_status(one) == "one-sided"
    noclock = {
        "game": "C vs D",
        "game_n": "c vs d",
        "skip": "no_trusted_clock",
        "two_sided": True,
        "t0_a": None,
        "t0_b": None,
        "t0_ts": None,
    }
    assert book_status(noclock) == "no clock"
    pending = {
        "game": "E vs F",
        "game_n": "e vs f",
        "skip": "",
        "two_sided": True,
        "t0_a": 0.58,
        "t0_b": 0.44,
        "t0_ts": 1,
        "t0_fav": 0.58,
        "fav": "a",
        "settled": False,
        "void": False,
        "venue": "Kalshi",
        "fav_path": {"empty": False, "path_status": "watched", "n_post": 3},
    }
    assert book_status(pending) == "unsettled"


def test_no_post_t0_is_a_skip_when_not_settled():
    book = {
        "game": "G vs H",
        "game_n": "g vs h",
        "skip": "",
        "two_sided": True,
        "t0_a": 0.61,
        "t0_b": 0.41,
        "t0_ts": 1,
        "t0_fav": 0.61,
        "fav": "a",
        "settled": False,
        "void": False,
        "venue": "Kalshi",
        "fav_path": {"empty": True, "path_status": "no_post_t0_path", "n_post": 0},
    }
    assert path_is_no_post(book)
    assert book_status(book) == "no post-T0"


def test_catalog_only_game_is_not_dropped():
    cat = {
        "game": "Cincinnati vs Baltimore",
        "game_n": "cincinnati vs baltimore",
        "listed_start": "2026-10-25T13:00:00-04:00",
        "date": "2026-10-25",
    }
    tape = [{
        "sport": "pro football",
        "kind": "spread",
        "game": "Baltimore vs Cleveland",
        "game_n": "baltimore vs cleveland",
        "skip": "",
        "two_sided": True,
        "t0_a": 0.73,
        "t0_b": 0.29,
        "t0_ts": 1,
        "t0_fav": 0.73,
        "fav": "a",
        "settled": True,
        "void": False,
        "venue": "Gemini",
        "fav_path": {"empty": False, "path_status": "complete"},
    }]
    rows = inventory_games(tape, [cat])
    names = {r["game_n"]: r["status"] for r in rows}
    assert names["baltimore vs cleveland"] == "settled unique-fav T0"
    assert names["cincinnati vs baltimore"] == "catalog only — no ticks"
    assert len(rows) == 2


def test_overlay_catalog_fills_empty_listed_only():
    books = [
        {"game_n": "cincinnati vs baltimore", "listed_raw": ""},
        {"game_n": "baltimore vs cleveland", "listed_raw": "already"},
    ]
    catalog = [
        {"game_n": "cincinnati vs baltimore", "listed_start": "2026-10-25T13:00:00-04:00"},
        {"game_n": "baltimore vs cleveland", "listed_start": "should-not-win"},
    ]
    n = overlay_catalog_starts(books, catalog)
    assert n == 1
    assert books[0]["listed_raw"] == "2026-10-25T13:00:00-04:00"
    assert books[1]["listed_raw"] == "already"


def test_sunday_first_set_helpers_and_asked_refresh():
    assert TODAY_ET == "2026-10-25"
    assert is_today_slate("2026-10-25T13:00:00-04:00")
    assert is_today_slate("2026-10-25T16:25:00-04:00")
    assert not is_today_slate("2026-10-26T20:15:00-04:00")
    assert not is_today_slate("2026-10-18")
    assert kickoff_window_label("2026-10-25T13:00:00-04:00") == "1pm ET first window"
    assert kickoff_window_label("2026-10-25T16:05:00-04:00") == "4:05pm ET"
    assert kickoff_window_label("2026-10-25T16:25:00-04:00") == "4:25pm ET"
    assert kickoff_window_label("2026-10-25T20:20:00-04:00") == "8:20pm ET"
    assert d_missed_1pm("2026-10-25T13:00:00-04:00")
    assert not d_missed_1pm("2026-10-25T16:05:00-04:00")
    text = GEN.read_text(encoding="utf-8")
    assert "Sunday Oct 25 first set" in text
    assert "1pm ET" in text
    assert "REST hydration" in text
    assert "Did not turn D NFL on" in text
    assert "Type A" in text
    assert "win% by T0" in text or "win% by T0 bucket" in text
    assert "how did we go through an entire day" in text
    assert "51-69 at T0" in text
    assert "26OCT21" in text
    assert "Cover Yes team 1" in [h[0] for h in SUNDAY_GAME_HEADERS]
    assert "Kickoff window" in [h[0] for h in SUNDAY_WINDOW_HEADERS]
    assert "Settled cover" in [h[0] for h in SUNDAY_GAME_HEADERS]
    assert "In unique-fav win%" in [h[0] for h in SUNDAY_GAME_HEADERS]
    games = [
        {
            "game": "Cincinnati vs Baltimore",
            "game_n": "cincinnati vs baltimore",
            "listed": "2026-10-25T13:00:00-04:00",
            "status": "unsettled",
            "n_books": 42,
            "n_two_sided": 39,
            "n_trusted": 11,
            "in_pnl": False,
            "catalog_only": False,
        },
        {
            "game": "Kansas City vs Seattle",
            "game_n": "kansas city vs seattle",
            "listed": "2026-10-25T20:20:00-04:00",
            "status": "unsettled",
            "n_books": 36,
            "n_two_sided": 36,
            "n_trusted": 12,
            "in_pnl": False,
            "catalog_only": False,
        },
        {
            "game": "Dallas vs Philadelphia",
            "game_n": "dallas vs philadelphia",
            "listed": "2026-10-26T20:15:00-04:00",
            "status": "unsettled",
            "n_books": 42,
            "n_two_sided": 39,
            "n_trusted": 11,
            "in_pnl": False,
            "catalog_only": False,
        },
        {
            "game": "Ghost vs Catalog",
            "game_n": "ghost vs catalog",
            "listed": "2026-10-25T13:00:00-04:00",
            "status": "catalog only — no ticks",
            "n_books": 0,
            "n_two_sided": 0,
            "n_trusted": 0,
            "in_pnl": False,
            "catalog_only": True,
        },
    ]
    sun = sunday_games(games)
    assert len(sun) == 3
    assert all(g["game"] != "Dallas vs Philadelphia" for g in sun)
    windows = sunday_window_rows(games)
    labels = [r[0] for r in windows]
    assert "1pm ET first window" in labels
    assert "8:20pm ET" in labels
    one_pm = next(r for r in windows if r[0] == "1pm ET first window")
    assert one_pm[1] == "2"
    assert one_pm[2] == "1"
    assert one_pm[3] == "1"
    rows = sunday_game_rows(games, [])
    joined = " ".join(" ".join(r) for r in rows)
    assert "Cincinnati vs Baltimore" in joined
    assert "Kansas City vs Seattle" in joined
    assert "Dallas vs Philadelphia" not in joined
    assert "yes — D pid froze in REST hydration" in joined
    assert play_state(
        "2026-10-25T20:20:00-04:00",
        settled=False,
        catalog_only=False,
        now=__import__("datetime").datetime(2026, 10, 25, 18, 19, tzinfo=__import__("zoneinfo").ZoneInfo("America/New_York")),
    ) == "not kicked off yet"


def test_both_grains_still_pick_d_line_and_all_lines():
    books = [
        {"game_n": "dalphi", "number": "7.5", "t0_fav": 0.72, "venue": "Kalshi"},
        {"game_n": "dalphi", "number": "3.5", "t0_fav": 0.58, "venue": "Kalshi"},
        {"game_n": "dalphi", "number": "3.5", "t0_fav": 0.56, "venue": "Gemini"},
        {"game_n": "nygwas", "number": "2.5", "t0_fav": 0.91, "venue": "Kalshi"},
    ]
    lines = pick_primary_line(books)
    assert len(lines) == 3
    assert any(r["venue"] == "Gemini" and r["number"] == "3.5" for r in lines)
    matches = pick_one_per_game(lines)
    by_game = {row["game_n"]: row for row in matches}
    assert by_game["dalphi"]["number"] == "3.5"
    assert by_game["dalphi"]["venue"] == "Gemini"
    assert len(matches) == 2


def test_middle_is_a_loss_not_open():
    from nfl_t0_type_a_collect import (
        bucket_winpct,
        overlay_cover_settlement,
        winpct_row,
        ALL_ID,
    )
    book = {
        "game": "Cincinnati vs Baltimore",
        "game_n": "cincinnati vs baltimore",
        "number": "3.5",
        "side_a": "Cincinnati wins by more than 3.5 points",
        "side_b": "Baltimore wins by more than 3.5 points",
        "fav": "a",
        "t0_fav": 0.62,
        "t0_a": 0.62,
        "t0_b": 0.41,
        "off_a": "pending",
        "off_b": "pending",
        "settled": False,
        "venue": "Kalshi",
        "listed_raw": "2026-10-25T13:00:00-04:00",
        "yes_a": [],
        "yes_b": [],
    }
    cover_index = {
        ("cincinnati vs baltimore", "3.5", "cincinnati"): {
            "result": "no", "source": "test", "ticker": "X-CIN3",
        },
        ("cincinnati vs baltimore", "3.5", "baltimore"): {
            "result": "no", "source": "test", "ticker": "X-BAL3",
        },
    }
    overlay_cover_settlement(book, cover_index)
    assert book["middle"] is True
    assert book["settled"] is True
    assert book["fav_won"] is False
    recs = bucket_winpct([book], prefix="test")
    assert recs["60-69"]["n"] == 1
    assert recs["60-69"]["n_win"] == 0
    assert recs[ALL_ID]["win_pct"] == 0.0
    row = winpct_row(recs["60-69"], display="60-69")
    assert row[0] == "60-69"
    assert row[1] == "1"
    assert row[2] == "0"


def test_under50_lands_in_lt50_bucket():
    from nfl_t0_type_a_collect import bucket_winpct
    dog = {
        "fav": "a",
        "t0_fav": 0.41,
        "t0_a": 0.41,
        "t0_b": 0.38,
        "fav_won": False,
        "cover_known": True,
        "settled": True,
        "venue": "Kalshi",
        "number": "7.5",
        "game": "A vs B",
        "game_n": "a vs b",
    }
    recs = bucket_winpct([dog], prefix="dog")
    assert recs["<50"]["n"] == 1
    assert recs["50-59"]["n"] == 0


def test_occ_map_listed_beats_expiration():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from nfl_t0_type_a_collect import occ_map_prefer_listed
    et = ZoneInfo("America/New_York")
    catalog = [{
        "game_n": "cincinnati vs baltimore",
        "game": "Cincinnati vs Baltimore",
        "listed_start": "2026-10-25T13:00:00-04:00",
    }]
    settlements = [{
        "game_n": "cincinnati vs baltimore",
        "game": "Cincinnati vs Baltimore",
        "occurrence": "2026-10-25T20:00:00Z",
    }]
    got = occ_map_prefer_listed(catalog, settlements)
    assert got["cincinnati vs baltimore"] == datetime(2026, 10, 25, 13, 0, tzinfo=et)


def test_51_69_drops_exact_50_and_excludes_open_and_novig_from_dollars():
    from nfl_t0_type_a_collect import (
        in_51_69,
        in_old_50_59,
        in_old_60_69,
        in_old_50_69_neighborhood,
        pick_fee_primary_line,
        score_t0_yes_band,
        t0_yes_trade,
        BAND_51_69_ID,
    )
    assert in_51_69(0.51) and in_51_69(0.69)
    assert not in_51_69(0.50)
    assert not in_51_69(0.505)
    assert not in_51_69(0.70)
    assert not in_51_69(0.695)
    assert in_old_50_59(0.51) and in_old_50_59(0.505) and not in_old_50_59(0.50)
    assert in_old_60_69(0.60) and in_old_60_69(0.695) and not in_old_60_69(0.70)
    assert not in_old_60_69(0.69) or in_51_69(0.69)

    def book(**kw):
        row = {
            "sport": "pro football",
            "kind": "spread",
            "game": "Cincinnati vs Baltimore",
            "game_n": "cincinnati vs baltimore",
            "number": "3.5",
            "side_a": "Cincinnati",
            "side_b": "Baltimore",
            "fav": "a",
            "fav_name": "Cincinnati",
            "t0_a": 0.55,
            "t0_b": 0.47,
            "t0_fav": 0.55,
            "cover_known": True,
            "settled": True,
            "fav_won": True,
            "two_sided": True,
            "venue": "Kalshi",
            "listed_raw": "2026-10-25T13:00:00-04:00",
            "t0_ts": 1761400800,
        }
        row.update(kw)
        return row

    win = book()
    loss = book(
        game="Atlanta vs Miami",
        game_n="atlanta vs miami",
        number="2.5",
        t0_fav=0.62,
        t0_a=0.62,
        fav_won=False,
        listed_raw="2026-10-18T13:00:00-04:00",
        t0_ts=1760796000,
    )
    fifty = book(
        game="Fifty vs Fifty",
        game_n="fifty vs fifty",
        number="1.5",
        t0_fav=0.50,
        t0_a=0.50,
        t0_b=0.50,
        fav_won=True,
    )
    open_kc = book(
        game="Kansas City vs Seattle",
        game_n="kansas city vs seattle",
        number="8.5",
        t0_fav=0.58,
        t0_a=0.58,
        settled=False,
        cover_known=False,
        fav_won=None,
        listed_raw="2026-10-25T20:20:00-04:00",
    )
    novig = book(
        game="Novig vs Only",
        game_n="novig vs only",
        number="6.5",
        t0_fav=0.57,
        t0_a=0.57,
        venue="Novig",
        fav_won=True,
    )
    rec = score_t0_yes_band(
        [win, loss, fifty, open_kc, novig],
        label=BAND_51_69_ID,
    )
    assert rec["n"] == 3  # win, loss, novig — fifty out, open out
    assert rec["n_win"] == 2
    assert rec["n_open"] == 1
    assert rec["n_fee"] == 2  # Kalshi win + loss; Novig omitted from $
    assert rec["n_no_fee"] == 1
    assert "Novig" in rec["no_fee_venues"]
    assert any("Seattle" in g or "seattle" in g.lower() for g in rec["open_games"])
    assert rec["pnl_sum"] is not None
    # Win 0.55 Kalshi + loss 0.62 Kalshi. Novig not in dollars.
    trade_win = t0_yes_trade(win, "t")
    trade_loss = t0_yes_trade(loss, "t")
    assert trade_win is not None and trade_loss is not None
    expected = trade_win["pnl_d"] + trade_loss["pnl_d"]
    assert abs(rec["pnl_sum"] - expected) < 1e-9
    assert t0_yes_trade(novig, "t") is None
    hood = pick_fee_primary_line([win, loss, fifty, open_kc, novig])
    s50 = score_t0_yes_band(hood, label="50", pred=in_old_50_59, pick=False)
    s60 = score_t0_yes_band(hood, label="60", pred=in_old_60_69, pick=False)
    comb = score_t0_yes_band(
        hood, label="comb", pred=in_old_50_69_neighborhood, pick=False
    )
    assert s50["n"] + s60["n"] == comb["n"]
    text = GEN.read_text(encoding="utf-8")
    assert "51-69 at T0" in text
    assert "ASKED_51_69" in text
    assert "Did not bump stake" in text
    assert "BAND_51_69_HEADERS" in text


def test_every_decile_half_open_and_20_39_adds():
    from nfl_t0_type_a_collect import (
        DECILE_20_39_ID,
        band_primary_row,
        build_every_decile_payload,
        decile_hero_rows,
        decile_verdict,
        explode_cover_yes_sides,
        in_20_29,
        in_20_39,
        in_30_39,
        in_90_100,
        in_half_open,
        unique_fav_decile_sides,
    )
    assert in_half_open(0.20, 0.20, 0.30) and in_20_29(0.20)
    assert in_20_29(0.299) and not in_20_29(0.30)
    assert in_30_39(0.30) and in_30_39(0.399) and not in_30_39(0.40)
    assert in_20_39(0.20) and in_20_39(0.399) and not in_20_39(0.40)
    assert not in_20_39(0.19)
    assert in_90_100(0.90) and in_90_100(1.00) and not in_90_100(0.899)
    assert in_half_open(0.00, 0.00, 0.10) and not in_half_open(0.10, 0.00, 0.10)
    assert in_half_open(0.50, 0.50, 0.60)

    def book(**kw):
        row = {
            "sport": "pro football",
            "kind": "spread",
            "game": "Denver vs Arizona",
            "game_n": "denver vs arizona",
            "number": "3.5",
            "side_a": "Arizona",
            "side_b": "Denver",
            "fav": "b",
            "fav_name": "Denver",
            "t0_a": 0.31,
            "t0_b": 0.64,
            "t0_fav": 0.64,
            "off_a": "loss",
            "off_b": "win",
            "cover_known": True,
            "settled": True,
            "fav_won": True,
            "two_sided": True,
            "venue": "Kalshi",
            "listed_raw": "2026-10-25T16:05:00-04:00",
            "t0_ts": 1761414300,
        }
        row.update(kw)
        return row

    den_ari = book()
    cheap_win = book(
        game="Buffalo vs Las Vegas",
        game_n="buffalo vs las vegas",
        number="7.5",
        side_a="Las Vegas",
        side_b="Buffalo",
        t0_a=0.22,
        t0_b=0.71,
        t0_fav=0.71,
        off_a="win",
        off_b="loss",
        fav="b",
        fav_name="Buffalo",
        fav_won=False,
        listed_raw="2026-10-18T13:00:00-04:00",
    )
    open_kc = book(
        game="Kansas City vs Seattle",
        game_n="kansas city vs seattle",
        number="2.5",
        t0_a=0.35,
        t0_b=0.57,
        t0_fav=0.57,
        off_a=None,
        off_b=None,
        settled=False,
        cover_known=False,
        fav_won=None,
        listed_raw="2026-10-25T20:20:00-04:00",
    )
    novig_dog = book(
        game="Novig vs Only",
        game_n="novig vs only",
        number="6.5",
        t0_a=0.25,
        t0_b=0.68,
        t0_fav=0.68,
        off_a="win",
        off_b="loss",
        venue="Novig",
        fav_won=False,
    )
    sides = explode_cover_yes_sides([den_ari])
    assert len(sides) == 2
    by_letter = {s["_side_letter"]: s for s in sides}
    assert abs(by_letter["a"]["t0_fav"] - 0.31) < 1e-12
    assert by_letter["a"]["fav_won"] is False
    assert abs(by_letter["b"]["t0_fav"] - 0.64) < 1e-12
    assert by_letter["b"]["fav_won"] is True
    uf = unique_fav_decile_sides(sides)
    assert len(uf) == 1
    assert uf[0]["t0_fav"] > 0.50
    payload = build_every_decile_payload(
        [den_ari, cheap_win, open_kc, novig_dog], sunday_date="2026-10-25"
    )
    assert payload["adds_20_39"] is True
    d20 = payload["all_days"]["20-29"]
    d30 = payload["all_days"]["30-39"]
    comb = payload["all_days"]["20-39"]
    assert d20["n"] + d30["n"] == comb["n"]
    # Arizona 0.31 loss, LV 0.22 win, Novig 0.25 win, KC 0.35 open out
    assert d20["n"] == 2  # LV Kalshi 0.22 + Novig 0.25
    assert d30["n"] == 1  # Arizona 0.31
    assert comb["n"] == 3
    assert comb["n_open"] >= 1
    assert any("Seattle" in g or "seattle" in g.lower() for g in comb["open_games"])
    assert comb["n_fee"] == 2  # Kalshi 0.22 win + Kalshi 0.31 loss; Novig omitted
    assert comb["n_no_fee"] == 1
    assert "Novig" in comb["no_fee_venues"]
    assert comb["pnl_sum"] is not None
    uf_all = payload["unique_fav"]
    for short in ("0-9", "10-19", "20-29", "30-39", "40-49"):
        assert int((uf_all.get(short) or {}).get("n") or 0) == 0
    rows = decile_hero_rows(payload["all_days"])
    labels = [r[0] for r in rows]
    assert any("20-29" in x for x in labels)
    assert any("30-39" in x for x in labels)
    assert any(DECILE_20_39_ID in x or "20-39 combined" in x for x in labels)
    idx_20 = next(i for i, x in enumerate(labels) if x.startswith("20-29"))
    idx_30 = next(i for i, x in enumerate(labels) if x.startswith("30-39"))
    idx_comb = next(i for i, x in enumerate(labels) if "20-39 combined" in x)
    idx_1029 = next(i for i, x in enumerate(labels) if "10-29 combined" in x)
    assert idx_20 < idx_1029 < idx_30 < idx_comb
    assert payload["adds_10_29"] is True
    assert payload["same_rows_yes_no"] is True
    row = band_primary_row(comb)
    assert len(row) == 10  # includes N_fee
    text = GEN.read_text(encoding="utf-8")
    assert "ASKED_DECILE" in text
    assert "ASKED_BUY_NO" in text
    assert "every decile" in text
    assert "N_fee" in text
    assert "Did not bump stake" in text
    assert "Buy No" in text
    assert "not exact negatives" in text
    v = decile_verdict(comb)
    assert "N=" in v
    from nfl_t0_spread_buckets_all_tracked_20261025 import DECILE_HEADERS, NO_DECILE_HEADERS
    assert any(h[0] == "N_fee" for h in DECILE_HEADERS)
    assert any(h[0] == "No wins (Yes lost)" for h in NO_DECILE_HEADERS)


def test_buy_no_is_flip_of_same_rows_fees_not_exact_negative():
    from nfl_t0_type_a_collect import (
        DECILE_10_29_ID,
        build_every_decile_payload,
        t0_no_cash,
        t0_no_trade,
        t0_yes_trade,
    )
    from write_t0_band_from_stay_above import documented_leg_fee

    def book(**kw):
        row = {
            "sport": "pro football",
            "kind": "spread",
            "game": "Cheap vs Dog",
            "game_n": "cheap vs dog",
            "number": "6.5",
            "side_a": "Cheap",
            "side_b": "Dog",
            "fav": "b",
            "fav_name": "Dog",
            "t0_a": 0.12,
            "t0_b": 0.81,
            "t0_fav": 0.81,
            "off_a": "loss",
            "off_b": "win",
            "cover_known": True,
            "settled": True,
            "fav_won": True,
            "two_sided": True,
            "venue": "Kalshi",
            "listed_raw": "2026-10-18T13:00:00-04:00",
            "t0_ts": 1760796000,
        }
        row.update(kw)
        return row

    cheap_loss = book()  # 10-19 Yes 0.12 lost
    mid_loss = book(
        game="Mid vs Fav",
        game_n="mid vs fav",
        number="3.5",
        t0_a=0.22,
        t0_b=0.71,
        t0_fav=0.71,
        off_a="loss",
        off_b="win",
        listed_raw="2026-10-25T13:00:00-04:00",
    )
    cheap_hit = book(
        game="Hit vs Fav",
        game_n="hit vs fav",
        number="7.5",
        t0_a=0.18,
        t0_b=0.75,
        t0_fav=0.75,
        off_a="win",
        off_b="loss",
        fav_won=False,
    )
    novig = book(
        game="Novig vs Only",
        game_n="novig vs only",
        number="2.5",
        t0_a=0.15,
        t0_b=0.78,
        t0_fav=0.78,
        off_a="loss",
        venue="Novig",
    )
    open_kc = book(
        game="Kansas City vs Seattle",
        game_n="kansas city vs seattle",
        number="8.5",
        t0_a=0.16,
        t0_b=0.77,
        t0_fav=0.77,
        off_a=None,
        off_b=None,
        settled=False,
        cover_known=False,
        fav_won=None,
        listed_raw="2026-10-25T20:20:00-04:00",
    )
    cheap_yes = dict(cheap_loss, t0_fav=0.12, fav="a", fav_won=False)
    assert abs(t0_no_cash(cheap_yes) - 0.88) < 1e-12
    yes_t = t0_yes_trade(cheap_yes, "y")
    no_t = t0_no_trade(cheap_yes, "n")
    assert yes_t is not None and no_t is not None
    fee_yes = documented_leg_fee("Kalshi", 0.12)
    fee_no = documented_leg_fee("Kalshi", 0.88)
    assert fee_yes is not None and fee_no is not None
    assert abs(float(fee_yes) - float(fee_no)) < 1e-9
    assert abs((yes_t["pnl_d"] + no_t["pnl_d"]) + 2.0 * float(fee_yes)) < 1e-8
    assert no_t["won"] is True
    assert yes_t["won"] is False
    payload = build_every_decile_payload(
        [cheap_loss, mid_loss, cheap_hit, novig, open_kc],
        sunday_date="2026-10-25",
    )
    yes10 = payload["all_days"]["10-19"]
    no10 = payload["all_days_no"]["10-19"]
    yes20 = payload["all_days"]["20-29"]
    no20 = payload["all_days_no"]["20-29"]
    yes1029 = payload["all_days"]["10-29"]
    no1029 = payload["all_days_no"]["10-29"]
    assert yes10["n"] == no10["n"]
    assert yes20["n"] == no20["n"]
    assert yes1029["n"] == no1029["n"]
    assert payload["adds_10_29"] is True
    assert payload["same_rows_yes_no"] is True
    # 10-19 Yes: 0.12 loss, 0.18 win, 0.15 Novig loss → N=3, Yes wins=1, No wins=2
    assert yes10["n"] == 3
    assert yes10["n_win"] == 1
    assert no10["n_win"] == 2
    assert no10["n_fee"] == 2  # Kalshi 0.12 + 0.18; Novig omitted
    assert no10["n_no_fee"] == 1
    assert "Novig" in no10["no_fee_venues"]
    assert no10["pnl_sum"] is not None
    assert no1029["n"] == yes10["n"] + yes20["n"]
    assert any("Seattle" in g or "seattle" in g.lower() for g in no10["open_games"])
    assert DECILE_10_29_ID in (no1029.get("arm") or "") or "10-29 combined" in (
        no1029.get("arm") or ""
    )
    # High No win% on 10-19 does not invent a Novig dollar.
    assert t0_no_trade(dict(novig, t0_fav=0.15, fav="a", fav_won=False), "n") is None


if __name__ == "__main__":
    test_yes_a_b_glossary_is_not_yes_plus_no()
    test_yes_no_view_arizona_la_is_not_a_lock()
    test_new_page_is_not_the_old_four_row_file()
    test_catalog_spread_sibling()
    test_game_status_does_not_drop_clock_hid_games()
    test_game_status_prefers_settled_unique_fav()
    test_one_sided_and_no_clock_and_unsettled()
    test_no_post_t0_is_a_skip_when_not_settled()
    test_catalog_only_game_is_not_dropped()
    test_overlay_catalog_fills_empty_listed_only()
    test_sunday_first_set_helpers_and_asked_refresh()
    test_both_grains_still_pick_d_line_and_all_lines()
    test_middle_is_a_loss_not_open()
    test_under50_lands_in_lt50_bucket()
    test_occ_map_listed_beats_expiration()
    test_51_69_drops_exact_50_and_excludes_open_and_novig_from_dollars()
    test_every_decile_half_open_and_20_39_adds()
    test_buy_no_is_flip_of_same_rows_fees_not_exact_negative()
    print("ok")
