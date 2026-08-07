#!/usr/bin/env python3
"""Print a one-table comparison of RS false-start A/B arms under rs_false_start_ab/.

Reads latest RS_Report_*.csv and RS_Closed_*.csv per arm folder.

Metrics:
  Total_PNL / Max_DD / WR — from RS_Report (full current seed).
  FS15_* — ImproveHints false_start_2022_2023: STOP exit, DATE_CLOSED year in
    {2022,2023}, DAYS_HELD <= 15, PNL_PCT < 0.
  STOP22_* — all STOP exits with DATE_CLOSED year in {2022,2023} (broader regime).
  HINT_* — same counts restricted to ImproveHints symbols
    (ASML,AVGO,GOOG,GOOGL,NVDA,TSLA).

Usage: python tools/summarize_rs_false_start_ab.py [--root drive/paul_experiments/rs_false_start_ab]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Optional

HINT_SYMBOLS = frozenset({"ASML", "AVGO", "GOOG", "GOOGL", "NVDA", "TSLA"})


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


def _closed_year(row: dict[str, str]) -> int:
    raw = str(row.get("DATE_CLOSED") or row.get("DATE CLOSED") or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 4 and digits[:4].isdigit():
        return int(digits[:4])
    return 0


def _stop_stats(closed: Path) -> dict[str, float]:
    """Return FS15 / STOP22 counts and $ for all + hint subset."""
    out = {
        "fs15_n": 0,
        "fs15_pnl": 0.0,
        "stop22_n": 0,
        "stop22_pnl": 0.0,
        "hint_fs15_n": 0,
        "hint_fs15_pnl": 0.0,
        "hint_stop22_n": 0,
        "hint_stop22_pnl": 0.0,
    }
    with open(closed, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            et = str(row.get("EXIT_TYPE") or row.get("EXIT TYPE") or "").strip().upper()
            if "STOP" not in et:
                continue
            year = _closed_year(row)
            if year not in (2022, 2023):
                continue
            days = int(_safe_num(row.get("DAYS_HELD", row.get("DAYS HELD", 0))))
            pnl_pct = _safe_num(row.get("PNL_PCT", row.get("PNL %", 0)))
            pnl_usd = _safe_num(row.get("PNL_DOLLARS", row.get("PNL", 0)))
            sym = str(row.get("SYMBOL") or "").strip().upper()
            is_hint = sym in HINT_SYMBOLS

            out["stop22_n"] += 1
            out["stop22_pnl"] += pnl_usd
            if is_hint:
                out["hint_stop22_n"] += 1
                out["hint_stop22_pnl"] += pnl_usd

            if days <= 15 and pnl_pct < 0:
                out["fs15_n"] += 1
                out["fs15_pnl"] += pnl_usd
                if is_hint:
                    out["hint_fs15_n"] += 1
                    out["hint_fs15_pnl"] += pnl_usd
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=Path("drive/paul_experiments/rs_false_start_ab"),
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
        stats = (
            _stop_stats(closed)
            if closed is not None
            else {k: 0 for k in (
                "fs15_n", "fs15_pnl", "stop22_n", "stop22_pnl",
                "hint_fs15_n", "hint_fs15_pnl", "hint_stop22_n", "hint_stop22_pnl",
            )}
        )
        rows.append(
            {
                "arm": arm.name,
                "stamp": stamp,
                "trades": trades,
                "pnl": _safe_num(r.get("Total_PNL", 0)),
                "maxdd": _safe_num(r.get("Max_DD", 0)),
                "wr": wr,
                **stats,
            }
        )

    hdr = (
        f"{'arm':28} {'stamp':12} {'trades':>7} {'Total_PNL':>12} {'Max_DD':>10} {'WR%':>7} "
        f"{'FS15_n':>6} {'FS15_$':>10} {'STOP22_n':>8} {'STOP22_$':>10} "
        f"{'HINT_FS':>7} {'HINT_S22':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        if row.get("stamp") == "MISSING":
            print(f"{row['arm']:28} {'MISSING':12}")
            continue
        print(
            f"{row['arm']:28} {row['stamp']:12} {row['trades']:7d} "
            f"{row['pnl']:12,.0f} {row['maxdd']:10,.0f} {row['wr']:6.1f}% "
            f"{int(row['fs15_n']):6d} {row['fs15_pnl']:10,.0f} "
            f"{int(row['stop22_n']):8d} {row['stop22_pnl']:10,.0f} "
            f"{int(row['hint_fs15_n']):7d} {int(row['hint_stop22_n']):8d}"
        )
    print()
    print(f"Root: {root.resolve()}")
    print(
        "FS15 = ImproveHints false_start (STOP, close yr 2022|2023, hold<=15d, pnl%<0). "
        "STOP22 = all STOP closed in 2022|2023. HINT_* = ASML/AVGO/GOOG/GOOGL/NVDA/TSLA."
    )
    print("Compare Total_PNL / Max_DD vs control; prefer lower FS15/STOP22 without killing PnL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
