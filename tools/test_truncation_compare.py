#!/usr/bin/env python3
"""truncation_test.compare flags a system whose pre-cut trades change when later data is removed.

Run: python tools/test_truncation_compare.py   (also works under pytest)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools" / "honest_bt"))
import truncation_test as tt  # noqa: E402

HDR_C = "SYMBOL,DATE_OPENED,ENTRY_PRICE,DATE_CLOSED,EXIT_PRICE\n"
HDR_O = "SYMBOL,DATE_OPENED,ENTRY_PRICE\n"


def _write(d: Path, sys_code: str, closed: str, opened: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sys_code}_Closed_261113000000.csv").write_text(HDR_C + closed)
    (d / f"{sys_code}_Open_261113000000.csv").write_text(HDR_O + opened)


def _run(cut_closed: str, cut_open: str) -> int:
    tmp = Path(tempfile.mkdtemp())
    old = tt.REPO
    try:
        tt.REPO = tmp
        root = tmp / "drive" / "honest_bt" / "T" / "trunc"
        # full run: AAA opened 2022-01-03 closed 2022-02-01; BBB opened 2022-06-01 (after the cut)
        _write(root / "full" / "XX", "XX", "AAA,20220103,10.00,20220201,11.00\nBBB,20220601,5.00,20220701,6.00\n", "")
        _write(root / "cut_20220331" / "XX", "XX", cut_closed, cut_open)
        return tt.compare("T", ["XX"], ["2022-03-31"])
    finally:
        tt.REPO = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_identical_pre_cut_trades_are_clean() -> None:
    assert _run("AAA,20220103,10.00,20220201,11.00\n", "") == 0


def test_trade_only_in_cut_run_is_a_leak() -> None:
    # the cut run takes a trade the full run skipped (the WPBR overhead pattern)
    assert _run("AAA,20220103,10.00,20220201,11.00\n", "CCC,20220325,7.00\n") == 1


def test_different_exit_before_cut_is_a_leak() -> None:
    assert _run("AAA,20220103,10.00,20220215,9.20\n", "") == 1


def test_trade_opened_on_cut_day_is_ignored() -> None:
    # the last bar of the cut data is not compared (edge of data)
    assert _run("AAA,20220103,10.00,20220201,11.00\n", "DDD,20220331,4.00\n") == 0


def main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {e!r}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
