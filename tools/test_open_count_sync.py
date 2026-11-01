"""House says 5 C open, Kalshi has 3 → page shows 3 and lists 2 phantoms.

No live orders. No secrets.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import open_count_sync as ocs
import orders_performance_refresh
import prediction_systems as ps

orders_performance_refresh.run_rebuild = lambda: ""


def _snap(tickers: list[str]) -> dict:
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    snap["pulled_at"] = "2026-10-24T20:06:00-04:00"
    by = {}
    rows = []
    codes = set()
    for ticker in tickers:
        row = {"venue": "kalshi", "ticker": ticker, "title": ticker, "side": "yes", "qty": "1"}
        rows.append(row)
        by[ticker] = row
        low = ticker.lower()
        if "bsuwsu" in low:
            codes.add("bsuwsu")
        if "sdsucsu" in low:
            codes.add("sdsucsu")
        if "gastarst" in low:
            codes.add("gastarst")
        if "misstex" in low:
            codes.add("misstex")
    snap["kalshi"] = rows
    snap["kalshi_by_ticker"] = by
    snap["kalshi_codes"] = codes
    return snap


HOUSE_C = {
    "system": "cfb_favorite",
    "currently_open": 5,
    "max_open": 5,
    "matches": [
        {
            "key": "college_football_untnavy_2026_10_24",
            "game": "NAVY vs UNT",
            "stage": "filled",
            "venue": "kalshi",
            "fav": "North Texas",
            "opened_at": "2026-10-24T15:32:11-04:00",
            "last_order": {
                "id": "navy",
                "fill_qty": "1",
                "time": "2026-10-24T15:32:12-04:00",
                "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT",
                "venue": "kalshi",
            },
            "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT",
        },
        {
            "key": "college_football_ulmtroy_2026_10_24",
            "game": "TROY vs ULM",
            "stage": "filled",
            "venue": "novig",
            "fav": "Troy",
            "opened_at": "2026-10-24T16:00:43-04:00",
            "last_order": {
                "id": "troy",
                "fill_qty": "1",
                "time": "2026-10-24T16:00:49-04:00",
                "instrument": "01a14fc3-bfe2-7d91-885e-77069c534056",
                "venue": "novig",
            },
        },
        {
            "key": "college_football_bsuwsu_2026_10_24",
            "game": "BSU vs WSU",
            "stage": "filled",
            "venue": "kalshi",
            "fav": "Boise St.",
            "opened_at": "2026-10-24T17:59:47-04:00",
            "last_order": {
                "fill_qty": "1",
                "time": "2026-10-24T17:59:50-04:00",
                "instrument": "KXNCAAFGAME-26OCT24BSUWSU-BSU",
                "venue": "kalshi",
            },
            "instrument": "KXNCAAFGAME-26OCT24BSUWSU-BSU",
        },
        {
            "key": "college_football_sdsucsu_2026_10_24",
            "game": "CSU vs SDSU",
            "stage": "filled",
            "venue": "kalshi",
            "fav": "Colorado St.",
            "opened_at": "2026-10-24T18:31:18-04:00",
            "last_order": {
                "fill_qty": "1",
                "time": "2026-10-24T18:31:21-04:00",
                "instrument": "KXNCAAFGAME-26OCT24SDSUCSU-CSU",
                "venue": "kalshi",
            },
            "instrument": "KXNCAAFGAME-26OCT24SDSUCSU-CSU",
        },
        {
            "key": "college_football_gastarst_2026_10_24",
            "game": "ARST vs GAST",
            "stage": "filled",
            "venue": "kalshi",
            "fav": "Georgia St.",
            "opened_at": "2026-10-24T19:02:15-04:00",
            "last_order": {
                "fill_qty": "1",
                "time": "2026-10-24T19:02:17-04:00",
                "instrument": "KXNCAAFGAME-26OCT24GASTARST-GAST",
                "venue": "kalshi",
            },
            "instrument": "KXNCAAFGAME-26OCT24GASTARST-GAST",
        },
    ],
}

KALSHI_3 = [
    "KXNCAAFGAME-26OCT24BSUWSU-BSU",
    "KXNCAAFGAME-26OCT24SDSUCSU-CSU",
    "KXNCAAFGAME-26OCT24GASTARST-GAST",
]


def test_house_5_kalshi_3_shows_3_and_lists_phantoms():
    snap = _snap(KALSHI_3)
    n = ocs.open_count("cfb_favorite", HOUSE_C, snapshot=snap)
    assert n == 3, n
    ghosts = ocs.phantoms("cfb_favorite", HOUSE_C, snap)
    names = {item["game"] for item in ghosts}
    assert names == {"NAVY vs UNT", "TROY vs ULM"}, names
    overlay = ocs.overlay_currently_open(HOUSE_C, "cfb_favorite", snap)
    assert overlay["currently_open"] == 3
    # currently_open() reads the live watch file; overlay on HOUSE_C is the page contract.
    assert ps.open_now_display(overlay["currently_open"]) == "3"
    assert len(ghosts) == 2


def test_unique_games_not_venues():
    status = {
        "system": "cfb_favorite",
        "matches": [
            {
                "key": "college_football_bsuwsu_2026_10_24",
                "game": "BSU vs WSU",
                "stage": "filled",
                "venue": "kalshi",
                "instrument": "KXNCAAFGAME-26OCT24BSUWSU-BSU",
                "last_order": {"fill_qty": "1", "instrument": "KXNCAAFGAME-26OCT24BSUWSU-BSU", "venue": "kalshi", "time": "2026-10-24T17:59:50-04:00"},
            },
            {
                "key": "college_football_bsuwsu_2026_10_24",
                "game": "BSU vs WSU",
                "stage": "filled",
                "venue": "gemini",
                "last_order": {"fill_qty": "1", "time": "2026-10-24T17:59:51-04:00"},
            },
        ],
    }
    snap = _snap(["KXNCAAFGAME-26OCT24BSUWSU-BSU"])
    assert ocs.open_count("cfb_favorite", status, snapshot=snap) == 1


def test_waiting_t0_without_fill_is_not_open():
    status = {
        "system": "spread_t0",
        "matches": [
            {
                "key": "college_football_misstex_2026_10_24",
                "game": "MISS vs TEX",
                "stage": "waiting_t0",
                "venue": "kalshi",
                "last_order": {"fill_qty": "0"},
            }
        ],
    }
    snap = _snap(KALSHI_3 + ["KXNCAAFSPREAD-26OCT24MISSTEX-TEX3"])
    assert ocs.open_count("spread_t0", status, snapshot=snap) == 0


def test_reconcile_drops_phantoms_does_not_invent_sell():
    snap = _snap(KALSHI_3)
    data, changed = ocs.reconcile_status("cfb_favorite", HOUSE_C, snap)
    assert data["currently_open"] == 3
    assert len(changed) == 2
    stages = {row["game"]: row["stage"] for row in data["matches"]}
    assert stages["NAVY vs UNT"] == "settled"
    assert stages["TROY vs ULM"] == "settled"
    assert stages["BSU vs WSU"] == "filled"
    for row in data["matches"]:
        assert "sell" not in str(row.get("note") or "").lower() or "did not sell" in str(row.get("note") or "").lower()


def test_open_now_display_strips_slash():
    assert ps.open_now_display("0 / 3") == "0"
    assert ps.open_now_display(3) == "3"


def test_d_does_not_inherit_c_ticker():
    """Skipped D rows must not count C's Kalshi moneyline as a D open."""
    status = {
        "system": "spread_t0",
        "matches": [
            {
                "key": "college_football_sdsucsu_2026_10_24",
                "game": "CSU vs SDSU",
                "stage": "skipped",
                "venue": "kalshi",
            },
            {
                "key": "college_football_misstex_2026_10_24",
                "game": "MISS vs TEX",
                "stage": "filled",
                "venue": "kalshi",
                "instrument": "KXNCAAFSPREAD-26OCT24MISSTEX-TEX3",
                "last_order": {
                    "fill_qty": "1",
                    "instrument": "KXNCAAFSPREAD-26OCT24MISSTEX-TEX3",
                    "venue": "kalshi",
                    "time": "2026-10-24T19:32:02-04:00",
                },
            },
        ],
    }
    snap = _snap(KALSHI_3 + ["KXNCAAFSPREAD-26OCT24MISSTEX-TEX3"])
    tape = {
        "by_id": {},
        "by_key": {
            ("cfb_favorite", "college_football_sdsucsu_2026_10_24"): {
                "venue": "kalshi",
                "instrument": "KXNCAAFGAME-26OCT24SDSUCSU-CSU",
                "system": "cfb_favorite",
            }
        },
    }
    assert ocs.open_count("spread_t0", status, snapshot=snap, tape=tape) == 1


def test_poly_empty_book_keeps_confirmed_fill():
    status = {
        "system": "tennis_crossover",
        "matches": [
            {
                "key": "tennis_abdoguidot_2026_10_25",
                "game": "Karim vs Guidotti",
                "stage": "waiting_cross",
                "venue": "polymarket",
                "instrument": "aec-itfme-karabd-margui-2026-10-25",
                "last_order": {"fill_qty": "1", "http": 200, "time": "2026-10-24T20:03:24-04:00"},
                "t0_yes": {
                    "a": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket"},
                    "b": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket"},
                },
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["poly_ok"] = True
    snap["poly"] = []
    snap["kalshi_ok"] = True
    assert ocs.open_count("tennis_crossover", status, snapshot=snap) == 1


def test_poly_empty_book_keeps_partial_032():
    """Namigata leftover: empty positions + activities 0.32 stays open."""
    status = {
        "system": "tennis_crossover",
        "matches": [
            {
                "key": "tennis_namigayoshim_2026_10_24",
                "game": "Junri Namigata vs. Natsuki Yoshimoto",
                "stage": "one_leg_miss",
                "venue": "polymarket",
                "instrument": "aec-utr-namjun-yosnat-2026-10-24",
                "last_order": {"fill_qty": "0.32", "http": 200, "time": "2026-10-24T20:04:31-04:00"},
                "t0_yes": {
                    "a": {
                        "player": "Namigata, Junri",
                        "filled": False,
                        "instrument": "aec-utr-namjun-yosnat-2026-10-24",
                        "venue": "polymarket",
                        "fill_qty": "0.32",
                    },
                    "b": {
                        "player": "Yoshimoto, Natsuki",
                        "filled": False,
                        "flattened": True,
                        "instrument": "aec-utr-namjun-yosnat-2026-10-24",
                        "venue": "polymarket",
                    },
                },
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["poly_ok"] = True
    snap["poly"] = []
    snap["kalshi_ok"] = True
    assert ocs.open_count("tennis_crossover", status, snapshot=snap) == 1
    item = ocs.classify_match("tennis_crossover", status["matches"][0], snap)
    assert item["real"] is True
    assert item["phantom"] is False
    assert "0.32" in str(item.get("qty") or "")


def test_poly_book_qty_032_is_open():
    status = {
        "system": "tennis_crossover",
        "matches": [
            {
                "key": "tennis_namigayoshim_2026_10_24",
                "game": "Junri Namigata vs. Natsuki Yoshimoto",
                "stage": "one_leg_miss",
                "venue": "polymarket",
                "instrument": "aec-utr-namjun-yosnat-2026-10-24",
                "last_order": {"fill_qty": "0.32", "http": 200},
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["poly_ok"] = True
    snap["poly"] = [
        {
            "venue": "polymarket",
            "ticker": "aec-utr-namjun-yosnat-2026-10-24",
            "qty": "0.3200",
            "title": "Junri Namigata vs. Natsuki Yoshimoto",
            "side": "Namigata, Junri",
        }
    ]
    snap["poly_by_slug"] = {snap["poly"][0]["ticker"]: snap["poly"][0]}
    snap["kalshi_ok"] = True
    assert ocs.open_count("tennis_crossover", status, snapshot=snap) == 1


def test_reconcile_restores_flattened_poly_partial():
    status = {
        "system": "tennis_crossover",
        "currently_open": 0,
        "matches": [
            {
                "key": "tennis_namigayoshim_2026_10_24",
                "game": "Junri Namigata vs. Natsuki Yoshimoto",
                "stage": "done",
                "venue": "polymarket",
                "instrument": "aec-utr-namjun-yosnat-2026-10-24",
                "phantom_cleared_at": "2026-10-24T20:18:02.017-04:00",
                "last_order": {"fill_qty": "0.32", "http": 200},
                "t0_yes": {
                    "a": {"filled": False, "instrument": "aec-utr-namjun-yosnat-2026-10-24", "venue": "polymarket"},
                    "b": {"filled": False, "flattened": True, "instrument": "aec-utr-namjun-yosnat-2026-10-24", "venue": "polymarket"},
                },
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["poly_ok"] = True
    snap["poly"] = []
    snap["kalshi_ok"] = True
    data, _changed = ocs.reconcile_status("tennis_crossover", status, snap)
    row = data["matches"][0]
    assert row["stage"] == "one_leg_miss", row["stage"]
    assert row.get("stopped") is True
    assert "phantom_cleared_at" not in row
    assert data["currently_open"] == 1


def test_settled_poly_empty_positions_ledger_filled_is_not_open():
    """Settled/expired Poly + empty GET + confirm qty 1 must not occupy Open."""
    status = {
        "system": "tennis_crossover",
        "matches": [
            {
                "key": "tennis_abdoguidot_2026_10_25",
                "game": "Karim vs Guidotti",
                "stage": "waiting_cross",
                "venue": "polymarket",
                "instrument": "aec-itfme-karabd-margui-2026-10-25",
                "last_order": {"fill_qty": "1", "http": 200, "time": "2026-10-24T20:03:24-04:00"},
                "t0_yes": {
                    "a": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket"},
                    "b": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket"},
                },
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["poly_ok"] = True
    snap["poly"] = []
    snap["kalshi_ok"] = True
    snap["poly_markets"] = {
        "aec-itfme-karabd-margui-2026-10-25": {
            "venue": "polymarket",
            "state": "MARKET_STATE_EXPIRED",
            "expired": True,
            "settlementPx": "1.00",
        }
    }
    tape = {
        "by_id": {
            "oid-karim": {
                "venue": "polymarket",
                "instrument": "aec-itfme-karabd-margui-2026-10-25",
                "confirm_qty": "1",
                "confirm_known": True,
                "system": "tennis_crossover",
            }
        },
        "by_key": {},
    }
    live = dict(status["matches"][0])
    live["last_order"] = {"id": "oid-karim", "fill_qty": "0", "http": 200, "time": "2026-10-24T20:03:24-04:00"}
    status["matches"] = [live]
    assert ocs.open_count("tennis_crossover", status, snapshot=snap, tape=tape) == 0
    item = ocs.classify_match("tennis_crossover", live, snap, tape=tape)
    assert item["real"] is False
    assert item["phantom"] is True
    data, changed = ocs.reconcile_status("tennis_crossover", status, snap, tape=tape)
    assert data["currently_open"] == 0
    assert data["matches"][0]["stage"] == "done"
    assert changed


def test_reconcile_does_not_restore_settled_poly():
    status = {
        "system": "tennis_crossover",
        "currently_open": 0,
        "matches": [
            {
                "key": "tennis_abdoguidot_2026_10_25",
                "game": "Karim vs Guidotti",
                "stage": "done",
                "venue": "polymarket",
                "instrument": "aec-itfme-karabd-margui-2026-10-25",
                "phantom_cleared_at": "2026-10-24T22:00:00-04:00",
                "last_order": {"fill_qty": "1", "http": 200, "time": "2026-10-24T20:03:24-04:00"},
                "t0_yes": {
                    "a": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket"},
                    "b": {"filled": True, "instrument": "aec-itfme-karabd-margui-2026-10-25", "venue": "polymarket"},
                },
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["poly_ok"] = True
    snap["kalshi_ok"] = True
    snap["poly_markets"] = {
        "aec-itfme-karabd-margui-2026-10-25": {"venue": "polymarket", "state": "MARKET_STATE_EXPIRED", "expired": True}
    }
    data, _changed = ocs.reconcile_status("tennis_crossover", status, snap)
    assert data["matches"][0]["stage"] == "done"
    assert data["currently_open"] == 0


def test_kalshi_closed_ticker_is_not_open():
    status = {
        "system": "cfb_favorite",
        "matches": [
            {
                "key": "college_football_untnavy_2026_10_24",
                "game": "NAVY vs UNT",
                "stage": "filled",
                "venue": "kalshi",
                "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT",
                "last_order": {
                    "fill_qty": "1",
                    "instrument": "KXNCAAFGAME-26OCT24UNTNAVY-UNT",
                    "venue": "kalshi",
                    "time": "2026-10-24T15:32:12-04:00",
                },
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    snap["kalshi_markets"] = {
        "KXNCAAFGAME-26OCT24UNTNAVY-UNT": {"venue": "kalshi", "status": "finalized", "result": "yes"}
    }
    assert ocs.open_count("cfb_favorite", status, snapshot=snap) == 0


def test_poly_qty_zero_is_phantom():
    status = {
        "system": "tennis_crossover",
        "matches": [
            {
                "key": "tennis_guajarbrain_2026_10_24",
                "game": "Alexander Guajardo vs. Lachlan Brain",
                "stage": "one_leg_miss",
                "venue": "polymarket",
                "instrument": "aec-utr-guaale-bralac-2026-10-24",
                "last_order": {"fill_qty": "0", "http": 200, "time": "2026-10-24T13:43:49-04:00"},
                "t0_yes": {
                    "b": {"filled": True, "instrument": "aec-utr-guaale-bralac-2026-10-24", "venue": "polymarket"}
                },
            }
        ],
    }
    snap = ocs.empty_snapshot()
    snap["poly_ok"] = True
    snap["kalshi_ok"] = True
    n = ocs.open_count("tennis_crossover", status, snapshot=snap)
    assert n == 0
    ghosts = ocs.phantoms("tennis_crossover", status, snap)
    assert len(ghosts) == 1


def test_lock_open_count_venues_zero_is_zero():
    import live_lock_orders

    g1 = "pro football\ttbcar\t2026-10-25\tmoneyline\tcode:TB\t\tkalshi\tgemini"
    rows = [
        {"event": "filled", "bet_key": g1, "game": "Tampa Bay vs Carolina", "venue": "kalshi", "instrument": "KX-TBCAR", "confirm_qty": "1"},
        {"event": "filled", "bet_key": g1, "game": "Tampa Bay vs Carolina", "venue": "gemini", "instrument": "GEM-TBCAR", "confirm_qty": "1"},
        {"event": "filled", "bet_key": "pro football\tnyghou\t2026-10-25\tmoneyline\tcode:NYG\t\tkalshi\tgemini", "game": "New York G vs Houston", "venue": "kalshi", "instrument": "KX-NYG", "confirm_qty": "1"},
        {"event": "filled", "bet_key": "pro football\tbufkc\t2026-10-25\tmoneyline\tcode:BUF\t\tkalshi\tgemini", "game": "Buffalo vs Kansas City", "venue": "kalshi", "instrument": "KX-BUF", "confirm_qty": "1"},
    ]
    snap = ocs.empty_snapshot()
    snap["kalshi_ok"] = True
    snap["poly_ok"] = True
    saved_orders = live_lock_orders._read_orders
    saved_watches = live_lock_orders.load_all_watches
    live_lock_orders._read_orders = lambda: rows
    live_lock_orders.load_all_watches = lambda: []
    try:
        assert ocs.open_count("lock", snapshot=snap) == 0
    finally:
        live_lock_orders._read_orders = saved_orders
        live_lock_orders.load_all_watches = saved_watches


def test_poly_resolution_long_cash_one_is_yes():
    item = {
        "type": "ACTIVITY_TYPE_POSITION_RESOLUTION",
        "positionResolution": {
            "side": "POSITION_RESOLUTION_SIDE_LONG",
            "afterPosition": {"cashValue": {"value": "1", "currency": "USD"}},
        },
    }
    assert ocs.poly_resolution_result(item) == "yes"
    short = {
        "type": "ACTIVITY_TYPE_POSITION_RESOLUTION",
        "positionResolution": {
            "side": "POSITION_RESOLUTION_SIDE_SHORT",
            "afterPosition": {"cashValue": {"value": "1", "currency": "USD"}},
        },
    }
    assert ocs.poly_resolution_result(short) == "no"
    long_zero = {
        "positionResolution": {
            "side": "POSITION_RESOLUTION_SIDE_LONG",
            "afterPosition": {"cashValue": {"value": "0"}},
        }
    }
    assert ocs.poly_resolution_result(long_zero) == "no"
    short_zero = {
        "positionResolution": {
            "side": "POSITION_RESOLUTION_SIDE_SHORT",
            "afterPosition": {"cashValue": {"value": "0"}},
        }
    }
    assert ocs.poly_resolution_result(short_zero) == "yes"
    # beforePosition=1 is contract size, not the Yes-token redeem (Pohle inversion).
    size_only = {
        "positionResolution": {
            "side": "POSITION_RESOLUTION_SIDE_SHORT",
            "beforePosition": {"cashValue": {"value": "1", "currency": "USD"}},
        }
    }
    assert ocs.poly_resolution_result(size_only) == ""


def test_poly_payload_fields_settlement_px():
    fields = ocs._poly_payload_fields({
        "state": "resolved",
        "settlementPx": "0",
        "closed": True,
    })
    assert fields["result"] == "no"
    assert fields["expired"] is True
    book_only = ocs._poly_payload_fields({"marketData": {"marketState": "open"}})
    assert book_only["result"] == ""
    assert book_only["state"] == "open"
    mid = ocs._poly_payload_fields({
        "state": "MARKET_STATE_CLOSED",
        "settlementPx": {"value": "0.6700", "currency": "USD"},
        "result": "no",
    })
    assert mid["result"] == ""
    assert str(mid.get("settlementPx") or "").startswith("0.67")


if __name__ == "__main__":
    test_house_5_kalshi_3_shows_3_and_lists_phantoms()
    test_unique_games_not_venues()
    test_waiting_t0_without_fill_is_not_open()
    test_reconcile_drops_phantoms_does_not_invent_sell()
    test_open_now_display_strips_slash()
    test_d_does_not_inherit_c_ticker()
    test_poly_empty_book_keeps_confirmed_fill()
    test_poly_empty_book_keeps_partial_032()
    test_poly_book_qty_032_is_open()
    test_reconcile_restores_flattened_poly_partial()
    test_settled_poly_empty_positions_ledger_filled_is_not_open()
    test_reconcile_does_not_restore_settled_poly()
    test_kalshi_closed_ticker_is_not_open()
    test_poly_qty_zero_is_phantom()
    test_lock_open_count_venues_zero_is_zero()
    test_poly_payload_fields_settlement_px()
    test_poly_resolution_long_cash_one_is_yes()
    print("ok")
