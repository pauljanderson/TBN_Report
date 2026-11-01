"""Tests for Kalshi+Poly combined T0 both-named-Yes pairing. No live orders."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import _write_kalshi_poly_combined_t0_both_sides_20261030 as w
import _write_kalshi_poly_combined_t0_decile_20261030 as comb
from test_kalshi_poly_combined_t0_decile_20261030 import _side


FORBIDDEN = ("Research candidate", "Not gold", "Not DailyRun")


def test_complement_map():
    assert w.COMPLEMENT["0-9"] == "90-99"
    assert w.COMPLEMENT["90-99"] == "0-9"
    assert w.COMPLEMENT["40-49"] == "50-59"


def test_cheaper_yes_drops_favorite_both_keeps():
    a = _side("kalshi", "tennis", "moneyline", "m1", "Dog", 0.08, won=False)
    b = _side("kalshi", "tennis", "moneyline", "m1", "Fav", 0.92, won=True)
    sides, _ = comb.attach_event_keys([a, b])
    cheap = comb.pick_cheaper_yes(sides)
    both = comb.pick_named_yes(sides)
    assert len(cheap) == 1
    assert abs(cheap[0]["t0_fav"] - 0.08) < 1e-12
    assert len(both) == 2
    bands = {w.decile_w.decile_of(s["t0_fav"]) for s in both}
    assert bands == {"0-9", "90-99"}
    cheap_bands = {w.decile_w.decile_of(s["t0_fav"]) for s in cheap}
    assert cheap_bands == {"0-9"}


def test_pairing_complement_hit():
    a = _side("kalshi", "tennis", "moneyline", "m1", "Dog", 0.08, won=False)
    b = _side("kalshi", "tennis", "moneyline", "m1", "Fav", 0.92, won=True)
    sides, _ = comb.attach_event_keys([a, b])
    recs = w.pair_records(sides)
    assert len(recs) == 1
    assert recs[0]["lo_band"] == "0-9"
    assert recs[0]["hi_band"] == "90-99"
    assert recs[0]["complement_hit"] is True
    assert abs(recs[0]["px_sum"] - 1.00) < 1e-9
    summ = w.pairing_summary(recs, sides, "tennis", "moneyline")
    assert summ["n_09"] == 1
    assert summ["n_9099"] == 1
    assert summ["gap"] == 0
    assert summ["n_09_with_9099"] == 1


def test_yes_yes_not_one_lands_adjacent():
    a = _side("kalshi", "tennis", "moneyline", "m2", "Dog", 0.08, won=False)
    b = _side("polymarket", "tennis", "moneyline", "m2", "Fav", 0.85, won=True)
    sides, _ = comb.attach_event_keys([a, b])
    recs = w.pair_records(sides)
    assert len(recs) == 1
    assert recs[0]["lo_band"] == "0-9"
    assert recs[0]["hi_band"] == "80-89"
    assert recs[0]["complement_hit"] is False
    summ = w.pairing_summary(recs, sides, "tennis", "moneyline")
    assert summ["n_09"] == 1
    assert summ["n_9099"] == 0
    assert summ["n_09_with_8089"] == 1
    assert summ["gap"] == 1
    assert "80–89" in summ["why"] or "80-89" in summ["why"]


def test_unpaired_dog_and_favorite_only():
    dog = _side("kalshi", "college football", "moneyline", "g1", "Alabama", 0.07, won=False)
    fav = _side("kalshi", "college football", "moneyline", "g2", "Georgia", 0.93, won=True)
    sides, _ = comb.attach_event_keys([dog, fav])
    recs = w.pair_records(sides)
    assert len(recs) == 2
    summ = w.pairing_summary(recs, sides, "college football", "moneyline")
    assert summ["n_09"] == 1
    assert summ["n_9099"] == 1
    assert summ["n_09_unpaired"] == 1
    assert summ["n_9099_unpaired"] == 1
    cheap = comb.pick_cheaper_yes(sides)
    assert len(cheap) == 1
    assert abs(cheap[0]["t0_fav"] - 0.07) < 1e-12


def test_complement_rows_gap():
    a = _side("kalshi", "pro football", "moneyline", "n1", "Dog", 0.05, won=False)
    b = _side("kalshi", "pro football", "moneyline", "n1", "Fav", 0.91, won=True)
    c = _side("kalshi", "pro football", "moneyline", "n2", "OtherDog", 0.08, won=False)
    sides, _ = comb.attach_event_keys([a, b, c])
    rows = w.complement_rows(sides, "pro football", "moneyline")
    by_low = {r[0]: r for r in rows}
    assert by_low["0-9"][1] == "2"
    assert by_low["0-9"][3] == "1"
    assert by_low["0-9"][4] == "1"


def test_html_has_asked_and_forbids_phrases():
    payload = {
        "cheap_tables": {"cells": {}, "all_decile": [], "sport_decile": [], "detail": [], "overall": [], "grand": {"n": 0}},
        "both_tables": {"cells": {}, "all_decile": [], "sport_decile": [], "detail": [], "overall": [], "grand": {"n": 0}},
        "arms": {},
        "cfb": {"n_09": 1285, "n_9099": 504, "gap": 781, "cheap_n_09": 1282, "cheap_n_9099": 0, "why": "test why"},
        "pairing_rows": [],
        "cfb_comp_rows": [["0-9", "1285", "90-99", "504", "781"]],
        "cfb_ml_both_rows": [],
        "ml_comp_html": "",
        "side_all_rows": [],
        "side_cfb_rows": [],
        "hidden_rows": [],
        "hidden_blurb": "Cheaper-Yes hid the favorite half of the ticket.",
    }
    path = w.write_html(payload, now="2026-10-30 12:00:00 ET")
    html = Path(path).read_text(encoding="utf-8")
    assert "What you asked" in html
    assert "In plain English" in html
    assert "1,282" in html or "1282" in html
    assert "90-99" in html
    assert 'name="viewport"' in html
    assert "class=\"sortable\"" in html
    assert "Swipe sideways" in html
    assert "HOLD" in html
    assert "Do not pick a band" in html
    assert "last trade" in html.lower() or "last-trade" in html.lower()
    assert "Yes ask" in html
    assert "System F was not started" in html or "Did not start System F" in html
    for phrase in FORBIDDEN:
        assert phrase not in html, phrase
    assert "Did not rewrite dashboard.html" in html


if __name__ == "__main__":
    test_complement_map()
    test_cheaper_yes_drops_favorite_both_keeps()
    test_pairing_complement_hit()
    test_yes_yes_not_one_lands_adjacent()
    test_unpaired_dog_and_favorite_only()
    test_complement_rows_gap()
    test_html_has_asked_and_forbids_phrases()
    print("ok")
