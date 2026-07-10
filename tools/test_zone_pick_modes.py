#!/usr/bin/env python3
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb


def pick_active(h, lo, mbh, mbi, n, mode="maxj"):
    de = np.full(n, np.nan)
    df = np.full(n, np.nan)
    dg = np.full(n, np.nan)
    ds = np.full(n, np.nan)
    for i in range(n):
        hi, lo_i = float(h[i]), float(lo[i])
        cands = []
        for j in range(i + 1):
            if not (np.isfinite(mbh[j]) and mbh[j] > 0):
                continue
            ce, cf = float(mbh[j]), float(mbi[j])
            if not (hi >= ce and lo_i <= cf):
                continue
            if i <= j:
                continue
            cnt = sum(
                1 for k in range(j, i + 1) if np.isfinite(mbh[k]) and mbh[k] > 0
            )
            ins = ce <= lo_i <= cf
            cands.append((j, ce, cf, cnt, ins))
        if not cands:
            continue
        if mode == "maxj":
            j, ce, cf, cnt, _ = max(cands, key=lambda x: x[0])
        elif mode == "maxj_lowin_ov_slack":
            j, ce, cf, cnt, ins = max(cands, key=lambda x: x[0])
            if ins:
                ov = [c for c in cands if not c[4]]
                if ov:
                    ov_max = max(x[3] for x in ov)
                    if ov_max - cnt > 2:
                        j, ce, cf, cnt, _ = max(ov, key=lambda x: x[3])
        elif mode == "maxj_unless_lowin_ov":
            j, ce, cf, cnt, ins = max(cands, key=lambda x: x[0])
            if ins:
                ov = [c for c in cands if not c[4]]
                if ov and max(x[3] for x in ov) > cnt:
                    j, ce, cf, cnt, _ = max(ov, key=lambda x: x[3])
        elif mode == "lowin_maxdn":
            ins = [c for c in cands if c[4]]
            pool = ins if ins else [c for c in cands if not c[4]]
            j, ce, cf, cnt, _ = max(pool, key=lambda x: x[3])
        elif mode == "ovonly_maxdn":
            ov = [c for c in cands if not c[4]]
            pool = ov if ov else [c for c in cands if c[4]]
            j, ce, cf, cnt, _ = max(pool, key=lambda x: x[3])
        elif mode == "hybrid2":
            ins = [c for c in cands if c[4]]
            ov = [c for c in cands if not c[4]]
            if ins and ov:
                ov_max = max(x[3] for x in ov)
                ins_max = max(x[3] for x in ins)
                if 0 <= ov_max - ins_max <= 2:
                    j, ce, cf, cnt, _ = max(ins, key=lambda x: x[3])
                else:
                    j, ce, cf, cnt, _ = max(ov, key=lambda x: x[3])
            elif ov:
                j, ce, cf, cnt, _ = max(ov, key=lambda x: x[3])
            elif ins:
                j, ce, cf, cnt, _ = max(ins, key=lambda x: x[3])
            else:
                continue
        else:
            raise ValueError(mode)
        de[i], df[i], dg[i], ds[i] = ce, cf, float(j), float(cnt)
    return de, df, dg, ds


def pick_active_sticky(h, lo, mbh, mbi, n, mode="hybrid2"):
    de = np.full(n, np.nan)
    df = np.full(n, np.nan)
    dg = np.full(n, np.nan)
    ds = np.full(n, np.nan)
    prev_j = -1
    for i in range(n):
        hi, lo_i = float(h[i]), float(lo[i])
        if prev_j >= 0 and prev_j <= i:
            ce, cf = float(mbh[prev_j]), float(mbi[prev_j])
            if hi >= ce and lo_i <= cf and i > prev_j:
                de[i], df[i], dg[i] = ce, cf, float(prev_j)
                ds[i] = sum(
                    1
                    for k in range(prev_j, i + 1)
                    if np.isfinite(mbh[k]) and mbh[k] > 0
                )
                continue
        cands = []
        for j in range(i + 1):
            if not (np.isfinite(mbh[j]) and mbh[j] > 0):
                continue
            ce, cf = float(mbh[j]), float(mbi[j])
            if not (hi >= ce and lo_i <= cf):
                continue
            if i <= j:
                continue
            cnt = sum(
                1 for k in range(j, i + 1) if np.isfinite(mbh[k]) and mbh[k] > 0
            )
            ins = ce <= lo_i <= cf
            cands.append((j, ce, cf, cnt, ins))
        if not cands:
            prev_j = -1
            continue
        if mode == "maxj":
            j, ce, cf, cnt, _ = max(cands, key=lambda x: x[0])
        elif mode == "hybrid2":
            ins = [c for c in cands if c[4]]
            ov = [c for c in cands if not c[4]]
            if ins and ov:
                ov_max = max(x[3] for x in ov)
                ins_max = max(x[3] for x in ins)
                if 0 <= ov_max - ins_max <= 2:
                    j, ce, cf, cnt, _ = max(ins, key=lambda x: x[3])
                else:
                    j, ce, cf, cnt, _ = max(ov, key=lambda x: x[3])
            elif ov:
                j, ce, cf, cnt, _ = max(ov, key=lambda x: x[3])
            elif ins:
                j, ce, cf, cnt, _ = max(ins, key=lambda x: x[3])
            else:
                prev_j = -1
                continue
        else:
            raise ValueError(mode)
        de[i], df[i], dg[i], ds[i] = ce, cf, float(j), float(cnt)
        prev_j = j
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
    for mode in ("maxj", "maxj_lowin_ov_slack", "hybrid2"):
        print("MODE", mode)
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
            de, dfa, dg, ds = pick_active(h, lo, mbh, mbi, n, mode)
            g = rb._precompute_mts_bi_gates(
                o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg
            )
            parts = []
            for d, sdn in rows:
                i = df.index.get_loc(__import__("pandas").Timestamp(d))
                parts.append(
                    f"{d}:DN{int(ds[i])}(s{sdn}) BI{int(g['bi'][i])}"
                )
            print(f"  {sym} " + "; ".join(parts))


if __name__ == "__main__":
    main()
