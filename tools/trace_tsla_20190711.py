#!/usr/bin/env python3
"""Trace TSLA 2019-07-11 AK/BG vs sheet formulas."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def main() -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)

    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "TSLA.csv"))
    dates = [
        "2019-07-08",
        "2019-07-09",
        "2019-07-10",
        "2019-07-11",
        "2019-07-12",
        "2019-07-15",
    ]
    ph, pl, php, plp = rb.compute_pivots(
        df,
        cfg.pivot_k,
        cfg.pivot_d,
        cfg.pivot_disp,
        cfg.pivot_m,
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

    hdr = (
        "Date       Open   High    Low  Close | "
        "DK(lo)   DL(up)  DMrow  DN | AK  AM  AQ  BC  BE  BG  BI"
    )
    print(hdr)
    print("-" * len(hdr))
    for d in dates:
        i = df.index.get_loc(pd.Timestamp(d))
        print(
            f"{d} {o[i]:6.2f} {h[i]:6.2f} {lo[i]:6.2f} {c[i]:6.2f} | "
            f"{de[i]:7.4f} {dfa[i]:7.4f} {int(dg[i]):5d} {int(ds[i]):2d} | "
            f"{int(g['ak'][i])}   {int(g['am'][i])}   {int(g['aq'][i])}   "
            f"{int(g['bc'][i])}   {int(g['be'][i])}   {int(g['bg'][i])}   {int(g['bi'][i])}"
        )

    i = df.index.get_loc(pd.Timestamp("2019-07-11"))
    ip = i - 1
    print("\n=== Sheet AK formula on 2019-07-11 (row 887 in paste) ===")
    print(f"Prior bar date: {df.index[ip].date()}")
    print(f"DK={de[i]:.4f}  DL={dfa[i]:.4f}  DM={int(dg[i])}")
    print(f"  ROW()>DM?           {i} > {int(dg[i])} = {i > dg[i]}")
    print(f"  Close[-1] > DL?     {c[ip]:.4f} > {dfa[i]:.4f} = {c[ip] > dfa[i]}")
    print(f"  Low <= DL?          {lo[i]:.4f} <= {dfa[i]:.4f} = {lo[i] <= dfa[i]}")
    print(f"  High >= DK?         {h[i]:.4f} >= {de[i]:.4f} = {h[i] >= de[i]}")
    sheet_ak = (
        np.isfinite(de[i])
        and np.isfinite(dfa[i])
        and i > dg[i]
        and c[ip] > dfa[i]
        and lo[i] <= dfa[i]
        and h[i] >= de[i]
    )
    print(f"  => Sheet AK887       {sheet_ak}")
    print(f"  => Engine AK         {bool(g['ak'][i])}")

    print("\n=== Sheet AK on 2019-07-10 (AK886) ===")
    ip2 = ip - 1
    print(f"Prior bar date: {df.index[ip2].date()}")
    print(f"DK={de[ip]:.4f}  DL={dfa[ip]:.4f}  DM={int(dg[ip])}")
    print(f"  Close[-1] > DL?     {c[ip2]:.4f} > {dfa[ip]:.4f} = {c[ip2] > dfa[ip]}")
    print(f"  Low <= DL?          {lo[ip]:.4f} <= {dfa[ip]:.4f} = {lo[ip] <= dfa[ip]}")
    print(f"  High >= DK?         {h[ip]:.4f} >= {de[ip]:.4f} = {h[ip] >= de[ip]}")
    sheet_ak_prev = (
        np.isfinite(de[ip])
        and np.isfinite(dfa[ip])
        and ip > dg[ip]
        and c[ip2] > dfa[ip]
        and lo[ip] <= dfa[ip]
        and h[ip] >= de[ip]
    )
    print(f"  => Sheet AK886       {sheet_ak_prev}")
    print(f"  => Engine AK         {bool(g['ak'][ip])}")

    print("\n=== Level Acceptance (BG) ===")
    for d in ["2019-07-10", "2019-07-11", "2019-07-12"]:
        j = df.index.get_loc(pd.Timestamp(d))
        akt = bool(g["ak"][j])
        aky = bool(g["ak"][j - 1]) if j >= 1 else False
        anchor = de[j] if akt else (de[j - 1] if j >= 1 else np.nan)
        s = max(0, j - 9)
        cnt = int(np.sum(c[s : j + 1] > anchor)) if np.isfinite(anchor) else -1
        sheet_bg = (akt or aky) and cnt >= 7
        print(
            f"{d}: AK={int(g['ak'][j])} AK[-1]={int(g['ak'][j-1])} "
            f"anchor={anchor:.4f} closes>{anchor:.4f} in last10={cnt} "
            f"=> sheet BG={sheet_bg} engine BG={bool(g['bg'][j])}"
        )

    print("\n=== Active zone on each day (engine) ===")
    for d in dates:
        j = df.index.get_loc(pd.Timestamp(d))
        print(
            f"{d}: DK={de[j]:.4f} DL={dfa[j]:.4f} DM={int(dg[j])} DN={int(ds[j])} "
            f"overlap? H>={de[j]:.2f} and L<={dfa[j]:.2f} => {h[j] >= de[j] and lo[j] <= dfa[j]}"
        )


if __name__ == "__main__":
    main()
