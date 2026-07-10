#!/usr/bin/env python3
"""TSLA sheet-only BO rows after ±0.01 zone tolerance (full list)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compare_breakout_retest import _load_engine_csv, _load_sheet_tsv  # noqa: E402
from brt_sheet_breakout_ledgers import BRT_SHEET_BREAKOUT_LEDGER  # noqa: E402


def near(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol + 1e-9


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260621201750"
    sym = "TSLA"
    eng_path = ROOT / "drive" / f"BRT_breakout_and_retest_{run_id}.csv"
    sheet = _load_sheet_tsv(BRT_SHEET_BREAKOUT_LEDGER[sym], sym)
    eng = _load_engine_csv(eng_path, sym)
    used = [False] * len(eng)

    sheet_only = []
    for s in sheet:
        hit = False
        for j, p in enumerate(eng):
            if used[j] or s.breakout_iso != p.breakout_iso:
                continue
            if near(s.zl, p.zl) and near(s.zu, p.zu):
                used[j] = True
                hit = True
                break
        if not hit:
            sheet_only.append(s)

    eng_only = [eng[j] for j in range(len(eng)) if not used[j]]

    print(f"TSLA sheet-only ({len(sheet_only)}):")
    for r in sheet_only:
        ctr = (r.zl + r.zu) / 2
        print(f"  {r.breakout_mdy}  ${r.zl:.2f}/${r.zu:.2f}  ctr~{ctr:.2f}  MR{r.main_row}")

    print(f"\nTSLA engine-only ({len(eng_only)}):")
    for r in eng_only[:40]:
        ctr = (r.zl + r.zu) / 2
        print(f"  {r.breakout_mdy}  ${r.zl:.2f}/${r.zu:.2f}  ctr~{ctr:.2f}  MR{r.main_row}")
    if len(eng_only) > 40:
        print(f"  ... +{len(eng_only) - 40} more")

    from collections import Counter

    print("\nSheet-only zone buckets:")
    for (zl, zu), n in Counter(
        (round(r.zl, 2), round(r.zu, 2)) for r in sheet_only
    ).most_common():
        print(f"  {n:2d}  ${zl:.2f}/${zu:.2f}")

    print("Engine-only zone buckets:")
    for (zl, zu), n in Counter(
        (round(r.zl, 2), round(r.zu, 2)) for r in eng_only
    ).most_common():
        print(f"  {n:2d}  ${zl:.2f}/${zu:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
