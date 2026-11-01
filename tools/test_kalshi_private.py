"""Kalshi GetBalance parse + shared 429 backoff. No live secrets. No orders."""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_private  # noqa: E402

# Today's live GET (2026-10-25): HTTP 200, these keys and types. Amounts are
# synthetic / redacted copies of the same shape (int cents + balance_dollars).
TODAY_SAMPLE = {
    "balance": 2135,
    "balance_breakdown": [
        {"balance": "21.3500", "exchange_index": 0},
        {"balance": "0.0000", "exchange_index": 1},
        {"balance": "0.0000", "exchange_index": 2},
        {"balance": "0.0000", "exchange_index": 3},
    ],
    "balance_dollars": "21.3500",
    "portfolio_value": 0,
    "updated_ts": 1761410000,
}

OCT19_REPO_SAMPLE = {
    "balance": 2253,
    "balance_breakdown": [
        {"balance": "22.5319", "exchange_index": 0},
        {"balance": "0.0000", "exchange_index": 1},
        {"balance": "0.0000", "exchange_index": 2},
        {"balance": "0.0000", "exchange_index": 3},
    ],
    "balance_dollars": "22.5319",
    "portfolio_value": 0,
    "updated_ts": 1792428509,
}


def _redirect_cache() -> tuple[Path, Path, Path]:
    folder = Path(tempfile.mkdtemp())
    saved = (kalshi_private.BALANCE_CACHE, kalshi_private.BALANCE_FAIL_LOG)
    kalshi_private.BALANCE_CACHE = folder / "kalshi_balance_cache.json"
    kalshi_private.BALANCE_FAIL_LOG = folder / "kalshi_balance_fail.log"
    kalshi_private.reset_balance_cache_for_tests()
    return folder, saved[0], saved[1]


def _restore_cache(saved_cache: Path, saved_fail: Path) -> None:
    kalshi_private.BALANCE_CACHE = saved_cache
    kalshi_private.BALANCE_FAIL_LOG = saved_fail


def test_today_sample_parses_to_decimal_ge0():
    got = kalshi_private.parse_balance_usd(TODAY_SAMPLE)
    assert got is not None
    assert got >= 0
    assert got == Decimal("21.3500")
    got_json = kalshi_private.parse_balance_usd(json.dumps(TODAY_SAMPLE))
    assert got_json == Decimal("21.3500")


def test_oct19_repo_sample_parses_ge0():
    got = kalshi_private.parse_balance_usd(OCT19_REPO_SAMPLE)
    assert got is not None and got >= 0
    assert got == Decimal("22.5319")


def test_balance_dollars_preferred_over_truncated_cents():
    got = kalshi_private.parse_balance_usd({"balance": 21, "balance_dollars": "21.3500"})
    assert got == Decimal("21.3500")


def test_available_balance_field():
    got = kalshi_private.parse_balance_usd({"available_balance": "18.00"})
    assert got == Decimal("18.00")


def test_cents_only_still_parses():
    got = kalshi_private.parse_balance_usd({"balance": 2135})
    assert got == Decimal("21.35")


def test_429_body_does_not_parse():
    assert kalshi_private.parse_balance_usd('{"error":{"code":"too_many_requests"}}') is None
    assert kalshi_private.parse_balance_usd({"error": {"code": "too_many_requests"}}) is None


def test_portfolio_value_is_not_cash():
    assert kalshi_private.parse_balance_usd({"portfolio_value": 1010}) is None


def test_balance_usd_cache_avoids_second_get():
    folder, saved_cache, saved_fail = _redirect_cache()
    calls = []

    def fake_balance():
        calls.append(1)
        if len(calls) == 1:
            return 200, json.dumps(TODAY_SAMPLE)
        return 429, '{"error":{"code":"too_many_requests"}}'

    try:
        with patch.object(kalshi_private, "_wait_kalshi_slot", lambda: None), patch.object(
            kalshi_private, "balance", fake_balance
        ):
            status1, usd1 = kalshi_private.balance_usd()
            status2, usd2 = kalshi_private.balance_usd()
        assert status1 == 200 and status2 == 200
        assert usd1 is not None and Decimal(usd1) >= 0
        assert usd2 == usd1
        assert len(calls) == 1
    finally:
        _restore_cache(saved_cache, saved_fail)
        del folder


def test_429_backs_off_without_second_get():
    folder, saved_cache, saved_fail = _redirect_cache()
    calls = []

    def fake_balance():
        calls.append(1)
        return 429, '{"error":{"code":"too_many_requests"}}'

    try:
        with patch.object(kalshi_private, "_wait_kalshi_slot", lambda: None), patch.object(
            kalshi_private, "balance", fake_balance
        ):
            status1, usd1 = kalshi_private.balance_usd()
            status2, usd2 = kalshi_private.balance_usd()
        assert status1 == 429 and usd1 is None
        assert status2 == 429 and usd2 is None
        assert len(calls) == 1
    finally:
        _restore_cache(saved_cache, saved_fail)
        del folder


if __name__ == "__main__":
    test_today_sample_parses_to_decimal_ge0()
    test_oct19_repo_sample_parses_ge0()
    test_balance_dollars_preferred_over_truncated_cents()
    test_available_balance_field()
    test_cents_only_still_parses()
    test_429_body_does_not_parse()
    test_portfolio_value_is_not_cash()
    test_balance_usd_cache_avoids_second_get()
    test_429_backs_off_without_second_get()
    print("ok")
