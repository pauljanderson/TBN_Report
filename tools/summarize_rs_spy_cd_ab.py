#!/usr/bin/env python3
"""Print a one-table comparison of RS spy_int + cooldown A/B arms under rs_spy_cd_ab/.

Reads latest RS_Report_*.csv and RS_Closed_*.csv per arm folder.

Metrics:
  Total_PNL / Max_DD / WR / trades — from RS_Report (full current seed).
  PTQS_* — post_target_quick_stop: TARGET then next trade STOP with DAYS_HELD<=10.
  STOP22_* — all STOP exits with DATE_CLOSED year in {2022,2023}.
  dPnL / dTrades / dPTQS / dSTOP22 — delta vs 01_control (when present).

Usage: python tools/summarize_rs_spy_cd_ab.py [--root drive/paul_experiments/rs_spy_cd_ab]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

MAX_QUICK_STOP_DAYS = 10
CONTROL_ARM = "01_control"


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


def _ymd8(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else digits


def _closed_year(row: dict[str, str]) -> int:
    raw = str(row.get("DATE_CLOSED") or row.get("DATE CLOSED") or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 4 and digits[:4].isdigit():
        return int(digits[:4])
    return 0


def _post_target_quick_stop_stats(closed: Path) -> dict[str, float]:
    by_sym: dict[str, list[dict[str, str]]] = defaultdict(list)
    with open(closed, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            sym = str(row.get("SYMBOL") or "").strip().upper()
            if sym:
                by_sym[sym].append(row)

    out = {"ptqs_n": 0, "ptqs_pnl": 0.0}
    for _sym, trades in by_sym.items():
        trades.sort(
            key=lambda r: (
                _ymd8(r.get("DATE_OPENED") or r.get("DATE OPENED")),
                _ymd8(r.get("DATE_CLOSED") or r.get("DATE CLOSED")),
            )
        )
        for i, r in enumerate(trades):
            if i + 1 >= len(trades):
                break
            et = str(r.get("EXIT_TYPE") or r.get("EXIT TYPE") or "").strip().upper()
            if "TARGET" not in et:
                continue
            nxt = trades[i + 1]
            nxt_et = str(nxt.get("EXIT_TYPE") or nxt.get("EXIT TYPE") or "").strip().upper()
            if "STOP" not in nxt_et:
                continue
            days = int(_safe_num(nxt.get("DAYS_HELD", nxt.get("DAYS HELD", 0))))
            if days > MAX_QUICK_STOP_DAYS:
                continue
            out["ptqs_n"] += 1
            out["ptqs_pnl"] += _safe_num(nxt.get("PNL_DOLLARS", nxt.get("PNL", 0)))
    return out


def _stop22_stats(closed: Path) -> dict[str, float]:
    out = {"stop22_n": 0, "stop22_pnl": 0.0}
    with open(closed, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            et = str(row.get("EXIT_TYPE") or row.get("EXIT TYPE") or "").strip().upper()
            if "STOP" not in et:
                continue
            if _closed_year(row) not in (2022, 2023):
                continue
            out["stop22_n"] += 1
            out["stop22_pnl"] += _safe_num(row.get("PNL_DOLLARS", row.get("PNL", 0)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=Path("drive/paul_experiments/rs_spy_cd_ab"),
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
        ptqs = (
            _post_target_quick_stop_stats(closed)
            if closed is not None
            else {"ptqs_n": 0, "ptqs_pnl": 0.0}
        )
        stop22 = (
            _stop22_stats(closed)
            if closed is not None
            else {"stop22_n": 0, "stop22_pnl": 0.0}
        )
        rows.append(
            {
                "arm": arm.name,
                "stamp": stamp,
                "trades": trades,
                "pnl": _safe_num(r.get("Total_PNL", 0)),
                "maxdd": _safe_num(r.get("Max_DD", 0)),
                "wr": wr,
                **ptqs,
                **stop22,
            }
        )

    control = next((r for r in rows if r.get("arm") == CONTROL_ARM and r.get("stamp") != "MISSING"), None)

    hdr = (
        f"{'arm':22} {'stamp':12} {'trades':>7} {'Total_PNL':>12} {'Max_DD':>10} {'WR%':>7} "
        f"{'PTQS_n':>6} {'PTQS_$':>10} {'STOP22_n':>8} {'STOP22_$':>10} "
        f"{'dPnL':>10} {'dTrades':>8} {'dPTQS':>6} {'dS22':>5}"
    )
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        if row.get("stamp") == "MISSING":
            print(f"{row['arm']:22} {'MISSING':12}")
            continue
        if control is not None and row["arm"] != CONTROL_ARM:
            d_pnl = row["pnl"] - control["pnl"]
            d_trades = int(row["trades"] - control["trades"])
            d_ptqs = int(row["ptqs_n"] - control["ptqs_n"])
            d_s22 = int(row["stop22_n"] - control["stop22_n"])
            d_pnl_s = f"{d_pnl:+,.0f}"
            d_tr_s = f"{d_trades:+d}"
            d_ptqs_s = f"{d_ptqs:+d}"
            d_s22_s = f"{d_s22:+d}"
        else:
            d_pnl_s = d_tr_s = d_ptqs_s = d_s22_s = "—"
        print(
            f"{row['arm']:22} {row['stamp']:12} {row['trades']:7d} "
            f"{row['pnl']:12,.0f} {row['maxdd']:10,.0f} {row['wr']:6.1f}% "
            f"{int(row['ptqs_n']):6d} {row['ptqs_pnl']:10,.0f} "
            f"{int(row['stop22_n']):8d} {row['stop22_pnl']:10,.0f} "
            f"{d_pnl_s:>10} {d_tr_s:>8} {d_ptqs_s:>6} {d_s22_s:>5}"
        )
    print()
    print(f"Root: {root.resolve()}")
    print(
        "PTQS = TARGET -> next trade STOP with DAYS_HELD<=10. "
        "STOP22 = all STOP closed in 2022|2023. "
        "d* = vs 01_control."
    )
    print(
        "Look for spy_int + cd combos that keep/raise Total_PNL vs control "
        "while cutting trades / PTQS / STOP22 more than spy_int-only or cd-alone."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
