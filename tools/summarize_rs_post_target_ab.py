#!/usr/bin/env python3
"""Print a one-table comparison of RS post-TARGET A/B arms under an arm-folder root.

Reads latest RS_Report_*.csv and RS_Closed_*.csv per arm folder.

Metrics:
  Total_PNL / Max_DD / WR — from RS_Report (full current seed).
  PTQS_* — ImproveHints post_target_quick_stop: chronologically per symbol,
    a TARGET exit followed by the next closed trade exiting STOP with
    DAYS_HELD <= 10. Count = number of such STOP trades; $ = their PNL_DOLLARS.
  HINT_* — same restricted to --hint-symbols (default ASML,NVDA,TSLA,TSM;
    v2 ImproveHints: MA,NVDA).

Usage:
  python tools/summarize_rs_post_target_ab.py [--root drive/paul_experiments/rs_post_target_ab]
  python tools/summarize_rs_post_target_ab.py --root drive/paul_experiments/rs_post_target_v2_ab --hint-symbols MA,NVDA
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

DEFAULT_HINT_SYMBOLS = frozenset({"ASML", "NVDA", "TSLA", "TSM"})
MAX_QUICK_STOP_DAYS = 10


def _parse_hint_symbols(raw: str) -> frozenset[str]:
    parts = [p.strip().upper() for p in str(raw or "").split(",") if p.strip()]
    return frozenset(parts) if parts else DEFAULT_HINT_SYMBOLS


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


def _post_target_quick_stop_stats(
    closed: Path, hint_symbols: frozenset[str]
) -> dict[str, float]:
    """Return PTQS counts/$ for all + hint subset (ImproveHints definition)."""
    by_sym: dict[str, list[dict[str, str]]] = defaultdict(list)
    with open(closed, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            sym = str(row.get("SYMBOL") or "").strip().upper()
            if sym:
                by_sym[sym].append(row)

    out = {
        "ptqs_n": 0,
        "ptqs_pnl": 0.0,
        "hint_ptqs_n": 0,
        "hint_ptqs_pnl": 0.0,
    }
    for sym, trades in by_sym.items():
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
            pnl_usd = _safe_num(nxt.get("PNL_DOLLARS", nxt.get("PNL", 0)))
            out["ptqs_n"] += 1
            out["ptqs_pnl"] += pnl_usd
            if sym in hint_symbols:
                out["hint_ptqs_n"] += 1
                out["hint_ptqs_pnl"] += pnl_usd
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=Path("drive/paul_experiments/rs_post_target_ab"),
        help="A/B output root (arm subdirs)",
    )
    ap.add_argument(
        "--hint-symbols",
        default="ASML,NVDA,TSLA,TSM",
        help="Comma-separated symbols for HINT_* PTQS columns (v2: MA,NVDA)",
    )
    args = ap.parse_args()
    root: Path = args.root
    hint_symbols = _parse_hint_symbols(args.hint_symbols)
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
            _post_target_quick_stop_stats(closed, hint_symbols)
            if closed is not None
            else {k: 0 for k in ("ptqs_n", "ptqs_pnl", "hint_ptqs_n", "hint_ptqs_pnl")}
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
        f"{'PTQS_n':>6} {'PTQS_$':>10} {'HINT_n':>6} {'HINT_$':>10}"
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
            f"{int(row['ptqs_n']):6d} {row['ptqs_pnl']:10,.0f} "
            f"{int(row['hint_ptqs_n']):6d} {row['hint_ptqs_pnl']:10,.0f}"
        )
    print()
    print(f"Root: {root.resolve()}")
    print(f"HINT symbols: {','.join(sorted(hint_symbols))}")
    print(
        "PTQS = post_target_quick_stop (TARGET -> next trade STOP with DAYS_HELD<=10). "
        "Prefer lower PTQS without killing Total_PNL / Max_DD."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
