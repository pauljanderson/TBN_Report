"""Spread two-Yes is not a lock candidate.

Does not place orders. Does not start live_strategy_b.py. Does not print secrets.
Does not sell. Does not overwrite the sibling all-tracked HTML.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"))

import overnight_scan as ov
from _write_spread_two_yes_not_a_lock_20261025 import YES_AB_GLOSSARY

STAMP = (
    ROOT / "drive" / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
    / "spread_two_yes_not_a_lock_20261025.html"
)
TYPES = STAMP.with_name("nfl_t0_by_spread_type_20261025.html")
ALL_TRACKED_GEN = ROOT / "tools" / "nfl_t0_spread_buckets_all_tracked_20261025.py"
TYPES_GEN = ROOT / "tools" / "nfl_t0_by_spread_type_20261025.py"


def _view(side: str, code: str, yes: str, no: str, ident: str) -> dict:
    return {
        "kind": "spread",
        "side": side,
        "number": "1.5",
        "code": code,
        "yes": Decimal(yes),
        "no": Decimal(no),
        "yes_size": Decimal("10"),
        "no_size": Decimal("10"),
        "label": f"{side} wins by more than 1.5 points",
        "ident": ident,
        "status": "open",
        "no_flipped_yes_bid": False,
        "no_reject": "",
        "sell_yes": None,
        "yes_bid": None,
        "buy_no": Decimal(no),
    }


def test_pair_contracts_does_not_send_both_spread_yeses():
    """Arizona Yes 0.41 + LA Yes 0.50 must not become a lock candidate."""
    kalshi = [
        _view("Arizona", "ARI", "0.41", "0.62", "KXNFLSPREAD-ARI1"),
        _view("Los Angeles R", "LAR", "0.50", "0.55", "KXNFLSPREAD-LAR1"),
    ]
    gemini = [
        _view("Arizona", "ARI", "0.41", "0.62", "GEMI-S-ARI1"),
        _view("Los Angeles R", "LAR", "0.50", "0.55", "GEMI-S-LAR1"),
    ]
    amap = {"ARI": "ARI", "LAR": "LAR"}
    cands = ov.pair_contracts(kalshi, gemini, amap)
    assert cands, "same-side Yes+No pairs should still exist"
    grosses = [ov.d(c.get("gross")) for c in cands]
    # Tempting two-Yes sum. A real lock on ARI would be 0.41+0.62=1.03.
    assert Decimal("0.91") not in grosses
    sides = {str(c.get("side_key") or "") for c in cands}
    assert any("ARI" in s or "arizona" in s.lower() for s in sides)
    assert any("LAR" in s or "los angeles" in s.lower() for s in sides)
    for cand in cands:
        assert cand.get("yes_venue") in {"kalshi", "gemini"}
        assert cand.get("no_venue") in {"kalshi", "gemini"}
        assert cand.get("yes_venue") != cand.get("no_venue")
        yes_px = ov.d(cand.get("yes_price"))
        no_px = ov.d(cand.get("no_price"))
        # Never Yes 0.41 paired with the other team's 0.50 Yes-as-if-No.
        if yes_px == Decimal("0.41"):
            assert no_px != Decimal("0.50")
        if yes_px == Decimal("0.50"):
            assert no_px != Decimal("0.41")


def test_glossary_and_stamp_exist():
    assert "not Yes plus No of one contract" in YES_AB_GLOSSARY
    gen = ALL_TRACKED_GEN.read_text(encoding="utf-8")
    assert "Glossary — T0 Yes A / T0 Yes B" in gen
    types_gen = TYPES_GEN.read_text(encoding="utf-8")
    assert "T0 Yes A" not in types_gen
    assert "T0 Yes B" not in types_gen
    if TYPES.is_file():
        types_html = TYPES.read_text(encoding="utf-8")
        assert "T0 Yes A" not in types_html
    assert STAMP.is_file(), STAMP
    html = STAMP.read_text(encoding="utf-8")
    assert "What you asked" in html
    assert "In plain English" in html
    assert "not a lock" in html.lower()
    assert "0.41" in html
    assert "sortable" in html
    assert "Swipe sideways" in html


if __name__ == "__main__":
    test_pair_contracts_does_not_send_both_spread_yeses()
    test_glossary_and_stamp_exist()
    print("ok")
