#!/usr/bin/env python3
"""Engineering diff: sheet TRIGGER date vs engine PURCHASE date (run 260619112330)."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_brt import (  # noqa: E402
    BRTConfig,
    _cfg_min_spy_compare_1y_at_trigger,
    _rs_excess_pct_points,
    _spy_compare_1y_at_trigger_gate_blocks,
)

RUN_ID = "260619112330"

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


def next_td(dates: list[str], d: str) -> str:
    i = dates.index(d)
    return dates[i + 1]


def parse_mdy(s) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    dt = pd.to_datetime(s, errors="coerce")
    return "" if pd.isna(dt) else dt.strftime("%Y-%m-%d")


@dataclass
class GateResult:
    ok: bool
    first_fail: str
    detail: dict[str, str]


def eval_gates(
    i: int,
    iso: list[str],
    op, hi, lo, cl,
    rs_st, rs_sp,
    dw_dates: set[str],
    cfg: BRTConfig,
) -> GateResult:
    d = {}
    if i < 0:
        return GateResult(False, "no_bar", d)
    d["AG_close_gt_open"] = "PASS" if cl[i] > op[i] else "FAIL"
    gb = int(getattr(cfg, "growth_bars", 756))
    d["AV_growth_3y"] = "PASS" if i >= gb and cl[i] >= cl[i - gb] else "FAIL"
    d["BO_countif"] = "PASS" if iso[i] in dw_dates else "FAIL"
    if i >= 1:
        d["red_to_green"] = "PASS" if (cl[i - 1] <= op[i - 1] and cl[i] > op[i]) else "FAIL"
    else:
        d["red_to_green"] = "FAIL"
    ah = all(d.get(k) == "PASS" for k in ("AG_close_gt_open", "AV_growth_3y", "BO_countif", "red_to_green"))
    d["sheet_AH"] = "PASS" if ah else "FAIL"
    thr = _cfg_min_spy_compare_1y_at_trigger(cfg)
    if rs_st is not None and thr > 0:
        e1, _, _ = _rs_excess_pct_points(rs_st, rs_sp, i)
        if _spy_compare_1y_at_trigger_gate_blocks(cfg, rs_st, rs_sp, i):
            d["SPY_1y"] = f"FAIL ({e1:.1f}<{thr:.1f})"
        else:
            d["SPY_1y"] = f"PASS ({e1:.1f}>={thr:.1f})"
    else:
        d["SPY_1y"] = "N/A"
    for k, v in d.items():
        if v == "FAIL" or str(v).startswith("FAIL"):
            return GateResult(False, k, d)
    return GateResult(True, "", d)


def engine_open_on(d: pd.Timestamp, eng: pd.DataFrame) -> pd.Series | None:
    m = eng[eng["open_d"] == d]
    if len(m) == 1:
        return m.iloc[0]
    if len(m) > 1:
        return m.iloc[0]  # flag below
    return None


def sheet_in_trade(d: pd.Timestamp, windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> bool:
    for a, b in windows:
        if a <= d <= b:
            return True
    return False


def main() -> None:
    meta = pd.read_csv(ROOT / "data" / "newdata" / "data" / "META.csv", parse_dates=["Date"]).sort_values("Date")
    iso_d = [d.strftime("%Y-%m-%d") for d in meta["Date"]]
    iso_y = [d.strftime("%Y%m%d") for d in meta["Date"]]
    op = meta["Open"].to_numpy(float)
    hi = meta["High"].to_numpy(float)
    lo = meta["Low"].to_numpy(float)
    cl = meta["Close"].to_numpy(float)

    rt = pd.read_csv(ROOT / "Drive" / f"YH_breakout_and_retest_{RUN_ID}.csv")
    rt = rt[rt["SYMBOL"] == "META"].copy()
    rt["rt_iso"] = rt["Retest Date"].map(parse_mdy)
    rt["bo_iso"] = rt["Breakout Date"].map(parse_mdy)
    dw_dates = set(iso_y[iso_d.index(r)] for r in rt["rt_iso"].dropna().unique() if r in iso_d)

    eng = pd.read_csv(ROOT / "Drive" / f"YH_Closed_{RUN_ID}.csv")
    eng = eng[eng["SYMBOL"] == "META"].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
    eng["cad"] = pd.to_datetime(eng["CLOSE_ABOVE_DATE"], errors="coerce")

    audit = pd.read_csv(ROOT / "Drive" / f"YH_Audit_Report_{RUN_ID}.csv")
    spy_thr = float(audit["min_spy_compare_1y_at_trigger"].iloc[0]) if "min_spy_compare_1y_at_trigger" in audit.columns else 50.0
    cfg = BRTConfig(growth_filter_enabled=True, growth_bars=756, min_spy_compare_1y_at_trigger=spy_thr)

    spy_df = pd.read_csv(ROOT / "data" / "newdata" / "data" / "SPY.csv", parse_dates=["Date"]).sort_values("Date")
    rs_st = None
    rs_sp = None

    windows = [(pd.Timestamp(a), pd.Timestamp(x)) for a, _, x, _ in SHEET]

    print("=" * 120)
    print(f"META engineering diff  run={RUN_ID}  (sheet date=TRIGGER, engine DATE_OPENED=PURCHASE=trigger+1 TD)")
    print(f"Config min_spy_compare_1y_at_trigger={spy_thr}")
    print("=" * 120)

    # Sheet overlap check
    overlaps = 0
    for i, (a0, a1) in enumerate(windows):
        for j, (b0, b1) in enumerate(windows):
            if j <= i:
                continue
            if b0 <= a1 and b1 >= a0:
                overlaps += 1
                print(f"SHEET OVERLAP: {a0.date()}-{a1.date()} vs {b0.date()}-{b1.date()}")
    print(f"Sheet overlapping open windows: {overlaps} (expect 0)\n")

    matched_eng: set[int] = set()
    stats = {"exact": 0, "price_miss": 0, "no_eng": 0, "wrong_eng": 0, "multi_eng": 0}

    for trig_s, entry_px, exit_s, exit_px in SHEET:
        purch_s = next_td(iso_d, trig_s)
        trig = pd.Timestamp(trig_s)
        purch = pd.Timestamp(purch_s)
        i_trig = iso_d.index(trig_s)
        i_purch = iso_d.index(purch_s)

        rt_rows = rt[rt["rt_iso"] == trig_s]
        g = eval_gates(i_trig, iso_y, op, hi, lo, cl, rs_st, rs_sp, dw_dates, cfg)
        meta_open = float(op[i_purch])
        in_sheet = sheet_in_trade(trig, windows)

        eng_rows = eng[eng["open_d"] == purch]
        er = eng_rows.iloc[0] if len(eng_rows) else None
        if len(eng_rows) > 1:
            stats["multi_eng"] += 1

        # Was engine already in a trade on trigger or purchase day?
        eng_open_trig = eng[(eng["open_d"] <= trig) & (eng["close_d"] >= trig)]
        eng_open_purch = eng[(eng["open_d"] <= purch) & (eng["close_d"] >= purch)]

        print(f"\n--- Sheet TRIGGER {trig_s}  purchase {purch_s}  sheet entry open ${entry_px:.2f} ---")
        print(f"  Retest ledger rows on trigger: {len(rt_rows)}")
        for _, r in rt_rows.head(2).iterrows():
            print(f"    BO {r['bo_iso']}  Z{r['Zone Lower']}-{r['Zone Upper']}  MR {r['Main Row']}")
        print(f"  META open on purchase day: ${meta_open:.2f}  (sheet ${entry_px:.2f}, diff ${abs(meta_open-entry_px):.2f})")
        print(f"  Gates on TRIGGER bar: AH={g.detail.get('sheet_AH')}  {g.detail}")
        print(f"  Sheet IN-trade on trigger day: {in_sheet}")
        print(f"  Engine positions open on trigger: {len(eng_open_trig)}  on purchase: {len(eng_open_purch)}")
        if len(eng_open_trig):
            for _, t in eng_open_trig.iterrows():
                print(f"    eng open {t.open_d.date()}->{t.close_d.date()} entry {t.ENTRY_PRICE}")

        if er is None:
            stats["no_eng"] += 1
            print(f"  RESULT: NO engine trade on purchase day {purch_s}")
            # nearest engine
            eng2 = eng.copy()
            eng2["dd"] = (eng2["open_d"] - purch).dt.days.abs()
            near = eng2.sort_values("dd").iloc[0]
            print(f"  Nearest engine open: {near.open_d.date()} (delta {int(near.dd)}d)  BO={near.BREAKOUT_DATE}  CAD={near.CLOSE_ABOVE_DATE}")
            continue

        matched_eng.add(int(er.name))
        price_ok = abs(float(er.ENTRY_PRICE) - entry_px) < 0.02 and abs(float(er.ENTRY_PRICE) - meta_open) < 0.02
        cad = er.cad.date() if pd.notna(er.cad) else None
        if cad == trig.date() and price_ok:
            stats["exact"] += 1
            tag = "EXACT MATCH"
        elif cad == trig.date():
            stats["price_miss"] += 1
            tag = "DATE OK, price delta"
        else:
            stats["wrong_eng"] += 1
            tag = "WRONG ENGINE ROW (CAD != trigger)"

        print(f"  Engine purchase {er.open_d.date()} entry ${float(er.ENTRY_PRICE):.2f} -> {er.close_d.date()} {er.EXIT_TYPE} {er.PNL_PCT}")
        print(f"  Engine CLOSE_ABOVE_DATE={cad}  BREAKOUT_DATE={er.BREAKOUT_DATE}  MATURITY={er.MATURITY_DATE}")
        print(f"  RESULT: {tag}")

    print("\n" + "=" * 120)
    print("SHEET SUMMARY:", stats)
    print("=" * 120)

    print("\nENGINE-ONLY purchases (not sheet trigger+1 purchase day):")
    for idx, er in eng.iterrows():
        if idx in matched_eng:
            continue
        od = er.open_d
        # infer trigger = prev TD
        i = iso_d.index(od.strftime("%Y-%m-%d")) - 1
        infer_trig = iso_d[i] if i >= 0 else "?"
        sheet_hold = sheet_in_trade(pd.Timestamp(infer_trig), windows)
        eng_hold = eng[(eng["open_d"] <= pd.Timestamp(infer_trig)) & (eng["close_d"] >= pd.Timestamp(infer_trig))]
        print(f"\n  PURCHASE {od.date()} entry ${float(er.ENTRY_PRICE):.2f}  infer trigger {infer_trig}")
        print(f"    exit {er.close_d.date()} {er.EXIT_TYPE} {er.PNL_PCT}  BO={er.BREAKOUT_DATE} CAD={er.CLOSE_ABOVE_DATE}")
        print(f"    sheet IN-trade on infer trigger: {sheet_hold}")
        print(f"    other eng open on infer trigger: {len(eng_hold)-1} (excluding self)")
        rr = rt[rt["rt_iso"] == infer_trig]
        print(f"    retest rows on infer trigger: {len(rr)}")
        if len(rr):
            print(f"      BO {rr.iloc[0]['bo_iso']} Z{rr.iloc[0]['Zone Lower']}-{rr.iloc[0]['Zone Upper']}")


if __name__ == "__main__":
    main()
