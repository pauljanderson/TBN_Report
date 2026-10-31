"""Local cash slip: debit on confirm, hourly GET, 429 keeps local. No secrets."""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import venue_cash_local  # noqa: E402


def _isolate() -> Path:
    return venue_cash_local.reset_for_tests()


def test_hourly_confirm_gets_once():
    path = _isolate()
    calls = []

    def fetch():
        calls.append(1)
        return Decimal("21.35")

    first = venue_cash_local.ensure_cash("kalshi", fetch)
    second = venue_cash_local.ensure_cash("kalshi", fetch)
    assert first == Decimal("21.35")
    assert second == Decimal("21.35")
    assert len(calls) == 1
    store = json.loads(path.read_text(encoding="utf-8"))
    assert store["kalshi"] == "21.35"
    assert store["venues"]["kalshi"]["last_venue_confirm_ts"] > 0


def test_debit_only_changes_local_cash():
    _isolate()
    venue_cash_local.ensure_cash("kalshi", lambda: Decimal("10.00"))
    got = venue_cash_local.apply_delta("kalshi", Decimal("-0.40"), order_id="ord-1")
    assert got == Decimal("9.60")
    again = venue_cash_local.apply_delta("kalshi", Decimal("-0.40"), order_id="ord-1")
    assert again == Decimal("9.60")
    other = venue_cash_local.apply_delta("kalshi", Decimal("-0.11"), order_id="ord-2")
    assert other == Decimal("9.49")


def test_429_keeps_local_and_does_not_spam_get():
    _isolate()
    venue_cash_local.ensure_cash("kalshi", lambda: Decimal("21.35"))
    calls = []

    def fail():
        calls.append(1)
        return None

    store = venue_cash_local.load()
    store["venues"]["kalshi"]["last_venue_confirm_ts"] = 1.0
    venue_cash_local.sync_memory(
        {"kalshi": Decimal("21.35")},
        {"kalshi": 1.0},
    )
    kept = venue_cash_local.confirm_from_venue("kalshi", fail, force=True, http_status=429)
    assert kept == Decimal("21.35")
    assert len(calls) == 1
    again = venue_cash_local.ensure_cash("kalshi", fail)
    assert again == Decimal("21.35")
    assert len(calls) == 1


def test_missing_cash_without_confirm_is_none():
    _isolate()
    assert venue_cash_local.cash_of(venue_cash_local.load(), "kalshi") is None


if __name__ == "__main__":
    test_hourly_confirm_gets_once()
    test_debit_only_changes_local_cash()
    test_429_keeps_local_and_does_not_spam_get()
    test_missing_cash_without_confirm_is_none()
    print("ok")
