#!/usr/bin/env python3
"""Regression: flat gettarget_positions must not fail DailyRun / run_gettarget.

2026-11-04 12:27 ET DailyRun died at [13/13] run_gettarget with:
  FileNotFoundError: No positions loaded. Edit ...\\gettarget_positions.csv
An empty book (header only / no holdings) is legitimate — clear getTarget_output
and exit 0.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import getTarget  # noqa: E402


def test_load_positions_header_only_is_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gettarget_positions.csv"
        path.write_text("symbol,purchase_date,entry_price,system\n", encoding="utf-8")
        assert getTarget.load_positions(path) == {}


def test_load_positions_missing_file_is_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "does_not_exist.csv"
        assert getTarget.load_positions(path) == {}


def test_main_empty_book_clears_output_and_exits_0() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        positions = tmp_path / "gettarget_positions.csv"
        out = tmp_path / "getTarget_output.csv"
        positions.write_text("symbol,purchase_date,entry_price,system\n", encoding="utf-8")
        # Prior live rows must be wiped so reports don't show stale stops/targets.
        out.write_text(
            "Symbol,System,PurchaseDate,TargetPrice,LimitPrice\nAAPL,BRT,2026-01-01,200,180\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                sys.executable,
                str(_REPO / "getTarget.py"),
                "--positions-csv",
                str(positions),
                "--out-csv",
                str(out),
                "--exclude-system=IND",
            ],
            cwd=str(_REPO),
            text=True,
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
        assert "No open positions" in (proc.stdout or "")
        body = out.read_text(encoding="utf-8").strip().splitlines()
        assert body[0].startswith("Symbol")
        assert len(body) == 1, body


def main() -> int:
    tests = [
        test_load_positions_header_only_is_empty,
        test_load_positions_missing_file_is_empty,
        test_main_empty_book_clears_output_and_exits_0,
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
