"""
Side-by-side: STONK_DATA sheet trades (user-provided) vs rocket_brt NVDA run.

Matching: each Python closed trade maps to one sheet row (closest unused sheet row by entry date + price).
Unmatched sheet rows = sheet trades with no Python counterpart under this config.

Run: python compare_nvda_sheet_vs_python.py
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

from rocket_brt_og import (
    BRTConfig,
    BRTTrade,
    load_csv,
    compute_pivots,
    compute_market_structure,
    compute_touch_stream,
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


# User sheet (STONK_DATA) — NVDA
SHEET: list[SheetRow] = [
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
]


def yyyymmdd_to_date(s: str) -> date:
    if not s or len(s) < 8:
        return date.min
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def trade_to_date(t: BRTTrade) -> tuple[date, date]:
    return yyyymmdd_to_date(t.date_opened), yyyymmdd_to_date(t.date_closed)


def px_close(a: float, b: float, rel: float = 0.02) -> bool:
    if a == 0 or b == 0:
        return abs(a - b) < 1e-6
    return abs(a - b) / max(abs(a), abs(b)) <= rel


def outcome(py: BRTTrade) -> str:
    return "WIN" if py.pnl_pct > 0 else ("LOSS" if py.pnl_pct < 0 else "BE")


def run_python(cfg: BRTConfig) -> list[BRTTrade]:
    data_dir = Path(r"C:\Users\songg\Downloads\stockresearch\data\newdata\data")
    sym = "NVDA"
    df = load_csv(str(data_dir / f"{sym}.csv"))
    benchmark_df = _load_benchmark_local(data_dir)
    ph, pl, php, plp = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = compute_market_structure(df, ph, pl, php, plp)
    l3 = compute_touch_stream(
        df, ph, pl, php, plp,
        cfg.band_pct, cfg.lookback_long, cfg.touch_threshold, cfg.lookback_short,
        strong_pivots_enabled=cfg.strong_pivots_enabled,
        strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
        strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
        strong_post_pivot_bars=cfg.strong_post_pivot_bars,
        strong_post_pivot_pct=cfg.strong_post_pivot_pct,
        strong_pivot_mode=cfg.strong_pivot_mode,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    closed, *_ = run_brt_backtest(sym, df, cfg, php, plp, struct, l3, benchmark_df=benchmark_df)
    closed.sort(key=lambda t: t.date_opened)
    return closed


def cost_sheet_py(s: SheetRow, t: BRTTrade) -> float:
    ped, _ = trade_to_date(t)
    dd = abs((ped - s.entry_d).days)
    pe = abs(t.entry_price - s.entry_px) / max(s.entry_px, 1e-9)
    return float(dd + pe * 120.0)


def assign_python_to_sheet_rows(
    sheet: list[SheetRow], py_trades: list[BRTTrade]
) -> list[Optional[int]]:
    """For each Python trade (in order), pick closest unused sheet row index."""
    used: set[int] = set()
    out: list[Optional[int]] = []
    for t in py_trades:
        best_i: Optional[int] = None
        best_c = 1e18
        for i, s in enumerate(sheet):
            if i in used:
                continue
            c = cost_sheet_py(s, t)
            if c < best_c:
                best_c = c
                best_i = i
        if best_i is not None:
            used.add(best_i)
        out.append(best_i)
    return out


def diff_notes(s: SheetRow, py: BRTTrade) -> tuple[bool, bool, str]:
    """Returns (exact, loose, notes)."""
    ped, pxd = trade_to_date(py)
    notes: list[str] = []
    if ped != s.entry_d:
        notes.append(f"entry_date off {(ped - s.entry_d).days}d")
    if not px_close(py.entry_price, s.entry_px, 0.015):
        notes.append(f"entry_px py={py.entry_price:.4f} sheet={s.entry_px:.2f}")
    if pxd != s.exit_d:
        notes.append(f"exit_date off {(pxd - s.exit_d).days}d")
    if not px_close(py.exit_price, s.exit_px, 0.015):
        notes.append(f"exit_px py={py.exit_price:.4f} sheet={s.exit_px:.2f}")
    if abs(py.pnl_pct - s.pnl_pct) > 0.75:
        notes.append(f"pnl% py={py.pnl_pct:.2f}% sheet={s.pnl_pct:.2f}%")
    if outcome(py) != s.result:
        notes.append(f"result py={outcome(py)} sheet={s.result}")
    if py.days_held != s.days:
        notes.append(f"days py={py.days_held} sheet={s.days}")
    exact = len(notes) == 0
    loose = exact or (
        abs((ped - s.entry_d).days) <= 1
        and px_close(py.entry_price, s.entry_px, 0.03)
        and outcome(py) == s.result
    )
    return exact, loose, "; ".join(notes) if notes else "aligned"


def print_report(title: str, cfg: BRTConfig) -> None:
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)
    print(
        f"touch_threshold={cfg.touch_threshold} | strong_pivots_enabled={cfg.strong_pivots_enabled} | "
        f"strong_pivot_mode={cfg.strong_pivot_mode!r} | "
        f"pre {cfg.strong_pre_pivot_bars}/{cfg.strong_pre_pivot_pct} | "
        f"post {cfg.strong_post_pivot_bars}/{cfg.strong_post_pivot_pct}"
    )
    py_trades = run_python(cfg)
    print(f"Python closed trades: {len(py_trades)} | Sheet rows: {len(SHEET)}")
    print()

    assign = assign_python_to_sheet_rows(SHEET, py_trades)
    used_sheet = {i for i in assign if i is not None}

    # --- A) Python trade -> sheet row ---
    print("--- A) Each PYTHON trade -> closest unused SHEET row ---")
    print(
        f"{'Py#':>4} {'Tag':^8} | {'Py entry':^12} {'Sheet#':>7} {'Sheet entry':^12} | "
        f"{'Py exit':^12} {'Sheet exit':^12} | {'Py pnl%':>8} {'Sheet pnl%':>10} | Notes"
    )
    print("-" * 130)
    for j, t in enumerate(py_trades):
        si = assign[j]
        ped, pxd = trade_to_date(t)
        if si is None:
            print(f"{j+1:4d} {'ORPHAN':^8} | {ped.isoformat()} {'--':>7} {'--':^12} | {pxd.isoformat()} {'--':^12} | {t.pnl_pct:8.2f} {'--':>10} | (no sheet row assigned)")
            continue
        s = SHEET[si]
        ex, lo, note = diff_notes(s, t)
        tag = "EXACT" if ex else ("LOOSE" if lo else "DIFF")
        print(
            f"{j+1:4d} {tag:^8} | {ped.isoformat()} {si+1:7d} {s.entry_d.isoformat()} | "
            f"{pxd.isoformat()} {s.exit_d.isoformat()} | {t.pnl_pct:8.2f} {s.pnl_pct:10.2f} | {note}"
        )

    # --- B) Sheet rows with no Python trade ---
    print()
    print("--- B) SHEET rows with NO Python trade (under this config) ---")
    missing = [i for i in range(len(SHEET)) if i not in used_sheet]
    if not missing:
        print("(none)")
    else:
        for i in missing:
            s = SHEET[i]
            print(
                f"  Sheet #{i+1}: entry {s.entry_d.isoformat()} @ {s.entry_px:.2f} -> exit {s.exit_d.isoformat()} @ {s.exit_px:.2f} "
                f"pnl%={s.pnl_pct:.2f}% {s.result} ({s.days}d)"
            )

    # --- C) Chronological alignment (sorted by entry date) ---
    print()
    print("--- C) Chronological alignment (sorted entry date): row k = k-th sheet vs k-th Python ---")
    sheet_sorted = sorted(enumerate(SHEET), key=lambda x: x[1].entry_d)
    n = max(len(py_trades), len(SHEET))
    for k in range(n):
        if k < len(sheet_sorted):
            si, s = sheet_sorted[k]
            s_line = f"Sheet #{si+1} {s.entry_d.isoformat()} @{s.entry_px:.2f} -> {s.exit_d.isoformat()} @{s.exit_px:.2f} ({s.pnl_pct:.1f}%)"
        else:
            s_line = "(no sheet row)"
        if k < len(py_trades):
            t = py_trades[k]
            ped, pxd = trade_to_date(t)
            p_line = f"Py #{k+1} {ped.isoformat()} @{t.entry_price:.4f} -> {pxd.isoformat()} @{t.exit_price:.4f} ({t.pnl_pct:.1f}%)"
        else:
            p_line = "(no Python trade)"
        print(f"  [{k+1:2d}] {s_line}")
        print(f"       {p_line}")


def main() -> None:
    print("NVDA: Google Sheet vs rocket_brt (same data/newdata/data/NVDA.csv)")
    print_report("Run 1: BRTConfig() defaults (touch=2, strong pre)", BRTConfig())
    print_report(
        "Run 2: strong_pivots_enabled=False (for count parity with 15-row sheet; not default)",
        BRTConfig(strong_pivots_enabled=False),
    )


if __name__ == "__main__":
    main()
