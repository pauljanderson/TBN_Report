#!/usr/bin/env python3
"""Summarize retest coverage on sheet-only vs engine-only NVDA breakout keys."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_analysis.compare_brt_breakout_sheet_program import _load_rows  # noqa: E402


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260620101456"
    zd = 2
    sheet = _load_rows(ROOT / "tools/nvda_breakout_ledger_full.tsv", "sheet", "NVDA")
    prog = _load_rows(ROOT / "Drive" / f"YH_breakout_and_retest_{run_id}.csv", "program", "NVDA")
    sm = {r.key(zd): r for r in sheet}
    pm = {r.key(zd): r for r in prog}
    only_s = [sm[k] for k in sorted(set(sm) - set(pm))]
    only_p = [pm[k] for k in sorted(set(pm) - set(sm))]

    print(f"Sheet-only: {len(only_s)}  Engine-only: {len(only_p)}")
    print(
        f"Sheet-only with retest: {sum(1 for r in only_s if r.retest_iso)}/{len(only_s)}  "
        f"without: {sum(1 for r in only_s if not r.retest_iso)}"
    )
    print(
        f"Engine-only with retest: {sum(1 for r in only_p if r.retest_iso)}/{len(only_p)}  "
        f"without: {sum(1 for r in only_p if not r.retest_iso)}"
    )

    sheet_by: dict[tuple[str, int], list] = defaultdict(list)
    eng_by: dict[tuple[str, int], list] = defaultdict(list)
    for r in only_s:
        sheet_by[(r.breakout_iso, r.main_row)].append(r)
    for r in only_p:
        eng_by[(r.breakout_iso, r.main_row)].append(r)
    paired = sorted(set(sheet_by) & set(eng_by))
    print(f"\nSame breakout date + Main Row, different zone: {len(paired)} pairs")
    for k in paired[:15]:
        ss, ep = sheet_by[k][0], eng_by[k][0]
        print(
            f"  {k[0]} MR{k[1]}: "
            f"sheet Z{ss.zl:.2f}-{ss.zu:.2f} RT={ss.retest_iso or '-'} | "
            f"eng Z{ep.zl:.2f}-{ep.zu:.2f} RT={ep.retest_iso or '-'}"
        )
    if len(paired) > 15:
        print(f"  ... +{len(paired) - 15} more")

    eng_only_bo = {r.breakout_iso for r in only_p}
    sheet_only_bo = {r.breakout_iso for r in only_s}
    print(f"\nEngine-only rows with unique BO dates not in sheet-only set: {len(eng_only_bo - sheet_only_bo)}")
    print(f"Sheet-only rows with unique BO dates not in engine-only set: {len(sheet_only_bo - eng_only_bo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
