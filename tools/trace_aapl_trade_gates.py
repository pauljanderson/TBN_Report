#!/usr/bin/env python3
"""Trace AAPL sheet AH buy gates vs engine for trade parity mismatches."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "260621103925"
SYMBOL = "AAPL"


def parse_mdy(s: str) -> str:
    s = str(s).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
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
            return (
                f"open {r.open_d.date()} -> close {r.close_d.date()} "
                f"{r.EXIT_TYPE} CAD={r.cad_key}"
            )
    return None


def gate_line(d: str, g: dict, extra: str = "") -> str:
    flags = " ".join(
        f"{k}={'Y' if v else 'N'}"
        for k, v in g.items()
        if k != "sheet_AH"
    )
    ah = "PASS" if g["sheet_AH"] else "FAIL"
    return f"  {d}  sheet_AH={ah}  {flags}{extra}"


def load_eng(run_id: str) -> pd.DataFrame:
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"YH_Closed_{run_id}.csv"
        if p.exists():
            eng = pd.read_csv(p)
            break
    else:
        raise FileNotFoundError(f"YH_Closed_{run_id}.csv")
    eng = eng[eng["SYMBOL"] == SYMBOL].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
    eng["cad"] = pd.to_datetime(eng["CLOSE_ABOVE_DATE"], errors="coerce")
    eng["cad_key"] = eng["cad"].dt.strftime("%Y-%m-%d")
    eng["purch_key"] = eng["open_d"].dt.strftime("%Y-%m-%d")
    return eng.sort_values("open_d")


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else RUN_ID
    meta = pd.read_csv(ROOT / "data/newdata/data/AAPL.csv", parse_dates=["Date"]).sort_values("Date")
    iso_d = [d.strftime("%Y-%m-%d") for d in meta["Date"]]
    op = meta["Open"].to_numpy(float)
    cl = meta["Close"].to_numpy(float)

    rt = pd.read_csv(ROOT / "drive" / f"YH_breakout_and_retest_{run_id}.csv")
    rt = rt[rt["SYMBOL"] == SYMBOL].copy()
    rt["rt_iso"] = rt["Retest Date"].map(parse_mdy)
    dw_strict = set(rt["rt_iso"].dropna())

    eng = load_eng(run_id)

    trace_sets = {
        "2019 sheet 5/1 vs engine 5/30": [
            "2019-04-26", "2019-04-29", "2019-04-30", "2019-05-01", "2019-05-02",
            "2019-05-03", "2019-05-28", "2019-05-29", "2019-05-30", "2019-05-31",
        ],
        "2019 sheet 6/14 (engine in 5/30 trade)": [
            "2019-06-12", "2019-06-13", "2019-06-14", "2019-06-17", "2019-06-18",
        ],
        "2021 sheet 8/5 vs engine 10/6": [
            "2021-08-03", "2021-08-04", "2021-08-05", "2021-08-06",
            "2021-07-12", "2021-07-13", "2021-10-04", "2021-10-05", "2021-10-06",
        ],
        "2023 sheet 8/18 vs engine 9/8": [
            "2023-08-16", "2023-08-17", "2023-08-18", "2023-08-21",
            "2023-09-06", "2023-09-07", "2023-09-08",
            "2024-03-13", "2024-03-14", "2024-03-15",
        ],
        "2025 sheet 10/17 vs engine 11/24 + 1/30": [
            "2025-10-15", "2025-10-16", "2025-10-17", "2025-10-20",
            "2025-11-20", "2025-11-21", "2025-11-24",
            "2026-01-28", "2026-01-29", "2026-01-30",
        ],
    }

    print(f"Run: {run_id}  Symbol: {SYMBOL}")
    print("Sheet AH = AG & AV & COUNTIF(BO,D) & red_to_green (H7<=E7 & H8>E8)\n")

    for title, dates in trace_sets.items():
        print(f"=== {title} ===")
        for d in dates:
            if d not in iso_d:
                print(f"  {d}  (not in CSV)")
                continue
            i = iso_d.index(d)
            g = sheet_gates(i, iso_d, op, cl, dw_strict)
            it = in_trade(d, eng)
            eng_cad = eng[eng["cad_key"] == d]
            note = ""
            if len(eng_cad):
                r = eng_cad.iloc[0]
                note = f" | ENGINE open={r.open_d.date()} entry={float(r.ENTRY_PRICE):.2f}"
            print(gate_line(d, g, note))
            if it:
                print(f"    IN_TRADE: {it}")
            if d in ("2019-05-01", "2019-05-29", "2021-08-05", "2023-08-18", "2025-10-17"):
                j = i - 1 if i >= 1 else i
                print(
                    f"    bars: prior {iso_d[j]} O={op[j]:.2f} C={cl[j]:.2f} "
                    f"| today O={op[i]:.2f} C={cl[i]:.2f}"
                )
        print()

    print("=== All engine trades (context) ===")
    for _, r in eng.iterrows():
        print(
            f"  CAD={r.cad_key} open {r.open_d.date()} ${float(r.ENTRY_PRICE):.2f} "
            f"-> {r.close_d.date()} ${float(r.EXIT_PRICE):.2f} {r.EXIT_TYPE} {r.PNL_PCT}"
        )
    print()

    debug_dates = [
        "20190501", "20190529", "20190614",
        "20210805", "20211005",
        "20230818", "20230907", "20240314",
        "20251017", "20251121", "20260129",
    ]
    print(f"=== Engine [TRACE] for {debug_dates} ===")
    cmd = [
        sys.executable,
        str(ROOT / "stock_analysis" / "rocket_brt.py"),
        "data/newdata/data",
        "-o", "drive",
        "-s", SYMBOL,
        "-w", "0",
        "--no-regression",
        "--no-equity-metrics",
        "--set", "yh_zones=true",
        "--set", "brt_zones=false",
        "--set", "too_high_multiplier=0",
        "--set", "min_spy_compare_1y_at_trigger=-1000",
        "--set", "sheet_red_to_green_entry_enabled=True",
        "--set", "sheet_dw_countif_include_prior_bar_date=False",
        "--set", "sheet_no_entry_same_bar_after_exit=True",
        "--trace-symbol", SYMBOL,
    ]
    for d in debug_dates:
        cmd.extend(["--trace-date", d])
        iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        cmd.extend(["--debug-entry", SYMBOL, iso])

    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    for line in proc.stdout.splitlines():
        if any(x in line for x in ("[TRACE]", "[DEBUG-ENTRY]", "block:", "pass:", "ENTER", "already in")):
            print(line)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout)[-4000:]
        print("BACKTEST FAILED:", tail, file=sys.stderr)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
