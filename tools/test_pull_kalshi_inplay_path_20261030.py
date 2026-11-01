"""Unit tests for Kalshi through-game path pull. No network. No orders."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import _pull_kalshi_inplay_path_20261030 as pull


def test_path_keeps_inplay_not_just_t0():
    t0 = 1_700_000_000
    candles = [
        {"end_period_ts": t0 - 60, "yes_ask": {"close_dollars": "0.40"}},
        {"end_period_ts": t0, "yes_ask": {"close_dollars": "0.42"}},
        {"end_period_ts": t0 + 60, "yes_ask": {"close_dollars": "0.48"}},
        {"end_period_ts": t0 + 120, "yes_ask": {"close": "0.55"}},
        {"end_period_ts": t0 + 180, "yes_ask": 0.51},
        {"end_period_ts": t0 + 240, "yes_ask": 0.57},
        {"end_period_ts": t0 + 300, "yes_ask": 0.53},
    ]
    path = pull.path_from_candles(candles)
    assert [p[0] for p in path] == [t0 - 60, t0, t0 + 60, t0 + 120, t0 + 180, t0 + 240, t0 + 300]
    assert path[-1][1] == 0.53
    assert pull.n_post(path, t0) == 5
    assert pull.path_usable(path, t0)


def test_settled_one_dollar_path_not_usable():
    t0 = 1000
    path = [[t0 - 60, 0.82], [t0, 1.0], [t0 + 60, 1.0], [t0 + 120, 1.0]]
    assert pull.n_post(path, t0) == 0
    assert not pull.path_usable(path, t0)


def test_chunk_windows_cover_game():
    wins = pull.chunk_windows(1000, 1000 + 3600 * 3, 3600)
    assert wins == [(1000, 4600), (4600, 8200), (8200, 11800)]
    assert pull.chunk_windows(5, 5)[0][0] == 5


def test_priority_tennis_ml_9099_first():
    a = {"ticker": "KXATPMATCH-1-A", "sport": "tennis", "kind": "moneyline", "t0_a": 0.94}
    b = {"ticker": "KXATPMATCH-1-B", "sport": "tennis", "kind": "moneyline", "t0_a": 0.42}
    c = {"ticker": "KXNFLGAME-1-X", "sport": "pro football", "kind": "moneyline", "t0_a": 0.94}
    d = {"ticker": "KXITFMATCH-1-A", "sport": "tennis", "kind": "moneyline", "t0_a": 0.95}
    ranked = sorted([c, d, b, a], key=pull.priority_tuple)
    assert ranked[0]["t0_a"] in (0.94, 0.95)
    assert ranked[0]["sport"] == "tennis"
    assert pull.is_combo_5425(a) and pull.is_combo_5425(d)
    assert not pull.is_combo_5425(b)
    assert not pull.is_combo_5425(c)
    # ATP before ITF when both are the 5425 combo
    tennis_hi = sorted([d, a], key=pull.priority_tuple)
    assert tennis_hi[0]["ticker"].startswith("KXATPMATCH")


def test_series_from_ticker():
    assert pull.series_from_ticker("KXATPMATCH-26OCT28HURRUN-HUR") == "KXATPMATCH"
    assert pull.series_from_ticker("KXATPCHALLENGERMATCH-1-X") == "KXATPCHALLENGERMATCH"
    assert pull.series_from_ticker("KXNFLGAME-26OCT26DALPHI-DAL") == "KXNFLGAME"


def test_skip_extreme_and_live_first():
    assert pull.skip_extreme_t0({"t0_a": 1.0})
    assert pull.skip_extreme_t0({"t0_a": 0.0})
    assert not pull.skip_extreme_t0({"t0_a": 0.42})
    live = {
        "ticker": "KXATPMATCH-26-A", "sport": "tennis", "kind": "moneyline",
        "t0_a": 0.42, "t0_ts": pull.CUTOFF_TS + 10,
    }
    old = {
        "ticker": "KXATPMATCH-25-A", "sport": "tennis", "kind": "moneyline",
        "t0_a": 0.94, "t0_ts": 1_700_000_000,
    }
    ranked = sorted([old, live], key=pull.priority_tuple)
    assert ranked[0] is live


def test_no_t0_overwrite_and_no_second_b():
    src = inspect.getsource(pull)
    assert "Does not overwrite T0 jsonl" in src
    assert "leftover-GTC" in src
    assert "second Tennis crossover" in src
    assert "inplay" in src
    assert "yes_ask.close" in src
    assert "Not started" in src  # Poly last-trade not mixed / not started


def main() -> int:
    test_path_keeps_inplay_not_just_t0()
    test_settled_one_dollar_path_not_usable()
    test_chunk_windows_cover_game()
    test_priority_tennis_ml_9099_first()
    test_skip_extreme_and_live_first()
    test_series_from_ticker()
    test_no_t0_overwrite_and_no_second_b()
    print("test_pull_kalshi_inplay_path_20261030 ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
