"""Classifier tests for the live-orders performance page. No network. No secrets."""
from datetime import datetime
from decimal import Decimal

import live_lock_orders
import write_orders_performance as w


def test_fill_requires_qty_at_least_one():
    empty = {"status": "cancelled", "fill_count": "0.00", "remaining_count": "0.00"}
    executed_empty = {"status": "executed", "fill_count": "0.00"}
    status_only = {"status": "filled"}
    real = {"average_fill_price": "0.3400", "fill_count": "1.00"}
    assert live_lock_orders.filled_contracts(empty) == Decimal("0")
    assert live_lock_orders.filled_contracts(executed_empty) == Decimal("0")
    assert live_lock_orders.filled_contracts(status_only) == Decimal("0")
    assert w.qty_is_fill(live_lock_orders.filled_contracts(empty)) is False
    assert w.qty_is_fill(live_lock_orders.filled_contracts(real)) is True
    assert w.qty_is_fill(Decimal("0.62")) is True
    assert w.qty_is_house_fill(Decimal("0.62")) is False
    assert w.qty_is_fill(Decimal("1")) is True
    assert w.qty_is_house_fill(Decimal("1")) is True


def test_kalshi_201_fill_count_zero_is_not_a_fill():
    payload = {"status": "cancelled", "fill_count": "0.00"}
    assert w.leg_fill_qty({"http_status": 201, "response": payload}) == Decimal("0")
    assert w.is_empty_http_fill(201, Decimal("0")) is True
    assert w.is_empty_http_fill(201, Decimal("1")) is False


def test_strategy_b_label():
    assert w.is_strategy_b_row({"bet_key": "tennis-b\tfoo", "step": "websocket"}) is True
    assert w.is_strategy_b_row({"bet_key": "tennis\tfoo", "step": "b-t0"}) is True
    assert w.is_strategy_b_row({"bet_key": "tennis\tfoo", "_strategy_b": True}) is True
    assert w.is_strategy_b_row({"system": "strategy_b"}) is True
    assert w.is_strategy_b_row({"source": "B"}) is True
    assert w.is_strategy_b_row({"bet_key": "tennis\tlinsin", "step": "simultaneous"}) is False
    assert w.source_label({"bet_key": "tennis-b\tx", "step": "b-t0"}) == "tennis_crossover"
    assert w.source_label({"system": "strategy_b"}) == "tennis_crossover"
    assert w.source_label({"bet_key": "tennis\tlinsin", "step": "simultaneous"}) == "lock"


def test_system_of_maps_lock_leftover_to_a_and_old_b_to_tennis():
    assert w.system_of({"intent": w.INTENT_FULL_LOCK, "is_b": False}) == "A"
    assert w.system_of({"intent": w.INTENT_INCOMPLETE_LOCK, "is_b": False}) == "A"
    assert w.system_of({"intent": w.INTENT_LEFTOVER, "is_b": False, "flatten_filled": True}) == "A"
    assert w.system_of({"intent": w.INTENT_LEFTOVER, "is_b": True}) == "B"
    assert w.system_of({"intent": w.INTENT_B, "is_b": True}) == "B"
    assert w.system_of({"intent": w.INTENT_TENNIS, "is_b": True}) == "B"
    assert w.system_of({"intent": w.INTENT_CFB, "kind": "cfb_favorite"}) == "C"
    assert w.system_of({"intent": w.INTENT_SPREAD, "kind": "spread_t0"}) == "D"
    assigned = w.assign_system({"intent": w.INTENT_B, "is_b": True, "b_t0_both": True})
    assert assigned["intent"] == w.INTENT_TENNIS
    assert assigned["system_name"] == "Tennis crossover"
    lock_left = w.assign_system({"intent": w.INTENT_INCOMPLETE_LOCK, "is_b": False, "n_fill_legs": 1})
    assert lock_left["system_letter"] == "A"
    assert "leftover" in lock_left["system_role"]


def test_changelog_stamps_parse():
    for row in w.CHANGELOG_STAMPS:
        assert w.parse_dt(row["when"]) is not None
        assert row["what"]
        assert row["systems"]
        assert row["source"]


def test_intent_buckets():
    assert w.classify_intent(is_b=False, posted=True, n_fill_legs=2, complementary=True) == w.INTENT_FULL_LOCK
    assert w.classify_intent(is_b=False, posted=True, n_fill_legs=1, complementary=False) == w.INTENT_INCOMPLETE_LOCK
    assert w.classify_intent(is_b=True, posted=True, n_fill_legs=2, complementary=True, b_t0_both=True) == w.INTENT_B
    assert w.classify_intent(
        is_b=True, posted=True, n_fill_legs=1, complementary=False, leftover_stack=True
    ) == w.INTENT_LEFTOVER
    assert w.classify_intent(is_b=False, posted=False, n_fill_legs=0, complementary=False) == w.INTENT_LEFTOVER
    assert w.classify_intent(is_b=False, posted=True, n_fill_legs=0, complementary=False) == w.INTENT_LOCK_MISS


def test_false_sent_without_http_is_not_a_trade():
    assert w.is_false_sent_no_http(n_order_io=0, opportunities_said_sent=True) is True
    assert w.is_false_sent_no_http(n_order_io=1, opportunities_said_sent=True) is False
    assert w.is_false_sent_no_http(n_order_io=0, opportunities_said_sent=False) is False
    shsu = w.is_shsu95_false_log("New Mexico State vs Sam Houston", "9.5", "2026-10-21T22:42:05-04:00")
    shsu2 = w.is_shsu95_false_log("New Mexico State vs Sam Houston", "9.5", "2026-10-21T22:58:48-04:00")
    other = w.is_shsu95_false_log("New Mexico State vs Sam Houston", "2.5", "2026-10-21T22:42:05-04:00")
    assert shsu is True and shsu2 is True and other is False


def test_tennis_same_bet_is_not_a_lock():
    goffin_yes = {"qty": 1, "side": "yes", "player": "Goffin", "instrument": "aec-atp-davgof-rember-2026-10-20"}
    bertola_no = {"qty": 1, "side": "no", "player": "Bertola", "instrument": "KXATPMATCH-26OCT20GOFBER-BER"}
    assert w.complementary_legs([goffin_yes, bertola_no]) is False
    goffin_no = {"qty": 1, "side": "no", "player": "Goffin", "instrument": "KX-GOF"}
    assert w.complementary_legs([goffin_yes, goffin_no]) is True
    fav_yes = {"qty": 1, "side": "yes", "player": "Taverna", "instrument": "KX-ROD"}
    dog_yes = {"qty": 1, "side": "yes", "player": "Bueno", "instrument": "KX-BUE"}
    assert w.complementary_legs([fav_yes, dog_yes]) is True


def test_b_match_id():
    assert w.b_match_id("tennis-b\ttennis_rodbue_2026_10_21\tRodriguez Taverna vs Bueno") == "tennis_rodbue_2026_10_21"


def test_leftover_plain_english():
    both = {"n_fill_legs": 2, "complementary": True}
    assert w.leftover_status(both) == w.LEFTOVER_NO
    one = {"n_fill_legs": 1, "complementary": False}
    assert w.leftover_status(one) == w.LEFTOVER_YES
    flat = {"n_fill_legs": 1, "flatten_filled": True}
    assert w.leftover_status(flat) == w.LEFTOVER_NO
    never = {"n_fill_legs": 0, "posted": False}
    assert w.leftover_status(never) == w.LEFTOVER_NO
    t0 = {"n_fill_legs": 2, "b_t0_both": True}
    assert w.leftover_status(t0) == w.LEFTOVER_NO


def test_fill_cash_ignores_sent_fill_qty_without_io():
    cash, fee, qty = w.fill_cash_fee({"fill_qty": "1", "limit_price": "0.40", "venue": "kalshi"}, None)
    assert qty == 0 or qty is None or w.qty_is_fill(qty) is False
    assert cash is None


def test_ribecai_pnl_only_on_fill_cluster():
    held = {
        "game": "Ribecai vs Houkes",
        "fill_legs": [{"venue": "kalshi", "instrument": "KXATPCHALLENGERMATCH-26OCT21RIBHOU-RIB", "qty": 1, "side": "no"}],
        "legs": [],
        "n_fill_legs": 1,
        "notes": [],
    }
    miss = {
        "game": "Ribecai vs Houkes",
        "fill_legs": [],
        "legs": [{"venue": "kalshi", "instrument": "KXATPCHALLENGERMATCH-26OCT21RIBHOU-RIB", "qty": 0}],
        "n_fill_legs": 0,
        "notes": [],
        "realized": Decimal("0"),
    }
    w.apply_paul_history([held, miss], [])
    assert held["realized"] == Decimal("-0.55")
    assert miss.get("paul_settled") is not True
    assert Decimal(str(miss.get("realized") or 0)) == Decimal("0")


def test_paul_history_ribecai_lost():
    cluster = {
        "game": "Ribecai vs Houkes",
        "fill_legs": [{"venue": "kalshi", "instrument": "KXATPCHALLENGERMATCH-26OCT21RIBHOU-RIB", "qty": 1, "side": "no"}],
        "legs": [],
        "n_fill_legs": 1,
        "notes": [],
    }
    w.apply_paul_history([cluster], [])
    assert cluster["realized"] == w.Decimal("-0.55")
    assert cluster["paul_settled"] is True
    assert cluster["price_mismatch"] is True
    assert cluster["void"] is not True
    assert w.match_bucket(cluster) == "matched"


def test_paul_history_danilova_void():
    cluster = {
        "game": "Danilova - Liu vs. Beck - Sibai",
        "fill_legs": [{"venue": "polymarket", "instrument": "aec-itfwo-olgdanyuhliu-avabecjizsib-2026-10-22", "qty": 1}],
        "legs": [],
        "n_fill_legs": 1,
        "notes": [],
    }
    w.apply_paul_history([cluster], [])
    assert cluster["void"] is True
    assert cluster["realized"] == w.Decimal("0")
    assert w.match_bucket(cluster) == "void"


def test_gemini_paste_arithmetic():
    assert w.GEMINI_PASTE[0]["pnl"] == w.Decimal("0.56")
    assert w.GEMINI_PASTE[1]["pnl"] == w.Decimal("0.01")
    assert w.GEMINI_PASTE[2]["pnl"] == w.Decimal("0.03")
    cluster = {
        "game": "Middle Tennessee vs FIU",
        "fill_legs": [{"venue": "gemini", "instrument": "GEMI-NCAAF-2610202300-MTN-FIU-T-O48", "qty": 1, "side": "yes"}],
        "legs": [],
        "n_fill_legs": 1,
        "notes": [],
    }
    w.apply_paul_history([cluster], [])
    assert cluster["gemini_settled"] is True
    assert cluster["realized"] == w.Decimal("0.56")
    assert cluster["venue_live"] is False


def test_funk_plus_one_cent():
    cluster = {
        "game": "Aaron Funk vs. Sergey Petrov",
        "fill_legs": [{"venue": "polymarket", "instrument": "aec-itfme-aarfun-serpet-2026-10-22", "qty": 1}],
        "legs": [],
        "n_fill_legs": 1,
        "notes": [],
    }
    w.apply_paul_history([cluster], [])
    assert cluster["realized"] == w.Decimal("0.01")
    assert cluster["paul_settled"] is True


def test_questions_do_not_reask_six():
    qs = w.questions_for_paul([], {"http": 200, "n": 0, "pulled_at": "now"}, {}, [], [])
    blob = " ".join(qs).lower()
    assert "is 0.55 the fill" not in blob
    assert "do you want those tape rows marked void" not in blob
    assert "paste the gemini and novig" not in blob
    assert "do you still see that match on poly" not in blob
    assert "do you still see machac" not in blob
    assert "what does your polymarket history show" not in blob


def test_restrict_realized_does_not_invent():
    cluster = {
        "game": "Some tennis",
        "fill_legs": [{"venue": "polymarket", "instrument": "aec-no-settle", "qty": 1, "side": "yes", "cash": "0.40", "fee": "0"}],
        "n_fill_legs": 1,
        "realized": w.Decimal("0.60"),
        "status_unknown": False,
        "notes": [],
    }
    w.restrict_realized([cluster], [])
    assert cluster["status_unknown"] is True
    assert cluster["realized"] == w.Decimal("0")
    assert w.match_bucket(cluster) == "mismatched"


def test_venue_holds_leg():
    index = {
        "kalshi": {"KX-RIB": {"position": "1.00"}},
        "polymarket": {"aec-urso": {"net": "-0.75"}},
    }
    assert w.venue_holds_leg({"venue": "kalshi", "instrument": "KX-RIB"}, index) is True
    assert w.venue_holds_leg({"venue": "kalshi", "instrument": "KX-CUI"}, index) is False
    assert w.venue_holds_leg({"venue": "polymarket", "instrument": "aec-urso"}, index) is True
    assert w.venue_holds_leg({"venue": "gemini", "instrument": "x"}, index) is False


def test_game_sides_and_players_label():
    assert w.game_sides("Ribecai vs Houkes") == ["Ribecai", "Houkes"]
    assert w.game_sides("Danilova - Liu vs. Beck - Sibai") == ["Danilova - Liu", "Beck - Sibai"]
    assert w.game_sides("Mattia Bellucci @ Terence Atmane Round of 16") == [
        "Mattia Bellucci",
        "Terence Atmane",
    ]
    assert "tennis" in w.players_game_label("Aaron Funk vs. Sergey Petrov", "tennis")
    assert w.match_code_to_name("RIB", ["Ribecai", "Houkes"]) == "Ribecai"
    assert w.match_code_to_name("KHA", ["Machac", "Khachanov"]) == "Khachanov"
    who = w.kalshi_ticker_who("KXATPCHALLENGERMATCH-26OCT21RIBHOU-RIB", ["Ribecai", "Houkes"])
    assert who == "Ribecai"


def test_removed_rows_name_for_against():
    rib = {
        "game": "Ribecai vs Houkes",
        "sport": "tennis",
        "fill_legs": [{
            "venue": "kalshi",
            "instrument": "KXATPCHALLENGERMATCH-26OCT21RIBHOU-RIB",
            "qty": 1,
            "side": "no",
            "player": "Ribecai",
            "cash": "0.53",
        }],
        "n_fill_legs": 1,
        "notes": [],
        "paul_settled": True,
        "status_unknown": False,
        "realized": w.Decimal("-0.55"),
    }
    gem = {
        "game": "Carolina vs Calgary",
        "sport": "pro hockey",
        "fill_legs": [{
            "venue": "gemini",
            "instrument": "GEMI-NHL-2610190000-CAR-CGY-M-CGY",
            "qty": 1,
            "side": "yes",
            "cash": "0.99",
        }],
        "n_fill_legs": 1,
        "notes": [],
        "gemini_settled": True,
        "status_unknown": False,
        "realized": w.Decimal("0.01"),
    }
    leftover = {
        "game": "Alves vs Pereira",
        "sport": "tennis",
        "is_b": True,
        "leftover_stack": True,
        "intent": w.INTENT_LEFTOVER,
        "fill_legs": [{
            "venue": "polymarket",
            "instrument": "aec-atp-matalv-josper-2026-10-19",
            "qty": 1,
            "side": "yes",
            "player": "Alves",
            "outcome_name": "Alves",
            "cash": "0.40",
        }],
        "n_fill_legs": 1,
        "result": "one-leg leftover",
        "notes": [],
        "status_unknown": True,
    }
    urso = {
        "game": "Aurora Urso vs. Aneta Poborilova",
        "sport": "tennis",
        "fill_legs": [{
            "venue": "polymarket",
            "instrument": "aec-itfwo-ursaur-pobane-2026-10-22",
            "qty": 1,
            "side": "no",
            "outcome_name": "Poborilova, Aneta",
        }],
        "n_fill_legs": 1,
        "notes": [],
        "venue_live": True,
    }
    open_rows = [{
        "game": "Aurora Urso vs. Aneta Poborilova",
        "venue": "polymarket",
        "instrument": "aec-itfwo-ursaur-pobane-2026-10-22",
    }]
    no_game = {
        "game": "",
        "sport": "college football",
        "fill_legs": [{
            "venue": "kalshi",
            "instrument": "KXNCAAFTOTAL-26OCT20MTUFIU-49",
            "qty": 1,
            "side": "no",
            "cash": "0.33",
        }],
        "n_fill_legs": 1,
        "notes": [],
        "status_unknown": True,
        "result": "one-leg leftover",
    }
    rows = w.removed_closed_rows([rib, gem, leftover, urso, no_game], open_rows, {})
    games = [r[0] for r in rows]
    assert not any("urso" in str(g).lower() for g in games)
    rib_row = next(r for r in rows if "Ribecai" in str(r[0]))
    assert "No Ribecai" in str(rib_row[2])
    assert "unpaired leftover" in str(rib_row[3]).lower()
    gem_row = next(r for r in rows if "Calgary" in str(r[0]) or "Carolina" in str(r[0]))
    assert "Yes Calgary" in str(gem_row[2])
    left_row = next(r for r in rows if "Alves" in str(r[0]))
    assert "Yes Alves" in str(left_row[2])
    assert "unpaired leftover / extra Yes" in str(left_row[3])
    dos = {
        "game": "",
        "sport": "",
        "is_b": True,
        "leftover_stack": True,
        "intent": w.INTENT_LEFTOVER,
        "fill_legs": [
            {"venue": "polymarket", "instrument": "aec-atp-santos-malla", "qty": 1, "side": "yes", "outcome_name": "Paulo Andre Saraiva Dos Santos"},
            {"venue": "polymarket", "instrument": "aec-atp-santos-malla", "qty": 1, "side": "no", "outcome_name": "Bastian Malla"},
        ],
        "n_fill_legs": 2,
        "notes": [],
        "status_unknown": True,
        "result": "one-leg leftover",
    }
    rows = w.removed_closed_rows([rib, gem, leftover, urso, no_game, dos], open_rows, {})
    forty_nine = next(
        r for r in rows
        if "49" in str(r[2]) or "Under" in str(r[2]) or "FIU" in str(r[0]) or "Middle Tennessee" in str(r[0])
    )
    assert "No" in str(forty_nine[2])
    assert "Under" in str(forty_nine[2]) or "total 49" in str(forty_nine[2])
    dos_row = next(r for r in rows if "Dos Santos" in str(r[0]) or "Malla" in str(r[0]))
    assert "unknown" not in str(dos_row[0]).lower()
    assert "Yes Paulo" in str(dos_row[2]) or "No Bastian" in str(dos_row[2])
    assert len(rows) == 5


def test_flatten_uses_leg_side_not_first_venue_fill():
    cluster = {
        "game": "Cui vs Wu",
        "sport": "tennis",
        "flatten_filled": True,
        "fill_legs": [
            {
                "venue": "kalshi",
                "instrument": "KXATPCHALLENGERMATCH-26OCT22CUIYIB-CUI",
                "qty": 1,
                "side": "no",
                "player": "Cui",
                "step": "",
                "cash": "0.51",
            },
            {
                "venue": "kalshi",
                "instrument": "KXATPCHALLENGERMATCH-26OCT22CUIYIB-CUI",
                "qty": 1,
                "side": "yes",
                "player": "Cui",
                "step": "flatten",
                "cash": "0.43",
            },
        ],
        "n_fill_legs": 2,
        "notes": [],
    }
    fills = {
        ("kalshi", "kxatpchallengermatch-26oct22cuiyib-cui"): [
            {"side": "yes", "qty": "1.00", "house_cash": "0.43", "house_fill": True},
            {"side": "no", "qty": "1.00", "house_cash": "0.51", "house_fill": True},
        ]
    }
    view = w.cluster_bet_view(cluster, fills)
    assert view["bet_for"].startswith("No Cui")
    assert "Yes Cui" in view["bet_against"]
    assert "flatten" in view["bet_against"]


def test_gemini_buy_label_from_paste():
    book, who = w.gemini_buy_label("GEMI-NCAAF-2610202300-MTN-FIU-T-O48", "Middle Tennessee vs FIU")
    assert book == "yes"
    assert "48.5" in who or "more than" in who.lower()
    book2, who2 = w.gemini_buy_label("GEMI-MLB-2610180000-TB-CLE-M-TB", "Tampa Bay vs Cleveland Game 5")
    assert book2 == "yes"
    assert "Tampa Bay" in who2


def test_league_from_catalog_tickers():
    assert w.league_from_instrument("KXATPMATCH-26OCT25COBDIM-COB") == "ATP"
    assert w.league_from_instrument("KXATPCHALLENGERMATCH-26OCT21RIBHOU-RIB") == "ATP Challenger"
    assert w.league_from_instrument("KXWTAMATCH-26OCT24ABC-ABC") == "WTA"
    assert w.league_from_instrument("aec-itfme-karabd-margui-2026-10-25") == "ITF"
    assert w.league_from_instrument("aec-atp-flacob-gridim-2026-10-25") == "ATP"
    assert w.league_from_instrument("KXNCAAFGAME-26OCT24UNTNAVY-UNT") == "CFB"
    assert w.league_from_instrument("KXNFLSPREAD-26OCT25KCSEA-KC3") == "NFL"
    assert w.league_from_instrument("aec-nfl-phi-was-2026-11-01") == "NFL"
    assert w.league_from_instrument("mystery-slug") == ""
    cluster = {
        "sport": "tennis",
        "fill_legs": [{"venue": "polymarket", "instrument": "aec-itfwo-ursaur-pobane-2026-10-22"}],
    }
    assert w.league_of(cluster) == "ITF"
    cfb = {
        "sport": "college football",
        "fill_legs": [{"venue": "kalshi", "instrument": "KXNCAAFGAME-26OCT24BSUWSU-BSU"}],
    }
    assert w.league_of(cfb) == "CFB"
    unknown = {"sport": "tennis", "fill_legs": [{"venue": "polymarket", "instrument": "no-prefix"}]}
    assert w.league_of(unknown) == "unknown"


def test_settled_means_venue_paid_not_empty_get():
    paid = {
        "game": "BSU vs WSU",
        "sport": "college football",
        "kind": "cfb_favorite",
        "n_fill_legs": 1,
        "fill_legs": [{
            "venue": "kalshi",
            "instrument": "KXNCAAFGAME-26OCT24BSUWSU-BSU",
            "side": "yes",
            "qty": 1,
            "cash": "0.62",
            "fee": "0",
        }],
        "notes": [],
    }
    settlements = [{
        "ticker": "KXNCAAFGAME-26OCT24BSUWSU-BSU",
        "result": "yes",
        "status": "finalized",
        "venue": "Kalshi",
    }]
    empty_books = {"kalshi": {}, "polymarket": {}, "kalshi_ok": True, "poly_ok": True}
    scored = w.score_cluster(paid, settlements, empty_books, w.market_index_of(settlements))
    assert w.cluster_is_settled(scored) is True
    assert scored.get("venue_live") is False
    assert Decimal(str(scored.get("open_cost") or 0)) == 0
    assert scored["realized"] > 0


def test_empty_poly_open_does_not_drop_fill():
    cluster = {
        "game": "Karim vs Guidotti",
        "sport": "tennis",
        "n_fill_legs": 1,
        "fill_legs": [{
            "venue": "polymarket",
            "instrument": "aec-itfme-karabd-margui-2026-10-25",
            "side": "yes",
            "qty": 1,
            "cash": "0.32",
            "fee": "0.01",
        }],
        "notes": [],
    }
    open_info = {
        "ticker": "aec-itfme-karabd-margui-2026-10-25",
        "status": "open",
        "venue": "Polymarket",
        "result": "",
    }
    books = {
        "kalshi": {},
        "polymarket": {"aec-itfme-karabd-margui-2026-10-25": {"net": "1"}},
        "kalshi_ok": True,
        "poly_ok": True,
    }
    scored = w.score_cluster(cluster, [open_info], books, w.market_index_of([open_info]))
    assert scored.get("venue_live") is True
    assert w.cluster_is_settled(scored) is False
    expired = {
        "ticker": "aec-itfme-karabd-margui-2026-10-25",
        "status": "expired",
        "expired": True,
        "venue": "Polymarket",
        "result": "yes",
        "settlementPx": "1",
    }
    gone = {"kalshi": {}, "polymarket": {}, "kalshi_ok": True, "poly_ok": True}
    closed = w.score_cluster(dict(cluster), [expired], gone, w.market_index_of([expired]))
    assert closed.get("venue_live") is False
    assert w.cluster_is_settled(closed) is True


def test_open_book_is_not_final_even_if_expired_flag():
    open_row = {
        "ticker": "aec-still-open",
        "status": "MARKET_STATE_OPEN",
        "expired": True,
        "venue": "polymarket",
        "result": "",
    }
    assert w.settlement_is_final(open_row, venue="polymarket") is False
    paid = {
        "ticker": "aec-done",
        "status": "resolved",
        "result": "yes",
        "venue": "polymarket",
    }
    assert w.settlement_is_final(paid, venue="polymarket") is True


def test_postponed_is_not_settled():
    cluster = {
        "game": "Patricio Llanes Echavarria vs. Edgar Hipolito Cruz Vazquez",
        "sport": "tennis",
        "n_fill_legs": 2,
        "fill_legs": [
            {"venue": "polymarket", "instrument": "aec-slug-llanes", "side": "yes", "qty": 1, "cash": "0.74", "fee": "0.01"},
            {"venue": "polymarket", "instrument": "aec-slug-llanes", "side": "no", "qty": 1, "cash": "0.74", "fee": "0.01"},
        ],
        "watch": {
            "stage": "postponed",
            "postponed_reason": "period=POST",
            "listed_start": "2026-11-02T12:00:00-05:00",
        },
        "start": datetime(2026, 11, 2, 12, 0, tzinfo=__import__("zoneinfo").ZoneInfo("America/New_York")),
        "notes": ["official postponed still open"],
        "complementary": True,
    }
    open_row = {
        "ticker": "aec-slug-llanes",
        "status": "MARKET_STATE_OPEN",
        "venue": "polymarket",
        "postponed": True,
        "result": "",
    }
    scored = w.score_cluster(cluster, [open_row], {"kalshi": {}, "polymarket": {}}, w.market_index_of([open_row]))
    assert scored.get("postponed") is True
    assert w.cluster_is_settled(scored) is False
    assert scored.get("hold_class") == w.HOLD_POSTPONED or "postponed" in str(scored.get("result") or "").lower()
    row = w.ledger_row(scored)
    assert "League" not in row  # values, not headers
    assert any("postponed" in str(cell).lower() for cell in row)


def test_closed_without_settlement_flips_when_px_arrives():
    """Watch postponed must not block a binary settlementPx."""
    slug = "aec-utr-morale-cartho-2026-10-28"
    cluster = {
        "game": "Alejandro Moreno vs. Thomas Cardona Herrera",
        "sport": "tennis",
        "n_fill_legs": 2,
        "fill_legs": [
            {"venue": "polymarket", "instrument": slug, "side": "yes", "qty": "1", "cash": "0.86", "fee": "0.01", "order_id": "TEST-FLAT-NOT-LIVE"},
            {"venue": "polymarket", "instrument": slug, "side": "no", "qty": "1", "cash": "0.16", "fee": "0.01", "order_id": "TEST-HER-NOT-LIVE"},
        ],
        "watch": {"stage": "postponed", "postponed_reason": "closed without settlement"},
        "notes": ["postponed closed without settlement"],
        "complementary": True,
    }
    paid = {
        "ticker": slug,
        "result": "yes",
        "settlementPx": "1.0000",
        "status": "MARKET_STATE_EXPIRED",
        "expired": True,
        "source": "live_market_get",
        "venue": "polymarket",
        "postponed": False,
    }
    scored = w.score_cluster(cluster, [paid], {"kalshi": {}, "polymarket": {}}, w.market_index_of([paid]))
    assert scored.get("postponed") is False
    assert scored.get("venue_paid") is True
    assert w.cluster_is_settled(scored) is True
    hits = w.scan_postponed_but_settled(
        [{**cluster, "postponed": True, "fill_legs": cluster["fill_legs"], "watch": cluster["watch"]}],
        [paid],
    )
    assert len(hits) == 1


def test_poly_partial_is_fill_not_house_one():
    assert w.qty_is_fill(Decimal("0.3")) is True
    assert w.qty_is_house_fill(Decimal("0.3")) is False
    assert w.flatten_marks_house_one(Decimal("0.3"), Decimal("1")) is True
    assert w.flatten_marks_house_one(Decimal("1"), Decimal("1")) is False
    assert w.is_empty_http_fill(200, Decimal("0.3")) is False
    assert w.is_empty_http_fill(200, Decimal("0")) is True


def test_poly_buy_short_cash_is_house_not_yes_wire():
    io_row = {
        "request": {"intent": "ORDER_INTENT_BUY_SHORT", "price": {"value": "0.360"}},
        "response": {
            "id": "DC4BN4J011MC",
            "executions": [{
                "lastPx": {"value": "0.3600"},
                "commissionSpreadPx": {"value": "0.6400"},
                "commissionNotionalCollected": {"value": "0.0200"},
                "order": {
                    "id": "DC4BN4J011MC",
                    "intent": "ORDER_INTENT_BUY_SHORT",
                    "state": "ORDER_STATE_FILLED",
                    "cumQuantity": 1,
                    "avgPx": {"value": "0.3600"},
                    "price": {"value": "0.36"},
                    "marketMetadata": {"outcome": "Arina Varaksina"},
                },
            }],
        },
    }
    # No house quote: complementary venue prices; debit is spread, not Yes-wire avgPx.
    cash, fee, qty = w.fill_cash_fee({"venue": "polymarket", "side": "no", "limit_price": "0.360"}, io_row)
    assert w.qty_is_fill(qty)
    assert Decimal(str(cash)) == Decimal("0.6400")
    assert Decimal(str(fee)) == Decimal("0.0200")
    poly = w.polymarket_fill(io_row["response"])
    assert Decimal(str(poly.get("cash"))) == Decimal("0.6400")
    assert poly.get("side") == "no"
    # House quote matching avgPx: per-order debit, not a global spread swap.
    quoted = {"venue": "polymarket", "side": "no", "limit_price": "0.360", "quote_price": "0.36"}
    cash_q, fee_q, qty_q = w.fill_cash_fee(quoted, io_row)
    assert Decimal(str(cash_q)) == Decimal("0.3600")
    assert Decimal(str(fee_q)) == Decimal("0.0200")
    assert w.qty_is_fill(qty_q)


def test_t0_node_matches_player_not_shared_slug():
    slug = "aec-itfwo-moemiy-arivar-2026-10-28"
    watch = {
        "t0_yes": {
            "a": {"player": "Moeka Miyata", "instrument": slug, "fill_px": "0.3700", "side": "yes"},
            "b": {"player": "Arina Varaksina", "instrument": slug, "fill_px": "0.3600", "side": "no"},
        }
    }
    yes_node = w.t0_node_for_sent(
        watch,
        {"instrument": slug, "side": "yes", "side_label": "Moeka Miyata", "step": "b-t0"},
    )
    no_node = w.t0_node_for_sent(
        watch,
        {"instrument": slug, "side": "no", "side_label": "Arina Varaksina", "step": "b-t0"},
    )
    assert "Miyata" in str(yes_node.get("player"))
    assert "Varaksina" in str(no_node.get("player"))
    assert yes_node.get("fill_px") == "0.3700"
    assert no_node.get("fill_px") == "0.3600"


def test_b_t0_poly_yes_no_stays_open_until_market_final():
    slug = "aec-itfwo-moemiy-arivar-2026-10-28"
    miyata = {
        "qty": 1, "side": "yes", "player": "Moeka Miyata", "cash": "0.37", "fee": "0.02",
        "venue": "polymarket", "instrument": slug, "order_id": "DC4BN1VG11N2", "step": "b-t0",
        "posted": True, "has_io": True, "http": 200,
        "http_line": "polymarket HTTP 200 fill 1",
    }
    vara = {
        "qty": 1, "side": "no", "player": "Arina Varaksina", "cash": "0.36", "fee": "0.02",
        "venue": "polymarket", "instrument": slug, "order_id": "DC4BN4J011MC", "step": "b-t0",
        "posted": True, "has_io": True, "http": 200,
        "http_line": "polymarket HTTP 200 fill 1",
    }
    cluster = {
        "is_b": True,
        "b_t0_both": True,
        "complementary": True,
        "game": "Moeka Miyata vs. Arina Varaksina",
        "fill_legs": [miyata, vara],
        "legs": [miyata, vara],
        "n_fill_legs": 2,
        "flatten_filled": False,
        "market_final": False,
        "venue_live": False,
        "notes": [],
    }
    scored = w.score_cluster(cluster, [], {"kalshi": {}, "polymarket": {}}, {})
    assert scored.get("venue_live") is True
    assert w.cluster_is_settled(scored) is False
    w.restrict_realized([scored], [])
    assert w.cluster_is_settled(scored) is False
    assert scored.get("venue_paid") is not True
    import write_dashboard as d
    rows = d.flatten_trades([scored])
    by_id = {row["order_id"]: row for row in rows}
    assert by_id["DC4BN1VG11N2"]["wire"] == "0.3700"
    assert by_id["DC4BN4J011MC"]["wire"] == "0.3600"
    assert by_id["DC4BN1VG11N2"]["side"] == "Yes Moeka Miyata"
    assert by_id["DC4BN4J011MC"]["side"] == "Yes Arina Varaksina"
    assert not str(by_id["DC4BN4J011MC"]["side"]).lower().startswith("no ")
    assert by_id["DC4BN1VG11N2"]["outcome"] == "open"
    assert by_id["DC4BN4J011MC"]["outcome"] == "open"
    assert by_id["DC4BN1VG11N2"]["settled"] is False
    w.apply_overlay_live_flags([scored], [])
    assert scored.get("venue_live") is True
    assert w.cluster_is_settled(scored) is False
    extra = w.extra_open_from_unsettled([scored], [])
    assert extra and extra[0]["venue"] == "polymarket"
    assert not w.same_slug_cloned_prices([scored])
    cloned = {
        "fill_legs": [
            {**miyata, "cash": "0.36", "player": "Arina Varaksina"},
            {**vara, "cash": "0.36", "player": "Arina Varaksina"},
        ]
    }
    assert w.same_slug_cloned_prices([cloned])


def test_cd_empty_get_is_not_auto_open():
    cluster = {
        "game": "NAVY vs UNT",
        "sport": "college football",
        "kind": "cfb_favorite",
        "system_letter": "C",
        "n_fill_legs": 1,
        "fill_legs": [{
            "venue": "kalshi",
            "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT",
            "side": "yes",
            "qty": 1,
            "cash": "0.67",
            "fee": "0",
        }],
        "settled_legs": 1,
        "market_final": True,
        "venue_paid": True,
        "venue_live": False,
        "flatten_filled": False,
    }
    extra = w.extra_open_from_unsettled([cluster], [])
    assert extra == []
    assert w.cluster_is_settled(cluster) is True


def test_split_b_extras_does_not_keep_cross_on_t0_legs():
    t0_a = {"step": "b-t0", "qty": 1, "order_id": "yas-t0", "player": "Yastremska", "cash": "0.46", "venue": "kalshi", "side": "yes"}
    t0_b = {"step": "b-t0", "qty": 1, "order_id": "vol-t0", "player": "Volynets", "cash": "0.56", "venue": "kalshi", "side": "yes"}
    cross = {"step": "b-cross", "qty": 1, "order_id": "yas-cross", "player": "Yastremska", "cash": "0.55", "venue": "kalshi", "side": "yes"}
    cluster = {
        "is_b": True,
        "fill_legs": [t0_a, t0_b, cross],
        "legs": [t0_a, t0_b, cross],
        "n_fill_legs": 3,
        "watch": {},
    }
    rows = w.split_b_extras(cluster)
    assert len(rows) == 2
    t0_row, extra_row = rows
    assert [leg["order_id"] for leg in t0_row["legs"]] == ["yas-t0", "vol-t0"]
    assert [leg["order_id"] for leg in extra_row["legs"]] == ["yas-cross"]
    assert [leg["order_id"] for leg in t0_row["fill_legs"]] == ["yas-t0", "vol-t0"]
    assert [leg["order_id"] for leg in extra_row["fill_legs"]] == ["yas-cross"]
    t0_ids = {leg["order_id"] for leg in t0_row["legs"]}
    extra_ids = {leg["order_id"] for leg in extra_row["legs"]}
    assert t0_ids.isdisjoint(extra_ids)


def test_stamp_ticket_pnl_win_xor_loss():
    yas = {
        "qty": 1,
        "cash": "0.46",
        "fee": "0.0174",
        "side": "yes",
        "instrument": "KXWTAMATCH-26OCT26YASVOL-YAS",
        "order_id": "yas-t0",
    }
    vol = {
        "qty": 1,
        "cash": "0.56",
        "fee": "0.0173",
        "side": "yes",
        "instrument": "KXWTAMATCH-26OCT26YASVOL-VOL",
        "order_id": "vol-t0",
    }
    cluster = {"fill_legs": [yas, vol], "legs": [yas, vol], "winner": ""}
    settlements = [
        {"ticker": "KXWTAMATCH-26OCT26YASVOL-YAS", "result": "yes"},
        {"ticker": "KXWTAMATCH-26OCT26YASVOL-VOL", "result": "no"},
    ]
    w.stamp_ticket_pnl([cluster], settlements)
    assert yas["ticket_status"] == "win"
    assert vol["ticket_status"] == "lose"
    assert Decimal(yas["ticket_pnl"]) > 0
    assert Decimal(vol["ticket_pnl"]) < 0
    assert yas["ticket_status"] != vol["ticket_status"]


def test_kitchen_side_label_poly_short_is_yes_player():
    slug = "aec-itfme-yutshi-yuhhsu-2026-10-28"
    shimizu = {
        "venue": "polymarket",
        "instrument": slug,
        "side": "yes",
        "player": "Yuta Shimizu",
        "outcome_name": "Yuta Shimizu",
        "io_intent": "ORDER_INTENT_BUY_LONG",
        "qty": 1,
        "step": "b-t0",
        "order_id": "shim-long",
        "has_io": True,
        "http": 200,
    }
    hsu = {
        "venue": "polymarket",
        "instrument": slug,
        "side": "no",
        "player": "Yu-Hsiou Hsu",
        "outcome_name": "Yuta Shimizu",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": 1,
        "step": "b-t0",
        "order_id": "hsu-short",
        "has_io": True,
        "http": 200,
    }
    cluster = {
        "game": "Yuta Shimizu vs. Yu-Hsiou Hsu",
        "sport": "tennis",
        "is_b": True,
        "kind": "b",
        "b_t0_both": True,
        "fill_legs": [shimizu, hsu],
        "legs": [shimizu, hsu],
        "watch": {
            "t0_yes": {
                "a": {"player": "Yuta Shimizu", "instrument": slug, "side": "yes"},
                "b": {"player": "Yu-Hsiou Hsu", "instrument": slug, "side": "no"},
            }
        },
    }
    assert w.kitchen_side_label(shimizu, cluster) == "Yes Yuta Shimizu"
    assert w.kitchen_side_label(hsu, cluster) == "Yes Yu-Hsiou Hsu"
    assert not w.kitchen_side_label(hsu, cluster).lower().startswith("no ")
    w.stamp_kitchen_side_labels(cluster)
    assert shimizu["side"] == "yes" and hsu["side"] == "no"
    assert shimizu["side_label"] == "Yes Yuta Shimizu"
    assert hsu["side_label"] == "Yes Yu-Hsiou Hsu"
    import write_dashboard as d
    rows = {row["order_id"]: row for row in d.flatten_trades([cluster])}
    assert rows["shim-long"]["side"] == "Yes Yuta Shimizu"
    assert rows["hsu-short"]["side"] == "Yes Yu-Hsiou Hsu"
    miyata = {
        "venue": "polymarket",
        "instrument": "aec-itfwo-moemiy-arivar-2026-10-28",
        "side": "yes",
        "player": "Moeka Miyata",
        "io_intent": "ORDER_INTENT_BUY_LONG",
        "qty": 1,
    }
    vara = {
        "venue": "polymarket",
        "instrument": "aec-itfwo-moemiy-arivar-2026-10-28",
        "side": "no",
        "player": "Arina Varaksina",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": 1,
    }
    miyata_cluster = {
        "game": "Moeka Miyata vs. Arina Varaksina",
        "is_b": True,
        "b_t0_both": True,
        "fill_legs": [miyata, vara],
        "legs": [miyata, vara],
        "watch": {
            "t0_yes": {
                "a": {"player": "Moeka Miyata", "instrument": miyata["instrument"], "side": "yes"},
                "b": {"player": "Arina Varaksina", "instrument": miyata["instrument"], "side": "no"},
            }
        },
    }
    assert w.kitchen_side_label(miyata, miyata_cluster) == "Yes Moeka Miyata"
    assert w.kitchen_side_label(vara, miyata_cluster) == "Yes Arina Varaksina"
    hong_yes = {
        "venue": "polymarket",
        "instrument": "aec-hong-wu",
        "side": "yes",
        "player": "Yi-Chen Hong",
        "outcome_name": "Yi-Chen Hong",
        "io_intent": "ORDER_INTENT_BUY_LONG",
        "qty": 1,
    }
    hong_no = {
        "venue": "polymarket",
        "instrument": "aec-hong-wu",
        "side": "no",
        "player": "Yi-Chen Hong",
        "outcome_name": "Yi-Chen Hong",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": 1,
    }
    hong_cluster = {
        "game": "Hong vs Wu",
        "kind": "lock",
        "complementary": True,
        "fill_legs": [hong_yes, hong_no],
        "legs": [hong_yes, hong_no],
    }
    assert w.kitchen_side_label(hong_yes, hong_cluster) == "Yes Yi-Chen Hong"
    assert w.kitchen_side_label(hong_no, hong_cluster) == "No Yi-Chen Hong"
    kalshi_no = {
        "venue": "kalshi",
        "instrument": "KXATPCHALLENGERMATCH-26OCT19MACRIB-RIB",
        "side": "no",
        "player": "Ribecai",
        "qty": 1,
    }
    assert w.kitchen_side_label(kalshi_no, {"game": "Ribecai vs Houkes"}) == "No Ribecai (Sold Yes = buy No)"


def test_e_poly_short_is_yes_player_leftover_is_not_e_dog():
    import order_types

    romano = {
        "venue": "polymarket",
        "instrument": "aec-tabur-romano",
        "side": "no",
        "player": "Filippo Romano",
        "outcome_name": "Clement Tabur",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": 1,
        "step": "e-t0",
        "order_id": "DCEA1H9G11N6",
        "has_io": True,
        "http": 200,
    }
    e_cluster = {
        "game": "Clement Tabur vs. Filippo Romano",
        "sport": "tennis",
        "kind": "tennis_t0_dog",
        "system_letter": "E",
        "fill_legs": [romano],
        "legs": [romano],
    }
    assert w.kitchen_side_label(romano, e_cluster) == "Yes Filippo Romano"
    assert not w.kitchen_side_label(romano, e_cluster).lower().startswith("no ")
    assert order_types.from_leg(romano, e_cluster) == order_types.TYPE_E
    humbert = {
        "venue": "polymarket",
        "instrument": "aec-djokovic-humbert",
        "side": "no",
        "player": "Ugo Humbert",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": 1,
        "step": "e-t0",
        "order_id": "DCF5J93G11MM",
        "has_io": True,
        "http": 200,
        "cash": "0.30",
    }
    djok = {
        "venue": "polymarket",
        "instrument": "aec-djokovic-humbert",
        "side": "yes",
        "player": "Novak Djokovic",
        "io_intent": "ORDER_INTENT_BUY_LONG",
        "qty": 1,
        "step": "watch",
        "order_id": "DCFWP54G11TB",
        "has_io": True,
        "http": 200,
        "cash": "0.55",
    }
    leftover_cluster = {
        "game": "Novak Djokovic vs. Ugo Humbert",
        "sport": "tennis",
        "kind": "tennis_t0_dog",
        "system_letter": "E",
        "fill_legs": [humbert, djok],
        "legs": [humbert, djok],
    }
    assert w.kitchen_side_label(humbert, leftover_cluster) == "Yes Ugo Humbert"
    assert w.kitchen_side_label(djok, leftover_cluster) == "Yes Novak Djokovic"
    assert order_types.from_leg(djok, leftover_cluster) == order_types.TYPE_LEFTOVER
    assert order_types.from_leg(humbert, leftover_cluster) == order_types.TYPE_E
    assert order_types.from_leg(djok, leftover_cluster) != "E Tennis T0 dog"
    assert "underdog" not in order_types.from_leg(djok, leftover_cluster).lower()
    musetti = {
        "venue": "kalshi",
        "instrument": "KXATPMATCH-26OCT28MUSTIA-MUS",
        "side": "no",
        "player": "Lorenzo Musetti",
        "qty": 1,
        "step": "watch",
        "order_id": "01a182f3-52f8-72fc-aac8-f260aa203891",
        "cash": "0.51",
    }
    musetti_cluster = {
        "game": "Lorenzo Musetti vs. Frances Tiafoe",
        "sport": "tennis",
        "kind": "tennis_t0_dog",
        "system_letter": "E",
        "fill_legs": [musetti],
        "legs": [musetti],
    }
    assert w.kitchen_side_label(musetti, musetti_cluster) == "No Lorenzo Musetti (Sold Yes = buy No)"
    assert order_types.from_leg(musetti, musetti_cluster) == order_types.TYPE_LEFTOVER
    e_yes = {
        "venue": "polymarket",
        "instrument": "aec-same-ticker",
        "side": "yes",
        "player": "Filippo Romano",
        "outcome_name": "Filippo Romano",
        "io_intent": "ORDER_INTENT_BUY_LONG",
        "qty": 1,
        "step": "e-t0",
    }
    hedge_no = {
        "venue": "polymarket",
        "instrument": "aec-same-ticker",
        "side": "no",
        "player": "Filippo Romano",
        "outcome_name": "Filippo Romano",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": 1,
        "step": "watch",
    }
    hedge_cluster = {
        "game": "Clement Tabur vs. Filippo Romano",
        "sport": "tennis",
        "kind": "tennis_t0_dog",
        "system_letter": "E",
        "fill_legs": [e_yes, hedge_no],
        "legs": [e_yes, hedge_no],
    }
    assert w.kitchen_side_label(e_yes, hedge_cluster) == "Yes Filippo Romano"
    assert w.kitchen_side_label(hedge_no, hedge_cluster) == "No Filippo Romano"
    humbert_live = {
        "venue": "polymarket",
        "instrument": "aec-atp-novdjo-ugohum-2026-10-25",
        "side": "no",
        "player": "Ugo Humbert",
        "outcome_name": "Novak Djokovic",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": 1,
        "step": "e-t0",
    }
    djok_claim_leak = {
        "venue": "polymarket",
        "instrument": "aec-atp-novdjo-ugohum-2026-10-25",
        "side": "yes",
        "player": "Ugo Humbert",
        "outcome_name": "Novak Djokovic",
        "io_intent": "ORDER_INTENT_BUY_LONG",
        "qty": 1,
        "step": "watch",
    }
    live_cluster = {
        "game": "Djokovic vs Humbert",
        "sport": "tennis",
        "kind": "tennis_t0_dog",
        "system_letter": "E",
        "fill_legs": [humbert_live, djok_claim_leak],
        "legs": [humbert_live, djok_claim_leak],
    }
    assert w.kitchen_side_label(humbert_live, live_cluster) == "Yes Ugo Humbert"
    assert w.kitchen_side_label(djok_claim_leak, live_cluster) == "Yes Novak Djokovic"


def test_restrict_yes_no_same_ticker_lock_no_winner():
    cluster = {
        "game": "Hong vs Wu",
        "complementary": True,
        "fill_legs": [
            {"venue": "polymarket", "instrument": "aec-hong-wu", "side": "yes", "qty": 1, "cash": "0.18", "fee": "0.01"},
            {"venue": "polymarket", "instrument": "aec-hong-wu", "side": "no", "qty": 1, "cash": "0.17", "fee": "0.01"},
        ],
        "n_fill_legs": 2,
        "realized": w.Decimal("0"),
        "status_unknown": True,
        "notes": [],
    }
    w.restrict_realized([cluster], [])
    assert cluster["status_unknown"] is False
    assert Decimal(str(cluster["realized"])) > 0


def test_backfill_fetches_expired_without_yes_no():
    cluster = {
        "game": "Need vs Result",
        "fill_legs": [{"venue": "polymarket", "instrument": "aec-need-result", "qty": 1}],
        "n_fill_legs": 1,
    }
    settlements = [{
        "ticker": "aec-need-result",
        "status": "expired",
        "expired": True,
        "venue": "polymarket",
        "result": "",
    }]
    called = []

    def fake(venue, ident, game=""):
        called.append((venue, ident))
        return {
            "source": "live_market_get",
            "ticker": ident,
            "venue": "Polymarket",
            "result": "yes",
            "status": "resolved",
            "settlementPx": "1",
            "game": game,
        }

    saved = w.fetch_one_market_settlement
    saved_save = w.save_live_settlements
    w.fetch_one_market_settlement = fake
    w.save_live_settlements = lambda rows: None
    try:
        out = w.backfill_venue_settlements([cluster], list(settlements), fetch=True)
    finally:
        w.fetch_one_market_settlement = saved
        w.save_live_settlements = saved_save
    assert called == [("polymarket", "aec-need-result")]
    assert w.ticker_result(out, "aec-need-result") == "yes"


def test_eagles_poly_yes_is_a_lock_gap_football_not_tennis_b():
    """Unmatched Poly Yes Eagles + Kalshi No Eagles is A lock gap / NFL, not B T0 tennis."""
    import job_status_positions as jsp
    import order_types
    import write_dashboard as dash

    slug = "aec-nfl-phi-was-2026-11-01"
    ticker = "KXNFLGAME-26NOV01PHIWAS-PHI"
    assert jsp.sport_from_ticker(slug) == "pro football"
    assert jsp.sport_from_ticker(ticker) == "pro football"
    assert jsp.sport_from_ticker("aec-itfme-lucliu-ryacol-2026-10-28") == "tennis"
    assert jsp.nfl_fixture_key(slug) == jsp.nfl_fixture_key(ticker) == "PHI-WAS"

    kalshi_pos = {
        "ok": True,
        "rows": [{
            "ticker": ticker,
            "position": "-1",
            "exposure": "0.6500",
        }],
        "by_ticker": {ticker: {"ticker": ticker, "position": "-1"}},
    }
    poly_pos = {
        "ok": True,
        "rows": [{
            "slug": slug,
            "title": "Philadelphia Eagles vs. Washington Commanders",
            "outcome": "Eagles",
            "net": "1.0000",
            "qty_bought": "1.0000",
            "qty_sold": "0.0000",
            "avg_px": "0.3130",
            "cost": "0.3130",
            "cash_value": "0.2913",
        }],
        "by_slug": {slug: {"slug": slug, "net": "1.0000"}},
    }
    liu_slug = "aec-itfme-lucliu-ryacol-2026-10-28"
    poly_pos["rows"].append({
        "slug": liu_slug,
        "title": "LUCCA LIU vs Ryan Colby",
        "outcome": "Ryan Colby",
        "net": "-1.0000",
        "qty_bought": "1.0000",
        "qty_sold": "2.0000",
        "avg_px": "0.5600",
        "cost": "0.5600",
        "cash_value": "0.1100",
    })
    rows = w.still_open_from_venue(kalshi_pos, poly_pos, [], {})
    eagles = [r for r in rows if "Eagles" in str(r.get("game") or r.get("players") or "")]
    liu = [r for r in rows if "Colby" in str(r.get("game") or r.get("players") or "")]
    assert len(eagles) == 2, [r.get("game") for r in rows]
    for row in eagles:
        assert row["system"] == "A", row
        assert row["sport"] == "pro football", row
        assert "tennis" not in str(row.get("players") or "").lower(), row
        assert row["open_type"] == "A lock gap", row
        assert "B" not in str(row.get("system") or "")
        assert order_types.open_now_type(row["system"]) == "A lock gap"
    assert {r["venue"] for r in eagles} == {"kalshi", "polymarket"}
    poly_eagles = next(r for r in eagles if r["venue"] == "polymarket")
    assert poly_eagles["instrument"] == slug
    assert "Yes" in str(poly_eagles.get("bet_for") or "")
    assert "Eagles" in str(poly_eagles.get("bet_for") or "")
    kalshi_eagles = next(r for r in eagles if r["venue"] == "kalshi")
    assert kalshi_eagles["instrument"] == ticker
    table = dash.open_table_rows(eagles)
    joined = " | ".join(" | ".join(map(str, row)) for row in table)
    assert "A lock gap" in joined
    assert "B T0" not in joined
    assert "tennis" not in joined.lower()
    assert "pro football" in joined
    assert len(liu) == 1
    assert liu[0]["system"] == "B"
    assert liu[0]["sport"] == "tennis"
    assert liu[0]["open_type"] == "B T0"


def test_result_labels():
    assert w.result_label(posted=False, n_fill_legs=0, flattened=False, complementary=False) == "never posted (claim+skip)"
    assert w.result_label(posted=True, n_fill_legs=0, flattened=False, complementary=False) == "both unfilled"
    assert w.result_label(posted=True, n_fill_legs=2, flattened=False, complementary=True) == "both filled lock"
    assert w.result_label(posted=True, n_fill_legs=1, flattened=False, complementary=False) == "one-leg leftover"
    assert w.result_label(posted=True, n_fill_legs=1, flattened=True, complementary=False, flatten_filled=True) == "flatten filled"
    assert w.result_label(posted=True, n_fill_legs=1, flattened=True, complementary=False, flatten_filled=False) == "flatten miss"


def main() -> None:
    test_fill_requires_qty_at_least_one()
    test_kalshi_201_fill_count_zero_is_not_a_fill()
    test_strategy_b_label()
    test_system_of_maps_lock_leftover_to_a_and_old_b_to_tennis()
    test_changelog_stamps_parse()
    test_intent_buckets()
    test_false_sent_without_http_is_not_a_trade()
    test_leftover_plain_english()
    test_fill_cash_ignores_sent_fill_qty_without_io()
    test_venue_holds_leg()
    test_split_b_extras_does_not_keep_cross_on_t0_legs()
    test_stamp_ticket_pnl_win_xor_loss()
    test_backfill_fetches_expired_without_yes_no()
    test_result_labels()
    test_ribecai_pnl_only_on_fill_cluster()
    test_paul_history_ribecai_lost()
    test_paul_history_danilova_void()
    test_gemini_paste_arithmetic()
    test_funk_plus_one_cent()
    test_questions_do_not_reask_six()
    test_restrict_realized_does_not_invent()
    test_kitchen_side_label_poly_short_is_yes_player()
    test_e_poly_short_is_yes_player_leftover_is_not_e_dog()
    test_restrict_yes_no_same_ticker_lock_no_winner()
    test_game_sides_and_players_label()
    test_removed_rows_name_for_against()
    test_flatten_uses_leg_side_not_first_venue_fill()
    test_gemini_buy_label_from_paste()
    test_league_from_catalog_tickers()
    test_settled_means_venue_paid_not_empty_get()
    test_empty_poly_open_does_not_drop_fill()
    test_open_book_is_not_final_even_if_expired_flag()
    test_postponed_is_not_settled()
    test_closed_without_settlement_flips_when_px_arrives()
    test_poly_partial_is_fill_not_house_one()
    test_cd_empty_get_is_not_auto_open()
    test_poly_buy_short_cash_is_house_not_yes_wire()
    test_t0_node_matches_player_not_shared_slug()
    test_b_t0_poly_yes_no_stays_open_until_market_final()
    test_eagles_poly_yes_is_a_lock_gap_football_not_tennis_b()
    print("test_write_orders_performance ok")


if __name__ == "__main__":
    main()
