#!/usr/bin/env python3
"""Simulate NFLX with sheet OHLC on 10/11 to verify zone/AK/BI chain."""
import sys
from dataclasses import asdict
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def run_nflx(label: str, low_1011: float) -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)

    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "NFLX.csv"))
    df = df.copy()
    df.loc[pd.Timestamp("2019-10-11"), "Low"] = low_1011

    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    n = len(df)
    o, h, lo, c = [df[x].to_numpy(float) for x in ["Open", "High", "Low", "Close"]]
    mbh, mbi = rb._precompute_mat_bh_bi_stream(
        l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
    )
    de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
    g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)

    print(f"\n=== {label} (10/11 Low={low_1011}) ===")
    for d in ["2019-10-11", "2019-10-14", "2019-10-21"]:
        i = df.index.get_loc(pd.Timestamp(d))
        print(
            f"{d}: DN={int(ds[i])} DK={de[i]:.4f}-{dfa[i]:.4f} "
            f"AK={int(g['ak'][i])} BG={int(g['bg'][i])} AQ={int(g['aq'][i])} BI={int(g['bi'][i])}"
        )
    # zone 719 overlap on 10/11
    j = 719
    zl = l3["zone_low"].to_numpy(float)
    zu = l3["zone_high"].to_numpy(float)
    ce, cf = float(zl[j]), float(zu[j])
    i = df.index.get_loc(pd.Timestamp("2019-10-11"))
    print(
        f"Zone719 overlap on 10/11? H>={ce} L<={cf} => "
        f"{float(h[i])>=ce and float(lo[i])<=cf} (L={float(lo[i]):.4f} CF={cf:.4f})"
    )


if __name__ == "__main__":
    run_nflx("Yahoo OHLC", 28.234)
    run_nflx("Sheet OHLC", 27.59)
