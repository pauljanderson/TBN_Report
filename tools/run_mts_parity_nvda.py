#!/usr/bin/env python3
"""Compare MTS NVDA closed trades (sheet-parity preset) vs STONK_DATA reference rows."""
from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

from rocket_brt import (  # noqa: E402
    BRTConfig,
    BRTTrade,
    build_level3_for_cfg,
    compute_market_structure,
    compute_pivots,
    load_csv,
    mts_sheet_parity_overrides,
    run_brt_backtest,
    _load_benchmark_local,
)


@dataclass
class SheetRow:
    entry_d: date
    entry_px: float
    exit_d: date
    exit_px: float
    pnl_pct: float
    days: int
    result: str


# Unlimited-zone sheet ground truth (MTS NVDA, 2016-01-01 start).
SHEET: list[SheetRow] = [
    SheetRow(date(2019, 4, 29), 4.45, date(2019, 5, 10), 4.10, -7.86, 11, "LOSS"),
    SheetRow(date(2019, 6, 4), 3.65, date(2019, 7, 24), 4.45, 22.00, 50, "WIN"),
    SheetRow(date(2019, 9, 17), 4.52, date(2019, 11, 25), 5.51, 22.00, 69, "WIN"),
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
    SheetRow(date(2024, 8, 8), 105.64, date(2024, 8, 19), 128.88, 22.00, 11, "WIN"),
    SheetRow(date(2025, 1, 28), 126.50, date(2025, 3, 7), 108.58, -14.17, 38, "LOSS"),
    SheetRow(date(2025, 3, 14), 122.74, date(2025, 3, 28), 110.35, -10.09, 14, "LOSS"),
    SheetRow(date(2025, 6, 2), 138.78, date(2025, 7, 15), 171.19, 23.35, 43, "WIN"),
]


def ymd(s: str) -> date:
    s = (s or "").replace("-", "")[:8]
    if len(s) < 8:
        return date.min
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def run_mts_nvda() -> list[BRTTrade]:
    data_dir = _REPO / "data" / "newdata" / "data"
    sym = "NVDA"
    base = asdict(BRTConfig())
    base.update(mts_sheet_parity_overrides())
    cfg = BRTConfig(**base)

    df = load_csv(str(data_dir / f"{sym}.csv"))
    benchmark_df = _load_benchmark_local(data_dir)
    ph, pl, php, plp = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = compute_market_structure(df, ph, pl, php, plp)
    l3 = build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    closed, *_ = run_brt_backtest(sym, df, cfg, php, plp, struct, l3, benchmark_df=benchmark_df)
    closed.sort(key=lambda t: t.date_opened)
    return closed


def match_cost(s: SheetRow, t: BRTTrade) -> float:
    ped = ymd(t.date_opened)
    dd = abs((ped - s.entry_d).days)
    pe = abs(t.entry_price - s.entry_px) / max(s.entry_px, 1e-9)
    return float(dd + pe * 120.0)


def main() -> int:
    py = run_mts_nvda()
    print(f"MTS sheet-parity NVDA closed trades: {len(py)}")
    print(f"Sheet reference rows: {len(SHEET)}")
    print()
    # Chronological 1:1 comparison (sheet order vs nearest Python trade by entry date).
    py_used: set[int] = set()
    for j, s in enumerate(SHEET, 1):
        best_i: Optional[int] = None
        best_c = 1e18
        for i, t in enumerate(py):
            if i in py_used:
                continue
            ped = ymd(t.date_opened)
            dd = abs((ped - s.entry_d).days)
            pe = abs(t.entry_price - s.entry_px) / max(s.entry_px, 1e-9)
            c = float(dd + pe * 120.0)
            if c < best_c:
                best_c = c
                best_i = i
        if best_i is not None:
            py_used.add(best_i)
            t = py[best_i]
            ped, pxd = ymd(t.date_opened), ymd(t.date_closed)
            tag = (
                "MATCH"
                if abs(t.pnl_pct - s.pnl_pct) < 1.5 and abs((ped - s.entry_d).days) <= 3
                else "LOOSE"
            )
            print(
                f"Sheet#{j:2d} {tag:5s}  entry {s.entry_d} ${s.entry_px:.2f} pnl {s.pnl_pct:+.2f}%  "
                f"-> Py entry {ped} ${t.entry_price:.2f} pnl {t.pnl_pct:+.2f}%"
            )
        else:
            print(f"Sheet#{j:2d} MISS   entry {s.entry_d} ${s.entry_px:.2f} pnl {s.pnl_pct:+.2f}%")
    extras = [i for i in range(len(py)) if i not in py_used]
    if extras:
        print("\nPython extras (no sheet match):")
        for i in extras:
            t = py[i]
            ped = ymd(t.date_opened)
            print(f"  Py entry {ped} ${t.entry_price:.2f} pnl {t.pnl_pct:+.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
