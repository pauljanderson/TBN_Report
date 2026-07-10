#!/usr/bin/env python3
"""Quick BI gate trace for named dates."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)


def trace(sym: str, dates: list[str]) -> None:
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
    iso = [str(x).replace("-", "")[:8] for x in df.index]
    idx = {f"{s[:4]}-{s[4:6]}-{s[6:8]}": i for i, s in enumerate(iso)}
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    o, h, lo, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
    mbh, mbi = rb._precompute_mat_bh_bi_stream(
        l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, len(df)
    )
    de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, len(df), cfg)
    g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, len(df), cfg)
    print(f"\n=== {sym} ===")
    for d in dates:
        if d not in idx:
            print(f"{d} not in data")
            continue
        i = idx[d]
        z = f"${de[i]:.2f}-${dfa[i]:.2f}" if np.isfinite(de[i]) else "----"
        dm = int(dg[i]) + 2 if np.isfinite(dg[i]) else "-"
        dn = int(ds[i]) if np.isfinite(ds[i]) else "-"
        print(
            f"{d} zone {z} DM{dm} DN{dn}  "
            f"AK={int(g['ak'][i])} AM={int(g['am'][i])} AR={int(g['ar'][i])} AW={int(g['aw'][i])} "
            f"BC={int(g['bc'][i])} BE={int(g['be'][i])} BG={int(g['bg'][i])} BW={int(g['bw'][i])} BI={int(g['bi'][i])}"
        )


if __name__ == "__main__":
    targets = sys.argv[1:]
    if not targets:
        trace("TSLA", ["2021-12-20", "2021-12-21", "2023-09-18", "2023-09-19"])
        trace("MSFT", ["2023-04-05", "2023-04-06", "2023-04-07"])
    else:
        sym = targets[0]
        trace(sym, targets[1:])
