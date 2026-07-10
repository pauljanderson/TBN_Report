#!/usr/bin/env python3
"""BO match with zone tolerance ±0.01 on bounds."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compare_breakout_retest import _load_engine_csv, _load_sheet_tsv  # noqa: E402
from brt_sheet_breakout_ledgers import BRT_SHEET_BREAKOUT_LEDGER, DEFAULT_SYMBOLS  # noqa: E402


def near(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol + 1e-9


def match_rows(sheet, eng, tol: float = 0.01):
    used = [False] * len(eng)
    matched = 0
    for s in sheet:
        hit = False
        for j, p in enumerate(eng):
            if used[j]:
                continue
            if s.breakout_iso != p.breakout_iso:
                continue
            if near(s.zl, p.zl, tol) and near(s.zu, p.zu, tol):
                used[j] = True
                matched += 1
                hit = True
                break
        if not hit:
            pass
    return matched, len(sheet) - matched, sum(1 for u in used if not u)


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260621201750"
    eng_path = ROOT / "drive" / f"BRT_breakout_and_retest_{run_id}.csv"
    print(f"{'SYM':6} exact  tol±0.01")
    tot_e = tot_t = 0
    sn = 0
    for sym in DEFAULT_SYMBOLS:
        sheet = _load_sheet_tsv(BRT_SHEET_BREAKOUT_LEDGER[sym], sym)
        eng = _load_engine_csv(eng_path, sym)
        exact = len({(r.breakout_iso, round(r.zl, 2), round(r.zu, 2)) for r in sheet} & {
            (r.breakout_iso, round(r.zl, 2), round(r.zu, 2)) for r in eng
        })
        tol_m, s_only, e_only = match_rows(sheet, eng, 0.01)
        print(f"{sym:6} {exact:4d}/{len(sheet):<3d}  {tol_m:4d}/{len(sheet):<3d}  (s_only={s_only} e_only={e_only})")
        tot_e += exact
        tot_t += tol_m
        sn += len(sheet)
    print(f"TOTAL  {tot_e:4d}/{sn:<3d}  {tot_t:4d}/{sn:<3d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
