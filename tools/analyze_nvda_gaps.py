#!/usr/bin/env python3
"""NVDA gap analysis: blocked sheet rows, BO/retest vs ledger, engine-only trades."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.compare_nvda_sheet import load_sheet, next_td  # noqa: E402
from tools.reconcile_nvda_retest_entries import (  # noqa: E402
    _closed_path,
    _parse_mdy,
    load_engine_retest,
)


def open_blocker(eng: pd.DataFrame, purch_d: str) -> pd.Series | None:
    p = pd.Timestamp(purch_d)
    for _, t in eng.iterrows():
        op = pd.to_datetime(str(t.DATE_OPENED), format="%Y%m%d")
        cl = pd.to_datetime(str(t.DATE_CLOSED), format="%Y%m%d")
        if op <= p <= cl:
            return t
    return None


def load_sheet_ledger() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "tools" / "nvda_breakout_ledger_full.tsv", sep="\t", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df["bo_iso"] = df["Breakout Date"].map(_parse_mdy)
    df["rt_iso"] = df["Retest Date"].map(_parse_mdy)
    return df


def sheet_trade_before(trigger_d: str, sheet: pd.DataFrame) -> pd.Series | None:
    t = pd.Timestamp(trigger_d)
    prior = sheet[sheet.trigger_d < trigger_d].sort_values("trigger_d", ascending=False)
    return prior.iloc[0] if len(prior) else None


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260620194127"
    eng = pd.read_csv(_closed_path(run_id))
    eng = eng[eng.SYMBOL == "NVDA"].copy()
    eng["open_d"] = pd.to_datetime(eng.DATE_OPENED.astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng.DATE_CLOSED.astype(str), format="%Y%m%d")
    eng["purch_key"] = eng.open_d.dt.strftime("%Y-%m-%d")
    eng["cad_key"] = pd.to_datetime(eng.CLOSE_ABOVE_DATE, errors="coerce").dt.strftime("%Y-%m-%d")

    meta = pd.read_csv(ROOT / "data/newdata/data/NVDA.csv", parse_dates=["Date"])
    iso = [d.strftime("%Y-%m-%d") for d in meta.sort_values("Date").Date]

    sheet = load_sheet()
    sheet["purch_d"] = sheet.trigger_d.map(lambda d: next_td(iso, d) if d in iso else "")
    rt = load_engine_retest(run_id)
    ledger = load_sheet_ledger()

    matched_purch = set()
    for _, s in sheet.iterrows():
        if s.purch_d in set(eng.purch_key):
            matched_purch.add(s.purch_d)

    print("=" * 90)
    print("1) SHEET_ONLY — engine 'blocked' but sheet also one-position (exit timing / extra engine trade)")
    print("=" * 90)
    for _, s in sheet.iterrows():
        if s.purch_d in matched_purch:
            continue
        blocker = open_blocker(eng, s.purch_d)
        if blocker is None:
            continue
        prev_sheet = sheet_trade_before(s.trigger_d, sheet)
        print(f"\nSheet trig {s.trigger_d} purch {s.purch_d} (sheet exit {s.exit_d})")
        print(
            f"  Engine blocker: open {blocker.open_d.date()} close {blocker.close_d.date()} "
            f"{blocker.EXIT_TYPE} CAD={blocker.cad_key}"
        )
        if prev_sheet is not None:
            print(
                f"  Prior SHEET trade: trig {prev_sheet.trigger_d} exit {prev_sheet.exit_d} "
                f"(sheet flat before purch? {pd.Timestamp(prev_sheet.exit_d) < pd.Timestamp(s.purch_d)})"
            )
        # Is blocker an engine-only trade (no sheet row on same purch)?
        block_purch = blocker.purch_key
        sheet_same = sheet[sheet.purch_d == block_purch]
        if len(sheet_same):
            print(f"  Blocker IS a sheet trade (purch {block_purch})")
        else:
            print(f"  Blocker is ENGINE-ONLY (no sheet purch {block_purch}) — extra engine entry caused block")

    print("\n" + "=" * 90)
    print("2) SHEET_ONLY — no retest on trigger (engine vs sheet ledger)")
    print("=" * 90)
    for _, s in sheet.iterrows():
        if s.purch_d in matched_purch:
            continue
        if open_blocker(eng, s.purch_d) is not None:
            continue
        trig = s.trigger_d
        eng_rt = rt[rt.rt_iso == trig]
        led_rt = ledger[ledger.rt_iso == trig]
        if len(eng_rt) or len(led_rt):
            continue  # has retest somewhere
        print(f"Trig {trig} purch {s.purch_d}: NO retest on trigger in engine or ledger")

    for _, s in sheet.iterrows():
        if s.purch_d in matched_purch:
            continue
        if open_blocker(eng, s.purch_d) is not None:
            continue
        trig = s.trigger_d
        eng_rt = rt[rt.rt_iso == trig]
        led_rt = ledger[ledger.rt_iso == trig]
        if len(eng_rt) == 0 and len(led_rt) > 0:
            print(f"\nTrig {trig}: SHEET LEDGER has retest but ENGINE export missing:")
            for _, r in led_rt.iterrows():
                print(f"  ledger BO {r['Breakout Date']} MR{r['Main Row']} RT {r['Retest Date']}")
        if len(led_rt) == 0 and len(eng_rt) > 0:
            print(f"\nTrig {trig}: ENGINE has retest but NOT in sheet ledger:")
            for _, r in eng_rt.iterrows():
                print(f"  eng BO {r['Breakout Date']} MR{int(r['Main Row'])} RT {r['Retest Date']}")
        if len(led_rt) and len(eng_rt):
            # compare keys
            def keys(df, src):
                out = set()
                for _, r in df.iterrows():
                    out.add((int(r["Main Row"]), _parse_mdy(r.get("Breakout Date", "")), float(r.get("zl", 0) if "zl" in r else 0)))
                return out
            if "zl" not in eng_rt.columns:
                eng_rt = eng_rt.copy()
                eng_rt["zl"] = eng_rt["Zone Lower"].astype(str).str.replace("$", "").astype(float)
            led = ledger[ledger.rt_iso == trig].copy()
            led["zl"] = led["Zone Lower"].astype(str).str.replace("$", "").astype(float)
            ek = {(int(r["Main Row"]), _parse_mdy(r["Breakout Date"]), round(r["zl"], 2)) for _, r in eng_rt.iterrows()}
            lk = {(int(r["Main Row"]), r["bo_iso"], round(r["zl"], 2)) for _, r in led.iterrows()}
            if ek != lk:
                print(f"\nTrig {trig}: engine vs ledger retest ROW mismatch")
                print(f"  engine only: {ek - lk}")
                print(f"  ledger only: {lk - ek}")

    print("\n" + "=" * 90)
    print("3) ENGINE_ONLY — trades sheet log does not list (suggestions)")
    print("=" * 90)
    for _, e in eng[~eng.purch_key.isin(matched_purch)].iterrows():
        trig = e.cad_key
        sheet_trig = sheet[sheet.trigger_d == trig]
        near = sheet.copy()
        near["dd"] = (pd.to_datetime(near.purch_d) - e.open_d).dt.days.abs()
        nearest = near.sort_values("dd").iloc[0] if len(near) else None
        print(
            f"\nEngine purch {e.open_d.date()} CAD={trig} -> {e.close_d.date()} {e.EXIT_TYPE} {e.PNL_PCT}"
        )
        if len(sheet_trig):
            print(f"  Sheet HAS trigger {trig} but different purch {sheet_trig.iloc[0].purch_d}")
        elif nearest is not None and int(nearest.dd) <= 10:
            print(
                f"  No sheet trigger {trig}; nearest sheet trig {nearest.trigger_d} "
                f"purch {nearest.purch_d} (delta {int(nearest.dd)}d)"
            )
        else:
            print(f"  No sheet trigger {trig}; no nearby sheet entry within 10d")
        eng_rt = rt[rt.rt_iso == trig] if trig else rt.iloc[0:0]
        if len(eng_rt):
            r = eng_rt.iloc[0]
            print(f"  Engine retest: BO {r['Breakout Date']} MR{int(r['Main Row'])} RT {r['Retest Date']}")
        else:
            print("  No engine retest row on trigger date")


if __name__ == "__main__":
    main()
