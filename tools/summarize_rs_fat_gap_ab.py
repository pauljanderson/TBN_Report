#!/usr/bin/env python3
"""Print a one-table comparison of RS fat-gap A/B arms under rs_fat_gap_ab/.

Reads latest RS_Report_*.csv and RS_Closed_*.csv per arm folder.
Usage: python tools/summarize_rs_fat_gap_ab.py [--root drive/paul_experiments/rs_fat_gap_ab]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Optional


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


def _gap_down_stats(closed: Path) -> tuple[int, float]:
    n = 0
    pnl = 0.0
    with open(closed, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            et = str(row.get("EXIT_TYPE", "") or "").strip().upper()
            if et == "GAP_DOWN":
                n += 1
                pnl += _safe_num(row.get("PNL_DOLLARS", row.get("PNL", 0)))
    return n, pnl


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=Path("drive/paul_experiments/rs_fat_gap_ab"),
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
            rows.append({"arm": arm.name, "stamp": "MISSING", "trades": "", "pnl": "", "maxdd": "", "wr": "", "gap_n": "", "gap_pnl": ""})
            continue
        with open(report, newline="", encoding="utf-8", errors="replace") as f:
            r = next(csv.DictReader(f), {}) or {}
        wins = int(_safe_num(r.get("Wins", 0)))
        losses = int(_safe_num(r.get("Losses", 0)))
        bes = int(_safe_num(r.get("BE", r.get("BEs", 0))))
        trades = int(_safe_num(r.get("Total_Trades", 0))) or (wins + losses + bes)
        wr = (100.0 * wins / trades) if trades else 0.0
        stamp = report.stem.split("_")[-1]
        gap_n, gap_pnl = (0, 0.0)
        if closed is not None:
            gap_n, gap_pnl = _gap_down_stats(closed)
        rows.append(
            {
                "arm": arm.name,
                "stamp": stamp,
                "trades": trades,
                "pnl": _safe_num(r.get("Total_PNL", 0)),
                "maxdd": _safe_num(r.get("Max_DD", 0)),
                "wr": wr,
                "gap_n": gap_n,
                "gap_pnl": gap_pnl,
            }
        )

    hdr = f"{'arm':22} {'stamp':12} {'trades':>7} {'Total_PNL':>12} {'Max_DD':>10} {'WR%':>7} {'GAP_DOWN':>8} {'GAP_PNL':>12}"
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        if row["stamp"] == "MISSING":
            print(f"{row['arm']:22} {'MISSING':12}")
            continue
        print(
            f"{row['arm']:22} {row['stamp']:12} {row['trades']:7d} "
            f"{row['pnl']:12,.0f} {row['maxdd']:10,.0f} {row['wr']:6.1f}% "
            f"{row['gap_n']:8d} {row['gap_pnl']:12,.0f}"
        )
    print()
    print(f"Root: {root.resolve()}")
    print("Compare Total_PNL / Max_DD vs control; fat risk ≈ GAP_DOWN count + GAP_PNL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
