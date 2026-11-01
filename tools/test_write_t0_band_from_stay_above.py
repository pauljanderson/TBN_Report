"""Synthetic-path tests for T0 stay-above-50 band tables. No orders. No tape scan."""
from __future__ import annotations

from decimal import Decimal

from write_t0_band_from_stay_above import (
    all_in_c,
    documented_leg_fee,
    favorite_yes_bucket,
    pair_has_trusted_t0,
    rate_cell,
    score_pair,
    stay_above_50,
    summarize_c_buckets,
    summarize_fav_buckets,
    wire_c_bucket,
)


def test_stay_above_never_prints_50_or_lower():
    t0 = 1_000
    ticks = [(t0, 0.72), (t0 + 10, 0.71), (t0 + 20, 0.80), (t0 + 30, 0.95)]
    assert stay_above_50(ticks, t0) is True


def test_stay_above_fails_on_print_at_50():
    t0 = 1_000
    ticks = [(t0, 0.61), (t0 + 5, 0.50), (t0 + 40, 0.88)]
    assert stay_above_50(ticks, t0) is False


def test_stay_above_fails_on_print_below_50():
    t0 = 1_000
    ticks = [(t0, 0.68), (t0 + 8, 0.49), (t0 + 90, 0.91)]
    assert stay_above_50(ticks, t0) is False


def test_t0_print_itself_is_not_a_fail():
    """Paul's rule is after T0. A 50-59 opener at 0.51 can still stay above."""
    t0 = 1_000
    ticks = [(t0, 0.51), (t0 + 3, 0.55), (t0 + 9, 0.70)]
    assert stay_above_50(ticks, t0) is True


def test_thin_tape_after_t0_is_not_stay_above():
    t0 = 1_000
    ticks = [(t0, 0.77)]
    assert stay_above_50(ticks, t0) is False


def test_favorite_yes_buckets():
    assert favorite_yes_bucket(0.91) == ">90"
    assert favorite_yes_bucket(0.90) == ">90"
    assert favorite_yes_bucket(0.895) == "80-89"
    assert favorite_yes_bucket(0.80) == "80-89"
    assert favorite_yes_bucket(0.70) == "70-79"
    assert favorite_yes_bucket(0.60) == "60-69"
    assert favorite_yes_bucket(0.50) == "50-59"
    assert favorite_yes_bucket(0.49) == "<50"


def test_wire_c_buckets_include_moutet_and_cap():
    assert wire_c_bucket(0.90) == "<0.95"
    assert wire_c_bucket(0.99) == "0.95-0.99"
    assert wire_c_bucket(1.01) == "1.00-1.04"
    assert wire_c_bucket(1.04) == "1.00-1.04"
    assert wire_c_bucket(1.20) == "1.15-1.20"
    assert wire_c_bucket(1.21) == ">1.20"


def test_kalshi_fees_turn_1_00_wire_over_1_all_in():
    """Two 50c Kalshi Yes: wire $1.00, documented fees push all-in over $1."""
    fee = documented_leg_fee("kalshi", Decimal("0.50"))
    assert fee is not None and fee > 0
    all_in = all_in_c("kalshi", Decimal("0.50"), Decimal("0.50"))
    assert all_in is not None
    assert all_in > Decimal("1")
    assert wire_c_bucket(float(all_in)) == "1.00-1.04"


def test_novig_all_in_unknown_without_coefficient():
    assert documented_leg_fee("novig", Decimal("0.40")) is None
    assert all_in_c("novig", Decimal("0.40"), Decimal("0.62")) is None


def test_dip_then_win_is_not_stay_above():
    """Favorite can dip under 50 and still win. Stay-above and win are different."""
    pair = {
        "t0_a": 0.72,
        "t0_b": 0.38,
        "t0_ts": 1_000,
        "yes_a": [(1_000, 0.72), (1_010, 0.48), (1_080, 0.96)],
        "yes_b": [(1_000, 0.38), (1_010, 0.52), (1_080, 0.04)],
        "side_a": "Fav",
        "side_b": "Dog",
        "winner": "a",
        "settled": True,
        "sport": "tennis",
        "game": "Fav vs Dog",
        "venue": "Kalshi",
        "market_type": "moneyline",
        "actual_source": "occurrence",
    }
    scored = score_pair(pair)
    assert scored is not None
    assert scored["stay_above"] is False
    assert scored["fav_won"] is True
    assert scored["fav_bucket"] == "70-79"
    assert scored["c_bucket"] == "1.10-1.14"


def test_last_tick_080_settle_lose_is_not_stay_above():
    pair = {
        "t0_a": 0.80,
        "t0_b": 0.28,
        "t0_ts": 1_000,
        "yes_a": [(1_000, 0.80), (1_010, 0.80)],
        "yes_b": [(1_000, 0.28), (1_010, 0.22)],
        "side_a": "Fav",
        "side_b": "Dog",
        "winner": "b",
        "settled": True,
        "sport": "college football",
        "game": "Fav vs Dog",
        "venue": "Kalshi",
        "market_type": "spread",
        "actual_source": "occurrence",
    }
    scored = score_pair(pair)
    assert scored is not None
    assert scored["stay_above"] is False
    assert scored["fav_won"] is False
    assert scored["missing_crash"] is True
    assert scored["stay_above_but_lost"] is True


def test_trusted_t0_drops_first_competitive():
    pair = {
        "t0_a": 0.60,
        "t0_b": 0.42,
        "t0_ts": 1_000,
        "actual_source": "first competitive two-sided Yes",
        "t0_label": "first competitive two-sided Yes",
    }
    assert pair_has_trusted_t0(pair) is False
    occ = dict(pair)
    occ["actual_source"] = "occurrence"
    assert pair_has_trusted_t0(occ) is True


def test_summaries_put_n_in_every_cell():
    rows = [
        {
            "fav_bucket": "70-79",
            "c_bucket": "1.00-1.04",
            "c_all_in_bucket": "1.00-1.04",
            "c_all_in": 1.03,
            "t0_fav": 0.72,
            "stay_above": True,
            "fav_won": True,
        },
        {
            "fav_bucket": "50-59",
            "c_bucket": "1.00-1.04",
            "c_all_in_bucket": "1.05-1.09",
            "c_all_in": 1.06,
            "t0_fav": 0.55,
            "stay_above": False,
            "fav_won": True,
        },
        {
            "fav_bucket": "50-59",
            "c_bucket": "1.15-1.20",
            "c_all_in": None,
            "t0_fav": 0.52,
            "stay_above": False,
            "fav_won": False,
        },
    ]
    fav = {r["bucket"]: r for r in summarize_fav_buckets(rows)}
    assert fav["70-79"]["stay_rate"] == "100.0% (1/1)"
    assert fav["50-59"]["stay_rate"] == "0.0% (0/2)"
    assert fav["All"]["stay_rate"] == "33.3% (1/3)"
    assert fav["All"]["n"] == 3
    assert rate_cell(0, 0) == "— (0)"
    cwire = {r["bucket"]: r for r in summarize_c_buckets(rows, all_in=False)}
    assert "1/2" in cwire["1.00-1.04"]["stay_rate"]
    call = {r["bucket"]: r for r in summarize_c_buckets(rows, all_in=True)}
    assert call["All"]["n"] == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ok")
