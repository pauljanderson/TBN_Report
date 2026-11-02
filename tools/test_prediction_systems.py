"""CLI parse, persist, gates, and do-not-double-spawn B. No live orders."""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers
import live_lock_orders
import prediction_job_control
import prediction_systems as ps


def test_fav_band_gates():
    assert ps.in_fav_band(Decimal("0.91")) is False
    assert ps.in_fav_band(Decimal("0.90")) is False
    assert ps.in_fav_band("0.89") is True
    assert ps.in_fav_band(Decimal("0.50")) is False
    assert ps.in_fav_band("0.51") is True
    assert ps.in_fav_band("0.50") is False


def test_contracts_for_stake():
    assert ps.contracts_for_stake(Decimal("0.72"), size=1, stake_usd=Decimal("1")) == 1
    assert ps.contracts_for_stake(Decimal("1.10"), size=1, stake_usd=Decimal("1")) == 0
    assert ps.contracts_for_stake(Decimal("0.40"), size=10, stake_usd=Decimal("1")) == 2


def test_best_venue_and_favorite():
    quotes = [
        {"venue": "gemini", "side": "LSU", "yes": Decimal("0.71")},
        {"venue": "kalshi", "side": "LSU", "yes": Decimal("0.68")},
        {"venue": "polymarket", "side": "LSU", "yes": Decimal("0.74")},
        {"venue": "kalshi", "side": "Auburn", "yes": Decimal("0.32")},
    ]
    best = ps.best_venue_yes(quotes, "LSU")
    assert best["venue"] == "kalshi"
    assert best["yes"] == Decimal("0.68")
    fav = ps.pick_favorite_primary({"LSU": Decimal("0.68"), "Auburn": Decimal("0.32")})
    assert fav == "LSU"
    assert ps.pick_favorite_primary({"LSU": Decimal("0.50"), "Auburn": Decimal("0.50")}) is None


def test_gemini_quote_only_compare_vs_send():
    """Gemini stays in compare; for_send=True never picks Gemini while soft-disabled."""
    import gemini_private

    quotes = [
        {"venue": "gemini", "side": "LSU", "yes": Decimal("0.61"), "team": "LSU"},
        {"venue": "kalshi", "side": "LSU", "yes": Decimal("0.68"), "team": "LSU"},
        {"venue": "polymarket", "side": "LSU", "yes": Decimal("0.70"), "team": "LSU"},
        {"venue": "gemini", "side": "Auburn", "yes": Decimal("0.40"), "team": "Auburn"},
        {"venue": "kalshi", "side": "Auburn", "yes": Decimal("0.33"), "team": "Auburn"},
    ]
    spreads = [
        {"venue": "gemini", "side": "LSU -3.5", "yes": Decimal("0.22"), "kind": "spread", "number": "3.5"},
        {"venue": "kalshi", "side": "LSU -3.5", "yes": Decimal("0.28"), "kind": "spread", "number": "3.5"},
        {"venue": "polymarket", "side": "LSU -7.5", "yes": Decimal("0.31"), "kind": "spread", "number": "7.5"},
    ]
    totals = [
        {"venue": "gemini", "side": "Over 2.5", "yes": Decimal("0.21"), "kind": "total", "number": "2.5"},
        {"venue": "kalshi", "side": "Over 2.5", "yes": Decimal("0.29"), "kind": "total", "number": "2.5"},
        {"venue": "polymarket", "side": "Over 2.5", "yes": Decimal("0.33"), "kind": "total", "number": "2.5"},
    ]
    saved = gemini_private.GEMINI_ORDERS_ENABLED
    gemini_private.GEMINI_ORDERS_ENABLED = False
    try:
        assert gemini_private.orders_live() is False
        assert ps.venue_sendable("gemini") is False
        assert ps.venue_sendable("kalshi") is True
        # Compare / truth still sees Gemini as cheapest.
        compare = ps.best_venue_yes(quotes, "LSU", for_send=False)
        assert compare is not None and compare["venue"] == "gemini"
        assert ps.pick_cheapest_spread_yes(spreads, for_send=False)["venue"] == "gemini"
        assert ps.pick_cheapest_total_yes(totals, for_send=False)["venue"] == "gemini"
        # Favorite truth still uses Gemini quotes across venues.
        teams = {"LSU": [Decimal("0.61"), Decimal("0.68")], "Auburn": [Decimal("0.40"), Decimal("0.33")]}
        assert ps.resolve_favorite_across_venues(teams) == "LSU"
        # Send pick falls back to non-Gemini; never requires a Gemini POST.
        send = ps.best_venue_yes(quotes, "LSU", for_send=True)
        assert send is not None and send["venue"] == "kalshi"
        assert ps.pick_cheapest_spread_yes(spreads, for_send=True)["venue"] == "kalshi"
        assert ps.pick_cheapest_total_yes(totals, for_send=True)["venue"] == "kalshi"
        only_gemini = [{"venue": "gemini", "side": "LSU", "yes": Decimal("0.61")}]
        assert ps.best_venue_yes(only_gemini, "LSU", for_send=True) is None
    finally:
        gemini_private.GEMINI_ORDERS_ENABLED = saved
    gemini_private.GEMINI_ORDERS_ENABLED = True
    try:
        assert ps.venue_sendable("gemini") is True
        assert ps.best_venue_yes(quotes, "LSU", for_send=True)["venue"] == "gemini"
    finally:
        gemini_private.GEMINI_ORDERS_ENABLED = saved


def test_venues_disagree_median_rule():
    teams = {
        "A": [Decimal("0.55"), Decimal("0.40")],
        "B": [Decimal("0.62"), Decimal("0.61")],
    }
    # Both have asks >50. B has higher median of >50 asks.
    assert ps.resolve_favorite_across_venues(teams) == "B"
    only = {"A": [Decimal("0.40")], "B": [Decimal("0.61")]}
    assert ps.resolve_favorite_across_venues(only) == "B"


def test_spread_line_closest_to_50():
    lines = [
        {"kind": "spread", "number": "7.5", "two_sided": True, "fav_ask": Decimal("0.72")},
        {"kind": "spread", "number": "3.5", "two_sided": True, "fav_ask": Decimal("0.54")},
        {"kind": "spread", "number": "14.5", "two_sided": True, "fav_ask": Decimal("0.91")},
        {"kind": "total", "number": "55.5", "two_sided": True, "fav_ask": Decimal("0.55")},
        {"kind": "spread", "number": "10.5", "two_sided": False, "fav_ask": Decimal("0.52")},
    ]
    picked = ps.pick_spread_line(lines)
    assert len(picked) == 1
    assert picked[0]["number"] == "3.5"
    stacked = ps.pick_spread_line(lines, all_lines=True)
    assert len(stacked) == 1
    assert stacked[0]["number"] == "3.5"
    none = ps.pick_spread_line([{"kind": "spread", "two_sided": True, "fav_ask": Decimal("0.50")}])
    assert none == []
    totals_only = ps.pick_spread_line([
        {"kind": "total", "number": "44.5", "two_sided": True, "fav_ask": Decimal("0.55")},
        {"kind": "team_total", "number": "24.5", "two_sided": True, "fav_ask": Decimal("0.58")},
    ])
    assert totals_only == []


def test_cli_parse_and_persist():
    folder = Path(tempfile.mkdtemp())
    path = folder / "systems.json"
    ns = ps.build_parser().parse_args([
        "--lock", "on", "--lock-max", "3", "--lock-stake", "1",
        "--tennis-crossover", "off",
        "--cfb-favorite", "on", "--cfb-favorite-max", "2", "--cfb-favorite-stake", "1",
        "--spread-t0", "on", "--d-max", "2", "--d-stake", "1",
        "--a",  # leftover? no, already used --lock
    ][:-1])
    updates = ps.flags_touched(ns)
    assert updates["lock"]["on"] is True
    assert updates["lock"]["max_open"] == 3
    assert updates["tennis_crossover"]["on"] is False
    assert updates["cfb_favorite"]["on"] is True
    assert updates["spread_t0"]["max_open"] == 2
    cfgs, notes = ps.apply_updates(updates, path=path, spawn=False)
    assert notes == []
    blob = json.loads(path.read_text(encoding="utf-8"))
    assert blob["systems"]["lock"]["max_open"] == 3
    assert blob["systems"]["tennis_crossover"]["on"] is False
    assert blob["systems"]["cfb_favorite"]["on"] is True
    loaded = ps.load_config(path)
    assert loaded["lock"].max_open == 3
    assert loaded["cfb_favorite"].stake_usd == Decimal("1")
    assert "net_max" not in blob["systems"]["lock"]
    assert loaded["lock"].net_max is None


def test_lock_net_max_cli_parse_persist_and_help():
    help_text = ps.build_parser().format_help()
    assert "--lock-net-max" in help_text
    assert "--lock-gap" in help_text
    ns = ps.build_parser().parse_args(["--lock-net-max", "0.984"])
    updates = ps.flags_touched(ns)
    assert updates["lock"]["net_max"] == Decimal("0.984")
    alias = ps.build_parser().parse_args(["--lock-gap", "0.99"])
    assert ps.flags_touched(alias)["lock"]["net_max"] == Decimal("0.99")
    three = ps.build_parser().parse_args([
        "--lock", "on", "--lock-max", "3", "--lock-stake", "1",
    ])
    assert "net_max" not in ps.flags_touched(three).get("lock", {})
    folder = Path(tempfile.mkdtemp())
    path = folder / "systems.json"
    started = []
    saved_spawn = ps._spawn_script
    ps._spawn_script = lambda sid: started.append(sid)
    try:
        _cfgs, notes = ps.apply_updates(updates, path=path, spawn=True)
    finally:
        ps._spawn_script = saved_spawn
    assert started == []
    assert any("in place" in note or "no restart" in note for note in notes)
    blob = json.loads(path.read_text(encoding="utf-8"))
    assert blob["systems"]["lock"]["net_max"] == "0.984"
    assert isinstance(blob["systems"]["lock"]["net_max"], str)
    loaded = ps.load_config(path)
    assert loaded["lock"].net_max == Decimal("0.984")
    saved = ps.CONFIG_PATH
    ps.CONFIG_PATH = path
    try:
        assert live_lock_orders.effective_net_max() == Decimal("0.984")
        assert live_lock_orders.NET_MAX == Decimal("0.984")
        rows = ps.status_rows(jobs={})
        lock_row = next(row for row in rows if row["letter"] == "A")
        assert "cap 0.984" in lock_row["name"]
    finally:
        ps.CONFIG_PATH = saved


def test_a_b_c_d_aliases():
    ns = ps.build_parser().parse_args(["--b", "off", "--c", "on", "--d", "on", "--a", "on"])
    updates = ps.flags_touched(ns)
    assert updates["tennis_crossover"]["on"] is False
    assert updates["cfb_favorite"]["on"] is True
    assert updates["spread_t0"]["on"] is True
    assert updates["lock"]["on"] is True


def test_e_aliases_and_default_off():
    ns = ps.build_parser().parse_args([
        "--tennis-t0-dog", "on", "--tennis-t0-dog-max", "2", "--tennis-t0-dog-stake", "1",
    ])
    updates = ps.flags_touched(ns)
    assert updates["tennis_t0_dog"]["on"] is True
    assert updates["tennis_t0_dog"]["max_open"] == 2
    assert updates["tennis_t0_dog"]["stake_usd"] == Decimal("1")
    short = ps.build_parser().parse_args(["--e", "off"])
    assert ps.flags_touched(short)["tennis_t0_dog"]["on"] is False
    folder = Path(tempfile.mkdtemp())
    path = folder / "systems.json"
    cfgs, notes = ps.apply_updates({}, path=path, spawn=False)
    assert notes == []
    empty = ps.empty_config()
    assert empty["tennis_t0_dog"].on is False
    loaded = ps.load_config(path)
    assert loaded["tennis_t0_dog"].on is False
    assert loaded["tennis_t0_dog"].max_open == 2


def test_f_cli_and_spread_band():
    assert ps.in_f_spread_band(Decimal("0.19")) is False
    assert ps.in_f_spread_band(Decimal("0.20")) is True
    assert ps.in_f_spread_band("0.49") is True
    assert ps.in_f_spread_band(Decimal("0.50")) is False
    quotes = [
        {"venue": "kalshi", "side": "A -1.5", "yes": Decimal("0.41"), "kind": "spread", "number": "1.5"},
        {"venue": "polymarket", "side": "A -2.5", "yes": Decimal("0.28"), "kind": "spread", "number": "2.5"},
        {"venue": "kalshi", "side": "Underdog", "yes": Decimal("0.22"), "kind": "moneyline", "number": ""},
    ]
    best = ps.pick_cheapest_spread_yes(quotes)
    assert best["number"] == "2.5"
    assert best["yes"] == Decimal("0.28")
    ns = ps.build_parser().parse_args([
        "--tennis-t0-spread", "on", "--tennis-t0-spread-max", "2", "--tennis-t0-spread-stake", "1",
    ])
    updates = ps.flags_touched(ns)
    assert updates["tennis_t0_spread"]["on"] is True
    assert updates["tennis_t0_spread"]["max_open"] == 2
    assert updates["tennis_t0_spread"]["stake_usd"] == Decimal("1")
    folder = Path(tempfile.mkdtemp())
    path = folder / "systems.json"
    cfgs, notes = ps.apply_updates(updates, path=path, spawn=False)
    assert notes == []
    assert cfgs["tennis_t0_spread"].on is True
    assert cfgs["tennis_t0_spread"].max_open == 2
    assert cfgs["tennis_t0_spread"].size == 1
    empty = ps.empty_config()
    assert empty["tennis_t0_spread"].on is False
    assert ps.LETTER["tennis_t0_spread"] == "F"
    assert ps.SCRIPTS["tennis_t0_spread"].name == "live_tennis_t0_spread.py"
    loaded = ps.load_config(path)
    assert loaded["tennis_t0_spread"].on is True
    off = ps.build_parser().parse_args(["--tennis-t0-spread", "off"])
    assert ps.flags_touched(off)["tennis_t0_spread"]["on"] is False


def test_g_cli_and_total_band():
    assert ps.in_g_total_band(Decimal("0.19")) is False
    assert ps.in_g_total_band(Decimal("0.20")) is True
    assert ps.in_g_total_band("0.49") is True
    assert ps.in_g_total_band(Decimal("0.50")) is False
    quotes = [
        {"venue": "kalshi", "side": "Over 2.5", "yes": Decimal("0.41"), "kind": "total", "number": "2.5"},
        {"venue": "polymarket", "side": "Over 2.5", "yes": Decimal("0.28"), "kind": "total", "number": "2.5"},
        {"venue": "kalshi", "side": "Arsenal", "yes": Decimal("0.22"), "kind": "moneyline", "number": ""},
        {"venue": "novig", "side": "Over 2.5", "yes": Decimal("0.21"), "kind": "total", "number": "2.5"},
    ]
    best = ps.pick_cheapest_total_yes(quotes)
    assert best["yes"] == Decimal("0.28")
    assert best["venue"] == "polymarket"
    ns = ps.build_parser().parse_args([
        "--soccer-t0-total", "on", "--soccer-t0-total-max", "2", "--soccer-t0-total-stake", "1",
    ])
    updates = ps.flags_touched(ns)
    assert updates["soccer_t0_total"]["on"] is True
    assert updates["soccer_t0_total"]["max_open"] == 2
    assert updates["soccer_t0_total"]["stake_usd"] == Decimal("1")
    folder = Path(tempfile.mkdtemp())
    path = folder / "systems.json"
    cfgs, notes = ps.apply_updates(updates, path=path, spawn=False)
    assert notes == []
    assert cfgs["soccer_t0_total"].on is True
    assert cfgs["soccer_t0_total"].max_open == 2
    assert cfgs["soccer_t0_total"].size == 1
    empty = ps.empty_config()
    assert empty["soccer_t0_total"].on is False
    assert ps.LETTER["soccer_t0_total"] == "G"
    assert ps.SCRIPTS["soccer_t0_total"].name == "live_soccer_t0_total.py"
    loaded = ps.load_config(path)
    assert loaded["soccer_t0_total"].on is True
    off = ps.build_parser().parse_args(["--soccer-t0-total", "off"])
    assert ps.flags_touched(off)["soccer_t0_total"]["on"] is False
    short = ps.build_parser().parse_args(["--g", "off"])
    assert ps.flags_touched(short)["soccer_t0_total"]["on"] is False


def test_e_cli_and_dog_band():
    assert ps.in_dog_band(Decimal("0.10")) is False
    assert ps.in_dog_band(Decimal("0.11")) is True
    assert ps.in_dog_band("0.49") is True
    assert ps.in_dog_band(Decimal("0.50")) is False
    assert ps.in_dog_band("0.09") is False
    dog = ps.pick_dog_primary({"Alcaraz": Decimal("0.72"), "Sinner": Decimal("0.28")})
    assert dog == "Sinner"
    assert ps.pick_dog_primary({"A": Decimal("0.50"), "B": Decimal("0.50")}) is None
    ns = ps.build_parser().parse_args([
        "--tennis-t0-dog", "on", "--tennis-t0-dog-max", "2", "--tennis-t0-dog-stake", "1",
    ])
    updates = ps.flags_touched(ns)
    assert updates["tennis_t0_dog"]["on"] is True
    assert updates["tennis_t0_dog"]["max_open"] == 2
    assert updates["tennis_t0_dog"]["stake_usd"] == Decimal("1")
    ns2 = ps.build_parser().parse_args(["--e", "on", "--e-max", "2", "--e-stake", "1"])
    assert ps.flags_touched(ns2)["tennis_t0_dog"]["on"] is True
    folder = Path(tempfile.mkdtemp())
    path = folder / "systems.json"
    cfgs, notes = ps.apply_updates(updates, path=path, spawn=False)
    assert notes == []
    assert cfgs["tennis_t0_dog"].on is True
    assert cfgs["tennis_t0_dog"].max_open == 2
    assert cfgs["tennis_t0_dog"].size == 1
    assert ps.LETTER["tennis_t0_dog"] == "E"
    assert ps.SCRIPTS["tennis_t0_dog"].name == "live_tennis_t0_dog.py"


def test_e_skips_when_b_holds_match():
    import live_tennis_t0_dog

    held = {"matches": [{"game": "Alcaraz vs Sinner", "stage": "waiting_cross"}]}
    assert live_tennis_t0_dog.b_holds_match("Alcaraz vs Sinner", sport="tennis", b_status=held) is True
    assert live_tennis_t0_dog.b_holds_match("Other Match", sport="tennis", b_status=held) is False
    assert live_tennis_t0_dog.b_holds_match("Alcaraz vs Sinner", sport="college football", b_status=held) is False
    skip_c = {
        "matches": [{
            "game": "Alcaraz vs Sinner",
            "stage": "skipped",
            "skip_reason": "t0_allin_c_over_105",
        }]
    }
    assert live_tennis_t0_dog.b_holds_match("Alcaraz vs Sinner", sport="tennis", b_status=skip_c) is False


def test_dog_line_snapshot_band():
    import live_t0_yes

    rows = [
        {"venue": "kalshi", "side": "Fav", "yes": Decimal("0.72"), "kind": "moneyline", "number": "",
         "spec": {"venue": "kalshi", "instrument": "KX-FAV"}},
        {"venue": "kalshi", "side": "Dog", "yes": Decimal("0.28"), "kind": "moneyline", "number": "",
         "spec": {"venue": "kalshi", "instrument": "KX-DOG"}},
    ]
    snap = live_t0_yes.dog_line_snapshot(rows)
    assert snap is not None
    assert snap["dog"] == "Dog"
    assert snap["fav_ask"] == Decimal("0.28")
    assert snap["best"]["venue"] == "kalshi"
    cheap = [
        {"venue": "kalshi", "side": "Fav", "yes": Decimal("0.92"), "kind": "moneyline", "number": ""},
        {"venue": "kalshi", "side": "Dog", "yes": Decimal("0.08"), "kind": "moneyline", "number": ""},
    ]
    assert live_t0_yes.dog_line_snapshot(cheap) is None
    tie = [
        {"venue": "kalshi", "side": "A", "yes": Decimal("0.50"), "kind": "moneyline", "number": ""},
        {"venue": "kalshi", "side": "B", "yes": Decimal("0.50"), "kind": "moneyline", "number": ""},
    ]
    assert live_t0_yes.dog_line_snapshot(tie) is None


def test_do_not_double_spawn_b():
    jobs = {
        "strategy_b": [{"pid": 4242, "started": "2026-10-24 12:00:00", "cmd": "python live_strategy_b.py"}],
        "cfb_favorite": [],
        "spread_t0": [],
        "tennis_t0_dog": [],
        "supervisor": [],
        "scan": [],
        "children": [],
    }
    started = []

    def fake_spawn(sid: str) -> None:
        started.append(sid)

    saved = ps._spawn_script
    ps._spawn_script = fake_spawn
    try:
        note = ps.apply_process(
            "tennis_crossover",
            ps.SystemCfg("tennis_crossover", True, 2, Decimal("1"), 1),
            jobs=jobs,
        )
    finally:
        ps._spawn_script = saved
    assert started == []
    assert "4242" in note
    assert "second" in note.lower() or "alive" in note.lower()


def test_ensure_system_skips_when_b_alive():
    jobs = {
        "strategy_b": [{"pid": 99, "cmd": "python live_strategy_b.py"}],
        "cfb_favorite": [],
        "spread_t0": [],
        "tennis_t0_dog": [],
        "supervisor": [],
        "scan": [],
        "children": [],
    }
    started = []
    saved = ps._spawn_script
    saved_on = ps.is_on
    ps._spawn_script = lambda sid: started.append(sid)
    ps.is_on = lambda sid, path=None: True
    try:
        assert ps.ensure_system("tennis_crossover", jobs) is False
        assert started == []
    finally:
        ps._spawn_script = saved
        ps.is_on = saved_on


def test_expand_sibling_tickers_adds_spread_keeps_ml():
    k, g = live_game_pollers.expand_sibling_tickers(
        ["KXNCAAFGAME-26OCT24LSUAUB"],
        ["NCAAF-2610241930-LSU-AUB-M"],
        "college football",
    )
    assert "KXNCAAFGAME-26OCT24LSUAUB" in k
    assert any("SPREAD" in t for t in k)
    assert any("TOTAL" in t and "TEAMTOTAL" not in t for t in k)
    assert any("TEAMTOTAL" in t for t in k)
    assert any(t.endswith("-S") for t in g)
    assert any(t.endswith("-M") for t in g)
    assert any(t.endswith("-T") and not t.endswith("-TT") for t in g)
    assert any(t.endswith("-TT") for t in g)
    k_tt, g_tt = live_game_pollers.expand_sibling_tickers(
        ["KXNFLTEAMTOTAL-26OCT25KCLV"],
        ["NFL-2610251700-KC-LV-TT"],
        "pro football",
    )
    assert "KXNFLGAME-26OCT25KCLV" in k_tt
    assert "KXNFLSPREAD-26OCT25KCLV" in k_tt
    assert "KXNFLTOTAL-26OCT25KCLV" in k_tt
    assert all("TEAMGAME" not in t and "TEAMSPREAD" not in t for t in k_tt)
    assert any(t.endswith("-M") for t in g_tt)
    k2, g2 = live_game_pollers.expand_sibling_tickers(
        ["KXATPMATCH-26OCT24ABC"],
        [],
        "tennis",
    )
    assert k2[0] == "KXATPMATCH-26OCT24ABC"
    assert "KXATPMATCH-26OCT24ABC" in k2
    assert "KXATPGSPREAD-26OCT24ABC" in k2
    assert "KXATPSSPREAD-26OCT24ABC" in k2
    assert "KXATPGAMESPREAD-26OCT24ABC" in k2
    assert not any("TOTAL" in t and "SPREAD" not in t for t in k2)
    assert g2 == []
    k3, g3 = live_game_pollers.expand_sibling_tickers(
        ["KXATPGSPREAD-26OCT30PAUALC"],
        ["ATP-2610301200-PAU-ALC-M"],
        "tennis",
    )
    assert "KXATPGSPREAD-26OCT30PAUALC" in k3
    assert "KXATPMATCH-26OCT30PAUALC" in k3
    assert "ATP-2610301200-PAU-ALC-M" in g3
    assert "ATP-2610301200-PAU-ALC-S" in g3
    assert not any(t.endswith("-T") for t in g3)


def test_d_all_lines_flag_is_not_stored():
    ns = ps.build_parser().parse_args(["--d-all-lines", "--d", "on"])
    updates = ps.flags_touched(ns)
    assert "all_lines" not in updates.get("spread_t0", {})
    assert updates["spread_t0"]["on"] is True


def test_market_type_team_total_before_total():
    from price_memory import market_type_from, norm_side

    assert market_type_from("KXNFLTEAMTOTAL-26OCT25KCLV-KC25") == "team_total"
    assert market_type_from("KXNFLTOTAL-26OCT25KCLV-45") == "total"
    assert market_type_from("KXNFLSPREAD-26OCT25KCLV-KC4") == "spread"
    assert market_type_from("KXATPGSPREAD-26OCT30PAUALC") == "spread"
    assert market_type_from("KXATPSSPREAD-26OCT30PAUALC") == "spread"
    assert market_type_from("KXATPMATCH-26OCT30PAUALC") == "moneyline"
    assert market_type_from("KXNFLGAME-26OCT25KCLV") == "moneyline"
    assert market_type_from("NFL-2610251700-KC-LV-TT") == "team_total"
    assert market_type_from("NFL-2610251700-KC-LV-T") == "total"
    assert market_type_from("NFL-2610251700-KC-LV-S") == "spread"
    assert market_type_from("NFL-2610251700-KC-LV-M") == "moneyline"
    assert norm_side("Chicago over 24.5 points", "team_total") == "chicago over"
    assert norm_side("Over 44.5", "total") == "over"


def test_lock_skips_open_cd():
    folder = Path(tempfile.mkdtemp())
    path = folder / "cfb_favorite_watch.json"
    path.write_text(
        json.dumps({"matches": [{"game": "LSU vs Auburn", "stage": "filled"}]}),
        encoding="utf-8",
    )
    saved = live_lock_orders.CFB_FAVORITE_STATE
    live_lock_orders.CFB_FAVORITE_STATE = path
    try:
        assert live_lock_orders.directional_blocks_lock("college football", "LSU vs Auburn") is True
        assert live_lock_orders.directional_blocks_lock("college football", "Other Game") is False
    finally:
        live_lock_orders.CFB_FAVORITE_STATE = saved


def test_send_blocked_cd_ignores_latch():
    assert live_lock_orders._send_blocked({"_system": "cfb_favorite"}) == ""
    assert live_lock_orders._send_blocked({"_system": "spread_t0"}) == ""
    assert live_lock_orders._send_blocked({"_system": "tennis_t0_dog"}) == ""
    assert live_lock_orders._send_blocked({"_system": "soccer_t0_total"}) == ""


def test_one_leg_turns_off_lock_a_only():
    folder = Path(tempfile.mkdtemp())
    path = folder / "systems.json"
    stop = folder / "orders_stopped.json"
    saved = (ps.CONFIG_PATH, live_lock_orders.ORDERS_STOP, live_lock_orders.ORDERS_ENABLED)
    ps.CONFIG_PATH = path
    live_lock_orders.ORDERS_STOP = stop
    live_lock_orders.ORDERS_ENABLED = True
    ps.apply_updates({sid: {"on": True} for sid in ps.SYSTEM_IDS}, path=path, spawn=False)
    try:
        live_lock_orders.stop_orders(
            "one leg filled and the other missed",
            {"venue": "gemini"},
            {"venue": "kalshi"},
        )
        loaded = ps.load_config(path)
        assert loaded["lock"].on is False
        for sid in ("tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog"):
            assert loaded[sid].on is True, sid
        assert stop.is_file()
        blob = json.loads(stop.read_text(encoding="utf-8"))
        assert blob.get("scope") == "lock"
        assert blob.get("letter") == "A"
        assert live_lock_orders._send_blocked({"_strategy_b": True}) == ""
        assert live_lock_orders._send_blocked({"_system": "cfb_favorite"}) == ""
        assert live_lock_orders._send_blocked({"_system": "spread_t0"}) == ""
        assert live_lock_orders._send_blocked({"_system": "tennis_t0_dog"}) == ""
        assert live_lock_orders._send_blocked({"_watch_recovery": True, "venue": "kalshi"}) == ""
        assert live_lock_orders._send_blocked({"venue": "kalshi"}) == "lock gap is off"
        ps.apply_updates({"lock": {"on": True}}, path=path, spawn=True)
        loaded = ps.load_config(path)
        assert loaded["lock"].on is True
        for sid in ("tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog"):
            assert loaded[sid].on is True, sid
        assert not stop.exists()
        assert live_lock_orders._send_blocked({"venue": "kalshi"}) == ""
    finally:
        ps.CONFIG_PATH, live_lock_orders.ORDERS_STOP, live_lock_orders.ORDERS_ENABLED = saved


def test_lock_currently_open_is_plain_count():
    saved = live_lock_orders.open_lock_keys
    live_lock_orders.open_lock_keys = lambda *a, **k: []
    try:
        text = ps.currently_open("lock")
    finally:
        live_lock_orders.open_lock_keys = saved
    assert text == "0"
    assert "/" not in text
    assert ps.open_now_display("0 / 3") == "0"
    assert ps.open_now_display("0/3") == "0"
    assert ps.open_now_display(2) == "2"
    assert live_lock_orders.MAX_OPEN_LOCKS == 3


def test_job_control_systems_help():
    src = Path(prediction_job_control.__file__).read_text(encoding="utf-8")
    assert "systems" in src
    assert "live_cfb_favorite.py" in src
    assert "live_tennis_t0_dog.py" in src
    assert "live_tennis_t0_spread.py" in src
    assert "live_soccer_t0_total.py" in src
    assert "--tennis-t0-spread" in Path(ps.__file__).read_text(encoding="utf-8")
    assert "--soccer-t0-total" in Path(ps.__file__).read_text(encoding="utf-8")
    assert "Tennis crossover" in src
    ensure_src = Path(prediction_job_control.__file__).read_text(encoding="utf-8")
    assert "if jobs.get(\"strategy_b\")" in ensure_src


if __name__ == "__main__":
    test_fav_band_gates()
    test_contracts_for_stake()
    test_best_venue_and_favorite()
    test_gemini_quote_only_compare_vs_send()
    test_venues_disagree_median_rule()
    test_spread_line_closest_to_50()
    test_cli_parse_and_persist()
    test_lock_net_max_cli_parse_persist_and_help()
    test_a_b_c_d_aliases()
    test_e_aliases_and_default_off()
    test_e_cli_and_dog_band()
    test_f_cli_and_spread_band()
    test_g_cli_and_total_band()
    test_e_skips_when_b_holds_match()
    test_dog_line_snapshot_band()
    test_do_not_double_spawn_b()
    test_ensure_system_skips_when_b_alive()
    test_expand_sibling_tickers_adds_spread_keeps_ml()
    test_d_all_lines_flag_is_not_stored()
    test_market_type_team_total_before_total()
    test_lock_skips_open_cd()
    test_send_blocked_cd_ignores_latch()
    test_one_leg_turns_off_lock_a_only()
    test_lock_currently_open_is_plain_count()
    test_job_control_systems_help()
    print("ok")
