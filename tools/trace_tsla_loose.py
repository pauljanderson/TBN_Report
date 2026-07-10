#!/usr/bin/env python3
"""Trace TSLA LOOSE trades: 2019-10-09 vs sheet 10/22, 2025-02-28 vs sheet 03-04."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def trace_dates(sym: str, dates: list[str]) -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
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
    _do = np.zeros(n, dtype=bool)
    for i in range(n):
        if np.isfinite(ds[i]) and (not np.isfinite(dg[i]) or i > dg[i]):
            _do[i] = True
    dp = np.zeros(n, dtype=bool)
    for i in range(n):
        if _do[i] and (i == 0 or not _do[i - 1] or ds[i] != ds[i - 1]):
            dp[i] = True

    print(f"\n{'='*72}\n{sym}\n{'='*72}")
    for d in dates:
        i = df.index.get_loc(pd.Timestamp(d))
        fill = df["Open"].iloc[i + 1] if i + 1 < n else float("nan")
        print(
            f"{d} O={o[i]:.2f} H={h[i]:.2f} L={lo[i]:.2f} C={c[i]:.2f} | "
            f"DN={int(ds[i])} {de[i]:.2f}-{dfa[i]:.2f} | "
            f"AK={int(g['ak'][i])} AM={int(g['am'][i])} AQ={int(g['aq'][i])} "
            f"AW={int(g['aw'][i])} BC={int(g['bc'][i])} BG={int(g['bg'][i])} "
            f"BI={int(g['bi'][i])} DP={int(dp[i])} -> fill={fill:.2f}"
        )


def bi_window(sym: str, start: str, end: str) -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
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
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    print(f"\n{sym} BI=1 in {start}..{end}:")
    for i, d in enumerate(df.index):
        if d < t0 or d > t1 or not g["bi"][i]:
            continue
        fill = df["Open"].iloc[i + 1] if i + 1 < n else float("nan")
        print(f"  {d.date()} DN={int(ds[i])} fill={df.index[i+1].date() if i+1<n else '?'} @ {fill:.2f}")


if __name__ == "__main__":
    trace_dates(
        "TSLA",
        [
            "2019-10-07", "2019-10-08", "2019-10-09", "2019-10-10",
            "2019-10-11", "2019-10-14", "2019-10-18", "2019-10-21", "2019-10-22",
        ],
    )
    bi_window("TSLA", "2019-10-01", "2019-10-25")
    trace_dates(
        "TSLA",
        [
            "2025-02-24", "2025-02-25", "2025-02-26", "2025-02-27", "2025-02-28",
            "2025-03-03", "2025-03-04", "2025-03-05",
        ],
    )
    bi_window("TSLA", "2025-02-20", "2025-03-10")
