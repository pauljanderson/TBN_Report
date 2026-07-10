#!/usr/bin/env python3
"""Compare sheet zone ladder vs engine YH_ZONES export.

Sheet format (one row per matured zone, in order):
  center<TAB>lower<TAB>upper
Optional header row is skipped when the first field is not numeric.

Engine: drive/YH_ZONES_{SYMBOL}_{RUN_ID}.csv (from YH run with --print-zones)

Usage:
  python tools/compare_zones.py <RUN_ID> [SYMBOL ...]

Examples:
  python tools/compare_zones.py 260621111231 META
  python tools/compare_zones.py 260621111231          # all symbols with ledgers
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sheet_zone_ledgers import DEFAULT_SYMBOLS, SHEET_ZONE_LEDGER  # noqa: E402

DRIVE_DIRS = [ROOT / "drive", ROOT / "Drive"]


def _parse_num(s: str) -> float | None:
    t = re.sub(r"[^0-9.\-]", "", (s or "").strip())
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _load_sheet_ladder(path: Path) -> list[tuple[float, float, float]]:
    rows: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"[\t, ]+", line)
        parts = [p for p in parts if p]
        if len(parts) < 3:
            continue
        c, lo, hi = (_parse_num(parts[0]), _parse_num(parts[1]), _parse_num(parts[2]))
        if c is None or lo is None or hi is None:
            continue
        rows.append((round(c, 2), round(lo, 2), round(hi, 2)))
    return rows


def _engine_zone_path(run_id: str, symbol: str) -> Path | None:
    name = f"YH_ZONES_{symbol.upper()}_{run_id}.csv"
    for d in DRIVE_DIRS:
        p = d / name
        if p.is_file():
            return p
    # fallback: newest matching symbol
    for d in DRIVE_DIRS:
        if not d.is_dir():
            continue
        matches = sorted(
            d.glob(f"YH_ZONES_{symbol.upper()}_*.csv"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
    return None


def _load_engine_ladder(path: Path) -> list[tuple[float, float, float, str]]:
    df = pd.read_csv(path)
    out: list[tuple[float, float, float, str]] = []
    for _, r in df.iterrows():
        c = _parse_num(str(r.get("ZONE_CENTER", "")))
        lo = _parse_num(str(r.get("ZONE_LOW", "")))
        hi = _parse_num(str(r.get("ZONE_HIGH", "")))
        if c is None or lo is None or hi is None:
            continue
        dt = str(r.get("DATE", "") or "")[:10]
        out.append((round(c, 2), round(lo, 2), round(hi, 2), dt))
    return out


def _half_width_pct(center: float, lower: float) -> float:
    if center <= 0:
        return float("nan")
    return (center - lower) / center * 100.0


def _compare_symbol(symbol: str, run_id: str) -> int:
    sym = symbol.upper()
    sheet_path = SHEET_ZONE_LEDGER.get(sym)
    if sheet_path is None or not sheet_path.is_file():
        print(f"SKIP {sym}: no sheet zone ledger (add tools/{sym.lower()}_sheet_zones.txt)")
        return 0

    eng_path = _engine_zone_path(run_id, sym)
    if eng_path is None:
        print(f"SKIP {sym}: no engine YH_ZONES file for run {run_id} (re-run with --print-zones)")
        return 0

    sheet = _load_sheet_ladder(sheet_path)
    eng = _load_engine_ladder(eng_path)

    print("=" * 100)
    print(f"{sym}  sheet={sheet_path.name}  engine={eng_path.name}")
    print(f"  sheet zones: {len(sheet)}  engine zones: {len(eng)}")
    print("=" * 100)

    if sheet and eng:
        sc, sl, sh = sheet[0]
        ec, el, eh, ed = eng[0]
        print(
            f"  First zone — sheet ctr={sc} lo={sl} hi={sh} (~{_half_width_pct(sc, sl):.2f}% half-width)  "
            f"engine ctr={ec} lo={el} hi={eh} on {ed} (~{_half_width_pct(ec, el):.2f}% half-width)"
        )
        print()

    # Sequence compare by index (canonical ladder order)
    n = max(len(sheet), len(eng))
    exact = center_only = miss = 0
    mismatches: list[str] = []

    for i in range(n):
        si = sheet[i] if i < len(sheet) else None
        ei = eng[i] if i < len(eng) else None
        if si is None:
            miss += 1
            mismatches.append(f"  #{i+1:3d}  SHEET missing  engine {ei[0]}/{ei[1]}/{ei[2]} ({ei[3]})")
            continue
        if ei is None:
            miss += 1
            mismatches.append(f"  #{i+1:3d}  sheet {si[0]}/{si[1]}/{si[2]}  ENGINE missing")
            continue
        sc, sl, sh = si
        ec, el, eh, ed = ei
        if sc == ec and sl == el and sh == eh:
            exact += 1
        elif sc == ec:
            center_only += 1
            mismatches.append(
                f"  #{i+1:3d}  center {sc} MATCH  lo/hi sheet={sl}/{sh}  engine={el}/{eh}  "
                f"(engine lower by {el-sl:+.2f})  {ed}"
            )
        else:
            miss += 1
            mismatches.append(
                f"  #{i+1:3d}  sheet {sc}/{sl}/{sh}  engine {ec}/{el}/{eh} ({ed})  "
                f"center delta {ec-sc:+.2f}"
            )

    print("--- Ladder sequence (same index = same rung) ---")
    print(f"  Exact (ctr+lo+hi):     {exact}")
    print(f"  Center match, band!=: {center_only}")
    print(f"  Center or row miss:  {miss}")
    print()

    if mismatches:
        print(f"Mismatches ({len(mismatches)}):")
        for line in mismatches[:50]:
            print(line)
        if len(mismatches) > 50:
            print(f"  ... +{len(mismatches) - 50} more")
        print()

    # Set compare (order-independent)
    sheet_set = {x for x in sheet}
    eng_set = {(e[0], e[1], e[2]) for e in eng}
    print("--- Set compare (order-independent) ---")
    print(f"  In both:      {len(sheet_set & eng_set)}")
    print(f"  Sheet-only:   {len(sheet_set - eng_set)}")
    print(f"  Engine-only:  {len(eng_set - sheet_set)}")
    print()
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: python tools/compare_zones.py <RUN_ID> [SYMBOL ...]", file=sys.stderr)
        return 2
    run_id = args[0]
    symbols = [a.upper() for a in args[1:]] if len(args) > 1 else DEFAULT_SYMBOLS
    rc = 0
    for sym in symbols:
        r = _compare_symbol(sym, run_id)
        if r:
            rc = r
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
