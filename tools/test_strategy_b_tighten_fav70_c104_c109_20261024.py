"""T0 gate + tiny Strategy B path with fees. No orders. No live B process."""
from __future__ import annotations

from decimal import Decimal

from strategy_b_tighten_fav70_c104_c109_20261024 import (
    ARM_C104,
    ARM_C109,
    ARM_CONTROL,
    ARM_FAV70,
    ARM_FAV70_C104,
    ARM_FAV70_C109,
    documented_taker_fee,
    simulate_b_on_book,
    t0_send_ok,
)
from write_t0_band_from_stay_above import documented_leg_fee


def test_fav_072_skipped_on_combined_and_fav70():
    assert t0_send_ok(0.72, 0.32, ARM_CONTROL)[0] is True
    assert t0_send_ok(0.72, 0.32, ARM_FAV70_C104)[0] is False
    assert t0_send_ok(0.72, 0.32, ARM_FAV70_C109)[0] is False
    assert t0_send_ok(0.72, 0.32, ARM_FAV70)[0] is False
    assert t0_send_ok(0.72, 0.32, ARM_C104)[0] is True  # C=1.04, any favorite


def test_fav_065_c103_sent_on_104_arm():
    ok, why = t0_send_ok(0.65, 0.38, ARM_FAV70_C104)
    assert ok is True, why
    assert t0_send_ok(0.65, 0.38, ARM_FAV70_C109)[0] is True
    assert t0_send_ok(0.65, 0.38, ARM_CONTROL)[0] is True


def test_c105_skipped_on_104_sent_on_109():
    assert t0_send_ok(0.65, 0.40, ARM_FAV70_C104)[0] is False
    assert t0_send_ok(0.65, 0.40, ARM_C104)[0] is False
    assert t0_send_ok(0.65, 0.40, ARM_FAV70_C109)[0] is True
    assert t0_send_ok(0.65, 0.40, ARM_C109)[0] is True
    assert t0_send_ok(0.65, 0.40, ARM_CONTROL)[0] is True


def test_c110_skipped_on_both_combined():
    assert t0_send_ok(0.65, 0.45, ARM_FAV70_C104)[0] is False
    assert t0_send_ok(0.65, 0.45, ARM_FAV70_C109)[0] is False
    assert t0_send_ok(0.65, 0.45, ARM_C104)[0] is False
    assert t0_send_ok(0.65, 0.45, ARM_C109)[0] is False
    assert t0_send_ok(0.65, 0.45, ARM_FAV70)[0] is True  # C=1.10, C_HI still 1.20
    assert t0_send_ok(0.65, 0.45, ARM_CONTROL)[0] is True


def test_fav_070_is_not_strictly_below_70():
    assert t0_send_ok(0.70, 0.34, ARM_FAV70)[0] is False
    assert t0_send_ok(0.699, 0.34, ARM_FAV70)[0] is True


def test_yes_band_and_live_c_hi():
    assert t0_send_ok(0.10, 0.50, ARM_CONTROL)[0] is False
    assert t0_send_ok(0.90, 0.20, ARM_CONTROL)[0] is False
    assert t0_send_ok(0.89, 0.32, ARM_CONTROL)[0] is False  # C=1.21 > 1.20
    assert t0_send_ok(0.89, 0.31, ARM_CONTROL)[0] is True  # C=1.20 on the cap


def test_tiny_path_pnl_with_fees_t0_only():
    """Kalshi T0 0.55/0.48, favorite wins, no extras. Always pays $1 on the T0 pair."""
    t0 = 1_000
    book = {
        "venue": "Kalshi",
        "t0_a": 0.55,
        "t0_b": 0.48,
        "t0_ts": t0,
        "yes_a": [(t0, 0.55), (t0 + 30, 0.80)],
        "yes_b": [(t0, 0.48), (t0 + 30, 0.20)],
        "winner": "a",
        "settled": True,
        "void": False,
        "sport": "tennis",
        "game": "Fav vs Dog",
        "kind": "moneyline",
        "number": "",
    }
    rec = simulate_b_on_book(book, ARM_FAV70_C104)
    assert rec["sent"] is True
    assert rec["n_t0"] == 1
    assert rec["n_cross"] == 0
    assert rec["n_dip"] == 0
    fee_a = documented_leg_fee("kalshi", Decimal("0.55"))
    fee_b = documented_leg_fee("kalshi", Decimal("0.48"))
    assert fee_a is not None and fee_b is not None
    fees = float(fee_a) + float(fee_b)
    assert rec["fees"] == fees
    assert abs(rec["pnl_fee"] - (1.0 - 1.03 - fees)) < 1e-9
    assert rec["payout"] == 1.0
    # T0-only P&L does not depend on who won.
    book["winner"] = "b"
    rec_b = simulate_b_on_book(book, ARM_FAV70_C104)
    assert abs(rec_b["pnl_fee"] - rec["pnl_fee"]) < 1e-12


def test_tiny_path_cross_and_dip_lock():
    t0 = 2_000
    book = {
        "venue": "Kalshi",
        "t0_a": 0.58,
        "t0_b": 0.45,
        "t0_ts": t0,
        "yes_a": [(t0, 0.58), (t0 + 40, 0.24)],
        "yes_b": [(t0, 0.45), (t0 + 20, 0.51)],
        "winner": "a",
        "settled": True,
        "void": False,
        "sport": "tennis",
        "game": "Fav vs Dog",
        "kind": "moneyline",
        "number": "",
    }
    rec = simulate_b_on_book(book, ARM_CONTROL)
    assert rec["sent"] is True
    assert rec["n_cross"] == 1
    assert rec["n_dip"] == 1
    assert abs(rec["cross_px"] - 0.51) < 1e-12
    assert abs(rec["dip_px"] - 0.24) < 1e-12
    cost = 0.58 + 0.45 + 0.51 + 0.24
    fees = sum(
        float(documented_taker_fee("kalshi", px))
        for px in (0.58, 0.45, 0.51, 0.24)
    )
    assert rec["payout"] == 2.0
    assert abs(rec["pnl_fee"] - (2.0 - cost - fees)) < 1e-9


def test_rewind_false_favorite_cross():
    """Dog already >50 at T0 is not an instant cross (Trungelliti)."""
    t0 = 3_000
    book = {
        "venue": "Gemini",
        "t0_a": 0.58,
        "t0_b": 0.52,
        "t0_ts": t0,
        "yes_a": [(t0, 0.58), (t0 + 10, 0.57), (t0 + 40, 0.23)],
        "yes_b": [(t0, 0.52), (t0 + 10, 0.56), (t0 + 20, 0.49), (t0 + 30, 0.53)],
        "winner": "a",
        "settled": True,
        "void": False,
        "sport": "tennis",
        "game": "Rewind",
        "kind": "moneyline",
        "number": "",
    }
    rec = simulate_b_on_book(book, ARM_CONTROL)
    assert rec["sent"] is True
    assert rec["n_cross"] == 1
    assert rec["cross_ts"] == t0 + 30
    assert abs(rec["cross_px"] - 0.53) < 1e-12
    # 0.56 right after T0 is not a cross; wait for 0.49 then 0.53.


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ok")
