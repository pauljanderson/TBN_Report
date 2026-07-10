#!/usr/bin/env python3
"""Forensics for engine-only META trades vs sheet log."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

SHEET = [
    ("2019-01-04", 137.56, "2019-01-31", 166.45),
    ("2019-02-04", 169.15, "2019-07-12", 204.67),
    ("2019-09-09", 187.44, "2019-10-02", 173.58),
    ("2019-10-21", 190.00, "2020-03-09", 169.60),
    ("2020-03-18", 146.62, "2020-04-14", 178.98),
    ("2020-04-22", 184.08, "2020-05-20", 223.50),
    ("2020-06-29", 220.59, "2020-08-07", 266.91),
    ("2020-09-21", 253.31, "2021-04-05", 306.51),
    ("2021-05-19", 313.58, "2021-08-30", 379.43),
    ("2021-10-12", 326.97, "2022-01-24", 296.42),
    ("2022-03-22", 213.33, "2022-04-21", 196.31),
    ("2022-05-19", 194.97, "2022-05-24", 177.09),
    ("2022-06-06", 191.93, "2022-06-10", 175.97),
    ("2023-03-08", 186.35, "2023-04-27", 239.89),
    ("2023-06-05", 270.14, "2023-10-11", 326.87),
    ("2023-12-04", 318.98, "2024-01-22", 387.95),
    ("2024-08-05", 479.00, "2024-10-01", 579.59),
    ("2024-11-29", 577.50, "2025-01-30", 698.78),
    ("2025-02-28", 673.68, "2025-03-10", 600.19),
    ("2025-03-14", 607.46, "2025-03-31", 555.52),
    ("2025-04-07", 543.25, "2025-05-13", 657.33),
    ("2025-05-30", 644.39, "2025-07-31", 779.71),
    ("2025-08-26", 752.30, "2025-10-06", 698.58),
    ("2025-10-13", 707.78, "2025-10-30", 660.94),
    ("2026-02-05", 665.49, "2026-03-13", 610.37),
]


def next_td(iso_d: list[str], d: str) -> str:
    return iso_d[iso_d.index(d) + 1]


def parse_mdy(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    dt = pd.to_datetime(s, errors="coerce")
    return "" if pd.isna(dt) else dt.strftime("%Y-%m-%d")


def sheet_window(trig: str) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    row = next(r for r in SHEET if r[0] == trig)
    purch = next_td(iso_d, trig)
    return pd.Timestamp(trig), pd.Timestamp(purch), pd.Timestamp(row[2])


def sheet_holding(d: pd.Timestamp) -> Optional[str]:
    for trig, _, exit_d, _ in SHEET:
        _, purch, exit_ts = pd.Timestamp(trig), pd.Timestamp(next_td(iso_d, trig)), pd.Timestamp(exit_d)
        if purch <= d <= exit_ts:
            return trig
    return None


@dataclass
class EngineOnly:
    purchase: str
    trigger: str
    entry: float
    exit_d: str
    exit_type: str
    pnl: str
    breakout: str
    close_above: str
    cause: str
    detail: str


def classify_engine_only(er: pd.Series, eng: pd.DataFrame) -> EngineOnly:
    od = er.open_d
    purch = od.strftime("%Y-%m-%d")
    i = iso_d.index(purch) - 1
    trig = iso_d[i]
    trig_ts = pd.Timestamp(trig)
    sheet_trig = sheet_holding(trig_ts)
    sheet_open = sheet_holding(od)
    prior = eng[(eng.index != er.name) & (eng.open_d < od)].sort_values("open_d")
    prev = prior.iloc[-1] if len(prior) else None

    rt_rows = rt[rt["rt_iso"] == trig]
    ah_retest = len(rt_rows) > 0

    # Find matching sheet trade by purchase day
    sheet_match_trig = None
    for t, ep, _, _ in SHEET:
        if next_td(iso_d, t) == purch:
            sheet_match_trig = t
            break

    cause = "unknown"
    detail = ""

    if sheet_match_trig:
        cause = "duplicate_purchase_day"
        detail = f"sheet also has trigger {sheet_match_trig} -> same purchase {purch}"
    elif sheet_open:
        cause = "reentry_while_sheet_in"
        st = sheet_open
        row = next(r for r in SHEET if r[0] == st)
        detail = (
            f"sheet IN from trigger {st} (purchase {next_td(iso_d, st)} -> exit {row[2]}); "
            f"engine flat and re-entered"
        )
        if prev is not None:
            ps = prev.close_d.strftime("%Y-%m-%d")
            detail += f"; prior engine trade {prev.open_d.date()}->{ps} {prev.EXIT_TYPE}"
            # Did engine exit before sheet?
            sheet_exit = pd.Timestamp(row[2])
            if prev.close_d < sheet_exit:
                detail += f" (engine exited {ps}, sheet still held until {row[2]})"
    elif sheet_trig and not sheet_open:
        cause = "reentry_after_sheet_trigger_while_flat"
        detail = f"trigger {trig} falls in sheet window starting {sheet_trig} but purchase {purch} after sheet exit"
    elif not ah_retest:
        cause = "no_retest_on_trigger"
        near = rt.copy()
        near["rt"] = pd.to_datetime(near["rt_iso"])
        near["dd"] = (near["rt"] - trig_ts).dt.days.abs()
        if len(near):
            nr = near.sort_values("dd").iloc[0]
            detail = f"no BO retest on {trig}; nearest {nr.rt_iso} BO {nr.bo_iso}"
        else:
            detail = f"no BO retest on {trig}"
    else:
        cause = "sheet_flat_extra_signal"
        r0 = rt_rows.iloc[0]
        detail = (
            f"retest OK on {trig} BO {r0.bo_iso} Z{r0['Zone Lower']}-{r0['Zone Upper']}; "
            f"sheet had no overlapping position"
        )

    return EngineOnly(
        purchase=purch,
        trigger=trig,
        entry=float(er.ENTRY_PRICE),
        exit_d=er.close_d.strftime("%Y-%m-%d"),
        exit_type=str(er.EXIT_TYPE),
        pnl=str(er.PNL_PCT),
        breakout=str(er.BREAKOUT_DATE),
        close_above=str(er.CLOSE_ABOVE_DATE),
        cause=cause,
        detail=detail,
    )


def analyze_run(run_id: str) -> None:
    global iso_d, rt
    meta = pd.read_csv(ROOT / "data" / "newdata" / "data" / "META.csv", parse_dates=["Date"]).sort_values("Date")
    iso_d = [d.strftime("%Y-%m-%d") for d in meta["Date"]]

    rt = pd.read_csv(ROOT / "Drive" / f"YH_breakout_and_retest_{run_id}.csv")
    rt = rt[rt["SYMBOL"] == "META"].copy()
    rt["rt_iso"] = rt["Retest Date"].map(parse_mdy)
    rt["bo_iso"] = rt["Breakout Date"].map(parse_mdy)

    eng = pd.read_csv(ROOT / "Drive" / f"YH_Closed_{run_id}.csv")
    eng = eng[eng["SYMBOL"] == "META"].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
    eng = eng.sort_values("open_d").reset_index(drop=True)

    audit = pd.read_csv(ROOT / "Drive" / f"YH_Audit_Report_{run_id}.csv")
    th = audit["too_high_multiplier"].iloc[0] if "too_high_multiplier" in audit.columns else "?"

    matched_purch = {next_td(iso_d, t) for t, _, _, _ in SHEET}
    exact = 0
    sheet_miss = []
    for trig, ep, _, _ in SHEET:
        purch = next_td(iso_d, trig)
        rows = eng[eng["open_d"] == pd.Timestamp(purch)]
        if len(rows) == 1 and abs(float(rows.iloc[0].ENTRY_PRICE) - ep) < 0.02:
            cad = str(rows.iloc[0].CLOSE_ABOVE_DATE)[:10]
            if cad == trig:
                exact += 1
                continue
        sheet_miss.append(trig)

    engine_only = []
    for _, er in eng.iterrows():
        purch = er.open_d.strftime("%Y-%m-%d")
        if purch in matched_purch:
            # check if exact
            trig = None
            for t, ep, _, _ in SHEET:
                if next_td(iso_d, t) == purch and abs(float(er.ENTRY_PRICE) - ep) < 0.02:
                    trig = t
                    break
            if trig and str(er.CLOSE_ABOVE_DATE)[:10] == trig:
                continue
        engine_only.append(classify_engine_only(er, eng))

    print("=" * 100)
    print(f"RUN {run_id}  too_high_multiplier={th}  META closed={len(eng)}  sheet={len(SHEET)}")
    print(f"Exact matches: {exact}/{len(SHEET)}  sheet_miss={len(sheet_miss)}  engine_only={len(engine_only)}")
    if sheet_miss:
        print(f"Sheet misses: {', '.join(sheet_miss)}")
    print("=" * 100)

    by_cause: dict[str, list[EngineOnly]] = {}
    for eo in engine_only:
        by_cause.setdefault(eo.cause, []).append(eo)

    print("\nENGINE-ONLY BY ROOT CAUSE:")
    for cause, items in sorted(by_cause.items(), key=lambda x: -len(x[1])):
        print(f"\n  [{cause}] x{len(items)}")
        for eo in items:
            print(f"    purchase {eo.purchase} (trigger {eo.trigger}) ${eo.entry:.2f} -> {eo.exit_d} {eo.exit_type} {eo.pnl}")
            print(f"      BO={eo.breakout} CAD={eo.close_above}")
            print(f"      {eo.detail}")

    # Exit timing diffs driving reentries
    print("\n" + "=" * 100)
    print("EXIT TIMING: matched sheet trades where engine exited before sheet")
    print("=" * 100)
    for trig, _, exit_s, _ in SHEET:
        purch = next_td(iso_d, trig)
        rows = eng[eng["open_d"] == pd.Timestamp(purch)]
        if len(rows) != 1:
            continue
        er = rows.iloc[0]
        if str(er.CLOSE_ABOVE_DATE)[:10] != trig:
            continue
        sheet_exit = pd.Timestamp(exit_s)
        eng_exit = er.close_d
        if eng_exit < sheet_exit:
            days = (sheet_exit - eng_exit).days
            # next engine trade after this exit
            nxt = eng[eng["open_d"] > eng_exit].head(1)
            nxt_s = ""
            if len(nxt):
                n = nxt.iloc[0]
                nxt_s = f" -> next engine {n.open_d.date()} {n.EXIT_TYPE}"
            print(
                f"  sheet trig {trig}: engine exit {eng_exit.date()} {er.EXIT_TYPE} "
                f"vs sheet {sheet_exit.date()} ({days}d early){nxt_s}"
            )


if __name__ == "__main__":
    runs = sys.argv[1:] or ["260619145037", "260619112330"]
    for r in runs:
        analyze_run(r)
        print()
