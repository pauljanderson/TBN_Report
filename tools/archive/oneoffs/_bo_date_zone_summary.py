#!/usr/bin/env python3
"""BO/retest parity using (breakout_date, zone) keys — MR offset tolerant."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compare_breakout_retest import _load_engine_csv, _load_sheet_tsv  # noqa: E402
from brt_sheet_breakout_ledgers import BRT_SHEET_BREAKOUT_LEDGER, DEFAULT_SYMBOLS  # noqa: E402


def _zone_key(r, zd: int = 2) -> tuple[str, float, float]:
    return (r.breakout_iso, round(r.zl, zd), round(r.zu, zd))


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260621201750"
    eng_path = ROOT / "drive" / f"BRT_breakout_and_retest_{run_id}.csv"
    syms = DEFAULT_SYMBOLS

    print(
        f"{'SYM':6} {'sheet':>5} {'date+zone':>9} {'rt_ex':>5} "
        f"{'rt_date':>7} {'rt_miss':>7} {'s_only':>6} {'e_only':>6}"
    )
    totals = [0] * 7
    for sym in syms:
        sheet = _load_sheet_tsv(BRT_SHEET_BREAKOUT_LEDGER[sym], sym)
        eng = _load_engine_csv(eng_path, sym)
        sm = {_zone_key(r): r for r in sheet}
        pm = {_zone_key(r): r for r in eng}
        common = set(sm) & set(pm)
        only_s = set(sm) - set(pm)
        only_p = set(pm) - set(sm)

        rt_ex = rt_date = rt_miss = 0
        for k in common:
            s, p = sm[k], pm[k]
            s_rt, p_rt = s.retest_iso or "", p.retest_iso or ""
            if not s_rt and not p_rt:
                continue
            row_ok = (
                s.retest_row is not None
                and p.retest_row is not None
                and int(s.retest_row) == int(p.retest_row)
            )
            if s_rt == p_rt and row_ok:
                rt_ex += 1
            elif s_rt == p_rt:
                rt_date += 1
            else:
                rt_miss += 1

        row = [len(sheet), len(common), rt_ex, rt_date, rt_miss, len(only_s), len(only_p)]
        for i, v in enumerate(row):
            totals[i] += v
        print(f"{sym:6} " + " ".join(f"{v:5d}" if i else f"{v:6d}" for i, v in enumerate(row)))

    print("TOTAL  " + " ".join(f"{v:5d}" if i else f"{v:6d}" for i, v in enumerate(totals)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
