#!/usr/bin/env python3
"""Audit META sheet entry dates vs engine run: retest rows (#3) then gate pass/fail (#1)."""
from __future__ import annotations

import sys
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

SHEET_TRADES = [
    ("2019-01-04", 137.56),
    ("2019-02-04", 169.15),
    ("2019-09-09", 187.44),
    ("2019-10-21", 190.00),
    ("2020-03-18", 146.62),
    ("2020-04-22", 184.08),
    ("2020-06-29", 220.59),
    ("2020-09-21", 253.31),
    ("2021-05-19", 313.58),
    ("2021-10-12", 326.97),
    ("2022-03-22", 213.33),
    ("2022-05-19", 194.97),
    ("2022-06-06", 191.93),
    ("2023-03-08", 186.35),
    ("2023-06-05", 270.14),
    ("2023-12-04", 318.98),
    ("2024-08-05", 479.00),
    ("2024-11-29", 577.50),
    ("2025-02-28", 673.68),
    ("2025-03-14", 607.46),
    ("2025-04-07", 543.25),
    ("2025-05-30", 644.39),
    ("2025-08-26", 752.30),
    ("2025-10-13", 707.78),
    ("2026-02-05", 665.49),
]

RUN_CFG = {
    "growth_filter_enabled": True,
    "growth_bars": 756,
    "require_close_gt_open": True,
    "sheet_dw_countif_entry_enabled": True,
    "sheet_dw_countif_include_prior_bar_date": False,
    "min_spy_compare_1y_at_trigger": 50.0,
    "entry_filter_meteoric_rise": "both",
    "entry_filter_meteoric_fall": "both",
    "tradeable_key_level_enabled": False,
    "consolidation_blocker_enabled": False,
    "do_gate_enabled": False,
    "dp_gate_enabled": False,
    "indicator_buy": "off",
}


def _load_ohlc(sym: str) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    path = ROOT / "data" / "newdata" / "data" / f"{sym}.csv"
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date")
    iso = [d.strftime("%Y%m%d") for d in df["Date"]]
    return (
        iso,
        df["Open"].to_numpy(dtype=np.float64),
        df["High"].to_numpy(dtype=np.float64),
        df["Low"].to_numpy(dtype=np.float64),
        df["Close"].to_numpy(dtype=np.float64),
    )


def _bar_idx(iso: list[str], date_s: str) -> int:
    key = date_s.replace("-", "")
    try:
        return iso.index(key)
    except ValueError:
        return -1


def _parse_mdy(s: str) -> str:
    if not isinstance(s, str) or not s.strip():
        return ""
    dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        return ""
    return dt.strftime("%Y-%m-%d")


def _retest_set(meta_rt: pd.DataFrame) -> set[str]:
    out: set[str] = set()
    for v in meta_rt["Retest Date"]:
        d = _parse_mdy(str(v))
        if d:
            out.add(d.replace("-", ""))
    return out


def _gate_audit(
    i: int,
    iso: list[str],
    op: np.ndarray,
    hi: np.ndarray,
    lo: np.ndarray,
    cl: np.ndarray,
    rs_st: np.ndarray,
    rs_sp: np.ndarray,
    dw_dates: set[str],
    cfg: BRTConfig,
) -> tuple[dict[str, str], str | None]:
    """Return per-gate PASS/FAIL/N/A and first engine blocker (sheet AL gates + engine extras)."""
    gates: dict[str, str] = {}
    if i < 0:
        return gates, "no_bar"

    # Sheet AH (BRT Rocket buy) per live layout D:CG and pasted formula:
    # =OR(AND(AG, AV, COUNTIF(BO,D)>0, H_prev<=E_prev, H>E))  [E=Open, H=Close]
    gates["sheet_AG_close_gt_open"] = "PASS" if cl[i] > op[i] else "FAIL"
    if i >= cfg.growth_bars:
        gates["sheet_AV_growth_3y"] = "PASS" if cl[i] >= cl[i - cfg.growth_bars] else "FAIL"
    else:
        gates["sheet_AV_growth_3y"] = "FAIL"
    gates["sheet_BO_retest_date"] = "PASS" if iso[i] in dw_dates else "FAIL"
    if i >= 1:
        prev_red = cl[i - 1] <= op[i - 1]
        today_green = cl[i] > op[i]
        gates["sheet_red_to_green"] = "PASS" if (prev_red and today_green) else "FAIL"
    else:
        gates["sheet_red_to_green"] = "FAIL"

    # Engine analogues (same run config as 260619083217 audit)
    gates["eng_require_close_gt_open"] = gates["sheet_AG_close_gt_open"]
    gates["eng_growth_filter"] = gates["sheet_AV_growth_3y"]
    gates["eng_sheet_dw_countif"] = gates["sheet_BO_retest_date"]

    if rs_st is not None and rs_sp is not None:
        e1, _, _ = _rs_excess_pct_points(rs_st, rs_sp, i)
        thr = _cfg_min_spy_compare_1y_at_trigger(cfg)
        if thr > 0:
            if e1 is None:
                gates["eng_min_spy_compare_1y"] = "FAIL"
            elif _spy_compare_1y_at_trigger_gate_blocks(cfg, rs_st, rs_sp, i):
                gates["eng_min_spy_compare_1y"] = f"FAIL ({e1:.1f} < {thr:.1f})"
            else:
                gates["eng_min_spy_compare_1y"] = f"PASS ({e1:.1f} >= {thr:.1f})"
        else:
            gates["eng_min_spy_compare_1y"] = "N/A"
    else:
        gates["eng_min_spy_compare_1y"] = "N/A"

    gates["eng_meteoric_rise"] = "N/A"
    gates["eng_meteoric_fall"] = "N/A"
    gates["eng_indicator_buy"] = "N/A"
    gates["eng_tkl"] = "N/A"
    gates["eng_consolidation"] = "N/A"
    gates["eng_do_gate"] = "N/A"
    gates["eng_dp_gate"] = "N/A"

    order = [
        "eng_require_close_gt_open",
        "eng_growth_filter",
        "eng_min_spy_compare_1y",
        "eng_sheet_dw_countif",
    ]
    first_block = None
    for k in order:
        v = gates.get(k, "N/A")
        if v.startswith("FAIL"):
            first_block = f"{k}: {v}"
            break
    return gates, first_block


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260619083217"
    retest_path = ROOT / "Drive" / f"YH_breakout_and_retest_{run_id}.csv"
    closed_path = ROOT / "Drive" / f"YH_Closed_{run_id}.csv"

    rt = pd.read_csv(retest_path)
    rt_meta = rt[rt["SYMBOL"] == "META"].copy()
    rt_meta["retest_iso"] = rt_meta["Retest Date"].map(_parse_mdy)
    retest_dates = set(rt_meta["retest_iso"].dropna())
    dw_dates = _retest_set(rt_meta)

    eng_entries: set[str] = set()
    if closed_path.is_file():
        eng = pd.read_csv(closed_path)
        eng = eng[eng["SYMBOL"] == "META"]
        for d in eng["DATE_OPENED"].astype(str):
            eng_entries.add(
                datetime.strptime(d[:8], "%Y%m%d").strftime("%Y-%m-%d")
                if len(d) >= 8
                else d
            )

    iso, op, hi, lo, cl = _load_ohlc("META")
    spy_iso, _, _, _, spy_cl = _load_ohlc("SPY")
    spy_map = {d: c for d, c in zip(spy_iso, spy_cl)}
    rs_st = cl.copy()
    rs_sp = np.array([spy_map.get(d, np.nan) for d in iso], dtype=np.float64)
    cfg = BRTConfig(**RUN_CFG)

    print(f"=== META sheet entry audit — run {run_id} ===")
    print(f"META retest rows in export: {len(rt_meta)}")
    print(f"Unique engine retest dates (sheet BO / COUNTIF set): {len(dw_dates)}")
    print(f"Engine META closed trades: {len(eng_entries)}")
    print()

    # --- #3 Retest date comparison (first) ---
    print("=" * 72)
    print("#3 RETEST DATE vs SHEET ENTRY DATE")
    print("=" * 72)
    print(
        f"{'Sheet Entry':<12} {'Retest=Entry?':<14} {'Retest Date':<12} "
        f"{'Breakout':<12} {'Maturity':<12} {'Zone lo-hi':<22} {'Eng trade?'}"
    )
    print("-" * 72)

    retest_audit_rows = []
    for entry_date, entry_px in SHEET_TRADES:
        exact = rt_meta[rt_meta["retest_iso"] == entry_date]
        if len(exact):
            row = exact.iloc[0]
            tag = "EXACT"
            rd = entry_date
            bo = str(row.get("Breakout Date", ""))
            mat = str(row.get("Maturity Date", ""))
            zlo = str(row.get("Zone Lower", ""))
            zhi = str(row.get("Zone Upper", ""))
            extra = f" (+{len(exact)-1} more)" if len(exact) > 1 else ""
        else:
            entry_ts = pd.Timestamp(entry_date)
            best = None
            for _, row in rt_meta.iterrows():
                rd_s = row["retest_iso"]
                if not rd_s:
                    continue
                delta = abs((pd.Timestamp(rd_s) - entry_ts).days)
                if best is None or delta < best[0]:
                    best = (delta, rd_s, row)
            if best and best[0] <= 10:
                tag = f"NEAR {best[0]}d"
                rd = best[1]
                row = best[2]
                bo = str(row.get("Breakout Date", ""))
                mat = str(row.get("Maturity Date", ""))
                zlo = str(row.get("Zone Lower", ""))
                zhi = str(row.get("Zone Upper", ""))
                extra = ""
            else:
                tag = "MISSING"
                rd = best[1] if best else ""
                bo = mat = zlo = zhi = ""
                extra = f" (nearest {best[0]}d)" if best else ""
        traded = "YES" if entry_date in eng_entries else "no"
        print(
            f"{entry_date:<12} {tag:<14} {rd:<12} {bo:<12} {mat:<12} "
            f"{zlo}-{zhi:<22} {traded}{extra}"
        )
        retest_audit_rows.append((entry_date, tag, rd))

    print()
    exact_n = sum(1 for _, t, _ in retest_audit_rows if t == "EXACT")
    near_n = sum(1 for _, t, _ in retest_audit_rows if t.startswith("NEAR"))
    miss_n = sum(1 for _, t, _ in retest_audit_rows if t == "MISSING")
    print(
        f"Retest summary: {exact_n} exact, {near_n} near (<=10d), {miss_n} missing "
        f"among {len(SHEET_TRADES)} sheet entries"
    )
    print()

    # --- #1 Gate audit ---
    print("=" * 72)
    print("#1 GATE PASS/FAIL ON SHEET ENTRY BAR")
    print(
        "Sheet AH = OR(AND(AG, AV, COUNTIF(BO,D)>0, H_prev<=E_prev, H>E)) "
        "[D:CG layout; BO=Retest Date, BY=YH Level]"
    )
    print("Engine extras from run audit (not in sheet AH): min_spy_compare_1y=50")
    print("=" * 72)

    for entry_date, entry_px in SHEET_TRADES:
        i = _bar_idx(iso, entry_date)
        gates, eng_block = _gate_audit(i, iso, op, hi, lo, cl, rs_st, rs_sp, dw_dates, cfg)
        traded = entry_date in eng_entries
        print()
        print(f"--- {entry_date}  sheet entry ${entry_px:.2f}  bar_idx={i}  engine_traded={traded} ---")
        if i < 0:
            print("  ERROR: date not in META.csv")
            continue
        print(
            f"  OHLC: O={op[i]:.2f} H={hi[i]:.2f} L={lo[i]:.2f} C={cl[i]:.2f}  "
            f"close>open={cl[i]>op[i]}"
        )
        sheet_ah = all(
            gates.get(k) == "PASS"
            for k in (
                "sheet_AG_close_gt_open",
                "sheet_AV_growth_3y",
                "sheet_BO_retest_date",
                "sheet_red_to_green",
            )
        )
        print(f"  Sheet AH (5-term AND): {'PASS' if sheet_ah else 'FAIL'}")
        for k in (
            "sheet_AG_close_gt_open",
            "sheet_AV_growth_3y",
            "sheet_BO_retest_date",
            "sheet_red_to_green",
            "eng_require_close_gt_open",
            "eng_growth_filter",
            "eng_min_spy_compare_1y",
            "eng_sheet_dw_countif",
        ):
            print(f"    {k:<28} {gates.get(k, 'N/A')}")
        if eng_block:
            print(f"  First engine-only blocker on this bar: {eng_block}")
        elif sheet_ah:
            print(
                "  All sheet AH + listed engine gates PASS on eval bar — "
                "miss likely: no pending maturity eval, portfolio contention, or next-bar entry"
            )
        else:
            fails = [k for k, v in gates.items() if k.startswith("sheet_") and v == "FAIL"]
            print(f"  Sheet AH fails: {', '.join(fails)}")


if __name__ == "__main__":
    main()
