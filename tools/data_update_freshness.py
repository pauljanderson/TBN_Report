#!/usr/bin/env python3
"""Decide whether DailyRun step 1 (pygetallMore) can be skipped.

Exit codes (--check):
  0 = data fresh enough → skip update (same as SKIP_GET=1)
  1 = stale → run run_update_data.bat

Designed for ~3 DailyRun invocations per day:
  - First run of the ET calendar day fetches bars.
  - Later same-day runs skip once today's update succeeded.
  - After 4:00 PM ET on a weekday, one post-close refresh runs if
    bars_fetched_at was before the close (ok_at alone is not enough —
    a late stamp rewrite over morning bars must not skip the evening pull).

P0 (2026-11-06): do not trust the stamp alone. A shared drive/ junction can
carry a fresh stamp while this tree's data/ is still on older bars. Always
compare max(date) in data/ohlcv.duckdb and data/newdata/data/SPY.csv to the
expected last US equity session, and require stamp.data_root to match this
repo's data root.

Sole writer of the stamp file: stock_analysis/pygetallMore.py. Never hand-write
or rebind drive/data_update_last_ok.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MARKET_CLOSE_ET = time(16, 0)
STAMP_NAME = "data_update_last_ok.json"

# US equity market holidays (full closures). Extend yearly as needed.
_US_MARKET_HOLIDAYS: frozenset[date] = frozenset(
    {
        date(2025, 1, 1),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),  # July 4 observed Friday
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),
        date(2027, 7, 5),  # July 4 observed Monday
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),  # Christmas observed
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def data_root(root: Path | None = None) -> Path:
    return (root or _repo_root()) / "data"


def stamp_path(root: Path | None = None) -> Path:
    return (root or _repo_root()) / "drive" / STAMP_NAME


def spy_csv_path(root: Path | None = None) -> Path:
    return data_root(root) / "newdata" / "data" / "SPY.csv"


def ohlcv_duckdb_path(root: Path | None = None) -> Path:
    return data_root(root) / "ohlcv.duckdb"


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _US_MARKET_HOLIDAYS


def expected_last_session_date(now_et: datetime | None = None) -> date:
    """Most recent US equity session whose regular close should be on disk.

    Before the 16:00 ET close on a session day, expect the prior session.
    At/after close (or on a weekend/holiday), expect that session day.
    """
    now = now_et or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)

    d = now.date()
    if is_trading_day(d) and now.time() < MARKET_CLOSE_ET:
        d = d - timedelta(days=1)
    while not is_trading_day(d):
        d = d - timedelta(days=1)
    return d


def _parse_ok_at(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def _load_stamp(root: Path | None = None) -> dict | None:
    path = stamp_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_weekday(d: datetime) -> bool:
    return d.weekday() < 5


def _parse_csv_max_date(path: Path) -> date | None:
    if not path.is_file():
        return None
    try:
        import pandas as pd

        df = pd.read_csv(path, usecols=["Date"], parse_dates=["Date"])
        if df.empty:
            return None
        ts = pd.to_datetime(df["Date"]).max()
        return ts.date() if hasattr(ts, "date") else None
    except Exception:
        # Fallback: last non-empty line, first comma field.
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            for line in reversed(lines[1:]):
                raw = line.split(",", 1)[0].strip().strip('"')
                if not raw:
                    continue
                return date.fromisoformat(raw[:10])
        except Exception:
            return None
    return None


def _parse_duckdb_max_date(path: Path) -> date | None:
    if not path.is_file():
        return None
    try:
        import duckdb

        con = duckdb.connect(str(path), read_only=True)
        try:
            row = con.execute("SELECT max(date) FROM prices").fetchone()
        finally:
            con.close()
        if not row or row[0] is None:
            return None
        val = row[0]
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        return date.fromisoformat(str(val)[:10])
    except Exception:
        return None


def warehouse_max_dates(root: Path | None = None) -> tuple[date | None, date | None]:
    """Return (spy_csv_max, duckdb_max)."""
    r = root or _repo_root()
    return _parse_csv_max_date(spy_csv_path(r)), _parse_duckdb_max_date(ohlcv_duckdb_path(r))


def warehouse_matches_expected(
    root: Path | None = None,
    *,
    now_et: datetime | None = None,
    expected: date | None = None,
) -> tuple[bool, str]:
    """True when SPY CSV and DuckDB both carry the expected last session."""
    r = root or _repo_root()
    want = expected if expected is not None else expected_last_session_date(now_et)
    spy_max, duck_max = warehouse_max_dates(r)
    parts: list[str] = []
    ok = True
    if spy_max is None:
        ok = False
        parts.append(f"SPY.csv missing or unreadable ({spy_csv_path(r)})")
    elif spy_max < want:
        ok = False
        parts.append(f"SPY.csv max {spy_max.isoformat()} < expected {want.isoformat()}")
    else:
        parts.append(f"SPY.csv max {spy_max.isoformat()}")

    if duck_max is None:
        ok = False
        parts.append(f"ohlcv.duckdb missing or unreadable ({ohlcv_duckdb_path(r)})")
    elif duck_max < want:
        ok = False
        parts.append(f"ohlcv.duckdb max {duck_max.isoformat()} < expected {want.isoformat()}")
    else:
        parts.append(f"ohlcv.duckdb max {duck_max.isoformat()}")

    detail = "; ".join(parts) + f"; expected session {want.isoformat()}"
    return ok, detail


def needs_data_update(
    stamp: dict | None,
    now_et: datetime | None = None,
    *,
    min_updated_ratio: float = 0.05,
    root: Path | None = None,
) -> tuple[bool, str]:
    """Return (needs_update, human_reason)."""
    now = now_et or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)
    r = (root or _repo_root()).resolve()
    expected_data = str(data_root(r).resolve())

    # Always verify the warehouse this process will read.
    wh_ok, wh_detail = warehouse_matches_expected(r, now_et=now)
    if not wh_ok:
        return True, f"warehouse behind expected session — {wh_detail}"

    if stamp is None:
        return True, f"no prior success stamp (first run or stamp missing); {wh_detail}"

    if not bool(stamp.get("ok", True)):
        return True, "last update recorded as failed"

    stamp_root = str(stamp.get("data_root") or "").strip()
    if stamp_root:
        try:
            if Path(stamp_root).resolve() != Path(expected_data).resolve():
                return (
                    True,
                    f"stamp data_root={stamp_root!r} != this tree {expected_data!r} "
                    f"(shared drive stamp / twin-tree drift)",
                )
        except OSError:
            return True, f"stamp data_root unreadable: {stamp_root!r}"
    else:
        # Legacy stamps without data_root: warehouse check already passed, but
        # force one refresh so the next stamp records data_root.
        return True, f"stamp missing data_root — refresh to bind stamp to {expected_data}"

    ok_at = _parse_ok_at(str(stamp.get("ok_at") or ""))
    if ok_at is None:
        return True, "stamp missing or invalid ok_at"

    bars_at = _parse_ok_at(str(stamp.get("bars_fetched_at") or ""))
    if bars_at is None:
        return True, "stamp missing bars_fetched_at — refresh via pygetallMore (do not hand-write stamp)"

    updated = int(stamp.get("updated") or 0)
    skipped = int(stamp.get("skipped") or 0)
    total = int(stamp.get("total") or (updated + skipped))
    full_backfill = int(stamp.get("full_backfill_count") or 0)
    summary = (
        f"last ok {ok_at.strftime('%Y-%m-%d %H:%M')} ET, "
        f"bars {bars_at.strftime('%Y-%m-%d %H:%M')} ET ({updated}/{total} updated"
    )
    if full_backfill:
        summary += f", {full_backfill} full backfill"
    summary += f"); {wh_detail}"

    if _is_weekday(now) and total > 0:
        ratio = updated / total
        if updated == 0:
            return True, f"last run updated 0/{total} symbols on a weekday — retry"
        if ratio < min_updated_ratio:
            return True, f"last run only updated {updated}/{total} symbols — retry"

    if bars_at.date() < now.date():
        return True, f"{summary}; need bars for {now.date().isoformat()}"

    # Same ET calendar day: post-close needs bars fetched at/after the close.
    # ok_at alone is wrong — a 16:27 stamp rewrite over 10:50 bars must not skip.
    if (
        _is_weekday(now)
        and now.time() >= MARKET_CLOSE_ET
        and bars_at.time() < MARKET_CLOSE_ET
    ):
        return True, f"{summary}; post-close run needs today's close (bars_fetched_at before 16:00 ET)"

    return False, summary


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else _repo_root()
    stamp = _load_stamp(root)
    stale, reason = needs_data_update(stamp, root=root)
    if stale:
        print(f"Data stale — running update: {reason}")
        return 1
    print(f"Data fresh — skipping update: {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DailyRun pygetallMore freshness gate.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 0 if update can be skipped, 1 if run_update_data should run.",
    )
    parser.add_argument(
        "--root",
        type=str,
        default="",
        help="Repo root (default: parent of tools/).",
    )
    ns = parser.parse_args(argv)
    if not ns.check:
        parser.error("use --check")
    return cmd_check(ns)


if __name__ == "__main__":
    raise SystemExit(main())
