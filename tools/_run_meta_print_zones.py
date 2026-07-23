#!/usr/bin/env python3
"""META-only BRT run with --print-zones and sheet-matching flags."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA = ROOT / "data" / "newdata" / "data"
PER_SYMBOL = ROOT / "stock_analysis" / "Per_Symbol_Optimized_Settings_Approved_Latest.json"
PY = sys.executable

BASE_V = [
    "stop_pct=0.934",
    "target_pct=1.21",
    "too_high_multiplier=0",
    "band_pct=0.0154",
    "strong_pre_pivot_pct=0.081",
    "strong_post_pivot_pct=0.108",
    "strong_pre_pivot_bars=7",
    "strong_post_pivot_bars=7",
    "breakout_bars=100",
    "tight_range_threshold_pct=0.35",
    "tight_range_lookback=105",
    "sheet_breakout_scan_start_row_delta=2",
    "brt_sheet_touch=true",
    "min_spy_compare_1y_at_trigger=-1000",
    "sheet_red_to_green_entry_enabled=true",
    "sheet_dw_countif_include_prior_bar_date=false",
    "growth_filter_enabled=true",
    "min_ind_score=-1",
    "compute_beta=true",
    "brt_zones=true",
    "yh_zones=false",
    "min_pivot_run_h_before_entry=0",
    "min_beta_at_trigger=0",
    "max_market_cap=0",
    "breakout_zone_pick=max",
    "stop_loss_based=trigger_low",
]


def newest_after(pattern: str, t0: float) -> Path | None:
    best = None
    best_m = t0
    for p in DRIVE.glob(pattern):
        m = p.stat().st_mtime
        if m >= t0 and (best is None or m > best_m):
            best, best_m = p, m
    return best


def main() -> None:
    cmd = [
        PY,
        str(ROOT / "stock_analysis" / "rocket_brt.py"),
        str(DATA),
        "-o",
        str(DRIVE),
        "-w",
        "1",
        "--no-regression",
        "--aggressive",
        "--print-zones",
        "-s",
        "META",
    ]
    if PER_SYMBOL.exists():
        cmd += ["--per-symbol-settings", str(PER_SYMBOL)]
    for v in BASE_V:
        cmd += ["-v", v]
    print("CMD:", " ".join(cmd), flush=True)
    t0 = time.time() - 1.0
    rc = subprocess.run(cmd, cwd=str(ROOT))
    if rc.returncode != 0:
        raise SystemExit(rc.returncode)
    closed = newest_after("BRT_Closed_*.csv", t0)
    zones = newest_after("BRT_ZONES_META_*.csv", t0)
    bos = newest_after("BRT_breakout_and_retest_*.csv", t0)
    print(f"closed={closed.name if closed else None}", flush=True)
    print(f"zones={zones.name if zones else None}", flush=True)
    print(f"bos={bos.name if bos else None}", flush=True)
    stamp = None
    if closed:
        stamp = closed.name.replace("BRT_Closed_", "").replace(".csv", "")
    print(f"STAMP={stamp}", flush=True)
    (DRIVE / "brt_sheet_reconcile" / "META_last_engine_stamp.txt").write_text(
        stamp or "", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
