#!/usr/bin/env python3
"""Why sheet trades missing in engine: open-position block vs no retest vs gates."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.compare_nvda_sheet import load_sheet, next_td  # noqa: E402
from tools.reconcile_nvda_retest_entries import load_engine_retest, _parse_mdy  # noqa: E402


def _closed_path(run_id: str) -> Path:
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"YH_Closed_{run_id}.csv"
        if p.exists():
            return p
    return ROOT / "Drive" / f"YH_Closed_{run_id}.csv"


def open_trade_on(eng: pd.DataFrame, purch_d: str) -> pd.Series | None:
    """Engine trade open on purchase morning (opened <= purch, closed >= purch)."""
    p = pd.Timestamp(purch_d)
    for _, t in eng.iterrows():
        op = pd.to_datetime(str(t.DATE_OPENED), format="%Y%m%d")
        cl = pd.to_datetime(str(t.DATE_CLOSED), format="%Y%m%d")
        if op <= p <= cl:
            return t
    return None


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260620194127"
    eng = pd.read_csv(_closed_path(run_id))
    eng = eng[eng.SYMBOL == "NVDA"].copy()
    eng["open_d"] = pd.to_datetime(eng.DATE_OPENED.astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng.DATE_CLOSED.astype(str), format="%Y%m%d")
    eng["purch_key"] = eng.open_d.dt.strftime("%Y-%m-%d")

    meta = pd.read_csv(ROOT / "data/newdata/data/NVDA.csv", parse_dates=["Date"])
    iso = [d.strftime("%Y-%m-%d") for d in meta.sort_values("Date").Date]

    sheet = load_sheet()
    sheet["purch_d"] = sheet.trigger_d.map(lambda d: next_td(iso, d) if d in iso else "")
    rt = load_engine_retest(run_id)

    matched = set()
    for _, s in sheet.iterrows():
        if s.purch_d in set(eng.purch_key):
            matched.add(s.purch_d)

    print(f"Run {run_id} — sheet_only diagnosis\n")
    for _, s in sheet.iterrows():
        if s.purch_d in matched:
            continue
        trig = s.trigger_d
        rt_trig = rt[rt.rt_iso == trig]
        blocker = open_trade_on(eng, s.purch_d)
        print(f"Sheet trig {trig} purch {s.purch_d} ${s.entry_px:.2f}")
        print(f"  retest rows on trigger: {len(rt_trig)}")
        if len(rt_trig):
            r = rt_trig.iloc[0]
            print(f"    BO {r['Breakout Date']} MR{int(r['Main Row'])} RT {r['Retest Date']}")
        if blocker is not None:
            print(
                f"  BLOCKED: engine open {blocker.open_d.date()}->{blocker.close_d.date()} "
                f"{blocker.EXIT_TYPE} CAD={blocker.CLOSE_ABOVE_DATE}"
            )
        else:
            print("  No engine trade on purch date and not blocked by overlapping closed trade")
        print()


if __name__ == "__main__":
    main()
