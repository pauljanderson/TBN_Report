#!/usr/bin/env python3
"""Compare sheet FILTER ledger (BH:BT spill) vs engine YH_breakout export for META."""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_analysis.compare_brt_breakout_sheet_program import _load_rows  # noqa: E402

SHEET_TRADES = [
    "2019-01-04",
    "2019-02-04",
    "2019-09-09",
    "2019-10-21",
    "2020-03-18",
    "2020-04-22",
    "2020-06-29",
    "2020-09-21",
    "2021-05-19",
    "2021-10-12",
    "2022-03-22",
    "2022-05-19",
    "2022-06-06",
    "2023-03-08",
    "2023-06-05",
    "2023-12-04",
    "2024-08-05",
    "2024-11-29",
    "2025-02-28",
    "2025-03-14",
    "2025-04-07",
    "2025-05-30",
    "2025-08-26",
    "2025-10-13",
    "2026-02-05",
]


def _replay(ohlc: pd.DataFrame, bo_iso: str, zl: float, zu: float, scan_delta: int) -> tuple[str, int]:
    dates = ohlc["iso"].tolist()
    if bo_iso not in dates:
        return "", -1
    b = dates.index(bo_iso)
    zlr, zur = round(zl, 2), round(zu, 2)
    start = b + max(1, scan_delta)
    for k in range(start, len(ohlc)):
        lo = round(float(ohlc.iloc[k]["Low"]), 2)
        hi = round(float(ohlc.iloc[k]["High"]), 2)
        if lo <= zur and hi >= zlr:
            return dates[k], k + 2
    return "", -1


def _filter_summary_rows(path: Path) -> None:
    """Drop BRT summary footer rows (non-date Breakout Date)."""
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines:
        return
    out = [lines[0]]
    for line in lines[1:]:
        first = line.split("\t")[0].split(",")[0].strip()
        if not first:
            continue
        if _parse_mdy(first):
            out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _parse_mdy(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260619083217"
    ledger_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "tools" / "meta_breakout_ledger_full.tsv"
    prog_path = ROOT / "Drive" / f"YH_breakout_and_retest_{run_id}.csv"
    ohlc_path = ROOT / "data" / "newdata" / "data" / "META.csv"

    if not ledger_path.is_file():
        print(f"ERROR: ledger not found: {ledger_path}", file=sys.stderr)
        return 2
    if not prog_path.is_file():
        print(f"ERROR: program export not found: {prog_path}", file=sys.stderr)
        return 2

    _filter_summary_rows(ledger_path)

    sheet = _load_rows(ledger_path, "sheet", "META", sheet_active_only=False)
    prog = _load_rows(prog_path, "program", "META", sheet_active_only=False)
    zd = 2
    sm = {r.key(zd): r for r in sheet}
    pm = {r.key(zd): r for r in prog}

    ohlc = pd.read_csv(ohlc_path, parse_dates=["Date"]).sort_values("Date")
    ohlc["iso"] = ohlc["Date"].dt.strftime("%Y-%m-%d")

    print("=" * 100)
    print("META sheet FILTER ledger vs engine export")
    print(f"  ledger: {ledger_path.name}  rows={len(sheet)}")
    print(f"  engine: {prog_path.name}  rows={len(prog)}")
    print("  match key: (Main Row, zone_lo@2dp, zone_hi@2dp)")
    print("=" * 100)

    only_s = sorted(set(sm) - set(pm))
    only_p = sorted(set(pm) - set(sm))
    common = sorted(set(sm) & set(pm))
    print(f"Only sheet: {len(only_s)}  Only engine: {len(only_p)}  Common: {len(common)}")

    mism_rt: list[tuple] = []
    delta2_fix = 0
    delta2_exact = 0
    other = 0
    for k in common:
        s, p = sm[k], pm[k]
        if (s.retest_iso or "") == (p.retest_iso or ""):
            continue
        mism_rt.append((s, p))
        sim2, _ = _replay(ohlc, s.breakout_iso, s.zl, s.zu, 2)
        sim3, _ = _replay(ohlc, s.breakout_iso, s.zl, s.zu, 3)
        if sim2 == (s.retest_iso or ""):
            if sim3 == (p.retest_iso or ""):
                delta2_fix += 1
            elif (p.retest_iso or "") == sim2:
                delta2_exact += 1
            else:
                other += 1
        else:
            other += 1

    print()
    print(f"Retest mismatches (common keys): {len(mism_rt)}")
    print(f"  sheet RT matches OHLC replay scan_delta=2: {delta2_fix + delta2_exact} (engine=d3: {delta2_fix}, engine already=d2: {delta2_exact})")
    print(f"  other (not explained by scan_delta alone): {other}")

    if mism_rt:
        print()
        print("--- First 15 retest mismatches (sheet | engine | replay d2 | replay d3) ---")
        for s, p in mism_rt[:15]:
            sim2, _ = _replay(ohlc, s.breakout_iso, s.zl, s.zu, 2)
            sim3, _ = _replay(ohlc, s.breakout_iso, s.zl, s.zu, 3)
            print(
                f"  BO {s.breakout_mdy} MR{s.main_row} Z${s.zl:.2f}-${s.zu:.2f}\n"
                f"    sheet RT {s.retest_iso or '-'} rr{s.retest_row} scan{s.scan_row}\n"
                f"    eng   RT {p.retest_iso or '-'} rr{p.retest_row} scan{p.scan_row}\n"
                f"    replay d2={sim2} d3={sim3}"
            )

    print()
    print("=" * 100)
    print("COUNTIF(BO, entry_D) — sheet ledger rows per trade entry date")
    print("=" * 100)
    for ed in SHEET_TRADES:
        hits = [r for r in sheet if r.retest_iso == ed]
        eng_hits = [r for r in prog if r.retest_iso == ed]
        print(f"\n{ed}  sheet BO hits={len(hits)}  engine BO hits={len(eng_hits)}")
        for r in hits[:3]:
            print(
                f"  sheet: BO {r.breakout_mdy} MR{r.main_row} Z${r.zl:.2f}-${r.zu:.2f} "
                f"scan{r.scan_row} rr{r.retest_row}"
            )
        if len(hits) > 3:
            print(f"  ... +{len(hits)-3} more sheet rows")
        for r in eng_hits[:2]:
            print(
                f"  engine: BO {r.breakout_mdy} MR{r.main_row} Z${r.zl:.2f}-${r.zu:.2f} "
                f"scan{r.scan_row} rr{r.retest_row}"
            )
        if not hits and not eng_hits:
            print("  ** NO retest row on entry date in either ledger **")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
