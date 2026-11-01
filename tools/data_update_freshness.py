#!/usr/bin/env python3
"""Decide whether DailyRun step 1 (pygetallMore) can be skipped.

Exit codes (--check):
  0 = data fresh enough → skip update (same as SKIP_GET=1)
  1 = stale → run run_update_data.bat

Designed for ~3 DailyRun invocations per day:
  - First run of the ET calendar day fetches bars.
  - Later same-day runs skip once today's update succeeded.
  - After 4:00 PM ET on a weekday, one post-close refresh runs if the
    last success was before the close (so an evening run picks up the close).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MARKET_CLOSE_ET = time(16, 0)
STAMP_NAME = "data_update_last_ok.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def stamp_path(root: Path | None = None) -> Path:
    return (root or _repo_root()) / "drive" / STAMP_NAME


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


def needs_data_update(
    stamp: dict | None,
    now_et: datetime | None = None,
    *,
    min_updated_ratio: float = 0.05,
) -> tuple[bool, str]:
    """Return (needs_update, human_reason)."""
    now = now_et or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)

    if stamp is None:
        return True, "no prior success stamp (first run or stamp missing)"

    if not bool(stamp.get("ok", True)):
        return True, "last update recorded as failed"

    ok_at = _parse_ok_at(str(stamp.get("ok_at") or ""))
    if ok_at is None:
        return True, "stamp missing or invalid ok_at"

    updated = int(stamp.get("updated") or 0)
    skipped = int(stamp.get("skipped") or 0)
    total = int(stamp.get("total") or (updated + skipped))
    full_backfill = int(stamp.get("full_backfill_count") or 0)
    summary = f"last ok {ok_at.strftime('%Y-%m-%d %H:%M')} ET ({updated}/{total} updated"
    if full_backfill:
        summary += f", {full_backfill} full backfill"
    summary += ")"

    if _is_weekday(now) and total > 0:
        ratio = updated / total
        if updated == 0:
            return True, f"last run updated 0/{total} symbols on a weekday — retry"
        if ratio < min_updated_ratio:
            return True, f"last run only updated {updated}/{total} symbols — retry"

    if ok_at.date() < now.date():
        return True, f"{summary}; need bars for {now.date().isoformat()}"

    # Same ET calendar day.
    if _is_weekday(now) and now.time() >= MARKET_CLOSE_ET and ok_at.time() < MARKET_CLOSE_ET:
        return True, f"{summary}; post-close run needs today's close"

    return False, summary


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else _repo_root()
    stamp = _load_stamp(root)
    stale, reason = needs_data_update(stamp)
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
