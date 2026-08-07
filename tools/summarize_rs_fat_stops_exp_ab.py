#!/usr/bin/env python3
"""Print a one-table comparison of RS fat_stops A/B arms under rs_fat_stops_exp_ab/.

Reads latest RS_Report_*.csv and RS_Closed_*.csv per arm folder.

Metrics:
  Total_PNL / Max_DD / WR / trades — from RS_Report.
  fat_n / fat_$ — fat_stops: EXIT_TYPE has STOP with PNL_PCT <= -12, or GAP_DOWN
    (matches ImproveHints fat_stops + gap-past-stop risk).
  dPnL / dDD / dWR / dTrades / dFat / dFat$ — delta vs 01_control (when present).

Usage:
  python tools/summarize_rs_fat_stops_exp_ab.py
  python tools/summarize_rs_fat_stops_exp_ab.py --root drive/paul_experiments/rs_fat_stops_exp_ab
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Optional

CONTROL_ARM = "01_control"
FAT_PNL_PCT_LTE = -12.0


def _safe_num(x: Any) -> float:
    if x is None or x == "" or str(x).strip().upper() == "N/A":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _fat_stop_stats(closed: Path) -> dict[str, float]:
    """Count fat STOP (PNL_PCT <= -12) or GAP_DOWN exits; sum PNL_DOLLARS."""
    out = {"fat_n": 0, "fat_pnl": 0.0}
    with open(closed, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            et = str(row.get("EXIT_TYPE") or row.get("EXIT TYPE") or "").strip().upper()
            pnl_pct = _safe_num(row.get("PNL_PCT", row.get("PNL %", 0)))
            pnl_usd = _safe_num(row.get("PNL_DOLLARS", row.get("PNL", 0)))
            is_gap = et == "GAP_DOWN" or et.startswith("GAP_DOWN")
            is_fat_stop = "STOP" in et and pnl_pct <= FAT_PNL_PCT_LTE
            if not (is_gap or is_fat_stop):
                continue
            out["fat_n"] += 1
            out["fat_pnl"] += pnl_usd
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=Path("drive/paul_experiments/rs_fat_stops_exp_ab"),
        help="A/B output root (arm subdirs)",
    )
    args = ap.parse_args()
    root: Path = args.root
    if not root.is_dir():
        print(f"No output root yet: {root}", file=sys.stderr)
        return 1

    arms = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
    if not arms:
        print(f"No arm folders under {root}", file=sys.stderr)
        return 1

    rows: list[dict[str, Any]] = []
    for arm in arms:
        report = _latest(arm, "RS_Report_*.csv")
        if report is None:
            report = _latest(arm, "RS_Audit_Report_*.csv")
        closed = _latest(arm, "RS_Closed_*.csv")
        if report is None:
            rows.append({"arm": arm.name, "stamp": "MISSING"})
            continue
        with open(report, newline="", encoding="utf-8", errors="replace") as f:
            r = next(csv.DictReader(f), {}) or {}
        wins = int(_safe_num(r.get("Wins", 0)))
        losses = int(_safe_num(r.get("Losses", 0)))
        bes = int(_safe_num(r.get("BE", r.get("BEs", 0))))
        trades = int(_safe_num(r.get("Total_Trades", 0))) or (wins + losses + bes)
        wr = (100.0 * wins / trades) if trades else 0.0
        stamp = report.stem.split("_")[-1]
        fat = (
            _fat_stop_stats(closed)
            if closed is not None
            else {"fat_n": 0, "fat_pnl": 0.0}
        )
        rows.append(
            {
                "arm": arm.name,
                "stamp": stamp,
                "trades": trades,
                "pnl": _safe_num(r.get("Total_PNL", 0)),
                "maxdd": _safe_num(r.get("Max_DD", 0)),
                "wr": wr,
                **fat,
            }
        )

    control = next(
        (r for r in rows if r.get("arm") == CONTROL_ARM and r.get("stamp") != "MISSING"),
        None,
    )

    hdr = (
        f"{'arm':22} {'stamp':12} {'trades':>7} {'Total_PNL':>12} {'Max_DD':>10} {'WR%':>7} "
        f"{'fat_n':>6} {'fat_$':>10} "
        f"{'dPnL':>10} {'dDD':>10} {'dWR':>7} {'dTrades':>8} {'dFat':>5} {'dFat$':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        if row.get("stamp") == "MISSING":
            print(f"{row['arm']:22} {'MISSING':12}")
            continue
        if control is not None and row["arm"] != CONTROL_ARM:
            d_pnl = row["pnl"] - control["pnl"]
            d_dd = row["maxdd"] - control["maxdd"]
            d_wr = row["wr"] - control["wr"]
            d_trades = int(row["trades"] - control["trades"])
            d_fat = int(row["fat_n"] - control["fat_n"])
            d_fat_pnl = row["fat_pnl"] - control["fat_pnl"]
            d_pnl_s = f"{d_pnl:+,.0f}"
            d_dd_s = f"{d_dd:+,.0f}"
            d_wr_s = f"{d_wr:+.1f}"
            d_tr_s = f"{d_trades:+d}"
            d_fat_s = f"{d_fat:+d}"
            d_fat_pnl_s = f"{d_fat_pnl:+,.0f}"
        else:
            d_pnl_s = d_dd_s = d_wr_s = d_tr_s = d_fat_s = d_fat_pnl_s = "—"
        print(
            f"{row['arm']:22} {row['stamp']:12} {row['trades']:7d} "
            f"{row['pnl']:12,.0f} {row['maxdd']:10,.0f} {row['wr']:6.1f}% "
            f"{int(row['fat_n']):6d} {row['fat_pnl']:10,.0f} "
            f"{d_pnl_s:>10} {d_dd_s:>10} {d_wr_s:>7} {d_tr_s:>8} {d_fat_s:>5} {d_fat_pnl_s:>10}"
        )
    print()
    print(f"Root: {root.resolve()}")
    print(
        "fat_* = STOP with PNL_PCT<=-12 or GAP_DOWN (ImproveHints fat_stops + gap risk). "
        "d* = vs 01_control."
    )
    print(
        "Look for arms that cut fat_n / fat_$ without collapsing Total_PNL vs control. "
        "Prior seed AB: tighter stop_pct hurt PnL — confirm on expanded universe."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
