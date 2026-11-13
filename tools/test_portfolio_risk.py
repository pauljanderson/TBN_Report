#!/usr/bin/env python3
"""Portfolio-level risk: heat, loss halts, overlap, and the allotment obeying them.

Run: python tools/test_portfolio_risk.py   (also works under pytest)
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
import portfolio_risk as pr  # noqa: E402
from live_style_sizing import allot_scan_buys  # noqa: E402

ASOF = date(2026, 11, 11)


def _write(d: Path, sym: str, closes: list[float], seed: int = 0) -> None:
    dates = pd.bdate_range(end=pd.Timestamp(ASOF), periods=len(closes))
    pd.DataFrame({"Date": dates, "Close": closes}).to_csv(d / f"{sym}.csv", index=False)


def _walk(n: int, seed: int, start: float = 100.0) -> list[float]:
    r = np.random.default_rng(seed).normal(0, 0.01, n)
    return list(start * np.cumprod(1 + r))


def _setup() -> Path:
    d = Path(tempfile.mkdtemp())
    _write(d, "AAA", [100.0] * 79 + [100.0])
    _write(d, "BBB", [50.0] * 78 + [50.0, 45.0])  # -10% today
    _write(d, "IND1", _walk(80, 1))
    _write(d, "IND2", _walk(80, 2))
    base = np.array(_walk(80, 3))
    _write(d, "TW1", list(base))
    _write(d, "TW2", list(base * 1.5))  # identical moves
    return d


def test_heat_is_distance_to_stop() -> None:
    d = _setup()
    pos = pr.build_positions([{"symbol": "AAA", "qty": 100, "buy_price": 100, "buy_date": "2026-10-01"}],
                             {"AAA": 95.0}, asof=ASOF, data_dir=d)
    rep = pr.evaluate(pos, equity=100_000, asof=ASOF, data_dir=d)
    assert rep.heat == 500.0, rep.heat
    assert not rep.halt_new_buys
    # 5% cap = $5,000 room; $500 used; 1% = $1,000 per new trade -> 4 new buys
    assert rep.max_new_buys == 4, rep.max_new_buys


def test_missing_stop_counts_whole_position() -> None:
    d = _setup()
    pos = pr.build_positions([{"symbol": "AAA", "qty": 100, "buy_price": 100}], {}, asof=ASOF, data_dir=d)
    rep = pr.evaluate(pos, equity=100_000, asof=ASOF, data_dir=d)
    assert rep.heat == 10_000.0
    assert rep.halt_new_buys and "heat" in rep.halt_reasons[0]
    assert any("no live stop" in w for w in rep.warnings)


def test_daily_loss_halts() -> None:
    d = _setup()
    pos = pr.build_positions([{"symbol": "BBB", "qty": 500, "buy_price": 50, "buy_date": "2026-10-01"}],
                             {"BBB": 44.9}, asof=ASOF, data_dir=d)
    rep = pr.evaluate(pos, equity=100_000, asof=ASOF, data_dir=d)  # 500 * -5 = -2,500 = -2.5%
    assert rep.day_pnl == -2500.0, rep.day_pnl
    assert rep.halt_new_buys and any("daily halt" in r for r in rep.halt_reasons)
    assert rep.max_new_buys == 0


def test_realized_month_loss_halts() -> None:
    d = _setup()
    rep = pr.evaluate([], equity=100_000, asof=ASOF, realized_month=-6_500, data_dir=d)
    assert rep.halt_new_buys and any("monthly halt" in r for r in rep.halt_reasons)


def test_empty_book_is_fine() -> None:
    d = _setup()
    rep = pr.evaluate([], equity=250_000, asof=ASOF, data_dir=d)
    assert not rep.halt_new_buys and rep.heat == 0 and rep.max_new_buys == 5


def test_overlap_effective_bets() -> None:
    d = _setup()
    lots = [{"symbol": s, "qty": 10, "buy_price": 100} for s in ("TW1", "TW2")]
    rep = pr.evaluate(pr.build_positions(lots, {"TW1": 90, "TW2": 140}, asof=ASOF, data_dir=d),
                      equity=1_000_000, asof=ASOF, data_dir=d)
    assert rep.avg_corr is not None and rep.avg_corr > 0.99
    assert rep.effective_bets is not None and rep.effective_bets < 1.05
    assert any("move together" in w for w in rep.warnings)
    lots = [{"symbol": s, "qty": 10, "buy_price": 100} for s in ("IND1", "IND2")]
    rep = pr.evaluate(pr.build_positions(lots, {"IND1": 90, "IND2": 90}, asof=ASOF, data_dir=d),
                      equity=1_000_000, asof=ASOF, data_dir=d)
    assert rep.effective_bets is not None and rep.effective_bets > 1.6


def _scan(syms: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"SYMBOL": syms, "SUGGESTED_SHARES": ["10"] * len(syms),
                         "SUGGESTED_NOTIONAL": ["$1,000"] * len(syms)})


def test_allotment_obeys_risk_halt() -> None:
    out, summ = allot_scan_buys({"SB": _scan(["X1", "X2"])}, open_symbols=set(), open_gross_notional=0,
                                current_equity=250_000, risk_halt_reason="heat 6.0% of equity >= 5% cap")
    assert list(out["SB"]["BUY_REC"]) == ["NONE (risk halt)"] * 2, list(out["SB"]["BUY_REC"])
    assert summ["risk_halt"] and summ["take_count"] == 0


def test_allotment_caps_takes_to_heat_room() -> None:
    out, summ = allot_scan_buys({"SB": _scan(["X1", "X2", "X3"])}, open_symbols=set(), open_gross_notional=0,
                                current_equity=250_000, max_new_buys=1)
    assert summ["take_count"] == 1, summ["take_count"]


def test_allotment_defaults_unchanged() -> None:
    out, summ = allot_scan_buys({"SB": _scan(["X1", "X2"])}, open_symbols=set(), open_gross_notional=0,
                                current_equity=250_000)
    assert summ["take_count"] == 2 and not summ["risk_halt"]


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
