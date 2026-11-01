"""Unit tests for hist sell-at-gain page. No network. No orders."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import _write_t0_buy_sell_gain_hist_20261030 as w


def test_why_callout_names_5425_combo_and_live_60():
    html = w.why_callout({
        "combo_5425": "tennis ALL Moneyline 90-99",
        "n_target": 40000,
        "n_target_5425": 40549,
        "n_usable": 0,
        "n_usable_5425": 0,
        "n_usable_tennis": 0,
        "running": True,
        "pid": 123,
        "cmd": "python -u tools/_pull_kalshi_inplay_path_20261030.py",
    })
    assert "5,425" in html or "5425" in html
    assert "tennis" in html.lower()
    assert "90-99" in html or "90–99" in html
    assert "60" in html
    assert "not yet a full hist gain study" in html.lower() or "not yet a full" in html
    assert "Research candidate" not in html
    assert "Not gold" not in html
    assert "Not DailyRun" not in html
    assert "last-trade" in html.lower()
    assert "not ask" in html.lower() or "not an ask" in html.lower()


def test_hist_compact_keeps_inplay_ticks():
    t0 = 1_700_000_000
    book = {
        "ticker": "KXATPMATCH-X-A",
        "sport": "tennis",
        "league": "ATP",
        "kind": "moneyline",
        "t0_a": 0.42,
        "t0_fav": 0.42,
        "t0_ts": t0,
        "end_ts": t0 + 3600,
        "fav_won": True,
        "venue": "kalshi",
        "game": "m1",
        "game_n": "m1",
        "fav_name": "Dog",
        "void": False,
    }
    path = {
        "path": [
            [t0 - 60, 0.40],
            [t0, 0.42],
            [t0 + 60, 0.48],
            [t0 + 120, 0.55],
            [t0 + 180, 0.51],
            [t0 + 240, 0.60],
            [t0 + 300, 0.58],
        ]
    }
    row = w.hist_compact(book, path)
    assert row is not None
    assert row["decile"] == "40-49"
    assert row["venue"] == "kalshi"
    assert len(row["ticks"]) == 5
    assert row["ticks"][0] == (t0 + 60, 0.48)
    fill = w.live_w.first_gain_fill(0.42, t0, row["ticks"], 0.52)
    assert fill is not None
    assert abs(fill["fill_px"] - 0.52) < 1e-12 or abs(fill["fill_px"] - 0.55) < 1e-12


def test_asked_quotes_paul():
    assert "did NOT do a full analysis" in w.ASKED
    assert "5425" in w.ASKED
    assert "60" in w.ASKED


def main() -> int:
    test_why_callout_names_5425_combo_and_live_60()
    test_hist_compact_keeps_inplay_ticks()
    test_asked_quotes_paul()
    print("test_t0_buy_sell_gain_hist_20261030 ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
