#!/usr/bin/env python3
"""Live allocation: only systems in LIVE_RISK_MULT get Suggested shares, at their fraction of risk.

Production (2026-11-13) lists none: every system is paper-only.

Run: python tools/test_live_risk_mult.py   (also works under pytest)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
import live_style_sizing as lss  # noqa: E402


def _size(system: str):
    return lss.size_trade(symbol="AAPL", system=system, entry=100.0, stop=92.0,
                          bom_equity=200_000.0, current_equity=200_000.0)


class _Mult:
    """Temporarily set LIVE_RISK_MULT (production is empty: everything on paper)."""

    def __init__(self, **m):
        self.m = m

    def __enter__(self):
        self.old = dict(lss.LIVE_RISK_MULT)
        lss.LIVE_RISK_MULT.clear()
        lss.LIVE_RISK_MULT.update(self.m)

    def __exit__(self, *exc):
        lss.LIVE_RISK_MULT.clear()
        lss.LIVE_RISK_MULT.update(self.old)


def test_listed_system_gets_its_fraction_of_risk() -> None:
    with _Mult(WPBR=0.5):
        r = _size("WPBR")
    assert abs(r.risk_dollar - 1_000.0) < 1e-6, r.risk_dollar  # 0.5 x 1% x 200k
    assert r.skip_reason != "paper_only"


def test_all_systems_paper_only_in_production() -> None:
    assert lss.LIVE_RISK_MULT == {}, lss.LIVE_RISK_MULT
    for s in ("WPBR", "WRL", "RL", "BRT", "SB", "RSI", "VZ", "YH", "MTS", "RS"):
        r = _size(s)
        assert r.skip_reason == "paper_only" and not r.sized and r.shares == 0, (s, r.skip_reason)
        assert r.as_row()["SUGGESTED_SHARES"] == "—"


def test_untested_liquidity_blocked() -> None:
    import pandas as pd
    import tempfile
    d = Path(tempfile.mkdtemp())
    n = 260
    df = pd.DataFrame({"Date": pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d"),
                       "Open": 30.0, "High": 31.0, "Low": 29.0, "Close": 30.0, "Volume": 40_000})
    df.to_csv(d / "THIN.csv", index=False)                       # $1.2M/day, like DNBBY
    df.assign(Volume=1_000_000).to_csv(d / "THICK.csv", index=False)  # $30M/day
    lss._OHLC_CACHE.clear(); lss._ADV_CACHE.clear()
    kw = dict(system="WPBR", entry=30.0, stop=27.6, bom_equity=200_000.0, current_equity=200_000.0, data_dir=d)
    with _Mult(WPBR=0.5):
        assert lss.size_trade(symbol="THIN", **kw).skip_reason == "untested_liquidity"
        r = lss.size_trade(symbol="THICK", **kw)
    assert r.sized and r.shares > 0, r.skip_reason
    lss._OHLC_CACHE.clear(); lss._ADV_CACHE.clear()


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
