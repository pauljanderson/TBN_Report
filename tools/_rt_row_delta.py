#!/usr/bin/env python3
"""Retest row delta when date matches on date+zone keys."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compare_breakout_retest import _load_engine_csv, _load_sheet_tsv  # noqa: E402
from brt_sheet_breakout_ledgers import BRT_SHEET_BREAKOUT_LEDGER, DEFAULT_SYMBOLS  # noqa: E402


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260621201750"
    eng_path = ROOT / "drive" / f"BRT_breakout_and_retest_{run_id}.csv"
    for sym in DEFAULT_SYMBOLS:
        sheet = _load_sheet_tsv(BRT_SHEET_BREAKOUT_LEDGER[sym], sym)
        eng = _load_engine_csv(eng_path, sym)

        def zk(r):
            return (r.breakout_iso, round(r.zl, 2), round(r.zu, 2))

        sm = {zk(r): r for r in sheet}
        pm = {zk(r): r for r in eng}
        deltas = Counter()
        for k in set(sm) & set(pm):
            s, p = sm[k], pm[k]
            if (s.retest_iso or "") != (p.retest_iso or ""):
                continue
            if not s.retest_iso:
                continue
            if s.retest_row is None or p.retest_row is None:
                deltas["missing_row"] += 1
                continue
            deltas[int(s.retest_row) - int(p.retest_row)] += 1
        if any(v for k, v in deltas.items() if k != 0):
            print(f"{sym}: retest row delta (sheet-eng) when date matches: {dict(deltas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
