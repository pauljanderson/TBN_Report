"""Unit tests for Kalshi+Poly combined T0 cheapest-ticket matching. No live orders."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import _write_kalshi_poly_combined_t0_decile_20261030 as w
from write_t0_band_from_stay_above import documented_leg_fee


def _side(venue, sport, kind, game, name, px, *, won=True, number="", ticker="", date="2025-10-08", ts=1_000_000):
    return {
        "sport": sport,
        "kind": kind,
        "game": game,
        "game_n": game,
        "fav_name": name,
        "t0_a": px,
        "t0_fav": px,
        "fav_won": won,
        "number": number,
        "ticker": ticker or game,
        "venue": venue,
        "entry_date": date,
        "t0_ts": ts,
        "end_ts": ts,
        "void": False,
        "settled": True,
        "cover_known": True,
        "off_a": "win" if won else "loss",
        "league": "ATP" if sport == "tennis" else "NFL",
    }


def test_fnum_and_decile():
    assert w.fnum(0) is None
    assert w.fnum(1) is None
    assert w.fnum(0.485) == 0.485
    assert w.decile_w.decile_of(0.49) == "40-49"
    assert w.decile_w.decile_of(0.50) == "50-59"


def test_names_equal_tennis_variants():
    assert w.names_equal("Felix Auger-Aliassime", "Auger-Aliassime")
    assert w.pid("Auger-Aliassime") == w.pid("Felix Auger-Aliassime")
    assert w.names_equal("Musetti", "Lorenzo Musetti")


def test_cheaper_tie_picks_kalshi():
    k_px, p_px = 0.40, 0.40
    k_cash = w.after_fee_cash("kalshi", k_px)
    p_cash = w.after_fee_cash("polymarket", p_px)
    assert k_cash is not None and p_cash is not None
    af, pick = w.cheaper_cmp(k_cash, p_cash, k_px, p_px)
    if abs(k_cash - p_cash) < 1e-4:
        assert af == "tie"
        assert pick == "kalshi"
    assert w.raw_cmp(0.40, 0.40) == "tie"
    assert w.raw_cmp(0.39, 0.41) == "kalshi"
    assert w.raw_cmp(0.41, 0.39) == "poly"


def test_after_fee_formulas():
    px = 0.40
    k = documented_leg_fee("kalshi", px)
    p = documented_leg_fee("polymarket", px)
    assert k is not None and p is not None
    assert abs(float(k) - 0.07 * 0.40 * 0.60) < 1e-3
    assert w.after_fee_cash("kalshi", px) == float(px) + float(k)
    assert w.after_fee_cash("novig", px) is None


def test_spread_sign_and_total_yes_id():
    assert w.signed_spread("Kansas City wins by over 2.5 points", "2.5") == -2.5
    assert w.signed_spread("Cardinals", "-1.5") == -1.5
    k = _side("kalshi", "pro football", "total", "g", "Over 59.5 points", 0.51, number="59.5")
    p = _side("polymarket", "pro football", "total", "g", "Over", 0.52, number="59.5")
    k2, _ = w.attach_event_keys([k])
    p2, _ = w.attach_event_keys([p])
    assert k2[0]["_yes_id"] == p2[0]["_yes_id"]
    assert k2[0]["_yes_id"].startswith("total|over|")


def test_match_tennis_same_settlement():
    k_a = _side("kalshi", "tennis", "moneyline", "KXATPMATCH-25OCT08AUGMUS", "Felix Auger-Aliassime", 0.48, ticker="KXATPMATCH-25OCT08AUGMUS-AUG", won=True)
    k_b = _side("kalshi", "tennis", "moneyline", "KXATPMATCH-25OCT08AUGMUS", "Lorenzo Musetti", 0.52, ticker="KXATPMATCH-25OCT08AUGMUS-MUS", won=False)
    p_a = _side("polymarket", "tennis", "moneyline", "atp-augeraliassime-vs-musetti-2025-10-08", "Auger-Aliassime", 0.485, won=True)
    p_b = _side("polymarket", "tennis", "moneyline", "atp-augeraliassime-vs-musetti-2025-10-08", "Musetti", 0.515, won=False)
    k_sides, _ = w.attach_event_keys([k_a, k_b])
    p_sides, _ = w.attach_event_keys([p_a, p_b])
    matched, leftover_k, leftover_p, stats = w.match_dual(k_sides, p_sides)
    assert stats["n_dual"] == 2
    assert leftover_k == []
    assert leftover_p == []
    selected, counts = w.select_combined(matched, leftover_k, leftover_p)
    assert counts["dual_n"] == 2
    assert counts["kalshi_cheaper_af"] + counts["poly_cheaper_af"] + counts["tie_af"] == 2


def test_winner_disagree_not_paired():
    k_a = _side("kalshi", "tennis", "moneyline", "KXATPMATCH-25OCT08AUGMUS", "Felix Auger-Aliassime", 0.48, ticker="KXATPMATCH-25OCT08AUGMUS-AUG", won=True)
    k_b = _side("kalshi", "tennis", "moneyline", "KXATPMATCH-25OCT08AUGMUS", "Lorenzo Musetti", 0.52, ticker="KXATPMATCH-25OCT08AUGMUS-MUS", won=False)
    p_a = _side("polymarket", "tennis", "moneyline", "atp-augeraliassime-vs-musetti-2025-10-08", "Auger-Aliassime", 0.485, won=False)
    p_b = _side("polymarket", "tennis", "moneyline", "atp-augeraliassime-vs-musetti-2025-10-08", "Musetti", 0.515, won=True)
    k_sides, _ = w.attach_event_keys([k_a, k_b])
    p_sides, _ = w.attach_event_keys([p_a, p_b])
    matched, leftover_k, leftover_p, stats = w.match_dual(k_sides, p_sides)
    assert stats["n_dual"] == 0
    assert stats["n_winner_disagree"] == 2
    assert len(leftover_k) == 2
    assert len(leftover_p) == 2


def test_pick_cheaper_yes_one_per_market():
    a = _side("kalshi", "tennis", "moneyline", "m1", "Dog", 0.42, won=False)
    b = _side("kalshi", "tennis", "moneyline", "m1", "Fav", 0.58, won=True)
    sides, _ = w.attach_event_keys([a, b])
    cheap = w.pick_cheaper_yes(sides)
    assert len(cheap) == 1
    assert abs(cheap[0]["t0_fav"] - 0.42) < 1e-12


if __name__ == "__main__":
    test_fnum_and_decile()
    test_names_equal_tennis_variants()
    test_cheaper_tie_picks_kalshi()
    test_after_fee_formulas()
    test_spread_sign_and_total_yes_id()
    test_match_tennis_same_settlement()
    test_winner_disagree_not_paired()
    test_pick_cheaper_yes_one_per_market()
    print("ok")
