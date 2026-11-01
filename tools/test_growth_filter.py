#!/usr/bin/env python3
"""Focused unit tests: growth filter fails closed when lookback Close is missing."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

import rocket_tbn as tbn  # noqa: E402


def _cfg(**kw) -> tbn.BRTConfig:
    return tbn.BRTConfig(
        growth_filter_enabled=kw.get("growth_filter_enabled", True),
        growth_bars=kw.get("growth_bars", 756),
        growth_history_slack_bars=kw.get("growth_history_slack_bars", 0),
    )


def test_ago_index_insufficient_history():
    cfg = _cfg(growth_history_slack_bars=0)
    assert tbn._growth_ago_bar_index(100, cfg) < 0
    assert tbn._growth_ago_bar_index(755, cfg) < 0
    assert tbn._growth_ago_bar_index(756, cfg) == 0


def test_trigger_gate_blocks_missing_history():
    cfg = _cfg()
    close = np.linspace(10.0, 50.0, 400)
    # Short series: no Close[eval-756]
    assert tbn._growth_filter_at_trigger_gate_blocks(cfg, close, signal_t=200) is True


def test_trigger_gate_blocks_zero_lookback_close():
    cfg = _cfg(growth_bars=10, growth_history_slack_bars=0)
    close = np.ones(30, dtype=float) * 20.0
    close[5] = 0.0  # lookback at signal 15 → bar 5
    assert tbn._growth_filter_at_trigger_gate_blocks(cfg, close, signal_t=15) is True


def test_trigger_gate_blocks_nan_lookback_close():
    cfg = _cfg(growth_bars=10, growth_history_slack_bars=0)
    close = np.ones(30, dtype=float) * 20.0
    close[5] = np.nan
    assert tbn._growth_filter_at_trigger_gate_blocks(cfg, close, signal_t=15) is True


def test_trigger_gate_passes_when_grown():
    cfg = _cfg(growth_bars=10, growth_history_slack_bars=0)
    close = np.arange(1.0, 31.0)  # Close[15]=16 > Close[5]=6
    assert tbn._growth_filter_at_trigger_gate_blocks(cfg, close, signal_t=15) is False


def test_trigger_gate_blocks_when_declined():
    cfg = _cfg(growth_bars=10, growth_history_slack_bars=0)
    close = np.linspace(100.0, 10.0, 30)  # declining
    assert tbn._growth_filter_at_trigger_gate_blocks(cfg, close, signal_t=15) is True


def test_trigger_gate_off_never_blocks():
    cfg = _cfg(growth_filter_enabled=False)
    close = np.linspace(10.0, 50.0, 50)
    assert tbn._growth_filter_at_trigger_gate_blocks(cfg, close, signal_t=5) is False


def main() -> int:
    tests = [
        test_ago_index_insufficient_history,
        test_trigger_gate_blocks_missing_history,
        test_trigger_gate_blocks_zero_lookback_close,
        test_trigger_gate_blocks_nan_lookback_close,
        test_trigger_gate_passes_when_grown,
        test_trigger_gate_blocks_when_declined,
        test_trigger_gate_off_never_blocks,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
