#!/usr/bin/env python3
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def active_zones(h, lo, mbh, mbi, n, pick="max", require_do=False):
    de = np.full(n, np.nan)
    df = np.full(n, np.nan)
    dg = np.full(n, np.nan)
    ds = np.full(n, np.nan)
    for i in range(n):
        hi, lo_i = float(h[i]), float(lo[i])
        matured = [
            j
            for j in range(i + 1)
            if np.isfinite(mbh[j]) and mbh[j] > 0 and np.isfinite(mbi[j])
        ]
        best = -1
        best_zl = best_zu = np.nan
        for j in matured:
            ce, cf = float(mbh[j]), float(mbi[j])
            if not (hi >= ce and lo_i <= cf):
                continue
            if require_do and i <= j:
                continue
            if pick == "max":
                if j > best:
                    best = j
                    best_zl, best_zu = ce, cf
            else:
                if best < 0 or j < best:
                    best = j
                    best_zl, best_zu = ce, cf
        if best >= 0:
            de[i], df[i], dg[i] = best_zl, best_zu, float(best)
            ds[i] = sum(
                1 for k in range(best, i + 1) if np.isfinite(mbh[k]) and mbh[k] > 0
            )
    return de, df, dg, ds


def main() -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    cases = {
        "NFLX": ["2019-10-11", "2019-10-14"],
        "TSLA": ["2019-07-11", "2019-07-12"],
        "NVDA": ["2025-05-27", "2025-06-02"],
    }
    sheet_dn = {
        ("NFLX", "2019-10-11"): 7,
        ("NFLX", "2019-10-14"): 13,
        ("TSLA", "2019-07-11"): 22,
        ("TSLA", "2019-07-12"): 11,
        ("NVDA", "2025-05-27"): 11,
        ("NVDA", "2025-06-02"): 16,
    }
    for sym, dates in cases.items():
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
        mbh, mbi = rb._precompute_mat_bh_bi_stream(
            l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
        )
        print(f"=== {sym} ===")
        for pick, req in [("max", False), ("min", False), ("max", True), ("min", True)]:
            de, dfa, dg, ds = active_zones(h, lo, mbh, mbi, n, pick, req)
            parts = []
            for d in dates:
                i = df.index.get_loc(__import__("pandas").Timestamp(d))
                sdn = sheet_dn[(sym, d)]
                if np.isfinite(de[i]):
                    parts.append(
                        f"{d} DN{int(ds[i])}(s{sdn}) {de[i]:.2f}-{dfa[i]:.2f}"
                    )
                else:
                    parts.append(f"{d} none (s{sdn})")
            print(f"  {pick} do={req}: " + "; ".join(parts))


if __name__ == "__main__":
    main()
