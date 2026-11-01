"""Synthetic 3 C + 1 D Kalshi tickets render 4 rows and a footer sum.

Unknown venue tickets still appear. Ledger-only rows are not invented.
Does not place orders. Does not print secrets.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import job_status_positions as jsp
import open_count_sync as ocs
import prediction_job_control
import prediction_systems as ps


def _snap(tickers: list[tuple[str, str, str, str]]) -> dict:
    """(ticker, qty, exposure, fees) Kalshi rows."""
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    snap["pulled_at"] = "2026-10-24T20:06:00-04:00"
    by = {}
    rows = []
    for ticker, qty, exposure, fees in tickers:
        row = {
            "venue": "kalshi",
            "ticker": ticker,
            "title": ticker,
            "side": "yes",
            "qty": qty,
            "exposure": exposure,
            "fees": fees,
        }
        rows.append(row)
        by[ticker] = row
    snap["kalshi"] = rows
    snap["kalshi_by_ticker"] = by
    return snap


C_D = [
    ("KXNCAAFGAME-26OCT24BSUWSU-BSU", "1", "0.8600", "0.0085"),
    ("KXNCAAFGAME-26OCT24SDSUCSU-CSU", "1", "0.5100", "0.0175"),
    ("KXNCAAFGAME-26OCT24GASTARST-GAST", "1", "0.5600", "0.0173"),
    ("KXNCAAFSPREAD-26OCT24MISSTEX-TEX3", "1", "0.5700", "0.0172"),
]

INTENT = {
    ("kalshi", "KXNCAAFGAME-26OCT24BSUWSU-BSU"): {
        "sid": "cfb_favorite",
        "letter": "C",
        "name": "College football favorite",
        "sport": "college football",
        "game": "BSU vs WSU",
        "kind": "moneyline",
        "number": "",
        "side_label": "Boise St.",
        "pay": "yes",
        "entry": Decimal("0.8600"),
        "opened_at": "2026-10-24T17:59:50-04:00",
    },
    ("kalshi", "KXNCAAFGAME-26OCT24SDSUCSU-CSU"): {
        "sid": "cfb_favorite",
        "letter": "C",
        "name": "College football favorite",
        "sport": "college football",
        "game": "CSU vs SDSU",
        "kind": "moneyline",
        "number": "",
        "side_label": "Colorado St.",
        "pay": "yes",
        "entry": Decimal("0.5100"),
        "opened_at": "2026-10-24T18:31:21-04:00",
    },
    ("kalshi", "KXNCAAFGAME-26OCT24GASTARST-GAST"): {
        "sid": "cfb_favorite",
        "letter": "C",
        "name": "College football favorite",
        "sport": "college football",
        "game": "ARST vs GAST",
        "kind": "moneyline",
        "number": "",
        "side_label": "Georgia St.",
        "pay": "yes",
        "entry": Decimal("0.5600"),
        "opened_at": "2026-10-24T19:02:17-04:00",
    },
    ("kalshi", "KXNCAAFSPREAD-26OCT24MISSTEX-TEX3"): {
        "sid": "spread_t0",
        "letter": "D",
        "name": "T0 spreads",
        "sport": "college football",
        "game": "MISS vs TEX",
        "kind": "spread",
        "number": "2.5",
        "side_label": "Texas",
        "pay": "yes",
        "entry": Decimal("0.5700"),
        "opened_at": "2026-10-24T19:32:02-04:00",
    },
}

QUOTES = {
    ("kalshi", "KXNCAAFGAME-26OCT24BSUWSU-BSU"): {"mark": Decimal("0.9000"), "src": "rest-mid", "kind": "mid"},
    ("kalshi", "KXNCAAFGAME-26OCT24SDSUCSU-CSU"): {"mark": Decimal("0.4800"), "src": "rest-mid", "kind": "mid"},
    ("kalshi", "KXNCAAFGAME-26OCT24GASTARST-GAST"): {"mark": Decimal("0.6100"), "src": "rest-mid", "kind": "mid"},
    ("kalshi", "KXNCAAFSPREAD-26OCT24MISSTEX-TEX3"): {"mark": Decimal("0.5900"), "src": "rest-mid", "kind": "mid"},
}


def test_three_c_one_d_four_rows_and_footer_sum():
    snap = _snap(C_D)
    bundle = jsp.build_rows(snap, intent=INTENT, quotes=QUOTES, fetch_quotes=False)
    rows = bundle["rows"]
    assert len(rows) == 4, [r.get("game") for r in rows]
    letters = sorted(r["letter"] for r in rows)
    assert letters == ["C", "C", "C", "D"], letters
    games = {r["game"] for r in rows}
    assert games == {
        "Boise State vs Washington State",
        "San Diego State vs Colorado State",
        "Georgia State vs Arkansas State",
        "Ole Miss vs Texas",
    }, games
    assert all(r.get("pnl") is not None for r in rows)
    footer = bundle["footer"]
    assert footer["n"] == 4
    total = sum((r["pnl"] for r in rows), Decimal("0"))
    assert footer["pnl"] == total
    # BSU: 0.90 - (0.86+0.0085) = 0.0315
    # SDSU: 0.48 - (0.51+0.0175) = -0.0475
    # GAST: 0.61 - (0.56+0.0173) = 0.0327
    # TEX:  0.59 - (0.57+0.0172) = 0.0028
    # sum = 0.0195
    assert total == Decimal("0.0195"), total
    html = jsp.render_table(bundle)
    assert html.count("<h2>Positions</h2>") == 1
    assert 'class="total-row"' in html
    assert "$0.0195" in html
    assert "4 rows" in html
    assert "Yes Boise State" in html or "Yes Boise St." in html
    assert "spread 2.5" in html or "spread" in html
    assert "ML" in html or "moneyline" in html
    assert html.count("<script>") == 0


def test_unknown_venue_ticket_still_appears():
    snap = _snap(C_D + [("KXATPMATCH-26OCT24STRANGER-ABC", "1", "0.4000", "0.0100")])
    bundle = jsp.build_rows(snap, intent=INTENT, quotes=QUOTES, fetch_quotes=False)
    rows = bundle["rows"]
    assert len(rows) == 5, [r.get("letter") for r in rows]
    unknown = [r for r in rows if r["letter"] == "unknown"]
    assert len(unknown) == 1, unknown
    assert "STRANGER" in unknown[0]["ticker"] or "STRANGER" in unknown[0]["game"]
    html = jsp.render_table(bundle)
    assert ">unknown</td>" in html
    assert "5 rows" in html
    # unknown has no quote → excluded from sum, 4 priced
    assert bundle["footer"]["priced"] == 4
    assert bundle["footer"]["skipped"] == 1
    assert "excluded from the Open P&L sum" in " ".join(bundle["warnings"])


def test_ledger_only_is_not_a_row():
    snap = _snap(C_D[:1])
    extra_intent = dict(INTENT)
    extra_intent[("kalshi", "KXNCAAFGAME-26OCT24UNTNAVY-UNT")] = {
        "sid": "cfb_favorite",
        "letter": "C",
        "name": "College football favorite",
        "sport": "college football",
        "game": "NAVY vs UNT",
        "kind": "moneyline",
        "side_label": "North Texas",
        "pay": "yes",
        "entry": Decimal("0.6000"),
        "opened_at": "2026-10-24T15:32:12-04:00",
    }
    bundle = jsp.build_rows(snap, intent=extra_intent, quotes=QUOTES, fetch_quotes=False)
    games = {r["game"] for r in bundle["rows"]}
    assert "NAVY vs UNT" not in games
    assert len(bundle["rows"]) == 1


def test_lock_both_legs_one_row():
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    snap["kalshi"] = [
        {"venue": "kalshi", "ticker": "KXATPMATCH-26OCT24AAAAAA-AAA", "qty": "1", "side": "yes", "exposure": "0.40", "fees": "0.01"},
        {"venue": "kalshi", "ticker": "KXATPMATCH-26OCT24AAAAAA-BBB", "qty": "1", "side": "yes", "exposure": "0.55", "fees": "0.01"},
    ]
    intent = {
        ("kalshi", "KXATPMATCH-26OCT24AAAAAA-AAA"): {
            "sid": "lock",
            "letter": "A",
            "name": "Lock gap",
            "sport": "tennis",
            "game": "Aaa vs Bbb",
            "kind": "moneyline",
            "side_label": "Aaa",
            "pay": "yes",
            "entry": Decimal("0.40"),
            "opened_at": "2026-10-24T12:00:00-04:00",
            "lock_pair": True,
        },
        ("kalshi", "KXATPMATCH-26OCT24AAAAAA-BBB"): {
            "sid": "lock",
            "letter": "A",
            "name": "Lock gap",
            "sport": "tennis",
            "game": "Aaa vs Bbb",
            "kind": "moneyline",
            "side_label": "Bbb",
            "pay": "yes",
            "entry": Decimal("0.55"),
            "opened_at": "2026-10-24T12:00:00-04:00",
            "lock_pair": True,
        },
    }
    quotes = {
        ("kalshi", "KXATPMATCH-26OCT24AAAAAA-AAA"): {"mark": Decimal("0.42"), "kind": "mid", "src": "rest-mid"},
        ("kalshi", "KXATPMATCH-26OCT24AAAAAA-BBB"): {"mark": Decimal("0.53"), "kind": "mid", "src": "rest-mid"},
    }
    bundle = jsp.build_rows(snap, intent=intent, quotes=quotes, fetch_quotes=False)
    assert len(bundle["rows"]) == 1, [r.get("bets") for r in bundle["rows"]]
    bets = bundle["rows"][0]["bets"]
    assert "Yes Aaa" in bets and "Yes Bbb" in bets
    # (0.42-0.41) + (0.53-0.56) = 0.01 - 0.03 = -0.02
    assert bundle["rows"][0]["pnl"] == Decimal("-0.02")


def test_write_page_positions_under_systems_one_sort_script():
    folder = Path(__import__("tempfile").mkdtemp())
    saved = prediction_job_control.STATUS_PAGE
    prediction_job_control.STATUS_PAGE = folder / "job_status.html"
    snap = {
        "supervisor": None,
        "scan": None,
        "children": [],
        "intended": [],
        "poller_compare": [],
        "consoles": {},
        "strategy_b": None,
        "strategy_b_extra": [],
        "strategy_b_log": "",
        "strategy_b_state": {},
        "systems": [
            {
                "letter": "A",
                "name": "Lock gap",
                "on": "on",
                "stake": "1",
                "size": "1",
                "max_open": "3",
                "open": "0",
                "pid": "1",
                "last": "-",
            }
        ],
        "latch_on": False,
        "latch_text": "not set",
        "watch_text": "no file",
        "send_line": "0.97",
        "lock_open": "0",
        "last_skip_text": "none",
        "filled_legs": [],
        "supervisor_log": "",
        "scan_log": "",
        "deadline_text": "bats start/stop",
        "checked": "2026-10-24 20:30:00 ET",
        "positions": jsp.build_rows(_snap(C_D), intent=INTENT, quotes=QUOTES, fetch_quotes=False),
    }
    try:
        prediction_job_control.write_page(snap)
        page = prediction_job_control.STATUS_PAGE.read_text(encoding="utf-8")
    finally:
        prediction_job_control.STATUS_PAGE = saved
    sys_at = page.index("<h2>Systems</h2>")
    pos_at = page.index("<h2>Positions</h2>")
    assert pos_at > sys_at
    assert "Open now is the count of Positions rows by system." in page
    assert page.count("function sortTable") == 1
    assert "Yes Boise State" in page or "Yes Boise St." in page
    assert "4 rows" in page
    assert 'class="total-row"' in page
    # Open now stays a count, Max stays separate.
    assert ">0</td>" in page
    assert "0 / 3" not in page.split("<h2>Positions</h2>")[0]


B_KARIM = {
    "key": "tennis_abdoguidot_2026_10_25",
    "game": "Karim vs Guidotti",
    "sport": "tennis",
    "stage": "waiting_cross",
    "venue": "polymarket",
    "instrument": "aec-itfme-karabd-margui-2026-10-25",
    "last_order": {
        "id": "oid-karim",
        "fill_qty": "1",
        "http": 200,
        "time": "2026-10-24T20:03:24-04:00",
    },
    "t0_yes": {
        "a": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket"},
        "b": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket"},
    },
}

B_NAMIGATA = {
    "key": "tennis_namigayoshim_2026_10_24",
    "game": "Junri Namigata vs. Natsuki Yoshimoto",
    "sport": "tennis",
    "stage": "one_leg_miss",
    "venue": "polymarket",
    "instrument": "aec-utr-namjun-yosnat-2026-10-24",
    "last_order": {
        "id": "oid-nami",
        "fill_qty": "0.32",
        "http": 200,
        "time": "2026-10-24T20:04:31-04:00",
    },
    "t0_yes": {
        "a": {
            "filled": False,
            "instrument": "aec-utr-namjun-yosnat-2026-10-24",
            "venue": "polymarket",
            "fill_qty": "0.32",
        },
        "b": {
            "filled": False,
            "flattened": True,
            "instrument": "aec-utr-namjun-yosnat-2026-10-24",
            "venue": "polymarket",
        },
    },
}


def _empty_poly_snap() -> dict:
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    snap["pulled_at"] = "2026-10-24T20:37:00-04:00"
    return snap


def test_b_confirm_empty_poly_one_positions_row_open_now_b_1():
    """B confirm + empty Poly positions → 1 Positions row and Open now B=1."""
    snap = _empty_poly_snap()
    watches = {"tennis_crossover": {"matches": [B_KARIM]}}
    bundle = jsp.build_rows(snap, watches=watches, fetch_quotes=False)
    assert len(bundle["rows"]) == 1, [r.get("game") for r in bundle["rows"]]
    row = bundle["rows"][0]
    assert row["letter"] == "B", row
    assert "Karim" in str(row.get("game") or "") or "Guidotti" in str(row.get("game") or "")
    assert row.get("qty_text") in {"1", "1.0", "1.00"}
    assert bundle["open_now"]["B"] == 1
    assert bundle["open_now"]["A"] == 0
    assert ps.currently_open("tennis_crossover", snapshot=snap, positions=bundle) == "1"
    html = jsp.render_table(bundle)
    assert "Open now is the count of Positions rows by system." in html
    assert ">B</td>" in html
    assert "Tennis crossover" in html


def test_b_ledger_filled_empty_poly_is_positions_row():
    """Empty Poly GET, house-open B, ledger FILLED confirm_qty 1 still lists."""
    snap = _empty_poly_snap()
    live = dict(B_KARIM)
    live["last_order"] = {"id": "oid-karim", "fill_qty": "0", "http": 200, "time": "2026-10-24T20:03:24-04:00"}
    tape = {
        "by_id": {
            "oid-karim": {
                "venue": "polymarket",
                "instrument": "aec-itfme-karabd-margui-2026-10-25",
                "side": "yes",
                "system": "tennis_crossover",
                "confirm_qty": "1",
                "confirm_known": True,
                "order_id": "oid-karim",
            }
        },
        "by_key": {},
    }
    watches = {"tennis_crossover": {"matches": [live]}}
    bundle = jsp.build_rows(snap, watches=watches, tape=tape, fetch_quotes=False)
    assert len(bundle["rows"]) == 1, [r.get("game") for r in bundle["rows"]]
    assert bundle["rows"][0]["letter"] == "B"
    assert bundle["open_now"]["B"] == 1


def test_b_partial_032_empty_poly_displays_qty():
    snap = _empty_poly_snap()
    watches = {"tennis_crossover": {"matches": [B_NAMIGATA]}}
    bundle = jsp.build_rows(snap, watches=watches, fetch_quotes=False)
    assert len(bundle["rows"]) == 1
    assert bundle["rows"][0]["letter"] == "B"
    assert "0.32" in str(bundle["rows"][0].get("qty_text") or "")
    assert bundle["open_now"]["B"] == 1


def test_settled_poly_ledger_filled_empty_get_zero_positions_namigata_stays():
    """Settled Karim is 0 rows. Namigata stays if still OPEN (qty 0.32)."""
    snap = _empty_poly_snap()
    snap["poly_markets"] = {
        "aec-itfme-karabd-margui-2026-10-25": {
            "venue": "polymarket",
            "state": "MARKET_STATE_EXPIRED",
            "expired": True,
            "settlementPx": "1.00",
        },
        "aec-utr-namjun-yosnat-2026-10-24": {
            "venue": "polymarket",
            "state": "MARKET_STATE_OPEN",
            "expired": False,
        },
    }
    snap["poly"] = [
        {
            "venue": "polymarket",
            "ticker": "aec-utr-namjun-yosnat-2026-10-24",
            "qty": "0.3200",
            "title": "Junri Namigata vs. Natsuki Yoshimoto",
            "side": "yes",
        }
    ]
    snap["poly_by_slug"] = {snap["poly"][0]["ticker"]: snap["poly"][0]}
    tape = {
        "by_id": {
            "oid-karim": {
                "venue": "polymarket",
                "instrument": "aec-itfme-karabd-margui-2026-10-25",
                "side": "yes",
                "system": "tennis_crossover",
                "confirm_qty": "1",
                "confirm_known": True,
                "order_id": "oid-karim",
            }
        },
        "by_key": {},
    }
    watches = {"tennis_crossover": {"matches": [B_KARIM, B_NAMIGATA]}}
    bundle = jsp.build_rows(snap, watches=watches, tape=tape, fetch_quotes=False)
    games = [str(r.get("game") or "") for r in bundle["rows"]]
    assert not any("Karim" in g or "Guidotti" in g for g in games), games
    assert any("Namigata" in g for g in games), games
    assert bundle["open_now"]["B"] == 1
    assert len(bundle["rows"]) == 1


def test_open_now_counts_match_positions_letters():
    snap = _snap(C_D)
    watches = {"tennis_crossover": {"matches": [B_KARIM]}}
    bundle = jsp.build_rows(snap, intent=INTENT, quotes=QUOTES, watches=watches, fetch_quotes=False)
    letters = [r["letter"] for r in bundle["rows"]]
    assert letters.count("B") == 1
    assert letters.count("C") == 3
    assert letters.count("D") == 1
    assert len(bundle["rows"]) == 5
    counts = jsp.open_now_from_rows(bundle["rows"])
    assert counts == {"A": 0, "B": 1, "C": 3, "D": 1, "E": 0}
    assert counts == bundle["open_now"]
    for sid, letter in (("lock", "A"), ("tennis_crossover", "B"), ("cfb_favorite", "C"), ("spread_t0", "D")):
        assert ps.currently_open(sid, snapshot=snap, positions=bundle) == str(counts[letter])


if __name__ == "__main__":
    test_three_c_one_d_four_rows_and_footer_sum()
    test_unknown_venue_ticket_still_appears()
    test_ledger_only_is_not_a_row()
    test_lock_both_legs_one_row()
    test_write_page_positions_under_systems_one_sort_script()
    test_b_confirm_empty_poly_one_positions_row_open_now_b_1()
    test_b_ledger_filled_empty_poly_is_positions_row()
    test_b_partial_032_empty_poly_displays_qty()
    test_settled_poly_ledger_filled_empty_get_zero_positions_namigata_stays()
    test_open_now_counts_match_positions_letters()
    print("ok")

