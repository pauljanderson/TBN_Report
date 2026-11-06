#!/usr/bin/env python3
"""Regression: freshness must not trust a twin-tree stamp over local warehouse dates.

2026-11-06: drive/ was a junction to Downloads\\stockresearch\\drive. A morning
update wrote a fresh stamp (and updated Downloads data/) while TBN data/ still
ended 2026-11-04. DailyRun skipped pygetallMore and ran on stale bars.

Also: a stamp rewritten after the close over bars fetched before the close
(16:27 ok_at, 10:50 bars_fetched_at) must still require a post-close update.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "tools"))

import data_update_freshness as fresh  # noqa: E402

ET = ZoneInfo("America/New_York")


def _write_spy(path: Path, last: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["Date,Open,High,Low,Close,Volume"]
    for i in range(2, -1, -1):
        day = date.fromordinal(last.toordinal() - i)
        rows.append(f"{day.isoformat()},1,1,1,1,1")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_duckdb(path: Path, last: date) -> None:
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE prices (symbol VARCHAR, date DATE, open DOUBLE, high DOUBLE, "
        "low DOUBLE, close DOUBLE, volume DOUBLE)"
    )
    con.execute(
        "INSERT INTO prices VALUES ('SPY', ?, 1, 1, 1, 1, 1)",
        [last],
    )
    con.close()


def _stamp(
    root: Path,
    *,
    ok_at: datetime,
    data_root: str | None,
    bars_fetched_at: datetime | None = None,
    updated: int = 100,
    total: int = 100,
) -> dict:
    drive = root / "drive"
    drive.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "ok_at": ok_at.isoformat(),
        "updated": updated,
        "skipped": 0,
        "total": total,
        "full_backfill_count": 0,
        "writer": "pygetallMore",
    }
    if bars_fetched_at is not None:
        payload["bars_fetched_at"] = bars_fetched_at.isoformat()
    if data_root is not None:
        payload["data_root"] = data_root
    (drive / fresh.STAMP_NAME).write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_fresh_stamp_stale_warehouse_needs_update() -> None:
    """Fresh stamp + matching data_root still fails when SPY/DuckDB are behind."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        stale = date(2026, 11, 4)
        _write_spy(fresh.spy_csv_path(root), stale)
        _write_duckdb(fresh.ohlcv_duckdb_path(root), stale)
        now = datetime(2026, 11, 6, 14, 0, tzinfo=ET)
        stamp = _stamp(
            root,
            ok_at=datetime(2026, 11, 6, 10, 50, tzinfo=ET),
            bars_fetched_at=datetime(2026, 11, 6, 10, 50, tzinfo=ET),
            data_root=str(fresh.data_root(root).resolve()),
        )
        needs, reason = fresh.needs_data_update(stamp, now_et=now, root=root)
        assert needs, reason
        assert "warehouse behind" in reason or "expected" in reason, reason


def test_stamp_other_data_root_needs_update() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        last = date(2026, 11, 6)
        _write_spy(fresh.spy_csv_path(root), last)
        _write_duckdb(fresh.ohlcv_duckdb_path(root), last)
        now = datetime(2026, 11, 6, 17, 0, tzinfo=ET)
        stamp = _stamp(
            root,
            ok_at=datetime(2026, 11, 6, 10, 50, tzinfo=ET),
            bars_fetched_at=datetime(2026, 11, 6, 10, 50, tzinfo=ET),
            data_root=r"C:\Users\songg\Downloads\stockresearch\data",
        )
        needs, reason = fresh.needs_data_update(stamp, now_et=now, root=root)
        assert needs, reason
        assert "data_root" in reason, reason


def test_matching_warehouse_and_stamp_can_skip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        last = date(2026, 11, 6)
        _write_spy(fresh.spy_csv_path(root), last)
        _write_duckdb(fresh.ohlcv_duckdb_path(root), last)
        now = datetime(2026, 11, 6, 17, 30, tzinfo=ET)
        stamp = _stamp(
            root,
            ok_at=datetime(2026, 11, 6, 16, 10, tzinfo=ET),
            bars_fetched_at=datetime(2026, 11, 6, 16, 10, tzinfo=ET),
            data_root=str(fresh.data_root(root).resolve()),
        )
        needs, reason = fresh.needs_data_update(stamp, now_et=now, root=root)
        assert not needs, reason


def test_post_close_stamp_over_pre_close_bars_needs_update() -> None:
    """2026-11-06: ok_at 16:27 over bars_fetched_at 10:50 must not skip evening pull."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        last = date(2026, 11, 6)
        _write_spy(fresh.spy_csv_path(root), last)
        _write_duckdb(fresh.ohlcv_duckdb_path(root), last)
        now = datetime(2026, 11, 6, 18, 30, tzinfo=ET)
        stamp = _stamp(
            root,
            ok_at=datetime(2026, 11, 6, 16, 27, tzinfo=ET),
            bars_fetched_at=datetime(2026, 11, 6, 10, 50, tzinfo=ET),
            data_root=str(fresh.data_root(root).resolve()),
        )
        needs, reason = fresh.needs_data_update(stamp, now_et=now, root=root)
        assert needs, reason
        assert "post-close" in reason or "bars_fetched_at" in reason, reason


def test_missing_bars_fetched_at_needs_update() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        last = date(2026, 11, 6)
        _write_spy(fresh.spy_csv_path(root), last)
        _write_duckdb(fresh.ohlcv_duckdb_path(root), last)
        now = datetime(2026, 11, 6, 17, 30, tzinfo=ET)
        stamp = _stamp(
            root,
            ok_at=datetime(2026, 11, 6, 16, 10, tzinfo=ET),
            bars_fetched_at=None,
            data_root=str(fresh.data_root(root).resolve()),
        )
        needs, reason = fresh.needs_data_update(stamp, now_et=now, root=root)
        assert needs, reason
        assert "bars_fetched_at" in reason, reason


def test_expected_last_session_before_close() -> None:
    now = datetime(2026, 11, 5, 10, 0, tzinfo=ET)
    assert fresh.expected_last_session_date(now) == date(2026, 11, 4)
    now2 = datetime(2026, 11, 5, 16, 5, tzinfo=ET)
    assert fresh.expected_last_session_date(now2) == date(2026, 11, 5)


def main() -> int:
    tests = [
        test_fresh_stamp_stale_warehouse_needs_update,
        test_stamp_other_data_root_needs_update,
        test_matching_warehouse_and_stamp_can_skip,
        test_post_close_stamp_over_pre_close_bars_needs_update,
        test_missing_bars_fetched_at_needs_update,
        test_expected_last_session_before_close,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK  {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
