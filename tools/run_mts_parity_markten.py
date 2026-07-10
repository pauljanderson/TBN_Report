#!/usr/bin/env python3
"""
MarkTen (Mag7 + AU + AMD + NFLX) MTS sheet-parity check.

Compares rocket_brt --mts-sheet-parity closed trades against user-provided
STONK_DATA reference rows. Add reference rows to REFERENCE as the user supplies them.

Usage:
    python tools/run_mts_parity_markten.py             # all symbols with reference data
    python tools/run_mts_parity_markten.py NVDA AAPL   # subset
"""
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


MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]

# STONK_DATA reference rows (Trigger Date = signal bar; entry fills next session).
REFERENCE: dict[str, list[SheetRow]] = {
    "AAPL": [
        SheetRow(date(2022, 9, 1), 159.75, date(2022, 9, 29), 144.46, -9.57, 28, "LOSS"),
    ],
    "AMZN": [
        SheetRow(date(2019, 4, 15), 92.57, date(2019, 6, 3), 84.95, -8.23, 49, "LOSS"),
        SheetRow(date(2020, 11, 3), 158.00, date(2022, 1, 24), 139.00, -12.03, 447, "LOSS"),
        SheetRow(date(2022, 2, 24), 150.55, date(2022, 4, 29), 129.85, -13.75, 64, "LOSS"),
        SheetRow(date(2022, 6, 15), 104.47, date(2022, 7, 29), 134.90, 29.13, 44, "WIN"),
        SheetRow(date(2022, 9, 22), 116.00, date(2022, 10, 13), 107.88, -7.00, 21, "LOSS"),
        SheetRow(date(2022, 10, 19), 113.83, date(2022, 10, 28), 97.91, -13.99, 9, "LOSS"),
    ],
    "META": [
        SheetRow(date(2021, 5, 11), 301.13, date(2021, 7, 23), 367.38, 22.00, 73, "WIN"),
    ],
    "NVDA": [
        SheetRow(date(2019, 4, 29), 4.45, date(2019, 5, 10), 4.10, -7.86, 11, "LOSS"),
        SheetRow(date(2019, 6, 4), 3.65, date(2019, 7, 24), 4.45, 22.00, 50, "WIN"),
        SheetRow(date(2019, 9, 16), 4.51, date(2019, 11, 25), 5.50, 22.00, 70, "WIN"),
        SheetRow(date(2021, 5, 11), 14.01, date(2021, 6, 3), 17.09, 22.00, 23, "WIN"),
        SheetRow(date(2022, 3, 8), 22.39, date(2022, 3, 24), 27.32, 22.00, 16, "WIN"),
        SheetRow(date(2022, 4, 13), 22.51, date(2022, 4, 21), 20.04, -10.96, 8, "LOSS"),
        SheetRow(date(2022, 5, 25), 16.04, date(2022, 6, 2), 19.57, 22.00, 8, "WIN"),
        SheetRow(date(2022, 6, 14), 16.10, date(2022, 7, 1), 14.39, -10.60, 17, "LOSS"),
        SheetRow(date(2022, 7, 8), 15.53, date(2022, 8, 3), 18.95, 22.00, 26, "WIN"),
        SheetRow(date(2022, 8, 8), 17.25, date(2022, 8, 29), 16.02, -7.13, 21, "LOSS"),
        SheetRow(date(2022, 10, 25), 12.87, date(2022, 11, 10), 15.70, 22.00, 16, "WIN"),
        SheetRow(date(2022, 12, 28), 14.40, date(2023, 1, 17), 17.57, 22.00, 20, "WIN"),
        SheetRow(date(2023, 1, 31), 19.69, date(2023, 3, 6), 24.02, 22.00, 34, "WIN"),
        SheetRow(date(2024, 8, 8), 105.64, date(2024, 8, 19), 128.88, 22.00, 11, "WIN"),
        SheetRow(date(2025, 1, 28), 126.50, date(2025, 3, 7), 108.58, -14.17, 38, "LOSS"),
    ],
}


def ymd(s: str) -> date:
    s = (s or "").replace("-", "")[:8]
    if len(s) < 8:
        return date.min
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def run_symbol(sym: str, cfg: BRTConfig, data_dir: Path, benchmark_df) -> list[BRTTrade]:
    df = load_csv(str(data_dir / f"{sym}.csv"))
    ph, pl, php, plp = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = compute_market_structure(df, ph, pl, php, plp)
    l3 = build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    closed, *_ = run_brt_backtest(sym, df, cfg, php, plp, struct, l3, benchmark_df=benchmark_df)
    closed.sort(key=lambda t: t.date_opened)
    return closed


def _price_close(a: float, b: float, rel: float = 0.03) -> bool:
    if a == 0 or b == 0:
        return abs(a - b) < 1e-6
    return abs(a - b) / max(abs(a), abs(b)) <= rel


def compare(sym: str, py: list[BRTTrade], sheet: list[SheetRow]) -> tuple[int, int, int]:
    """Greedy match by entry date (±3 sessions) + price (±3%). Returns (matched, extra, missing)."""
    used: set[int] = set()
    matched = 0
    print(f"\n=== {sym} : python {len(py)} vs sheet {len(sheet)} ===")
    for i, t in enumerate(py, 1):
        ped = ymd(t.date_opened)
        best_j: Optional[int] = None
        best_c = 1e18
        for j, s in enumerate(sheet):
            if j in used:
                continue
            dd = abs((ped - s.entry_d).days)
            if dd > 6:
                continue
            pe = abs(t.entry_price - s.entry_px) / max(s.entry_px, 1e-9)
            c = dd + pe * 120.0
            if c < best_c:
                best_c = c
                best_j = j
        if best_j is not None:
            used.add(best_j)
            s = sheet[best_j]
            ok = _price_close(t.entry_price, s.entry_px) and abs((ped - s.entry_d).days) <= 3
            if ok:
                matched += 1
            tag = "MATCH" if ok else "NEAR"
            print(
                f"  {tag:5s} py {ped} ${t.entry_price:8.2f} {t.pnl_pct:+6.2f}%  "
                f"<-> sheet {s.entry_d} ${s.entry_px:8.2f} {s.pnl_pct:+6.2f}%"
            )
        else:
            print(f"  EXTRA py {ped} ${t.entry_price:8.2f} {t.pnl_pct:+6.2f}%")
    missing = [j for j in range(len(sheet)) if j not in used]
    for j in missing:
        s = sheet[j]
        print(f"  MISS  sheet {s.entry_d} ${s.entry_px:8.2f} {s.pnl_pct:+6.2f}% ({s.result})")
    extra = len(py) - len(used)
    return matched, extra, len(missing)


def main() -> int:
    args = [a.upper() for a in sys.argv[1:]]
    symbols = args or [s for s in MARKTEN if s in REFERENCE]
    data_dir = _REPO / "data" / "newdata" / "data"
    benchmark_df = _load_benchmark_local(data_dir)
    base = asdict(BRTConfig())
    base.update(mts_sheet_parity_overrides())
    cfg = BRTConfig(**base)

    tot_m = tot_e = tot_x = 0
    rows = []
    for sym in symbols:
        ref = REFERENCE.get(sym, [])
        if not ref:
            print(f"\n=== {sym} : (no reference rows yet) ===")
        try:
            py = run_symbol(sym, cfg, data_dir, benchmark_df)
        except FileNotFoundError:
            print(f"  [skip] no data CSV for {sym}")
            continue
        m, x, mi = compare(sym, py, ref)
        tot_m += m
        tot_x += x
        tot_x += 0
        tot_e += mi
        rows.append((sym, len(py), len(ref), m, x, mi))

    print("\n================ SUMMARY ================")
    print(f"{'SYM':6s} {'PY':>4s} {'SHEET':>6s} {'MATCH':>6s} {'EXTRA':>6s} {'MISS':>5s}")
    for sym, npy, nsh, m, x, mi in rows:
        print(f"{sym:6s} {npy:4d} {nsh:6d} {m:6d} {x:6d} {mi:5d}")
    print(f"\nTOTAL matched={tot_m}  extra={sum(r[4] for r in rows)}  missing={tot_e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
