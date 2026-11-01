"""Hist T0 pull helpers. No network. No secrets."""
from decimal import Decimal

import _pull_pm_hist_t0_20261028 as pull


def test_yes_ask_close_dollars_and_close():
    t0 = 1_700_000_000
    candles = [
        {"end_period_ts": t0 - 60, "yes_ask": {"close_dollars": "0.42", "close": "42"}},
        {"end_period_ts": t0 - 120, "yes_ask": {"close": "0.31"}},
        {"end_period_ts": t0 + 60, "yes_ask": {"close_dollars": "0.99"}},
    ]
    px, ts = pull.yes_ask_from_candles(candles, t0)
    assert px == 0.42
    assert ts == t0 - 60


def test_yes_ask_raw_number_and_decimal():
    t0 = 1_700_000_000
    candles = [
        {"end_period_ts": t0 - 30, "yes_ask": Decimal("0.55")},
        {"end_period_ts": t0 - 90, "yes_ask": 0.22},
    ]
    px, ts = pull.yes_ask_from_candles(candles, t0)
    assert px == 0.55
    assert ts == t0 - 30


def test_yes_ask_empty_series_is_none():
    px, ts = pull.yes_ask_from_candles([], 1_700_000_000)
    assert px is None and ts is None
    px, ts = pull.yes_ask_from_candles([{"end_period_ts": "nope", "yes_ask": {"close": "0.4"}}], 1)
    assert px is None


def test_classify_skips_props_keeps_challenger():
    assert pull.classify_series({"ticker": "KXNFLGAME1Q", "tags": ["Football"], "title": "Q1"}) is None
    got = pull.classify_series({"ticker": "KXATPCHALLENGERMATCH", "tags": ["Tennis"], "title": "Challenger"})
    assert got is not None
    assert got["kind"] == "moneyline"
    assert got["sport"] == "tennis"
    assert "KXATPCHALLENGERMATCH" in pull.PRIORITY_TICKER


def test_occurrence_clock_not_listed_midnight():
    mkt = {
        "result": "yes",
        "occurrence_datetime": "2026-10-01T23:00:00Z",
        "expected_expiration_time": "2026-10-02T00:00:00Z",
        "ticker": "KX-A",
        "yes_sub_title": "A",
    }
    ts = pull.parse_ts(mkt.get("occurrence_datetime") or mkt.get("expected_expiration_time"))
    listed = pull.parse_ts(mkt.get("expected_expiration_time"))
    assert ts != listed
    side = pull.kalshi_side(
        {"sport": "tennis", "league": "ATP", "kind": "moneyline", "event_ticker": "E"},
        mkt,
        {"yes_ask": 0.61, "interval": 1, "endpoint": "historical"},
    )
    assert side is not None
    assert side["t0_ts"] == ts
    assert side["t0_label"].startswith("last yes_ask.close")
    assert "sportsbook" not in side["t0_label"].lower()


def test_poly_tape_is_last_trade_not_ask():
    import inspect
    src = inspect.getsource(pull.pull_poly_sport) + inspect.getsource(pull.build_poly_books)
    assert "CLOB last-trade" in src
    assert "not ask" in src.lower() or "not Yes ask" in src
    assert "sportsbook" not in src.lower()
    assert "poly_clob_last_trade" in src


def test_px_float_nested_close():
    assert pull._px_float(Decimal("0.7")) == 0.7
    assert pull._px_float({"close_dollars": "0.12"}) == 0.12
    assert pull._px_float(None) is None


def test_leftover_skips_only_complete_t0():
    assert pull.leftover_should_skip(None) is False
    assert pull.leftover_should_skip({"candles_fetched": True, "n_t0": 0, "n_missing": 44}) is False
    assert pull.leftover_should_skip({"candles_fetched": True, "n_t0": 14567, "n_missing": 17413}) is False
    assert pull.leftover_should_skip({"candles_fetched": True, "n_t0": 90, "n_missing": 0}) is True
    assert pull.leftover_should_skip({"candles_fetched": False, "n_t0": 10, "n_missing": 0}) is False


def test_leftover_metas_keeps_missing_soccer_and_itf():
    keep = [
        pull.classify_series({"ticker": "KXEPLTOTAL", "tags": ["Soccer"], "title": "EPL total"}),
        pull.classify_series({"ticker": "KXITFMATCH", "tags": ["Tennis"], "title": "ITF"}),
        pull.classify_series({"ticker": "KXPRESCUPMATCH", "tags": ["Golf"], "title": "Presidents Cup"}),
    ]
    coverage = [
        {"platform": "kalshi", "series": "KXEPLTOTAL", "candles_fetched": True, "n_t0": 542, "n_missing": 505},
        {"platform": "kalshi", "series": "KXITFMATCH", "candles_fetched": True, "n_t0": 14567, "n_missing": 17413},
        {"platform": "kalshi", "series": "KXPRESCUPMATCH", "candles_fetched": True, "n_t0": 90, "n_missing": 0},
    ]
    got = pull.leftover_metas(keep, coverage)
    tickers = [r["ticker"] for r in got]
    assert "KXEPLTOTAL" in tickers
    assert "KXITFMATCH" in tickers
    assert "KXPRESCUPMATCH" not in tickers
    assert tickers.index("KXEPLTOTAL") < tickers.index("KXITFMATCH")


def test_poly_date_windows_cover_spring_2026():
    windows = pull.poly_date_windows()
    assert ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z") in windows
    assert windows[0][0].startswith("2024-01")
    assert windows[-1][0].startswith("2026-11")


def test_poly_hole_keys_include_itf_and_ncaab():
    assert "itf" in pull.POLY_HOLE_KEYS
    assert "ncaab" in pull.POLY_HOLE_KEYS
    assert "lal" in pull.POLY_HOLE_KEYS
    assert "atp" in pull.POLY_CAPPED_KEYS


def main() -> None:
    test_yes_ask_close_dollars_and_close()
    test_yes_ask_raw_number_and_decimal()
    test_yes_ask_empty_series_is_none()
    test_classify_skips_props_keeps_challenger()
    test_occurrence_clock_not_listed_midnight()
    test_poly_tape_is_last_trade_not_ask()
    test_px_float_nested_close()
    test_leftover_skips_only_complete_t0()
    test_leftover_metas_keeps_missing_soccer_and_itf()
    test_poly_date_windows_cover_spring_2026()
    test_poly_hole_keys_include_itf_and_ncaab()
    print("test_pull_pm_hist_t0_20261028 ok")


if __name__ == "__main__":
    main()
