"""Four kitchen overlay tickers decode to teams, type, and who the $1 pays.

No network. Does not invert Polymarket BUY_SHORT cash.
"""
from __future__ import annotations

import kalshi_ticker_decode as d
import write_orders_performance as w
import write_dashboard as dash
import job_status_positions as jsp
from decimal import Decimal
import open_count_sync as ocs


FOUR = [
    {
        "ticker": "KXNFLTOTAL-26OCT29CARGB-49",
        "pay": "no",
        "game": "Carolina Panthers vs Green Bay Packers",
        "type": "Points Total 49",
        "bet_for": "Under",
        "yes_no": "No (Under)",
        "phrase": "No (Under)",
    },
    {
        "ticker": "KXNFLGAME-26NOV01PHIWAS-PHI",
        "pay": "no",
        "game": "Philadelphia Eagles vs Washington Commanders",
        "type": "moneyline",
        "bet_for": "Washington Commanders",
        "yes_no": "No",
        "phrase": "No Philadelphia Eagles",
    },
    {
        "ticker": "KXNFLSPREAD-26NOV01MINDET-DET4",
        "pay": "yes",
        "game": "Minnesota Vikings vs Detroit Lions",
        "type": "spread Detroit Lions -4",
        "bet_for": "Detroit Lions -4",
        "yes_no": "Yes",
        "phrase": "Yes Detroit Lions -4",
    },
    {
        "ticker": "KXNFLGAME-26NOV01MINDET-DET",
        "pay": "yes",
        "game": "Minnesota Vikings vs Detroit Lions",
        "type": "moneyline",
        "bet_for": "Detroit Lions",
        "yes_no": "Yes",
        "phrase": "Yes Detroit Lions",
    },
]


def test_four_quoted_tickers():
    for row in FOUR:
        got = d.display_row(row["ticker"], row["pay"])
        assert got["game"] == row["game"], (row["ticker"], got["game"])
        assert got["type"] == row["type"], (row["ticker"], got["type"])
        assert got["bet_for"] == row["bet_for"], (row["ticker"], got["bet_for"])
        assert got["yes_no"] == row["yes_no"], (row["ticker"], got["yes_no"])
        assert got["phrase"] == row["phrase"], (row["ticker"], got["phrase"])
        assert "Yes no" not in got["phrase"].lower() or got["phrase"] == "Yes no"
        assert got["phrase"].lower() != "yes no"


def test_sold_yes_is_buy_no_gloss():
    assert d.sold_yes_buy_no_gloss("no") == "Sold Yes = buy No"
    assert d.sold_yes_buy_no_gloss("yes") == ""


def test_no_eagles_names_the_ticker_not_the_opponent():
    got = d.display_row("KXNFLGAME-26NOV01PHIWAS-PHI", "no")
    assert got["phrase"] == "No Philadelphia Eagles"
    assert got["bet_for"] == "Washington Commanders"
    decoded = d.decode_kalshi_ticker("KXNFLGAME-26NOV01PHIWAS-PHI", pay="no")
    assert d.kitchen_clear(decoded, "no") == (
        "No Philadelphia Eagles (pays if Washington Commanders win)"
    )
    assert d.pays_if_label(decoded, "no") == "Washington Commanders win"
    yes_phi = d.display_row("KXNFLGAME-26NOV01PHIWAS-PHI", "yes")
    assert yes_phi["phrase"] == "Yes Philadelphia Eagles"


def test_garbled_yes_no_recovers_real_side():
    assert d.pay_from_garbled_bet("Yes no 0.5300 Kalshi") == "no"
    assert d.pay_from_garbled_bet("Yes yes 0.4800") == "yes"
    assert d.pay_from_garbled_bet("No (Under) 0.5300 Kalshi") == "no"


def test_spread_sign_from_title_plus():
    decoded = d.decode_kalshi_ticker(
        "KXNFLSPREAD-26NOV01MINDET-DET4",
        title="Will the Detroit Lions cover +4.5?",
    )
    assert decoded.line.startswith("+"), decoded.line
    assert "4" in decoded.line


def test_spread_sign_from_title_win_by_over():
    decoded = d.decode_kalshi_ticker(
        "KXNFLSPREAD-26NOV01MINDET-DET4",
        title="Will the Detroit Lions win by over 3.5 points?",
    )
    assert decoded.line == "-3.5", decoded.line


def test_cfb_and_tennis_untouched_path():
    cfb = d.decode_kalshi_ticker("KXNCAAFGAME-26OCT24BSUWSU-BSU")
    assert cfb.game == "Boise State vs Washington State"
    assert cfb.kind == "moneyline"
    tennis = d.decode_kalshi_ticker("KXATPCHALLENGERMATCH-26OCT21RIBHOU-RIB")
    assert tennis.kind == ""
    assert w.kitchen_side_label(
        {
            "venue": "kalshi",
            "instrument": "KXATPCHALLENGERMATCH-26OCT19MACRIB-RIB",
            "side": "no",
            "player": "Ribecai",
            "qty": 1,
        },
        {"game": "Ribecai vs Houkes"},
    ) == "No Ribecai (Sold Yes = buy No)"
    shimizu = {
        "venue": "polymarket",
        "instrument": "aec-itfme-yutshi-yuhhsu-2026-10-28",
        "side": "yes",
        "player": "Yuta Shimizu",
        "outcome_name": "Yuta Shimizu",
        "io_intent": "ORDER_INTENT_BUY_LONG",
        "qty": 1,
    }
    hsu = {
        "venue": "polymarket",
        "instrument": "aec-itfme-yutshi-yuhhsu-2026-10-28",
        "side": "no",
        "player": "Yu-Hsiou Hsu",
        "outcome_name": "Yuta Shimizu",
        "io_intent": "ORDER_INTENT_BUY_SHORT",
        "qty": 1,
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
                "a": {"player": "Yuta Shimizu", "instrument": shimizu["instrument"], "side": "yes"},
                "b": {"player": "Yu-Hsiou Hsu", "instrument": hsu["instrument"], "side": "no"},
            }
        },
    }
    assert w.kitchen_side_label(shimizu, cluster) == "Yes Yuta Shimizu"
    assert w.kitchen_side_label(hsu, cluster) == "Yes Yu-Hsiou Hsu"


def test_overlay_rows_use_names_not_ticker():
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    tickers = [
        ("KXNFLTOTAL-26OCT29CARGB-49", "no", "0.5300"),
        ("KXNFLGAME-26NOV01PHIWAS-PHI", "no", "0.6500"),
        ("KXNFLSPREAD-26NOV01MINDET-DET4", "yes", "0.4800"),
        ("KXNFLGAME-26NOV01MINDET-DET", "yes", "0.6100"),
    ]
    rows = []
    intent = {}
    for ticker, pay, px in tickers:
        signed = px if pay == "yes" else f"-{px}"
        rows.append(
            {
                "venue": "kalshi",
                "ticker": ticker,
                "title": ticker,
                "side": pay,
                "qty": "1",
                "pay": pay,
                "exposure": px,
                "fees": "0.0175",
            }
        )
        intent[("kalshi", ticker)] = {
            "sid": "lock",
            "letter": "A",
            "name": "Lock gap",
            "sport": "pro football",
            "game": ticker,
            "kind": "",
            "number": "",
            "side_label": pay,
            "pay": pay,
            "entry": Decimal(px),
            "opened_at": "2026-10-28T12:00:00-04:00",
            "lock_pair": True,
        }
        _ = signed
    snap["kalshi"] = rows
    snap["kalshi_by_ticker"] = {r["ticker"]: r for r in rows}
    bundle = jsp.build_rows(snap, intent=intent, quotes={}, fetch_quotes=False)
    games = [r.get("game") for r in bundle["rows"]]
    bets = " | ".join(str(r.get("bets") or "") for r in bundle["rows"])
    html = jsp.render_table(bundle)
    assert "Carolina Panthers vs Green Bay Packers" in games
    assert "Philadelphia Eagles vs Washington Commanders" in games
    assert "Minnesota Vikings vs Detroit Lions" in games
    assert not any(str(g).startswith("KXNFL") for g in games), games
    assert "Yes no" not in bets
    assert "Yes no" not in html
    assert "No (Under)" in bets or "No (Under)" in html
    assert "No Philadelphia Eagles" in bets or "No Philadelphia Eagles" in html
    assert "No Washington Commanders" not in bets
    assert "No Washington Commanders" not in html
    assert "Washington Commanders" in bets or "Washington Commanders" in html
    assert "Detroit Lions" in html
    open_rows = dash.open_from_positions(bundle)
    labels = " ".join(str(r.get("players") or r.get("game") or "") for r in open_rows)
    fors = " ".join(str(r.get("bet_for") or "") for r in open_rows)
    assert "KXNFLTOTAL" not in labels
    assert "Carolina Panthers" in labels
    assert "Yes no" not in fors
    assert "No (Under)" in fors
    table = dash.open_table_rows(open_rows)
    joined = " ".join(" | ".join(map(str, row)) for row in table)
    assert "KXNFLGAME-26NOV01PHIWAS-PHI" not in joined
    assert "Yes no" not in joined
    assert "No Philadelphia Eagles" in joined
    assert "No Washington Commanders" not in joined
    assert "A lock gap" in joined


def test_poly_eagles_yes_pairs_kalshi_no_as_a_lock_gap():
    """Kitchen Positions: Poly Yes Eagles 0.313 + Kalshi No Eagles → A lock gap / football."""
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    ticker = "KXNFLGAME-26NOV01PHIWAS-PHI"
    slug = "aec-nfl-phi-was-2026-11-01"
    snap["kalshi"] = [{
        "venue": "kalshi",
        "ticker": ticker,
        "title": ticker,
        "side": "no",
        "qty": "1",
        "pay": "no",
        "exposure": "0.6500",
        "fees": "0.0175",
    }]
    snap["kalshi_by_ticker"] = {ticker: snap["kalshi"][0]}
    snap["poly"] = [{
        "venue": "polymarket",
        "ticker": slug,
        "title": "Philadelphia Eagles vs. Washington Commanders",
        "qty": "1.0000",
        "pay": "yes",
        "side": "yes",
        "exposure": "0.3130",
    }]
    snap["poly_by_slug"] = {slug: snap["poly"][0]}
    intent = {
        ("kalshi", ticker): {
            "sid": "lock",
            "letter": "A",
            "name": "Lock gap",
            "sport": "pro football",
            "game": "Philadelphia Eagles vs Washington Commanders",
            "kind": "moneyline",
            "number": "",
            "side_label": "Philadelphia Eagles",
            "pay": "no",
            "entry": Decimal("0.6500"),
            "opened_at": "2026-10-29T12:00:00-04:00",
            "lock_pair": True,
        },
    }
    bundle = jsp.build_rows(snap, intent=intent, quotes={}, fetch_quotes=False)
    rows = bundle["rows"]
    sports = {str(r.get("sport") or "") for r in rows}
    letters = {str(r.get("letter") or "") for r in rows}
    types = {str(r.get("open_type") or "") for r in rows}
    games = " | ".join(str(r.get("game") or "") for r in rows)
    assert "tennis" not in sports, sports
    assert sports == {"pro football"}, sports
    assert letters == {"A"}, letters
    assert types == {"A lock gap"}, types
    assert "Philadelphia Eagles vs Washington Commanders" in games
    assert "tennis" not in games.lower()
    open_rows = dash.open_from_positions(bundle)
    table = dash.open_table_rows(open_rows)
    joined = " | ".join(" | ".join(map(str, row)) for row in table)
    assert "A lock gap" in joined
    assert "B T0" not in joined
    assert "B Tennis" not in joined
    assert "tennis" not in joined.lower()
    assert "pro football" in joined
    assert bundle["open_now"]["A"] >= 1
    assert bundle["open_now"]["B"] == 0


def test_poly_buy_short_cash_not_inverted():
    w.test_poly_buy_short_cash_is_house_not_yes_wire() if hasattr(w, "test_poly_buy_short_cash_is_house_not_yes_wire") else None
    # Re-run the house cash assertion from the performance tests.
    from test_write_orders_performance import test_poly_buy_short_cash_is_house_not_yes_wire

    test_poly_buy_short_cash_is_house_not_yes_wire()


def main() -> None:
    test_four_quoted_tickers()
    test_sold_yes_is_buy_no_gloss()
    test_no_eagles_names_the_ticker_not_the_opponent()
    test_garbled_yes_no_recovers_real_side()
    test_spread_sign_from_title_plus()
    test_spread_sign_from_title_win_by_over()
    test_cfb_and_tennis_untouched_path()
    test_overlay_rows_use_names_not_ticker()
    test_poly_eagles_yes_pairs_kalshi_no_as_a_lock_gap()
    test_poly_buy_short_cash_not_inverted()
    print("test_kalshi_ticker_decode ok")


if __name__ == "__main__":
    main()
