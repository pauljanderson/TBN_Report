#!/usr/bin/env python3
"""Smoke: OHLC-easy IND add-ons compute + DIFF stays core-only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
sys.path.insert(0, str(_REPO))

from brt_entry_indicators import (  # noqa: E402
    INDICATOR_CORE_IDS,
    INDICATOR_IDS,
    OHLC_ADDON_INDICATOR_IDS,
    build_entry_indicator_precompute,
    entry_indicator_csv_headers,
    snapshot_for_entry,
)

OUT = _REPO / "drive/paul_experiments/ind_ohlc_indicators_add_20260902/smoke_results.json"


def synth_df(n: int = 500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n)))
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl == "open":
            mapping[c] = "Open"
        elif cl == "high":
            mapping[c] = "High"
        elif cl == "low":
            mapping[c] = "Low"
        elif cl == "close":
            mapping[c] = "Close"
        elif cl == "volume":
            mapping[c] = "Volume"
    return df.rename(columns=mapping) if mapping else df


def main() -> int:
    assert len(INDICATOR_CORE_IDS) == 47, len(INDICATOR_CORE_IDS)
    assert len(OHLC_ADDON_INDICATOR_IDS) == 13, len(OHLC_ADDON_INDICATOR_IDS)
    assert len(INDICATOR_IDS) == 60, len(INDICATOR_IDS)

    results: dict = {
        "core_n": len(INDICATOR_CORE_IDS),
        "addon_n": len(OHLC_ADDON_INDICATOR_IDS),
        "symbols": {},
    }
    dfs: dict[str, pd.DataFrame] = {}
    try:
        from ohlcv_store import DEFAULT_DB_PATH, load_symbol_df

        if Path(DEFAULT_DB_PATH).is_file():
            for sym in ("SPY", "AAPL"):
                try:
                    df = load_symbol_df(sym)
                    if df is not None and len(df) >= 220:
                        dfs[sym] = df
                except Exception as e:  # noqa: BLE001
                    results.setdefault("load_errors", []).append(f"{sym}: {e}")
    except Exception as e:  # noqa: BLE001
        results["duckdb"] = f"skip: {e}"

    if not dfs:
        dfs["SYNTH_SPY"] = synth_df(500, 1)
        dfs["SYNTH_AAPL"] = synth_df(500, 2)
        results["data"] = "synthetic"

    for sym, df in dfs.items():
        df = _norm_cols(df)
        for need in ("Open", "High", "Low", "Close", "Volume"):
            if need not in df.columns:
                raise SystemExit(f"{sym} missing {need}: {list(df.columns)}")
        pre = build_entry_indicator_precompute(df, symbol=sym, use_cache=False)
        assert pre is not None, sym
        for iid in OHLC_ADDON_INDICATOR_IDS:
            assert iid in pre.states, iid
        i = len(pre.dates) - 1
        snap = snapshot_for_entry(pre, i, "LONG")
        addon_states = {iid: snap.get(f"IND_{iid}") for iid in OHLC_ADDON_INDICATOR_IDS}
        core_bull = sum(1 for iid in INDICATOR_CORE_IDS if snap.get(f"IND_{iid}") == "BULL")
        core_bear = sum(1 for iid in INDICATOR_CORE_IDS if snap.get(f"IND_{iid}") == "BEAR")
        assert int(snap["IND_DIFF"]) == core_bull - core_bear
        assert int(snap["IND_ENTRY_BULL_N"]) == core_bull
        hdrs = entry_indicator_csv_headers()
        for iid in OHLC_ADDON_INDICATOR_IDS:
            assert f"IND_{iid}" in hdrs
        results["symbols"][sym] = {
            "n_bars": int(len(pre.dates)),
            "last_date": int(pre.dates[-1]),
            "IND_DIFF": snap["IND_DIFF"],
            "addon_states": addon_states,
        }
        print(sym, "ok DIFF", snap["IND_DIFF"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
