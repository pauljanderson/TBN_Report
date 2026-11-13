#!/usr/bin/env python3
"""Governance lock: drift detection, CRLF immunity, quarterly budget, and the live lock existing.

Run: python tools/test_governance.py   (also works under pytest)
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
import governance as gov  # noqa: E402

KNOBS = {"RISK_FRAC": 0.01}


def _fake_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "run_rsi.bat").write_bytes(b"@echo off\r\nset RSI_OB=70\r\n")
    (d / "drive" / "universes").mkdir(parents=True)
    (d / "drive" / "universes" / "rsi_universe.csv").write_text("symbol\nAAPL\n")
    return d


def test_clean_after_lock() -> None:
    d = _fake_repo()
    lock = d / "lock.json"
    gov.write_lock(gov.fingerprint(d, sizing=KNOBS), lock)
    assert gov.drift(d, lock, sizing=KNOBS) == []


def test_crlf_and_trailing_space_do_not_drift() -> None:
    d = _fake_repo()
    lock = d / "lock.json"
    gov.write_lock(gov.fingerprint(d, sizing=KNOBS), lock)
    (d / "run_rsi.bat").write_bytes(b"@echo off   \nset RSI_OB=70\n")
    assert gov.drift(d, lock, sizing=KNOBS) == []


def test_param_change_drifts() -> None:
    d = _fake_repo()
    lock = d / "lock.json"
    gov.write_lock(gov.fingerprint(d, sizing=KNOBS), lock)
    (d / "run_rsi.bat").write_bytes(b"@echo off\r\nset RSI_OB=75\r\n")
    assert gov.drift(d, lock, sizing=KNOBS) == ["RSI:run_rsi.bat"]
    assert gov.systems_for(gov.drift(d, lock, sizing=KNOBS)) == ["RSI"]


def test_universe_and_sizing_changes_drift() -> None:
    d = _fake_repo()
    lock = d / "lock.json"
    gov.write_lock(gov.fingerprint(d, sizing=KNOBS), lock)
    (d / "drive" / "universes" / "rsi_universe.csv").write_text("symbol\nAAPL\nNVDA\n")
    assert "RSI:drive/universes/rsi_universe.csv" in gov.drift(d, lock, sizing=KNOBS)
    assert "SIZING:knobs" in gov.drift(d, lock, sizing={"RISK_FRAC": 0.02})


def test_missing_lock_is_drift() -> None:
    d = _fake_repo()
    assert gov.drift(d, d / "nope.json", sizing=KNOBS)


def test_quarterly_budget() -> None:
    d = _fake_repo()
    led = d / "ADOPTIONS.csv"
    today = date(2026, 11, 12)
    gov.append_ledger({"date": "2026-11-12", "system": "ALL", "change": "baseline"}, led)
    assert gov.budget_problems(["RSI"], today, led) == []  # baseline row exempt
    gov.append_ledger({"date": "2026-10-05", "system": "RSI", "change": "x", "override_reason": "urgent"}, led)
    assert any("RSI already changed" in p for p in gov.budget_problems(["RSI"], today, led))  # overrides count
    assert gov.budget_problems(["RSI"], date(2027, 1, 2), led) == []  # new quarter
    gov.append_ledger({"date": "2026-11-01", "system": "VZ", "change": "y"}, led)
    gov.append_ledger({"date": "2026-11-02", "system": "SB", "change": "z"}, led)
    assert any("adoptions already this quarter" in p for p in gov.budget_problems(["WRL"], today, led))


def test_live_lock_exists_and_covers_every_wired_system() -> None:
    assert gov.LOCK_PATH.is_file(), "governance/production_lock.json missing (python tools/adopt.py --init)"
    keys = gov.load_lock()
    for s in ("BRT", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "WRL", "RL", "SIZING"):
        assert any(k.startswith(s + ":") for k in keys), f"{s} not in lock"


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
