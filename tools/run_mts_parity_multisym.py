#!/usr/bin/env python3
"""MTS sheet-parity for AAPL, AMZN, META, GOOGL, MSFT, NFLX, NVDA, TSLA."""
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

from rocket_brt import (  # noqa: E402
    BRTConfig,
    BRTTrade,
    _load_benchmark_local,
    _precompute_mat_bh_bi_stream,
    build_level3_for_cfg,
    compute_market_structure,
    compute_pivots,
    load_csv,
    mts_sheet_parity_overrides,
    run_brt_backtest,
)

DATA_DIR = _REPO / "data" / "newdata" / "data"
CE_DIR = _REPO / "sheet_ce_ground_truth"


@dataclass
class SheetRow:
    entry_d: date
    entry_px: float
    exit_d: date
    exit_px: float
    pnl_pct: float
    days: int
    result: str


REFERENCE: dict[str, list[SheetRow]] = {
    "AAPL": [
        SheetRow(date(2022, 9, 1), 159.75, date(2022, 9, 29), 144.46, -9.57, 28, "LOSS"),
    ],
    "AMZN": [
        SheetRow(date(2019, 4, 15), 92.57, date(2019, 6, 3), 84.95, -8.23, 49, "LOSS"),
        SheetRow(date(2020, 11, 3), 158.00, date(2022, 1, 24), 139.00, -12.03, 447, "LOSS"),
        SheetRow(date(2022, 2, 24), 150.55, date(2022, 4, 29), 129.85, -13.75, 64, "LOSS"),
        SheetRow(date(2022, 6, 15), 104.47, date(2022, 7, 29), 134.90, 29.13, 44, "WIN"),
        SheetRow(date(2022, 8, 23), 132.75, date(2022, 9, 1), 124.18, -6.46, 9, "LOSS"),
        SheetRow(date(2022, 9, 22), 116.00, date(2022, 10, 13), 107.88, -7.00, 21, "LOSS"),
        SheetRow(date(2022, 10, 19), 113.83, date(2022, 10, 28), 97.91, -13.99, 9, "LOSS"),
        SheetRow(date(2023, 1, 26), 99.53, date(2023, 3, 2), 90.52, -9.05, 35, "LOSS"),
    ],
    "META": [
        SheetRow(date(2021, 5, 11), 301.13, date(2021, 7, 23), 367.38, 22.00, 73, "WIN"),
    ],
    "GOOGL": [
        SheetRow(date(2023, 5, 31), 122.82, date(2024, 1, 24), 149.84, 22.00, 238, "WIN"),
    ],
    "MSFT": [
        SheetRow(date(2023, 4, 6), 289.21, date(2023, 7, 18), 352.84, 22.00, 103, "WIN"),
    ],
    "NFLX": [
        SheetRow(date(2019, 2, 8), 35.00, date(2019, 7, 19), 31.57, -9.80, 161, "LOSS"),
        SheetRow(date(2019, 10, 14), 28.38, date(2020, 1, 23), 34.62, 22.00, 101, "WIN"),
        SheetRow(date(2020, 1, 30), 34.74, date(2020, 3, 12), 31.68, -8.80, 42, "LOSS"),
        SheetRow(date(2020, 3, 13), 30.66, date(2020, 3, 30), 37.41, 22.00, 17, "WIN"),
        SheetRow(date(2020, 4, 13), 39.75, date(2020, 7, 1), 48.50, 22.00, 79, "WIN"),
    ],
    "NVDA": [
        SheetRow(date(2019, 4, 29), 4.45, date(2019, 5, 10), 4.10, -7.86, 11, "LOSS"),
        SheetRow(date(2019, 6, 4), 3.65, date(2019, 7, 24), 4.45, 22.00, 50, "WIN"),
        SheetRow(date(2019, 9, 16), 4.51, date(2019, 11, 25), 5.50, 22.00, 70, "WIN"),
        SheetRow(date(2019, 12, 3), 5.28, date(2020, 1, 24), 6.44, 22.00, 52, "WIN"),
        SheetRow(date(2020, 3, 18), 5.05, date(2020, 3, 24), 6.16, 22.00, 6, "WIN"),
        SheetRow(date(2021, 5, 11), 14.01, date(2021, 6, 3), 17.09, 22.00, 23, "WIN"),
        SheetRow(date(2022, 3, 8), 22.39, date(2022, 3, 24), 27.32, 22.00, 16, "WIN"),
        SheetRow(date(2022, 4, 13), 22.51, date(2022, 4, 21), 20.04, -10.96, 8, "LOSS"),
        SheetRow(date(2022, 5, 25), 16.04, date(2022, 6, 2), 19.57, 22.00, 8, "WIN"),
        SheetRow(date(2022, 6, 14), 16.10, date(2022, 7, 1), 14.39, -10.60, 17, "LOSS"),
        SheetRow(date(2022, 7, 8), 15.53, date(2022, 8, 3), 18.95, 22.00, 26, "WIN"),
        SheetRow(date(2022, 8, 8), 17.25, date(2022, 8, 29), 16.02, -7.13, 21, "LOSS"),
        SheetRow(date(2022, 10, 25), 12.87, date(2022, 11, 10), 15.70, 22.00, 16, "WIN"),
        SheetRow(date(2023, 1, 31), 19.69, date(2023, 3, 6), 24.02, 22.00, 34, "WIN"),
        SheetRow(date(2023, 5, 5), 28.52, date(2023, 5, 25), 38.52, 35.06, 20, "WIN"),
        SheetRow(date(2024, 8, 5), 103.84, date(2024, 8, 19), 126.68, 22.00, 14, "WIN"),
        SheetRow(date(2025, 1, 28), 126.50, date(2025, 3, 7), 108.58, -14.17, 38, "LOSS"),
        SheetRow(date(2025, 3, 14), 122.74, date(2025, 3, 28), 110.35, -10.09, 14, "LOSS"),
        SheetRow(date(2025, 6, 2), 138.78, date(2025, 7, 15), 171.19, 23.35, 43, "WIN"),
    ],
    "TSLA": [
        SheetRow(date(2019, 1, 2), 20.47, date(2019, 3, 5), 18.61, -9.11, 62, "LOSS"),
        SheetRow(date(2019, 4, 3), 17.46, date(2019, 4, 4), 17.46, 0.00, 1, "LOSS"),
        SheetRow(date(2019, 4, 16), 18.32, date(2019, 4, 25), 16.49, -10.02, 9, "LOSS"),
        SheetRow(date(2019, 10, 22), 16.97, date(2019, 10, 25), 20.70, 22.00, 3, "WIN"),
        SheetRow(date(2019, 11, 19), 24.00, date(2020, 1, 3), 29.37, 22.38, 45, "WIN"),
        SheetRow(date(2021, 3, 19), 228.20, date(2021, 5, 13), 194.47, -14.78, 55, "LOSS"),
        SheetRow(date(2021, 5, 27), 209.50, date(2021, 6, 3), 191.84, -8.43, 7, "LOSS"),
        SheetRow(date(2021, 12, 21), 321.89, date(2022, 1, 3), 392.71, 22.00, 13, "WIN"),
        SheetRow(date(2022, 1, 24), 304.73, date(2022, 1, 28), 265.09, -13.01, 4, "LOSS"),
        SheetRow(date(2022, 1, 31), 311.74, date(2022, 2, 22), 268.38, -13.91, 22, "LOSS"),
        SheetRow(date(2022, 3, 8), 279.83, date(2022, 3, 23), 341.39, 22.00, 15, "WIN"),
        SheetRow(date(2022, 4, 18), 335.02, date(2022, 4, 26), 303.05, -9.54, 8, "LOSS"),
        SheetRow(date(2022, 6, 7), 240.09, date(2022, 6, 13), 214.90, -10.49, 6, "LOSS"),
        SheetRow(date(2022, 6, 17), 224.60, date(2022, 7, 22), 276.22, 22.98, 35, "WIN"),
        SheetRow(date(2022, 9, 1), 281.07, date(2022, 10, 3), 248.58, -11.56, 32, "LOSS"),
        SheetRow(date(2022, 11, 28), 184.99, date(2022, 12, 13), 167.19, -9.62, 15, "LOSS"),
        SheetRow(date(2023, 2, 17), 204.99, date(2023, 3, 8), 184.47, -10.01, 19, "LOSS"),
        SheetRow(date(2023, 3, 14), 180.80, date(2023, 4, 20), 165.45, -8.49, 37, "LOSS"),
        SheetRow(date(2023, 4, 21), 164.65, date(2023, 5, 30), 200.87, 22.00, 39, "WIN"),
        SheetRow(date(2023, 6, 27), 249.70, date(2023, 8, 17), 224.95, -9.91, 51, "LOSS"),
        SheetRow(date(2023, 8, 18), 221.55, date(2023, 9, 11), 270.29, 22.00, 24, "WIN"),
        SheetRow(date(2023, 9, 19), 267.04, date(2023, 9, 25), 243.38, -8.86, 6, "LOSS"),
        SheetRow(date(2023, 9, 26), 244.26, date(2023, 10, 19), 225.71, -7.59, 23, "LOSS"),
        SheetRow(date(2023, 10, 23), 216.50, date(2023, 12, 28), 264.13, 22.00, 66, "WIN"),
        SheetRow(date(2024, 7, 12), 255.97, date(2024, 7, 24), 217.71, -14.95, 12, "LOSS"),
        SheetRow(date(2024, 7, 25), 221.19, date(2024, 8, 5), 185.22, -16.26, 11, "LOSS"),
        SheetRow(date(2025, 3, 4), 272.92, date(2025, 3, 10), 244.56, -10.39, 6, "LOSS"),
        SheetRow(date(2025, 10, 23), 446.83, date(2025, 11, 14), 386.30, -13.55, 22, "LOSS"),
        SheetRow(date(2025, 11, 24), 414.42, date(2026, 3, 20), 374.62, -9.60, 116, "LOSS"),
    ],
}


def ymd(s: str) -> date:
    s = (s or "").replace("-", "")[:8]
    if len(s) < 8:
        return date.min
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def trigger_date(t: BRTTrade) -> date:
    """Sheet Trigger Date = MTS buy (BI) signal bar, stored as close_above_date."""
    cad = getattr(t, "close_above_date", "") or ""
    if cad:
        d = ymd(cad)
        if d != date.min:
            return d
    return ymd(t.date_opened)


def fill_date(t: BRTTrade) -> date:
    """Fill date = next-session open after the BI signal bar."""
    return ymd(t.date_opened)


def run_symbol(sym: str, cfg: BRTConfig, benchmark_df) -> list[BRTTrade]:
    df = load_csv(str(DATA_DIR / f"{sym}.csv"))
    ph, pl, php, plp = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = compute_market_structure(df, ph, pl, php, plp)
    l3 = build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    closed, *_ = run_brt_backtest(sym, df, cfg, php, plp, struct, l3, benchmark_df=benchmark_df)
    closed.sort(key=lambda t: t.date_opened)
    return closed


def compare_trades(sym: str, py: list[BRTTrade], sheet: list[SheetRow]) -> tuple[int, int, int]:
    used: set[int] = set()
    matched = 0
    paired_py = 0
    print(f"\n=== {sym} TRADES: python {len(py)} vs sheet {len(sheet)} ===")
    for t in py:
        trig = trigger_date(t)
        fill = fill_date(t)
        best_j: Optional[int] = None
        best_c = 1e18
        for j, s in enumerate(sheet):
            if j in used:
                continue
            # Sheet Trigger Date + Entry Price (fill at next open after BI signal).
            dd = abs((trig - s.entry_d).days)
            pe = abs(t.entry_price - s.entry_px) / max(s.entry_px, 1e-9)
            c = dd + pe * 120.0
            if c < best_c:
                best_c = c
                best_j = j
        if best_j is not None and best_c < 50:
            used.add(best_j)
            paired_py += 1
            s = sheet[best_j]
            pe = abs(t.entry_price - s.entry_px) / max(s.entry_px, 1e-9)
            ok = (
                abs(t.pnl_pct - s.pnl_pct) < 2.0
                and abs((trig - s.entry_d).days) <= 1
                and pe < 0.02
            )
            if ok:
                matched += 1
            tag = "MATCH" if ok else "LOOSE"
            print(
                f"  {tag:5s} sheet {s.entry_d} ${s.entry_px:8.2f} {s.pnl_pct:+7.2f}%  "
                f"-> py trig {trig} fill {fill} ${t.entry_price:8.2f} {t.pnl_pct:+7.2f}%"
            )
        else:
            print(
                f"  EXTRA py trig {trig} fill {fill} ${t.entry_price:8.2f} {t.pnl_pct:+7.2f}%"
            )
    for j, s in enumerate(sheet):
        if j not in used:
            print(f"  MISS  sheet {s.entry_d} ${s.entry_px:8.2f} {s.pnl_pct:+7.2f}%")
    extra = len(py) - paired_py
    missing = len(sheet) - len(used)
    return matched, extra, missing


def load_sheet_ce(sym: str) -> list[str]:
    p = CE_DIR / f"{sym}_ce.txt"
    if not p.exists():
        return []
    vals = []
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        vals.append(f"{float(ln.replace('$', '')):.2f}")
    return vals


def compare_ce(sym: str, cfg: BRTConfig) -> float | None:
    sheet = load_sheet_ce(sym)
    if not sheet:
        return None
    df = load_csv(str(DATA_DIR / f"{sym}.csv"))
    ph, pl, php, plp = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    n = len(df)
    mbh, _ = _precompute_mat_bh_bi_stream(
        l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
    )
    eng = [f"{mbh[i]:.2f}" for i in range(n) if np.isfinite(mbh[i]) and mbh[i] > 0]
    sm = difflib.SequenceMatcher(a=sheet, b=eng, autojunk=False)
    print(f"\n=== {sym} ZONES: sheet {len(sheet)} vs engine {len(eng)}  ratio={sm.ratio():.3f} ===")
    n_diff = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            for k in range(i1, min(i2, i1 + 3)):
                print(f"  sheet-only zone={sheet[k]}")
                n_diff += 1
        if tag in ("replace", "insert"):
            for k in range(j1, min(j2, j1 + 3)):
                print(f"  engine-only zone={eng[k]}")
                n_diff += 1
    if n_diff == 0:
        print("  (perfect zone sequence match)")
    return sm.ratio() * 100.0


def main() -> int:
    syms = [a.upper() for a in sys.argv[1:]] if len(sys.argv) > 1 else list(REFERENCE.keys())
    benchmark_df = _load_benchmark_local(DATA_DIR)
    base = asdict(BRTConfig())
    base.update(mts_sheet_parity_overrides())
    cfg = BRTConfig(**base)

    rows = []
    ce_rows = []
    for sym in syms:
        ref = REFERENCE.get(sym, [])
        try:
            py = run_symbol(sym, cfg, benchmark_df)
        except FileNotFoundError:
            print(f"\n=== {sym}: no CSV ===")
            continue
        m, x, mi = compare_trades(sym, py, ref)
        ce_ratio = compare_ce(sym, cfg)
        rows.append((sym, len(py), len(ref), m, x, mi))
        ce_rows.append((sym, ce_ratio))

    print("\n================ SUMMARY ================")
    print(f"{'SYM':6s} {'PY':>4s} {'SHT':>4s} {'MATCH':>6s} {'EXTRA':>6s} {'MISS':>5s} {'ZONE%':>6s}")
    for (sym, npy, nsh, m, x, mi), (_, cr) in zip(rows, ce_rows):
        ce_s = f"{cr:.1f}" if cr is not None else "n/a"
        print(f"{sym:6s} {npy:4d} {nsh:4d} {m:6d} {x:6d} {mi:5d} {ce_s:>6s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
