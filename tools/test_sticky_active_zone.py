#!/usr/bin/env python3
"""Test sticky active-zone selection vs sheet DN."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def sticky_active(h, lo, mbh, mbi, n):
    de = np.full(n, np.nan)
    df = np.full(n, np.nan)
    dg = np.full(n, np.nan)
    ds = np.full(n, np.nan)
    prev_j = -1
    for i in range(n):
        hi, lo_i = float(h[i]), float(lo[i])
        matured = [
            j
            for j in range(i + 1)
            if np.isfinite(mbh[j]) and mbh[j] > 0 and np.isfinite(mbi[j])
        ]
        best = -1
        best_zl = best_zu = np.nan
        if prev_j >= 0 and prev_j <= i:
            ce, cf = float(mbh[prev_j]), float(mbi[prev_j])
            if hi >= ce and lo_i <= cf and i > prev_j:
                best = prev_j
                best_zl, best_zu = ce, cf
        if best < 0:
            for j in matured:
                ce, cf = float(mbh[j]), float(mbi[j])
                if hi >= ce and lo_i <= cf and i > j and j > best:
                    best = j
                    best_zl, best_zu = ce, cf
        if best >= 0:
            de[i], df[i], dg[i] = best_zl, best_zu, float(best)
            ds[i] = sum(
                1 for k in range(best, i + 1) if np.isfinite(mbh[k]) and mbh[k] > 0
            )
            prev_j = best
        else:
            prev_j = -1
    return de, df, dg, ds


def main() -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    cases = {
        "NFLX": [("2019-10-11", 7), ("2019-10-14", 13)],
        "TSLA": [("2019-07-11", 22), ("2019-07-12", 11)],
        "NVDA": [("2025-05-27", 11), ("2025-06-02", 16)],
    }
    for sym, rows in cases.items():
        df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
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
        h, lo = [df[x].to_numpy(float) for x in ["High", "Low"]]
        o, c = [df[x].to_numpy(float) for x in ["Open", "Close"]]
        mbh, mbi = rb._precompute_mat_bh_bi_stream(
            l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
        )
        de, dfa, dg, ds = sticky_active(h, lo, mbh, mbi, n)
        g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
        print(f"=== {sym} sticky ===")
        for d, sdn in rows:
            i = df.index.get_loc(__import__("pandas").Timestamp(d))
            if np.isfinite(de[i]):
                print(
                    f"  {d} DN{int(ds[i])}(s{sdn}) {de[i]:.2f}-{dfa[i]:.2f} "
                    f"AK={int(g['ak'][i])} BG={int(g['bg'][i])} BI={int(g['bi'][i])}"
                )
            else:
                print(f"  {d} none (s{sdn}) BI={int(g['bi'][i])}")


if __name__ == "__main__":
    main()
