#!/usr/bin/env python3
"""Trace TSLA sheet AH buy gates vs engine for trade parity mismatches."""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "260621083209"


def parse_mdy(s: str) -> str:
    s = str(s).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    if "/" in s:
        m, d, y = s.split("/")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    dt = pd.to_datetime(s, errors="coerce")
    return "" if pd.isna(dt) else dt.strftime("%Y-%m-%d")


def sheet_gates(i: int, iso_d: list[str], op, cl, dw: set[str], gb: int = 756) -> dict:
    g = {
        "AG_close_gt_open": cl[i] > op[i],
        "AV_growth_3y": i >= gb and cl[i] >= cl[i - gb],
        "BO_countif": iso_d[i] in dw,
        "H7_le_E7": i >= 1 and cl[i - 1] <= op[i - 1],
        "H8_gt_E8": cl[i] > op[i],
    }
    g["red_to_green"] = g["H7_le_E7"] and g["H8_gt_E8"]
    g["sheet_AH"] = all(
        g[k]
        for k in ("AG_close_gt_open", "AV_growth_3y", "BO_countif", "red_to_green")
    )
    return g


def in_trade(iso_d: str, eng: pd.DataFrame) -> str | None:
    ts = pd.Timestamp(iso_d)
    for _, r in eng.iterrows():
        if r.open_d <= ts <= r.close_d:
            return f"{r.open_d.date()}->{r.close_d.date()} {r.EXIT_TYPE} CAD={r.cad_key}"
    return None


def gate_line(d: str, g: dict, extra: str = "") -> str:
    flags = " ".join(
        f"{k}={'Y' if v else 'N'}"
        for k, v in g.items()
        if k != "sheet_AH"
    )
    ah = "PASS" if g["sheet_AH"] else "FAIL"
    return f"  {d}  sheet_AH={ah}  {flags}{extra}"


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else RUN_ID
    meta = pd.read_csv(ROOT / "data/newdata/data/TSLA.csv", parse_dates=["Date"]).sort_values("Date")
    iso_d = [d.strftime("%Y-%m-%d") for d in meta["Date"]]
    op = meta["Open"].to_numpy(float)
    cl = meta["Close"].to_numpy(float)

    rt = pd.read_csv(ROOT / "drive" / f"YH_breakout_and_retest_{run_id}.csv")
    rt = rt[rt["SYMBOL"] == "TSLA"].copy()
    rt["rt_iso"] = rt["Retest Date"].map(parse_mdy)
    dw_strict = set(rt["rt_iso"].dropna())
    dw_expanded = set(dw_strict)
    for r in list(dw_strict):
        if r in iso_d:
            j = iso_d.index(r)
            if j + 1 < len(iso_d):
                dw_expanded.add(iso_d[j + 1])

    eng = pd.read_csv(ROOT / "drive" / f"YH_Closed_{run_id}.csv")
    eng = eng[eng["SYMBOL"] == "TSLA"].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
    eng["cad"] = pd.to_datetime(eng["CLOSE_ABOVE_DATE"], errors="coerce")
    eng["cad_key"] = eng["cad"].dt.strftime("%Y-%m-%d")

    trace_sets = {
        "2019-10-28 engine-only WIN (blocks sheet 11/14)": [
            "2019-10-24",
            "2019-10-25",
            "2019-10-28",
            "2019-10-29",
            "2019-11-13",
            "2019-11-14",
            "2019-11-15",
        ],
        "2021-12-27 engine early entry vs sheet 12/30 trigger": [
            "2021-12-22",
            "2021-12-23",
            "2021-12-27",
            "2021-12-28",
            "2021-12-29",
            "2021-12-30",
            "2021-12-31",
        ],
    }

    print(f"Run: {run_id}")
    print("Sheet AH = AG & AV & COUNTIF(BO,D) & red_to_green (H7<=E7 & H8>E8)\n")

    for title, dates in trace_sets.items():
        print(f"=== {title} ===")
        for d in dates:
            if d not in iso_d:
                print(f"  {d}  (not in CSV)")
                continue
            i = iso_d.index(d)
            gs = sheet_gates(i, iso_d, op, cl, dw_strict)
            ge = sheet_gates(i, iso_d, op, cl, dw_expanded)
            it = in_trade(d, eng)
            eng_row = eng[eng["cad_key"] == d]
            eng_note = ""
            if len(eng_row):
                r = eng_row.iloc[0]
                eng_note = (
                    f" | engine trade open={r.open_d.date()} "
                    f"entry={float(r.ENTRY_PRICE):.2f} CAD={r.cad_key}"
                )
            print(gate_line(d, gs, f" BO_exp={'Y' if ge['BO_countif'] else 'N'}"))
            if it:
                print(f"    IN_TRADE: {it}")
            if eng_note:
                print(f"    ENGINE:{eng_note}")
            if d == "2019-10-25":
                j = i - 1
                print(
                    f"    bars: prior {iso_d[j]} O={op[j]:.2f} C={cl[j]:.2f} "
                    f"| today O={op[i]:.2f} C={cl[i]:.2f}"
                )
        print()

    # Engine closed rows for context
    print("=== Engine trades in these windows ===")
    for lo, hi in [("2019-10-01", "2019-12-31"), ("2021-12-01", "2022-01-15")]:
        w = eng[(eng["open_d"] >= lo) | (eng["close_d"] >= lo)]
        w = w[w["open_d"] <= hi]
        for _, r in w.sort_values("open_d").iterrows():
            print(
                f"  open {r.open_d.date()} ${float(r.ENTRY_PRICE):.2f} "
                f"-> {r.close_d.date()} ${float(r.EXIT_PRICE):.2f} {r.EXIT_TYPE} "
                f"CAD={r.cad_key} {r.PNL_PCT}"
            )
    print()

    # Rocket BRT trace for engine trigger dates
    debug_dates = ["2019-10-25", "2019-11-14", "2021-12-23", "2021-12-30"]
    print(f"=== Engine [TRACE] for {debug_dates} ===")
    cmd = [
        sys.executable,
        str(ROOT / "stock_analysis" / "rocket_brt.py"),
        "data/newdata/data",
        "-o",
        "drive",
        "-s",
        "TSLA",
        "-w",
        "0",
        "--no-regression",
        "--no-equity-metrics",
        "--set",
        "yh_zones=true",
        "--set",
        "brt_zones=false",
        "--set",
        "too_high_multiplier=0",
        "--set",
        "min_spy_compare_1y_at_trigger=-1000",
        "--trace-symbol",
        "TSLA",
    ]
    for d in debug_dates:
        cmd.extend(["--trace-date", d.replace("-", "")])
        cmd.extend(["--debug-entry", "TSLA", d])

    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if any(
            x in line
            for x in ("[TRACE]", "[DEBUG-ENTRY]", "block:", "pass:", "ENTER", "already in")
        ):
            print(line)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout)[-3000:]
        print("BACKTEST FAILED:", tail, file=sys.stderr)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
