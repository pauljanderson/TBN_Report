#!/usr/bin/env python3
"""RL compare must refuse stale stamps, not report a parity failure.

An old AWK stamp + a fresh Python stamp (vs this DailyRun's start) => 'stale input'.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "tools"))

import compare_rl_engine_outputs as cmp  # noqa: E402


def test_old_awk_new_python_is_stale_not_parity() -> None:
    daily_start = "261106164900"
    old_awk = "261106120000"  # before DailyRun
    new_py = "261106165500"  # after DailyRun start
    errs = cmp.check_stale_inputs(old_awk, new_py, daily_start)
    assert errs, "expected stale-input errors"
    assert all(e.startswith("stale input") for e in errs), errs
    assert any("AWK" in e for e in errs), errs
    assert not any("Python" in e and "older" in e for e in errs), errs

    ok, lines = cmp.compare_rl_runs(
        _REPO / "drive",
        old_awk,
        new_py,
        not_before=daily_start,
    )
    assert ok is False
    assert lines and lines[0].startswith("stale input")
    # Must not proceed into artifact parity messaging
    assert not any(line.startswith("AWK run:") for line in lines)
    assert not any("FAIL" in line and "RL_Closed" in line for line in lines)


def test_both_fresh_passes_stale_gate() -> None:
    daily_start = "261106164900"
    awk = "261106165010"
    py = "261106165120"
    assert cmp.check_stale_inputs(awk, py, daily_start) == []


def main() -> int:
    tests = (
        test_old_awk_new_python_is_stale_not_parity,
        test_both_fresh_passes_stale_gate,
    )
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
