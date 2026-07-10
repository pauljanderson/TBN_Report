#!/usr/bin/env python3
"""Formula-by-formula MTS gate trace for sheet vs engine (NFLX/NVDA mismatches)."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb  # noqa: E402

# Sheet paste ground truth (from user mismatch_paste.tsv tail columns)
SHEET_ZONE = {
    ("NFLX", "2019-10-11"): (26.5776, 27.66, 721, 7),
    ("NFLX", "2019-10-14"): (28.6748, 29.85, 590, 13),
    ("NFLX", "2019-10-21"): (26.5776, 27.66, 721, 7),
    ("NVDA", "2025-05-27"): (129.164, 134.44, 2250, 11),
    ("NVDA", "2025-06-02"): (133.427, 138.87, 2152, 16),
}

SHEET_GATES = {
    # col names from parse_mismatch_gates focus — values from paste where reliable
    ("NFLX", "2019-10-11"): {
        "Support test": True,
        "Level Acceptance": True,
        "MTS buy": False,
        "Close above open": True,
    },
    ("NFLX", "2019-10-14"): {
        "Support test": False,
        "Level Acceptance": True,
        "MTS buy": True,
        "Close above open": True,
        "Zone Eligible Long": True,
    },
    ("NVDA", "2025-05-27"): {
        "Support test": False,
        "Level Acceptance": False,
        "Close above open": True,
        "Range Qualifier": True,
        "magic touch event": True,
    },
    ("NVDA", "2025-06-02"): {
        "Support test": False,
        "Level Acceptance": False,
        "Close above open": True,
    },
}


def sheet_ak(i: int, o, h, lo, c, dk, dl, dm) -> bool:
    if not (np.isfinite(dk) and np.isfinite(dl) and np.isfinite(dm)):
        return False
    if i <= int(dm):
        return False
    ip = i - 1
    return bool(c[ip] > dl and lo[i] <= dl and h[i] >= dk)


def sheet_bg(i: int, ak_arr, c, de) -> bool:
    akt = ak_arr[i]
    aky = ak_arr[i - 1] if i >= 1 else False
    if not (akt or aky):
        return False
    anchor = de[i] if akt else de[i - 1]
    if not np.isfinite(anchor):
        return False
    s = max(0, i - 9)
    return int(np.sum(c[s : i + 1] > anchor)) >= 7


def sheet_bi(i: int, g) -> bool:
    bc_ok = g["bc"][i] or (g["bc"][i - 1] if i >= 1 else False)
    aq_ok = g["aq"][i] or (g["aq"][i - 1] if i >= 1 else False)
    return bool(g["bw"][i] and bc_ok and g["be"][i] and g["bg"][i] and aq_ok)


def overlap_zones(h, lo, mbh, mbi, i: int, n: int) -> list[tuple]:
    out = []
    for j in range(i + 1):
        if not (np.isfinite(mbh[j]) and mbh[j] > 0 and np.isfinite(mbi[j])):
            continue
        ce, cf = float(mbh[j]), float(mbi[j])
        if h[i] >= ce and lo[i] <= cf and i >= j:
            cnt = sum(
                1 for k in range(j, i + 1) if np.isfinite(mbh[k]) and mbh[k] > 0
            )
            out.append((j, ce, cf, cnt))
    return sorted(out, key=lambda x: x[0], reverse=True)


def trace_sym(sym: str, dates: list[str]) -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)

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

    print(f"\n{'=' * 78}\n{sym}\n{'=' * 78}")
    hdr = (
        "date       O      H      L      C | DK-DL (DM DN) | "
        "AK AM AQ BC BE BG BW BI | DO DP"
    )
    print(hdr)
    print("-" * len(hdr))

    ak_manual = np.zeros(n, dtype=bool)
    for i in range(n):
        if np.isfinite(de[i]) and np.isfinite(dfa[i]) and np.isfinite(dg[i]):
            ak_manual[i] = sheet_ak(i, o, h, lo, c, de[i], dfa[i], dg[i])

    for d in dates:
        if d not in {x.strftime("%Y-%m-%d") for x in df.index}:
            print(f"{d}  (missing from CSV)")
            continue
        i = df.index.get_loc(pd.Timestamp(d))
        z = f"{de[i]:.4f}-{dfa[i]:.4f}" if np.isfinite(de[i]) else "----"
        dm = int(dg[i]) if np.isfinite(dg[i]) else -1
        dn = int(ds[i]) if np.isfinite(ds[i]) else -1
        print(
            f"{d} {o[i]:6.2f} {h[i]:6.2f} {lo[i]:6.2f} {c[i]:6.2f} | "
            f"{z} ({dm} {dn}) | "
            f"{int(g['ak'][i])}  {int(g['am'][i])}  {int(g['aq'][i])}  "
            f"{int(g['bc'][i])}  {int(g['be'][i])}  {int(g['bg'][i])}  "
            f"{int(g['bw'][i])}  {int(g['bi'][i])} | {int(_do[i])}  {int(dp[i])}"
        )

    for d in dates:
        if d not in {x.strftime("%Y-%m-%d") for x in df.index}:
            continue
        i = df.index.get_loc(pd.Timestamp(d))
        key = (sym, d)
        print(f"\n--- {d} detail ---")
        print(f"Engine zone: DK={de[i]:.4f} DL={dfa[i]:.4f} DM={int(dg[i])} DN={int(ds[i])}")
        if key in SHEET_ZONE:
            sdk, sdl, sdm, sdn = SHEET_ZONE[key]
            print(
                f"Sheet zone:  DK={sdk:.4f} DL={sdl:.4f} DM={sdm} DN={sdn} "
                f"match={abs(de[i]-sdk)<0.02 and abs(dfa[i]-sdl)<0.02 and int(ds[i])==sdn}"
            )
        if i >= 1:
            ip = i - 1
            print(
                f"AK: Close[{df.index[ip].date()}]={c[ip]:.4f} > DL={dfa[i]:.4f}? "
                f"{c[ip] > dfa[i]} | L={lo[i]:.4f}<=DL? {lo[i] <= dfa[i]} | "
                f"H={h[i]:.4f}>=DK? {h[i] >= de[i]}"
            )
            print(
                f"    engine AK={int(g['ak'][i])} manual AK={int(ak_manual[i])} "
                f"BG={int(g['bg'][i])} BI={int(g['bi'][i])}"
            )
        sg = SHEET_GATES.get(key)
        if sg:
            print("Sheet paste gates:", sg)
            for gate, val in sg.items():
                eng_map = {
                    "Support test": g["ak"][i],
                    "Level Acceptance": g["bg"][i],
                    "MTS buy": g["bi"][i],
                    "Close above open": g["be"][i],
                    "Zone Eligible Long": g["aq"][i],
                    "Range Qualifier": g["bc"][i],
                    "magic touch event": g["aw"][i],
                }
                if gate in eng_map:
                    ev = bool(eng_map[gate])
                    mark = "OK" if ev == val else "MISMATCH"
                    print(f"  {gate}: sheet={val} engine={ev} {mark}")

        zones = overlap_zones(h, lo, mbh, mbi, i, n)
        print(f"Overlapping matured zones ({len(zones)}) — max row first:")
        for j, ce, cf, cnt in zones[:6]:
            ov_note = ""
            if lo[i] > cf:
                ov_note = f" NO-OVERLAP: L {lo[i]:.4f} > CF {cf:.4f}"
            print(
                f"  j={j} {df.index[j].date()} CE={ce:.4f} CF={cf:.4f} DN={cnt}"
                f"{ov_note}"
            )


def find_bi_bars(sym: str, start: str, end: str) -> None:
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
    print(f"\n{sym} BI=1 bars {start}..{end}:")
    for i, d in enumerate(df.index):
        if d < t0 or d > t1:
            continue
        if g["bi"][i]:
            fill = df["Open"].iloc[i + 1] if i + 1 < n else float("nan")
            print(
                f"  {d.date()} BI=1 DN={int(ds[i])} zone {de[i]:.2f}-{dfa[i]:.2f} "
                f"-> fill {df.index[i+1].date() if i+1<n else '?'} @ {fill:.2f}"
            )


def main() -> None:
    trace_sym(
        "NFLX",
        [
            "2019-10-09",
            "2019-10-10",
            "2019-10-11",
            "2019-10-14",
            "2019-10-15",
            "2019-10-18",
            "2019-10-21",
            "2019-10-22",
        ],
    )
    find_bi_bars("NFLX", "2019-09-20", "2019-10-25")

    trace_sym(
        "NVDA",
        [
            "2025-05-22",
            "2025-05-23",
            "2025-05-27",
            "2025-05-28",
            "2025-05-30",
            "2025-06-02",
            "2025-06-03",
        ],
    )
    find_bi_bars("NVDA", "2025-05-20", "2025-06-10")


if __name__ == "__main__":
    main()
