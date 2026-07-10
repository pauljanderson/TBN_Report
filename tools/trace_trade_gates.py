#!/usr/bin/env python3
"""Trace BI/DP/AQ gates around loose or extra trade dates."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def trace_window(sym: str, dates: list[str], cfg: rb.BRTConfig | None = None) -> None:
    if cfg is None:
        base = asdict(rb.BRTConfig())
        base.update(rb.mts_sheet_parity_overrides())
        cfg = rb.BRTConfig(**base)

    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
    iso_idx = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}

    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    o, h, lo, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
    n = len(df)
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
    for i in range(1, n):
        if _do[i] and (not _do[i - 1] or ds[i] != ds[i - 1]):
            dp[i] = True
    if _do[0]:
        dp[0] = True

    print(f"\n{'='*72}\n{sym}\n{'='*72}")
    hdr = (
        "date       Close   DK-DL      DN DO DP AW AR AM AK AQ BC BE BG BW BI"
    )
    print(hdr)
    for d in dates:
        if d not in iso_idx:
            print(f"{d}  (missing)")
            continue
        i = iso_idx[d]
        z = (
            f"${de[i]:.2f}-{dfa[i]:.2f}"
            if np.isfinite(de[i]) and np.isfinite(dfa[i])
            else "----"
        )
        dn = int(ds[i]) if np.isfinite(ds[i]) else -1
        print(
            f"{d} {c[i]:8.2f} {z:16s} {dn:2d} "
            f"{int(_do[i])}  {int(dp[i])}  "
            f"{int(g['aw'][i])}  {int(g['ar'][i])}  {int(g['am'][i])}  {int(g['ak'][i])}  "
            f"{int(g['aq'][i])}  {int(g['bc'][i])}  {int(g['be'][i])}  {int(g['bg'][i])}  "
            f"{int(g['bw'][i])}  {int(g['bi'][i])}"
        )


CASES = {
    "MSFT": {
        "label": "Sheet 2023-04-06 vs engine 2023-04-10",
        "dates": [
            "2023-04-03", "2023-04-04", "2023-04-05", "2023-04-06",
            "2023-04-07", "2023-04-10", "2023-04-11", "2023-04-12",
        ],
    },
    "NFLX": {
        "label": "Sheet 2019-10-14 vs engine 2019-10-22",
        "dates": [
            "2019-10-07", "2019-10-08", "2019-10-09", "2019-10-10",
            "2019-10-11", "2019-10-14", "2019-10-15", "2019-10-16",
            "2019-10-17", "2019-10-18", "2019-10-21", "2019-10-22",
            "2019-10-23", "2019-10-24",
        ],
    },
    "NVDA": {
        "label": "Sheet 2025-06-02 vs engine 2025-05-28",
        "dates": [
            "2025-05-22", "2025-05-23", "2025-05-27", "2025-05-28",
            "2025-05-29", "2025-05-30", "2025-06-02", "2025-06-03",
            "2025-06-04", "2025-06-05",
        ],
    },
    "TSLA": {
        "label": "Extra 2019-07-15",
        "dates": [
            "2019-07-08", "2019-07-09", "2019-07-10", "2019-07-11",
            "2019-07-12", "2019-07-15", "2019-07-16", "2019-07-17",
        ],
    },
}


def main() -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)

    syms = sys.argv[1:] if len(sys.argv) > 1 else list(CASES)
    for sym in syms:
        if sym not in CASES:
            continue
        print(f"\n>>> {CASES[sym]['label']}")
        trace_window(sym, CASES[sym]["dates"], cfg)

    # TSLA loose trades
    for label, dates in [
        ("TSLA loose 2022-06-17 vs 2022-06-21", [
            "2022-06-13", "2022-06-14", "2022-06-15", "2022-06-16",
            "2022-06-17", "2022-06-21", "2022-06-22",
        ]),
        ("TSLA loose 2023-02-17 vs 2023-02-21", [
            "2023-02-13", "2023-02-14", "2023-02-15", "2023-02-16",
            "2023-02-17", "2023-02-21", "2023-02-22",
        ]),
    ]:
        print(f"\n>>> {label}")
        trace_window("TSLA", dates, cfg)


if __name__ == "__main__":
    main()
