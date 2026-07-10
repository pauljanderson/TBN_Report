#!/usr/bin/env python3
"""Compare spreadsheet canonical META YH zones vs engine YH_ZONES CSV."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SHEET_FILE = ROOT / "tools" / "meta_sheet_zones.txt"
SHEET_END = "2025-07-31"


def _load_sheet() -> list[tuple[float, float, float]]:
    out: list[tuple[float, float, float]] = []
    for line in SHEET_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.replace(",", "\t").split("\t")
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= 3:
            out.append((round(float(parts[0]), 2), round(float(parts[1]), 2), round(float(parts[2]), 2)))
    return out


def _load_engine(path: Path, end_date: str) -> list[tuple[float, float, float, str]]:
    eng_df = pd.read_csv(path)
    eng_df = eng_df[eng_df["DATE"] <= end_date]
    return [
        (round(float(r.ZONE_CENTER), 2), round(float(r.ZONE_LOW), 2), round(float(r.ZONE_HIGH), 2), str(r.DATE))
        for r in eng_df.itertuples()
    ]


def _compare(label: str, sheet: list[tuple[float, float, float]], eng: list[tuple[float, float, float, str]]) -> None:
    sheet_c = {x[0] for x in sheet}
    eng_c = {x[0] for x in eng}
    both = sorted(sheet_c & eng_c)
    sheet_only = sorted(sheet_c - eng_c)
    eng_only = sorted(eng_c - sheet_c)

    print(f"=== {label} ===")
    print(f"Sheet canonical zones:              {len(sheet)}")
    print(f"Engine rows (<= {SHEET_END}):       {len(eng)}")
    print(f"Exact center matches:               {len(both)}")
    print(f"Sheet-only centers:                 {len(sheet_only)}")
    print(f"Engine-only centers:                {len(eng_only)}")
    print()

    if sheet and eng:
        c, zl, _ = sheet[0]
        ec, el, _ = eng[0][0], eng[0][1], eng[0][2]
        print(f"Sheet band zone 1: center={c} lo={zl} -> ~{(c - zl) / c * 100:.2f}% half-width")
        print(f"Engine band zone 1: center={ec} lo={el} -> ~{(ec - el) / ec * 100:.2f}% half-width")
        print()

    tol = 1.0
    matched_tol = sum(1 for c, _, _, _ in eng if any(abs(c - s) <= tol for s in sheet_c))
    sheet_matched_tol = sum(1 for sc, _, _ in sheet if any(abs(sc - ec) <= tol for ec, _, _, _ in eng))
    print(f"Engine rows matching sheet within ${tol:.2f}: {matched_tol}/{len(eng)}")
    print(f"Sheet rows matching engine within ${tol:.2f}: {sheet_matched_tol}/{len(sheet)}")
    print()

    print("Sheet sequence check (match / near / miss):")
    for i, (sc, sl, sh) in enumerate(sheet, 1):
        exact = [e for e in eng if e[0] == sc]
        if exact:
            lo_ok = any(abs(e[1] - sl) <= 0.05 and abs(e[2] - sh) <= 0.05 for e in eng if e[0] == sc)
            tag = "MATCH" if lo_ok else "CENTER"
            print(f"  {i:2d} {sc:7.2f}  {tag:6s}  engine {exact[0][3]}  lo/hi diff={exact[0][1]-sl:+.2f}/{exact[0][2]-sh:+.2f}")
            continue
        near = min(eng, key=lambda e: abs(e[0] - sc))
        if abs(near[0] - sc) <= 0.05:
            print(f"  {i:2d} {sc:7.2f}  NEAR   engine {near[0]:.2f} on {near[3]}")
        else:
            print(f"  {i:2d} {sc:7.2f}  MISS   (closest engine {near[0]:.2f} on {near[3]})")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-csv", type=Path, help="YH_ZONES_META CSV path")
    args = ap.parse_args()

    sheet = _load_sheet()
    drive = ROOT / "Drive"
    if args.engine_csv:
        engine_path = args.engine_csv
    else:
        matches = sorted(drive.glob("YH_ZONES_META_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches:
            raise SystemExit(f"No YH_ZONES_META_*.csv found under {drive}")
        engine_path = matches[0]

    eng = _load_engine(engine_path, SHEET_END)
    _compare(f"META YH zones: spreadsheet vs {engine_path.name}", sheet, eng)


if __name__ == "__main__":
    main()
