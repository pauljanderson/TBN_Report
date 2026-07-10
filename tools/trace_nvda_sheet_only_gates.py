#!/usr/bin/env python3
"""Run per-bar [TRACE] gate lines for NVDA sheet_only trigger dates (sequential NVDA backtest)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.compare_nvda_sheet import load_sheet, next_td  # noqa: E402
from tools.analyze_nvda_gaps import _closed_path, open_blocker  # noqa: E402
import pandas as pd  # noqa: E402


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260620194127"
    eng = pd.read_csv(_closed_path(run_id))
    eng = eng[eng.SYMBOL == "NVDA"].copy()
    eng["open_d"] = pd.to_datetime(eng.DATE_OPENED.astype(str), format="%Y%m%d")
    eng["purch_key"] = eng.open_d.dt.strftime("%Y-%m-%d")

    meta = pd.read_csv(ROOT / "data/newdata/data/NVDA.csv", parse_dates=["Date"])
    iso = [d.strftime("%Y-%m-%d") for d in meta.sort_values("Date").Date]
    sheet = load_sheet()
    sheet["purch_d"] = sheet.trigger_d.map(lambda d: next_td(iso, d) if d in iso else "")

    matched = {s.purch_d for _, s in sheet.iterrows() if s.purch_d in set(eng.purch_key)}

    dates: list[str] = []
    for _, s in sheet.iterrows():
        if s.purch_d in matched:
            continue
        if open_blocker(eng, s.purch_d) is not None:
            continue
        dates.append(s.trigger_d)
        # also trace purchase day (entry eval may roll to next bar)
        if s.purch_d:
            dates.append(s.purch_d)

    dates = sorted(set(dates))
    print(f"Tracing {len(dates)} dates: {dates}\n")

    cmd = [
        sys.executable,
        str(ROOT / "stock_analysis" / "rocket_brt.py"),
        "data/newdata/data",
        "-o",
        "drive",
        "-s",
        "NVDA",
        "-w",
        "0",
        "--no-regression",
        "--no-equity-metrics",
        "--set",
        "too_high_multiplier=0",
        "--set",
        "min_spy_compare_1y_at_trigger=-1000",
        "--set",
        "yh_zones=true",
        "--set",
        "brt_zones=false",
        "--trace-symbol",
        "NVDA",
    ]
    for d in dates:
        cmd.extend(["--trace-date", d])

    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("[TRACE]") or line.startswith("[DEBUG-ENTRY]"):
            print(line)
    if proc.returncode != 0:
        print(proc.stderr[-2000:] if proc.stderr else "backtest failed", file=sys.stderr)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
