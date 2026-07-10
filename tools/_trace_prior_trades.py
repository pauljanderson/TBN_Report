#!/usr/bin/env python3
"""List trades before LOOSE trigger dates to check IN-trade blocking."""
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def list_trades(sym: str, before: str, n: int = 5) -> None:
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
    cutoff = pd.Timestamp(before)
    prior = []
    for t in closed:
        trig = getattr(t, "close_above_date", "") or getattr(t, "date_opened", "")
        if len(trig) >= 8:
            td = pd.Timestamp(f"{trig[:4]}-{trig[4:6]}-{trig[6:8]}" if trig[4] != "-" else trig[:10])
        else:
            continue
        if td < cutoff:
            prior.append(t)
    print(f"\n{sym} last {n} trades before {before}:")
    for t in prior[-n:]:
        trig = getattr(t, "close_above_date", "")
        op = getattr(t, "date_opened", "")
        cl = getattr(t, "date_closed", "")
        print(
            f"  trig={trig} open={op} @ {getattr(t,'entry_price',0):.2f} "
            f"close={cl} pnl={getattr(t,'pnl_pct',0):+.2f}%"
        )
    # open on cutoff date?
    for t in prior[-3:]:
        cl = getattr(t, "date_closed", "") or ""
        if len(cl) >= 8:
            cd = pd.Timestamp(f"{cl[:4]}-{cl[4:6]}-{cl[6:8]}" if cl[4] != "-" else cl[:10])
            if cd >= cutoff:
                print(f"  ** STILL OPEN on {before}: opened {getattr(t,'date_opened','')} **")


if __name__ == "__main__":
    list_trades("TSLA", "2019-10-09", 3)
    list_trades("TSLA", "2019-10-22", 3)
    list_trades("TSLA", "2025-02-28", 3)
    list_trades("TSLA", "2025-03-04", 3)
    list_trades("NVDA", "2025-05-27", 5)
    list_trades("NVDA", "2025-06-02", 5)
