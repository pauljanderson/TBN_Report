#!/usr/bin/env python3
"""Retest date parity on tolerance-matched BO rows."""
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


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260621201750"
    eng_path = ROOT / "drive" / f"BRT_breakout_and_retest_{run_id}.csv"
    print(f"{'SYM':6} bo_tol   rt_date   rt_ex   rt_row±1")
    tot = [0, 0, 0, 0]
    for sym in DEFAULT_SYMBOLS:
        sheet = _load_sheet_tsv(BRT_SHEET_BREAKOUT_LEDGER[sym], sym)
        eng = _load_engine_csv(eng_path, sym)
        used = [False] * len(eng)
        bo = rt_date = rt_ex = rt_row1 = 0
        for s in sheet:
            pj = None
            for j, p in enumerate(eng):
                if used[j] or s.breakout_iso != p.breakout_iso:
                    continue
                if near(s.zl, p.zl) and near(s.zu, p.zu):
                    pj = j
                    break
            if pj is None:
                continue
            used[pj] = True
            bo += 1
            p = eng[pj]
            s_rt, p_rt = s.retest_iso or "", p.retest_iso or ""
            if not s_rt and not p_rt:
                continue
            if s_rt == p_rt:
                rt_date += 1
                if s.retest_row is not None and p.retest_row is not None:
                    d = int(s.retest_row) - int(p.retest_row)
                    if d == 0:
                        rt_ex += 1
                    elif d == -1:
                        rt_row1 += 1
        row = [bo, rt_date, rt_ex, rt_row1]
        for i, v in enumerate(row):
            tot[i] += v
        print(f"{sym:6} {bo:4d}     {rt_date:4d}      {rt_ex:4d}    {rt_row1:4d}")
    print(f"TOTAL  {tot[0]:4d}     {tot[1]:4d}      {tot[2]:4d}    {tot[3]:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
