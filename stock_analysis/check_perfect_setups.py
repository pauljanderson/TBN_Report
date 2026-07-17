#!/usr/bin/env python3
"""Regression check: verify all BRT_PerfectSetups trades are present in BRT_Closed.
Exit 0 if all match, exit 1 if any are missing. Used by BRTRegressionCheck.ps1."""
import csv
import re
import sys
from pathlib import Path
from datetime import datetime

PERFECT_SETUP_TOLERANCE_DAYS = 5  # Allow entry dates to differ (next-open convention)


def parse_manual_date(s: str) -> str:
    """Parse M/D/YYYY to YYYYMMDD."""
    try:
        parts = s.strip().split("/")
        if len(parts) == 3:
            m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{y:04d}{m:02d}{d:02d}"
    except (ValueError, IndexError):
        pass
    return ""


def parse_manual_line(line: str) -> dict | None:
    parts = re.split(r"\t+|\s{2,}", line.strip())
    if len(parts) < 7:
        return None
    if parts[0].lower() == "stock":
        return None
    try:
        entry_d = parse_manual_date(parts[1])
        if not entry_d:
            return None
        float(parts[2].replace("$", "").replace(",", ""))
        exit_d = parse_manual_date(parts[3])
        float(parts[4].replace("$", "").replace(",", ""))
        return {
            "symbol": parts[0].upper(),
            "entry_date": entry_d,
            "exit_date": exit_d,
            "entry_price": parts[2],
            "exit_price": parts[4],
            "profit_pct": parts[5],
            "days": parts[6],
            "result": parts[7] if len(parts) > 7 else "",
        }
    except (ValueError, IndexError):
        return None


def load_manual(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [r for line in f for r in [parse_manual_line(line)] if r]


def load_brt(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({
                "symbol": row.get("SYMBOL", "").upper(),
                "entry_date": row.get("DATE_OPENED", "").replace("-", ""),
                "exit_date": row.get("DATE_CLOSED", "").replace("-", ""),
                "entry_price": row.get("ENTRY_PRICE", ""),
                "exit_price": row.get("EXIT_PRICE", ""),
                "profit_pct": row.get("PNL_PCT", ""),
                "days": row.get("DAYS_HELD", ""),
            })
    return rows


def parse_yyyymmdd(s: str) -> datetime | None:
    if len(s) != 8:
        return None
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def entry_dates_within_tolerance(e1: str, e2: str, tol: int) -> bool:
    d1, d2 = parse_yyyymmdd(e1), parse_yyyymmdd(e2)
    if d1 is None or d2 is None:
        return False
    return abs((d1 - d2).days) <= tol


def fuzzy_match_pairs(brt: list[dict], manual: list[dict], tolerance: int) -> list[tuple]:
    used_brt, used_manual = set(), set()
    pairs = []
    for b in sorted(brt, key=lambda r: (r["symbol"], r["exit_date"], r["entry_date"])):
        if id(b) in used_brt:
            continue
        best_m, best_diff = None, 999
        for m in manual:
            if id(m) in used_manual:
                continue
            if b["symbol"] != m["symbol"] or b["exit_date"] != m["exit_date"]:
                continue
            if not entry_dates_within_tolerance(b["entry_date"], m["entry_date"], tolerance):
                continue
            e1 = parse_yyyymmdd(b["entry_date"])
            e2 = parse_yyyymmdd(m["entry_date"])
            diff = abs((e1 - e2).days) if e1 and e2 else 999
            if diff < best_diff:
                best_diff, best_m = diff, m
        if best_m is not None:
            used_brt.add(id(b))
            used_manual.add(id(best_m))
            pairs.append((b, best_m))
    return pairs


def check(brt_path: str, perfect_setups_path: str) -> tuple[bool, list[dict]]:
    """Returns (all_present, missing_trades)."""
    brt = load_brt(brt_path)
    manual = load_manual(perfect_setups_path)
    pairs = fuzzy_match_pairs(brt, manual, PERFECT_SETUP_TOLERANCE_DAYS)
    matched_manual = {id(m) for _, m in pairs}
    missing = [m for m in manual if id(m) not in matched_manual]
    return len(missing) == 0, missing


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: check_perfect_setups.py <BRT_Closed.csv> <BRT_PerfectSetups.txt>", file=sys.stderr)
        return 2
    brt_path = sys.argv[1]
    setups_path = sys.argv[2]
    if not Path(brt_path).exists():
        print(f"BRT_Closed not found: {brt_path}", file=sys.stderr)
        return 2
    if not Path(setups_path).exists():
        print(f"Perfect setups file not found: {setups_path}", file=sys.stderr)
        return 2
    all_present, missing = check(brt_path, setups_path)
    if all_present:
        print("OK: All 22 perfect-setup trades present in BRT_Closed.")
        return 0
    # Use stdout so PowerShell doesn't treat as RemoteException when invoked by BRTRegressionCheck.ps1
    print("REGRESSION: Missing perfect-setup trades:")
    for m in sorted(missing, key=lambda x: (x["symbol"], x["entry_date"])):
        print(f"  {m['symbol']} Entry {m['entry_date']} -> Exit {m['exit_date']} ({m['result']})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
