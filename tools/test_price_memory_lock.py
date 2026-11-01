"""price_memory.lock must not convoy helpers on a 15 MB rewrite.

No orders. No secrets. Fake IO only.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import price_memory

ET = ZoneInfo("America/New_York")


def _retarget(folder: Path) -> dict:
    saved = {
        "RAW": price_memory.RAW,
        "LAST": price_memory.LAST,
        "LAST_DIR": price_memory.LAST_DIR,
        "HISTORY_DIR": price_memory.HISTORY_DIR,
        "CSV_DIR": price_memory.CSV_DIR,
        "HISTORY": price_memory.HISTORY,
        "cache": dict(price_memory._legacy_last_cache),
        "stats": dict(price_memory._lock_stats),
    }
    price_memory.RAW = folder
    price_memory.LAST = folder / "price_last.json"
    price_memory.LAST_DIR = folder / "price_last_games"
    price_memory.HISTORY_DIR = folder / "price_memory"
    price_memory.CSV_DIR = folder / "price_memory" / "csv"
    price_memory.HISTORY = folder / "price_memory.jsonl"
    price_memory._legacy_last_cache["mtime"] = None
    price_memory._legacy_last_cache["data"] = None
    for key in ("last_wait_ms", "last_hold_ms", "wait_ms_sum", "hold_ms_sum", "n", "over_budget_n"):
        price_memory._lock_stats[key] = 0.0 if key != "n" and key != "over_budget_n" else 0
    price_memory._lock_stats["n"] = 0
    price_memory._lock_stats["over_budget_n"] = 0
    price_memory._lock_stats["last_game"] = ""
    price_memory._lock_stats["last_sport"] = ""
    return saved


def _restore(saved: dict) -> None:
    price_memory.RAW = saved["RAW"]
    price_memory.LAST = saved["LAST"]
    price_memory.LAST_DIR = saved["LAST_DIR"]
    price_memory.HISTORY_DIR = saved["HISTORY_DIR"]
    price_memory.CSV_DIR = saved["CSV_DIR"]
    price_memory.HISTORY = saved["HISTORY"]
    price_memory._legacy_last_cache.clear()
    price_memory._legacy_last_cache.update(saved["cache"])
    price_memory._lock_stats.clear()
    price_memory._lock_stats.update(saved["stats"])


def _huge_last(n: int = 4000) -> dict:
    seen = "2026-10-28T00:00:00-04:00"
    out = {}
    for i in range(n):
        game = f"Dummy {i} vs Other {i}"
        key = f"tennis|{game}|moneyline|dummy {i}||Polymarket|yes"
        out[key] = {
            "price": "0.5000",
            "seen_at": seen,
            "sport": "tennis",
            "game": game,
            "market_type": "moneyline",
            "side": f"Dummy {i}",
            "number": "",
            "venue": "Polymarket",
            "pay": "yes",
            "game_start": None,
        }
    return out


def _quote(game: str, player: str, price: str, seen: datetime):
    return price_memory.quote_row(
        "tennis",
        game,
        "moneyline",
        player,
        "",
        "Polymarket",
        "yes",
        Decimal(price),
        seen,
        None,
    )


def test_lock_paths_are_per_game():
    a = price_memory.game_lock_path("tennis", "Yuta Shimizu vs. Yu Hsiou Hsu")
    b = price_memory.game_lock_path("tennis", "Other vs Foo")
    assert a != b
    assert a.parent == b.parent
    assert price_memory.LOCK_HOLD_BUDGET_MS <= 500


def test_remember_books_lock_hold_under_500ms_with_huge_legacy_last():
    """A compare/write under lock must not rewrite the leftover 15 MB snapshot."""
    folder = Path(tempfile.mkdtemp(prefix="pm_lock_"))
    saved = _retarget(folder)
    seen = datetime(2026, 10, 28, 0, 23, 57, tzinfo=ET)
    game = "Yuta Shimizu vs. Yu Hsiou Hsu"
    huge = _huge_last(4000)
    price_memory.LAST.write_text(json.dumps(huge, indent=2), encoding="utf-8")
    before_mtime = price_memory.LAST.stat().st_mtime
    before_size = price_memory.LAST.stat().st_size
    canned = [_quote(game, "Yuta Shimizu", "0.52", seen)]
    http_hits = []

    def boom(*_a, **_k):
        http_hits.append(1)
        raise AssertionError("HTTP during remember_books")

    try:
        with patch("urllib.request.urlopen", boom):
            with patch.object(price_memory, "quotes_from_book", return_value=[]):
                with patch.object(price_memory, "quotes_from_polymarket", return_value=canned):
                    with patch.object(price_memory, "quotes_from_novig", return_value=[]):
                        n = price_memory.remember_books(
                            "tennis",
                            game,
                            seen,
                            polymarket_contracts=[{"unused": True}],
                        )
        assert n >= 1
        assert http_hits == []
        stats = price_memory.lock_stats()
        assert stats["last_hold_ms"] < price_memory.LOCK_HOLD_BUDGET_MS
        assert stats["last_hold_ms"] < 500
        assert stats["over_budget_n"] == 0
        after = price_memory.LAST.stat()
        assert after.st_mtime == before_mtime
        assert after.st_size == before_size
        game_path = price_memory.game_last_path("tennis", game)
        assert game_path.is_file()
        payload = json.loads(game_path.read_text(encoding="utf-8"))
        assert payload
        assert all("Dummy" not in str(v.get("game") or "") for v in payload.values() if isinstance(v, dict))
    finally:
        _restore(saved)


def test_two_games_do_not_share_one_lock():
    folder = Path(tempfile.mkdtemp(prefix="pm_lock2_"))
    saved = _retarget(folder)
    seen = datetime(2026, 10, 28, 0, 24, 0, tzinfo=ET)
    try:
        n1 = price_memory._remember_game(
            "tennis",
            "Game A vs B",
            [_quote("Game A vs B", "A", "0.40", seen)],
            seen,
            None,
        )
        n2 = price_memory._remember_game(
            "tennis",
            "Game C vs D",
            [_quote("Game C vs D", "C", "0.60", seen)],
            seen,
            None,
        )
        assert n1 >= 1 and n2 >= 1
        assert price_memory.game_lock_path("tennis", "Game A vs B") != price_memory.game_lock_path(
            "tennis", "Game C vs D"
        )
        assert price_memory.game_last_path("tennis", "Game A vs B").is_file()
        assert price_memory.game_last_path("tennis", "Game C vs D").is_file()
        assert not price_memory.LAST.exists()
        stats = price_memory.lock_stats()
        assert stats["last_hold_ms"] < 500
        assert stats["n"] == 2
    finally:
        _restore(saved)


def test_fake_slow_http_is_not_under_lock():
    folder = Path(tempfile.mkdtemp(prefix="pm_http_"))
    saved = _retarget(folder)
    seen = datetime(2026, 10, 28, 0, 25, 0, tzinfo=ET)
    game = "Fast vs Slow"
    inside = {"n": 0}
    import venue_pace

    class GuardLock(venue_pace.FileLock):
        def __enter__(self):
            inside["n"] += 1
            return super().__enter__()

        def __exit__(self, exc_type, exc, tb):
            inside["n"] = max(0, inside["n"] - 1)
            return super().__exit__(exc_type, exc, tb)

    def slow_http(*_a, **_k):
        if inside["n"]:
            raise AssertionError("HTTP while price_memory lock held")
        time.sleep(0.05)
        raise RuntimeError("no network in unit test")

    canned = [_quote(game, "Fast", "0.41", seen)]
    try:
        with patch.object(venue_pace, "FileLock", GuardLock):
            with patch("urllib.request.urlopen", slow_http):
                with patch.object(price_memory, "quotes_from_book", return_value=[]):
                    with patch.object(price_memory, "quotes_from_polymarket", return_value=canned):
                        with patch.object(price_memory, "quotes_from_novig", return_value=[]):
                            n = price_memory.remember_books("tennis", game, seen, polymarket_contracts=[{}])
        assert n >= 1
        assert price_memory.lock_stats()["last_hold_ms"] < 500
    finally:
        _restore(saved)


if __name__ == "__main__":
    test_lock_paths_are_per_game()
    test_remember_books_lock_hold_under_500ms_with_huge_legacy_last()
    test_two_games_do_not_share_one_lock()
    test_fake_slow_http_is_not_under_lock()
    print("ok")
