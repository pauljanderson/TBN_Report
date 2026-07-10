#!/usr/bin/env python3
"""Deep-dive TSLA MTS parity: trades, gates, zones for every mismatch."""
from __future__ import annotations

import difflib
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

DATA = _REPO / "data" / "newdata" / "data"
CE_FILE = _REPO / "sheet_ce_ground_truth" / "TSLA_ce.txt"


@dataclass
class SheetTrade:
    trigger_d: date
    entry_px: float
    exit_d: date
    exit_px: float
    pnl_pct: float
    days: int
    result: str


SHEET: list[SheetTrade] = [
    SheetTrade(date(2019, 1, 2), 20.47, date(2019, 3, 5), 18.61, -9.11, 62, "LOSS"),
    SheetTrade(date(2019, 4, 3), 17.46, date(2019, 4, 4), 17.46, 0.00, 1, "LOSS"),
    SheetTrade(date(2019, 4, 16), 18.32, date(2019, 4, 25), 16.49, -10.02, 9, "LOSS"),
    SheetTrade(date(2019, 10, 22), 16.97, date(2019, 10, 25), 20.70, 22.00, 3, "WIN"),
    SheetTrade(date(2019, 11, 19), 24.00, date(2020, 1, 3), 29.37, 22.38, 45, "WIN"),
    SheetTrade(date(2021, 3, 19), 228.20, date(2021, 5, 13), 194.47, -14.78, 55, "LOSS"),
    SheetTrade(date(2021, 5, 27), 209.50, date(2021, 6, 3), 191.84, -8.43, 7, "LOSS"),
    SheetTrade(date(2021, 12, 21), 321.89, date(2022, 1, 3), 392.71, 22.00, 13, "WIN"),
    SheetTrade(date(2022, 1, 24), 304.73, date(2022, 1, 28), 265.09, -13.01, 4, "LOSS"),
    SheetTrade(date(2022, 1, 31), 311.74, date(2022, 2, 22), 268.38, -13.91, 22, "LOSS"),
    SheetTrade(date(2022, 3, 8), 279.83, date(2022, 3, 23), 341.39, 22.00, 15, "WIN"),
    SheetTrade(date(2022, 4, 18), 335.02, date(2022, 4, 26), 303.05, -9.54, 8, "LOSS"),
    SheetTrade(date(2022, 6, 7), 240.09, date(2022, 6, 13), 214.90, -10.49, 6, "LOSS"),
    SheetTrade(date(2022, 6, 17), 224.60, date(2022, 7, 22), 276.22, 22.98, 35, "WIN"),
    SheetTrade(date(2022, 9, 1), 281.07, date(2022, 10, 3), 248.58, -11.56, 32, "LOSS"),
    SheetTrade(date(2022, 11, 28), 184.99, date(2022, 12, 13), 167.19, -9.62, 15, "LOSS"),
    SheetTrade(date(2023, 2, 17), 204.99, date(2023, 3, 8), 184.47, -10.01, 19, "LOSS"),
    SheetTrade(date(2023, 3, 14), 180.80, date(2023, 4, 20), 165.45, -8.49, 37, "LOSS"),
    SheetTrade(date(2023, 4, 21), 164.65, date(2023, 5, 30), 200.87, 22.00, 39, "WIN"),
    SheetTrade(date(2023, 6, 27), 249.70, date(2023, 8, 17), 224.95, -9.91, 51, "LOSS"),
    SheetTrade(date(2023, 8, 18), 221.55, date(2023, 9, 11), 270.29, 22.00, 24, "WIN"),
    SheetTrade(date(2023, 9, 19), 267.04, date(2023, 9, 25), 243.38, -8.86, 6, "LOSS"),
    SheetTrade(date(2023, 9, 26), 244.26, date(2023, 10, 19), 225.71, -7.59, 23, "LOSS"),
    SheetTrade(date(2023, 10, 23), 216.50, date(2023, 12, 28), 264.13, 22.00, 66, "WIN"),
    SheetTrade(date(2024, 7, 12), 255.97, date(2024, 7, 24), 217.71, -14.95, 12, "LOSS"),
    SheetTrade(date(2024, 7, 25), 221.19, date(2024, 8, 5), 185.22, -16.26, 11, "LOSS"),
    SheetTrade(date(2025, 10, 23), 446.83, date(2025, 11, 14), 386.30, -13.55, 22, "LOSS"),
    SheetTrade(date(2025, 11, 24), 414.42, date(2026, 3, 20), 374.62, -9.60, 116, "LOSS"),
]


def ymd(s: str) -> date:
    s = str(s).replace("-", "")[:8]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def dstr(d: date) -> str:
    return d.isoformat()


def load_engine():
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(DATA / "TSLA.csv"))
    iso = [str(x).replace("-", "")[:8] for x in df.index]
    idx = {f"{s[:4]}-{s[4:6]}-{s[6:8]}": i for i, s in enumerate(iso)}
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    n = len(df)
    o, h, lo, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
    mbh, mbi = rb._precompute_mat_bh_bi_stream(
        l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
    )
    de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
    g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
    closed, *_ = rb.run_brt_backtest(
        "TSLA", df, cfg, php, plp, struct, l3,
        benchmark_df=rb._load_benchmark_local(DATA),
    )
    closed.sort(key=lambda t: t.date_opened)
    return cfg, df, iso, idx, l3, mbh, mbi, de, dfa, dg, ds, g, closed


def gate_row(g, ds, de, dfa, dg, i, label=""):
    dn = int(ds[i]) if np.isfinite(ds[i]) else None
    z = f"${de[i]:.2f}-${dfa[i]:.2f}" if np.isfinite(de[i]) else "----"
    dm = int(dg[i]) + 2 if np.isfinite(dg[i]) else None
    print(
        f"  {label:12s} AK={int(g['ak'][i])} AM={int(g['am'][i])} AQ={int(g['aq'][i])} "
        f"AW={int(g['aw'][i])} BC={int(g['bc'][i])} BE={int(g['be'][i])} "
        f"BG={int(g['bg'][i])} BW={int(g['bw'][i])} BI={int(g['bi'][i])}  "
        f"zone {z} DM{dm} DN{dn}"
    )


def match_trades(py, sheet):
    used_py: set[int] = set()
    used_sh: set[int] = set()
    pairs = []
    for j, s in enumerate(sheet):
        best_i, best_c = None, 1e18
        for i, t in enumerate(py):
            if i in used_py:
                continue
            ped = ymd(t.date_opened)
            dd = abs((ped - s.trigger_d).days)
            pe = abs(t.entry_price - s.entry_px) / max(s.entry_px, 1e-9)
            c = dd + pe * 80.0 + abs(t.pnl_pct - s.pnl_pct) * 2.0
            if c < best_c:
                best_c, best_i = c, i
        if best_i is not None and best_c < 80:
            used_py.add(best_i)
            used_sh.add(j)
            pairs.append((j, best_i, best_c))
    return pairs, used_py, used_sh


def ce_diff():
    sheet = [ln.strip() for ln in CE_FILE.read_text().splitlines() if ln.strip()]
    _, _, iso, _, l3, mbh, *_ = load_engine()
    eng, meta = [], []
    for i, s in enumerate(iso):
        if np.isfinite(mbh[i]) and mbh[i] > 0:
            eng.append(f"{mbh[i]:.2f}")
            meta.append((i, s))
    sm = difflib.SequenceMatcher(a=sheet, b=eng, autojunk=False)
    print(f"\n{'='*70}\nCE STREAM: sheet {len(sheet)} vs engine {len(eng)}  ratio={sm.ratio():.4f}\n")
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            for k in range(i1, i2):
                print(f"  SHEET-ONLY CE={sheet[k]}  [sheet idx {k}]")
        if tag in ("replace", "insert"):
            for k in range(j1, j2):
                b, d = meta[k]
                dd = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                tp = l3["touch_price"].iloc[b - 7] if b >= 7 else np.nan
                print(f"  ENGINE-ONLY CE={eng[k]} matured {dd} bar{b} piv_tp={tp}")


def trace_window(idx, g, ds, de, dfa, dg, iso, start, end, title):
    print(f"\n--- {title} ({start} .. {end}) ---")
    for d in sorted(idx.keys()):
        if d < start or d > end:
            continue
        i = idx[d]
        if g["bi"][i] or g["aw"][i] or g["ak"][i]:
            gate_row(g, ds, de, dfa, dg, i, d)


def main():
    cfg, df, iso, idx, l3, mbh, mbi, de, dfa, dg, ds, g, py = load_engine()
    print(f"Engine closed trades: {len(py)}  Sheet reference: {len(SHEET)}")

    pairs, used_py, used_sh = match_trades(py, SHEET)
    print(f"\n{'='*70}\nTRADE-BY-TRADE COMPARISON\n")
    exact = loose = 0
    for j, i, _ in pairs:
        s, t = SHEET[j], py[i]
        ped, pxd = ymd(t.date_opened), ymd(t.date_closed)
        ok = abs(t.pnl_pct - s.pnl_pct) < 1.5 and abs((ped - s.trigger_d).days) <= 3
        if ok:
            exact += 1
            tag = "EXACT"
        else:
            loose += 1
            tag = "LOOSE"
        print(
            f"#{j+1:2d} {tag:5s} sheet {s.trigger_d} ${s.entry_px:7.2f} {s.pnl_pct:+7.2f}%  "
            f"-> py {ped} ${t.entry_price:7.2f} {t.pnl_pct:+7.2f}%  "
            f"(d_entry={(ped-s.trigger_d).days}d d_pnl={t.pnl_pct-s.pnl_pct:+.2f}%)"
        )

    print(f"\nMatched pairs: {len(pairs)}  EXACT={exact} LOOSE={loose}")
    print("\nSHEET MISSES (no python match):")
    for j, s in enumerate(SHEET):
        if j not in used_sh:
            print(f"  #{j+1} {s.trigger_d} ${s.entry_px:.2f} {s.pnl_pct:+.2f}% {s.result}")

    print("\nPYTHON EXTRAS (no sheet match):")
    for i, t in enumerate(py):
        if i not in used_py:
            ped = ymd(t.date_opened)
            print(f"  py {ped} ${t.entry_price:.2f} {t.pnl_pct:+.2f}% exit {ymd(t.date_closed)}")

    ce_diff()

    # Deep traces for key mismatches
    traces = [
        ("2018-12-20", "2019-01-15", "MISS #1 Jan-2019 entry"),
        ("2019-01-25", "2019-02-15", "EXTRA Feb-2019"),
        ("2019-06-25", "2019-07-25", "EXTRA Jul-2019"),
        ("2021-12-10", "2022-01-10", "MISS #8 Dec-2021 WIN"),
        ("2022-06-10", "2022-06-25", "LOOSE #14 Jun-17 WIN"),
        ("2023-02-10", "2023-02-25", "LOOSE #17 Feb-17"),
        ("2023-09-10", "2023-10-05", "MISS #22 Sep-19 + nearby"),
        ("2025-02-20", "2025-03-10", "EXTRA Mar-2025"),
    ]
    print(f"\n{'='*70}\nGATE TRACES (BI/AW/AK bars)\n")
    for start, end, title in traces:
        trace_window(idx, g, ds, de, dfa, dg, iso, start, end, title)

    # BI true bars not in sheet reference
    print(f"\n{'='*70}\nALL ENGINE BI=TRUE BARS (entry candidates)\n")
    for i, s in enumerate(iso):
        if not g["bi"][i]:
            continue
        d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        # find if any sheet trade within 5d
        dd_min = min(abs((date(int(s[:4]), int(s[4:6]), int(s[6:8])) - st.trigger_d).days) for st in SHEET)
        flag = "" if dd_min <= 5 else " <- NO SHEET TRADE"
        gate_row(g, ds, de, dfa, dg, i, d + flag)


if __name__ == "__main__":
    main()
