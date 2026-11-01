"""Sport/league T0 decile report. No network. No secrets."""
from decimal import Decimal

import _write_sport_league_t0_decile_20261027 as w


def test_decile_bands():
    assert w.decile_of(0.05) == "0-9"
    assert w.decile_of(0.099) == "0-9"
    assert w.decile_of(0.10) == "10-19"
    assert w.decile_of(0.37) == "30-39"
    assert w.decile_of(0.50) == "50-59"
    assert w.decile_of(0.90) == "90-99"
    assert w.decile_of(0.99) == "90-99"
    assert w.decile_of(None) is None


def test_league_map():
    assert w.league_of_side({"sport": "pro football"}) == "NFL"
    assert w.league_of_side({"sport": "college football"}) == "CFB"
    assert w.league_of_side({"sport": "tennis"}) == "tennis"
    assert w.league_of_side({"sport": "tennis", "game": "aec-atp-foo"}) == "ATP"


def test_asked_is_this_regenerate():
    low = w.ASKED.lower()
    assert "latest decile results from kalshi" in low
    assert "historical numbers" in low or "historical" in low
    assert "regen" in low or "regenerate" in low or "decile" in low
    assert "decile" in low
    assert "points total" in low
    assert "polymarket" in low
    assert "kalshi" in low
    assert "named-Yes T0" in w.TAPE_NOTE or "named-Yes T0 tape" in w.TAPE_NOTE
    assert "BUY_SHORT" in w.TAPE_NOTE
    assert "ticker result=yes" in w.TAPE_NOTE
    assert "never averaged" in w.PLAIN.lower() or "never blended" in w.PLAIN.lower()
    assert "last trade" in w.PLAIN.lower() or "last-trade" in w.PLAIN.lower()
    assert "central limit order book" in w.PLAIN.lower()
    assert "jump to it first" in w.PLAIN.lower() or "kalshi history is first" in w.PLAIN.lower()
    blob = w.ASKED + w.PLAIN + w.TAPE_NOTE
    assert "Not gold" not in blob
    assert "Not DailyRun" not in blob
    assert "Research candidate" not in blob


def test_compare_to_prev_same_cells():
    prev = {
        "independent": {
            "tennis_ml_10_49": {"n": 152, "n_win": 70, "n_fee": 128, "pnl_sum": 16.39},
            "soccer_all": {"n": 170, "n_win": 59, "n_fee": 170, "pnl_sum": 4.7006},
            "cfb_40_49": {
                "moneyline": {"n": 2, "n_win": 1, "n_fee": 2, "pnl_sum": 0.1},
                "spread": {"n": 21, "n_win": 8, "n_fee": 21, "pnl_sum": -1.746},
                "total": {"n": 21, "n_win": 11, "n_fee": 21, "pnl_sum": 1.4495},
            },
            "cfb_40_49_grand": {"n": 44, "n_win": 20, "n_fee": 44, "pnl_sum": -0.1965},
            "overall": {"n": 1707, "n_win": 540, "n_fee": 1607, "pnl_sum": -64.2795},
        },
        "cfb_40_49": {
            "moneyline": {"n": 2, "n_win": 1, "n_fee": 2, "pnl_sum": 0.1},
            "spread": {"n": 21, "n_win": 8, "n_fee": 21, "pnl_sum": -1.746},
            "total": {"n": 21, "n_win": 11, "n_fee": 21, "pnl_sum": 1.4495},
        },
        "cfb_40_49_grand": {"n": 44, "n_win": 20, "n_fee": 44, "pnl_sum": -0.1965},
        "grand": {"n": 1707, "n_win": 540, "n_fee": 1607, "pnl_sum": -64.2795},
    }
    spot = w._prev_spot(prev)
    cmp = w.compare_to_prev(spot, prev)
    assert cmp["had_prev"] is True
    assert cmp["changed"] is False
    assert "did not change" in cmp["verdict"]


def test_kind_label_total_is_points_total():
    assert w.kind_label("total") == "Points Total"
    assert w.kind_label("spread") == "Spread"
    assert w.kind_label("moneyline") == "Moneyline"
    assert w.kind_label("ALL") == "ALL bet types"
    rec = {
        "n": 21, "n_win": 11, "win_pct": 52.381, "n_fee": 21,
        "pnl_sum": 1.45, "avg_pnl": 0.07, "note": "",
    }
    cells = w.row_cells("college football", "ALL", "total", "40-49", rec)
    assert cells[2] == "Points Total"
    assert cells[2] != "total"


def test_over_under_is_not_sum_of_spread_and_moneyline():
    sides = [
        _side(sport="college football", kind="total", px=0.45, won=True, game="OU vs A", letter="a"),
        _side(sport="college football", kind="total", px=0.41, won=False, game="OU vs B", letter="a"),
        _side(sport="college football", kind="spread", px=0.44, won=False, game="SP vs A", letter="a"),
        _side(sport="college football", kind="spread", px=0.48, won=False, game="SP vs B", letter="a"),
        _side(sport="college football", kind="spread", px=0.42, won=True, game="SP vs C", letter="a"),
        _side(sport="college football", kind="moneyline", px=0.46, won=True, game="ML vs A", letter="a"),
    ]
    tables = w.build_tables(sides)
    ou = tables["cells"][("college football", "ALL", "total", "40-49")]
    sp = tables["cells"][("college football", "ALL", "spread", "40-49")]
    ml = tables["cells"][("college football", "ALL", "moneyline", "40-49")]
    assert ou["n"] == 2 and sp["n"] == 3 and ml["n"] == 1
    assert ou["n"] != sp["n"] + ml["n"]
    assert abs(float(ou["pnl_sum"]) - (float(sp["pnl_sum"]) + float(ml["pnl_sum"]))) > 0.01
    labels = [row[2] for row in tables["sport_decile"]]
    assert "Points Total" in labels
    assert "total" not in labels
    assert "Over/Under" not in labels
    dump = w.json_dump(tables)
    assert dump["cfb_40_49"]["total"]["kind"] == "total"
    assert dump["cfb_40_49"]["total"]["kind_label"] == "Points Total"
    assert dump["kind_labels"]["total"] == "Points Total"
    assert dump["cfb_40_49_grand"]["n"] == 6
    assert "Points Total" in dump["cfb_40_49_grand"]["note"]
    assert "Over/Under" not in dump["kind_note"]


def _side(*, sport, kind, px, won, venue="kalshi", game="A vs B", letter="a"):
    return {
        "sport": sport,
        "kind": kind,
        "game": game,
        "game_n": game.lower(),
        "venue": venue,
        "number": "",
        "_side_letter": letter,
        "t0_fav": px,
        "t0_a": px if letter == "a" else None,
        "t0_b": px if letter == "b" else None,
        "t0_ts": 1761600000,
        "end_ts": 1761610000,
        "fav": letter,
        "fav_won": won,
        "off_a": "win" if won and letter == "a" else ("loss" if letter == "a" else "pending"),
        "off_b": "win" if won and letter == "b" else ("loss" if letter == "b" else "pending"),
        "void": False,
        "settled": True,
        "cover_known": True,
    }


def test_hist_books_are_not_blended_into_live_grand():
    live = [
        _side(sport="pro football", kind="moneyline", px=0.60, won=True, game="Live A"),
    ]
    hist = [
        _side(sport="pro football", kind="moneyline", px=0.40, won=False, game="Hist A"),
        _side(sport="pro football", kind="moneyline", px=0.41, won=False, game="Hist B"),
    ]
    live_t = w.build_tables(live)
    hist_t = w.build_tables(hist)
    assert live_t["grand"]["n"] == 1
    assert hist_t["grand"]["n"] == 2
    assert live_t["grand"]["n"] != live_t["grand"]["n"] + hist_t["grand"]["n"]
    dump = w.json_dump(live_t)
    assert dump["grand"]["n"] == 1
    rows = w.coverage_rows([{
        "sport": "pro football", "league": "NFL", "kind": "total",
        "platform": "kalshi", "price_kind": "yes_ask", "span_lo": "2025-07-31",
        "span_hi": "2026-10-26", "n_events": 10, "n_t0": 20, "n_missing": 0,
        "candles_fetched": True, "note": "primary",
    }])
    assert rows[0][2] == "Points Total"


def test_parse_html_skips_kalshi_before_book1():
    html = (
        "<h2 id=\"kalshi-history\">Kalshi history — Yes-ask T0 candles (Book 2, not blended)</h2>"
        "<div class=\"table-wrap\"><table class=\"sortable\">"
        "<tr><td>tennis</td><td>ATP</td><td>Moneyline</td><td>40-49</td>"
        "<td>99</td><td>1</td><td>1.0</td><td>99</td><td>-$9.00</td>"
        "<td></td><td></td><td></td><td></td><td></td></tr></table></div>"
        "<h2 id=\"book1-live\">Book 1 — 11-day four-platform live tape (not history)</h2>"
        "<div class=\"table-wrap\"><table class=\"sortable\">"
        "<tr><td>tennis</td><td>ATP</td><td>Moneyline</td><td>40-49</td>"
        "<td>10</td><td>4</td><td>40.0</td><td>10</td><td>$1.20</td>"
        "<td>$0.12</td><td>—</td><td>—</td><td>—</td><td></td></tr></table></div>"
        "<h2 id=\"poly-history\">Polymarket historical (CLOB last-trade) — separate book</h2>"
    )
    prior = w.parse_html_live_cells(html)
    assert prior["tennis|ATP|Moneyline|40-49"]["n"] == 10
    assert prior["tennis|ATP|Moneyline|40-49"]["n_win"] == 4


def test_kalshi_headlines_pool_bands():
    sides = [
        _side(sport="college football", kind="moneyline", px=0.55, won=True, game="CFB A"),
        _side(sport="college football", kind="moneyline", px=0.72, won=False, game="CFB B"),
        _side(sport="college football", kind="moneyline", px=0.81, won=True, game="CFB C"),
        _side(sport="tennis", kind="moneyline", px=0.15, won=True, game="Ten A"),
        _side(sport="tennis", kind="moneyline", px=0.42, won=False, game="Ten B"),
        _side(sport="pro football", kind="spread", px=0.62, won=True, game="NFL A"),
        _side(sport="hockey", kind="spread", px=0.84, won=False, game="NHL A"),
    ]
    tables = w.build_tables(sides)
    spots = {r["label"]: r for r in w.kalshi_headlines(tables["cells"])}
    assert spots["CFB ML 50-89"]["n"] == 3
    assert spots["CFB ML 70-89"]["n"] == 2
    assert spots["Tennis ML 10-49"]["n"] == 2
    assert spots["Spreads 50-89 (all sports)"]["n"] == 2
    html = w.kalshi_headline_html(tables)
    assert "Kalshi tape — headline slices" in html
    assert "class=\"sortable\"" in html


def test_parse_html_and_same_n_flip():
    html = (
        "<h2>Book 1 — 11-day</h2><div class=\"table-wrap\"><table class=\"sortable\">"
        "<tr><td>tennis</td><td>ATP</td><td>Moneyline</td><td>40-49</td>"
        "<td>10</td><td>4</td><td>40.0</td><td>10</td><td>$1.20</td>"
        "<td>$0.12</td><td>—</td><td>—</td><td>—</td><td></td></tr>"
        "</table></div>"
        "<h2>Kalshi historical T0 (Yes ask candles) — separate book</h2>"
        "<tr><td>tennis</td><td>ATP</td><td>Moneyline</td><td>40-49</td>"
        "<td>99</td><td>1</td><td>1.0</td><td>99</td><td>-$9.00</td>"
        "<td></td><td></td><td></td><td></td><td></td></tr>"
    )
    prior = w.parse_html_live_cells(html)
    assert prior["tennis|ATP|Moneyline|40-49"]["n"] == 10
    assert prior["tennis|ATP|Moneyline|40-49"]["n_win"] == 4
    assert abs(prior["tennis|ATP|Moneyline|40-49"]["pnl_sum"] - 1.20) < 0.001
    now = {
        "tennis|ATP|Moneyline|40-49": {
            "n": 10, "n_win": 6, "n_fee": 10, "pnl_sum": -0.40,
        }
    }
    cmp = w.compare_live_cells(now, prior)
    assert cmp["n_flip_same_n"] == 1
    assert cmp["n_tennis_flip"] == 1
    same = w.compare_live_cells(prior, prior)
    assert same["n_flip_same_n"] == 0


def test_tables_split_sport_and_decile():
    sides = [
        _side(sport="tennis", kind="moneyline", px=0.25, won=True, game="Dog vs Fav"),
        _side(sport="tennis", kind="moneyline", px=0.75, won=False, game="Dog vs Fav", letter="b"),
        _side(sport="pro football", kind="spread", px=0.62, won=True, game="NY vs DAL"),
    ]
    tables = w.build_tables(sides)
    tennis_lo = tables["cells"][("tennis", "tennis", "moneyline", "20-29")]
    tennis_hi = tables["cells"][("tennis", "tennis", "moneyline", "70-79")]
    nfl = tables["cells"][("pro football", "NFL", "spread", "60-69")]
    assert tennis_lo["n"] == 1 and tennis_lo["n_win"] == 1
    assert tennis_hi["n"] == 1 and tennis_hi["n_win"] == 0
    assert nfl["n"] == 1 and nfl["n_win"] == 1
    assert tennis_lo["n_fee"] == 1
    assert tennis_lo["pnl_sum"] is not None and tennis_lo["pnl_sum"] > 0
    assert tennis_hi["pnl_sum"] is not None and tennis_hi["pnl_sum"] < 0
    grand = tables["grand"]
    assert grand["n"] == 3
    assert grand["n_win"] == 2


def main() -> None:
    test_decile_bands()
    test_league_map()
    test_asked_is_this_regenerate()
    test_compare_to_prev_same_cells()
    test_kind_label_total_is_points_total()
    test_over_under_is_not_sum_of_spread_and_moneyline()
    test_hist_books_are_not_blended_into_live_grand()
    test_parse_html_skips_kalshi_before_book1()
    test_kalshi_headlines_pool_bands()
    test_parse_html_and_same_n_flip()
    test_tables_split_sport_and_decile()
    print("test_sport_league_t0_decile_20261027 ok")


if __name__ == "__main__":
    main()
