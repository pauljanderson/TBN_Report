#!/usr/bin/env python3
"""Compare BRT sheet zone ladder vs engine BRT_ZONES export.

Sheet format (one row per matured zone, in order):
  center<TAB>lower<TAB>upper

Engine: drive/BRT_ZONES_{SYMBOL}_{RUN_ID}.csv (from BRT run with --print-zones, brt_zones=true)

Usage:
  python tools/compare_brt_zones.py <RUN_ID> [SYMBOL ...]
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brt_sheet_zone_ledgers import BRT_SHEET_ZONE_LEDGER, DEFAULT_SYMBOLS  # noqa: E402

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
    name = f"BRT_ZONES_{symbol.upper()}_{run_id}.csv"
    for d in DRIVE_DIRS:
        p = d / name
        if p.is_file():
            return p
    for d in DRIVE_DIRS:
        if not d.is_dir():
            continue
        matches = sorted(
            d.glob(f"BRT_ZONES_{symbol.upper()}_*.csv"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0]
    return None


def _load_engine_ladder(path: Path) -> list[tuple[float, float, float, str]]:
    df = pd.read_csv(path)
    if "MATURED_NOW" in df.columns:
        df = df[df["MATURED_NOW"].astype(str).str.strip().isin(("1", "1.0", "True", "true"))]
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


def _zone_near_match(
    sheet: tuple[float, float, float],
    eng: tuple[float, float, float],
    tol: float = 0.01,
) -> bool:
    eps = 1e-6
    return all(abs(s - e) <= tol + eps for s, e in zip(sheet, eng))


def compare_symbol(symbol: str, run_id: str, *, tol: float = 0.01) -> dict[str, int]:
    sym = symbol.upper()
    sheet_path = BRT_SHEET_ZONE_LEDGER.get(sym)
    if sheet_path is None or not sheet_path.is_file():
        print(f"SKIP {sym}: no BRT sheet zone ledger (add tools/{sym.lower()}_brt_sheet_zones.txt)")
        return {"exact": 0, "center_only": 0, "miss": 0, "sheet_n": 0, "engine_n": 0}

    eng_path = _engine_zone_path(run_id, sym)
    if eng_path is None:
        print(f"SKIP {sym}: no engine BRT_ZONES file for run {run_id} (re-run with --print-zones brt_zones=true)")
        return {"exact": 0, "center_only": 0, "miss": 0, "sheet_n": 0, "engine_n": 0}

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

    n = max(len(sheet), len(eng))
    exact = center_only = miss = near = 0
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
        elif _zone_near_match(si, (ec, el, eh), tol):
            near += 1
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
    print(f"  Near (all within {tol}): {near}")
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

    sheet_set = {x for x in sheet}
    eng_set = {(e[0], e[1], e[2]) for e in eng}
    sheet_ctr = Counter(sheet)
    eng_ctr = Counter((e[0], e[1], e[2]) for e in eng)
    multiset_match = sum(min(sheet_ctr[k], eng_ctr.get(k, 0)) for k in sheet_ctr)
    sheet_only_ms = sum(sheet_ctr.values()) - multiset_match
    eng_only_ms = sum(eng_ctr.values()) - multiset_match

    # Greedy ±tol match (OHLC vs Google Finance cents drift)
    multiset_near = 0
    eng_items = list(eng_ctr.elements())
    used = [False] * len(eng_items)
    for s in sheet_ctr.elements():
        for j, e in enumerate(eng_items):
            if used[j]:
                continue
            if _zone_near_match(s, e, tol):
                multiset_near += 1
                used[j] = True
                break

    print("--- Set compare (order-independent) ---")
    print(f"  Unique in both:   {len(sheet_set & eng_set)}")
    print(f"  Sheet-only uniq:  {len(sheet_set - eng_set)}")
    print(f"  Engine-only uniq: {len(eng_set - sheet_set)}")
    print(f"  Multiset matched: {multiset_match}/{len(sheet)} (sheet rows)")
    print(f"  Multiset ±{tol}:  {multiset_near}/{len(sheet)} (sheet rows)")
    if sheet_only_ms or eng_only_ms:
        print(f"  Multiset sheet-only rows: {sheet_only_ms}  engine-only rows: {eng_only_ms}")
    print()
    return {
        "exact": exact,
        "center_only": center_only,
        "miss": miss,
        "sheet_n": len(sheet),
        "engine_n": len(eng),
        "multiset_match": multiset_match,
        "sheet_only_ms": sheet_only_ms,
        "eng_only_ms": eng_only_ms,
        "near": near,
        "multiset_near": multiset_near,
    }


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: python tools/compare_brt_zones.py <RUN_ID> [SYMBOL ...]", file=sys.stderr)
        return 2
    run_id = args[0]
    symbols = [a.upper() for a in args[1:]] if len(args) > 1 else DEFAULT_SYMBOLS
    tot_exact = tot_sheet = 0
    for sym in symbols:
        stats = compare_symbol(sym, run_id)
        tot_exact += stats["exact"]
        tot_sheet += stats["sheet_n"]
    print("=" * 100)
    print(f"TOTAL exact zones: {tot_exact}/{tot_sheet}")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
