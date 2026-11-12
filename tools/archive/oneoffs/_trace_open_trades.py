#!/usr/bin/env python3
"""Trace open-trade state around TSLA/NVDA LOOSE BI bars."""
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def mts_trades(sym: str, start: str, end: str) -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    closed, *_ = rb.run_brt_backtest(sym, df, cfg, php, plp, struct, l3)
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    print(f"\n{sym} trades {start}..{end}:")
    for t in closed:
        trig = getattr(t, "close_above_date", "") or ""
        opened = getattr(t, "date_opened", "") or ""
        closed = getattr(t, "date_closed", "") or ""
        # normalize YYYYMMDD
        def norm(d):
            if len(d) >= 10 and d[4] == "-":
                return d[:10]
            if len(d) >= 8 and d[:8].isdigit():
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            return d

        td = norm(trig) or norm(opened)
        if not td:
            continue
        ts = pd.Timestamp(td)
        if ts < t0 and (not closed or pd.Timestamp(norm(closed)) < t0):
            continue
        if ts > t1 and norm(opened) > end:
            continue
        print(
            f"  trig={norm(trig)} open={norm(opened)} @ {getattr(t,'entry_price',0):.2f} "
            f"close={norm(closed)} pnl={getattr(t,'pnl_pct',0):+.2f}%"
        )


if __name__ == "__main__":
    mts_trades("TSLA", "2019-09-01", "2019-10-25")
    mts_trades("TSLA", "2025-02-01", "2025-03-10")
    mts_trades("NVDA", "2025-05-01", "2025-06-10")
    mts_trades("NFLX", "2019-09-01", "2019-10-25")
