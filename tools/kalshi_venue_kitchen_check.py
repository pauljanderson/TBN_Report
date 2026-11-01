"""Kalshi-only venue-vs-kitchen helper (bank-true settlements).

Prefer tools/pm_venue_kitchen_check.py / run_pm_venue_kitchen_check.bat for
ALL platforms (kalshi + polymarket + gemini + novig). This module stays as the
Kalshi settlement math + same-direction stack detector used by the all-shop gate.

    python -u tools/kalshi_venue_kitchen_check.py --dump path/to/kalshi_recon_dump_latest.json
    python -u tools/kalshi_venue_kitchen_check.py --dump ... --kitchen-pnl -0.90 --tolerance 0.50
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_same_direction as ksd  # noqa: E402

ET = ZoneInfo("America/New_York")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _settlements(pack: dict) -> list[dict]:
    block = pack.get("settlements") or {}
    if isinstance(block, dict):
        rows = block.get("settlements")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        body = block.get("body") or {}
        if isinstance(body, dict) and isinstance(body.get("settlements"), list):
            return [r for r in body["settlements"] if isinstance(r, dict)]
    if isinstance(pack.get("settlements"), list):
        return [r for r in pack["settlements"] if isinstance(r, dict)]
    return []


def _fills(pack: dict) -> list[dict]:
    block = pack.get("fills") or {}
    if isinstance(block, dict):
        rows = block.get("fills")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        body = block.get("body") or {}
        if isinstance(body, dict) and isinstance(body.get("fills"), list):
            return [r for r in body["fills"] if isinstance(r, dict)]
    return []


def _settled_day(row: dict) -> str:
    raw = row.get("settled_time") or row.get("settled_ts") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(ET)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def venue_settlement_totals(pack: dict) -> dict:
    rows = _settlements(pack)
    by_day: dict[str, Decimal] = {}
    total = Decimal("0")
    priced = 0
    for row in rows:
        pnl = ksd.settlement_pnl_usd(row)
        if pnl is None:
            continue
        priced += 1
        total += pnl
        day = _settled_day(row) or "unknown"
        by_day[day] = by_day.get(day, Decimal("0")) + pnl
    return {
        "n_settlements": len(rows),
        "n_priced": priced,
        "venue_pnl": total,
        "by_day": {d: ksd.money(v) for d, v in sorted(by_day.items())},
        "venue_pnl_money": ksd.money(total),
    }


def analyze(pack: dict, *, kitchen_pnl: Decimal | None, tolerance: Decimal) -> dict:
    totals = venue_settlement_totals(pack)
    stacks = ksd.find_same_direction_stacks(_settlements(pack) + _fills(pack))
    # De-dupe stacks by event.
    seen = set()
    unique_stacks = []
    for row in stacks:
        key = row.get("event")
        if key in seen:
            continue
        seen.add(key)
        unique_stacks.append(row)

    venue = totals["venue_pnl"]
    gap = None
    gap_money = None
    if kitchen_pnl is not None:
        gap = (venue - kitchen_pnl).quantize(Decimal("0.01"))
        gap_money = ksd.money(gap)

    over = bool(gap is not None and abs(gap) > tolerance)
    return {
        "written_at": pack.get("written_at"),
        "days": pack.get("days"),
        "venue": totals,
        "kitchen_pnl": ksd.money(kitchen_pnl) if kitchen_pnl is not None else None,
        "gap": gap_money,
        "tolerance": ksd.money(tolerance),
        "gap_over_tolerance": over,
        "same_direction_stacks": unique_stacks,
        "ok": (not over) and (not unique_stacks),
        "note": (
            "ok means no same-direction stack in the dump window and (when kitchen "
            "P&L is supplied) |venue − kitchen| ≤ tolerance. Combined dashboard P&L "
            "is not a Kalshi bank-true number."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Kalshi venue vs kitchen gap check.")
    parser.add_argument("--dump", required=True, help="Path to kalshi_recon_dump_latest.json")
    parser.add_argument(
        "--kitchen-pnl",
        default=None,
        help="Kitchen Kalshi-labeled closed P&L for the same window (e.g. -0.90).",
    )
    parser.add_argument(
        "--tolerance",
        default="0.50",
        help="Max |venue − kitchen| dollars before fail (default 0.50).",
    )
    parser.add_argument("--json-out", default="", help="Optional path to write the report JSON.")
    args = parser.parse_args()

    path = Path(args.dump)
    if not path.is_file():
        print(f"MISSING dump: {path}", flush=True)
        return 2
    try:
        pack = _load(path)
    except Exception as exc:
        print(f"BAD dump JSON: {exc}", flush=True)
        return 2

    kitchen = None
    if args.kitchen_pnl not in (None, ""):
        kitchen = Decimal(str(args.kitchen_pnl))
    tolerance = Decimal(str(args.tolerance))
    report = analyze(pack, kitchen_pnl=kitchen, tolerance=tolerance)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"dump        {path}")
    print(f"written_at  {report.get('written_at')}")
    print(f"venue_pnl   {report['venue']['venue_pnl_money']}  (n={report['venue']['n_priced']})")
    if report.get("kitchen_pnl") is not None:
        print(f"kitchen_pnl {report['kitchen_pnl']}")
        print(f"gap         {report['gap']}  (tol {report['tolerance']})")
    stacks = report.get("same_direction_stacks") or []
    print(f"same_dir_n  {len(stacks)}")
    for row in stacks[:12]:
        print(f"  STACK {row.get('event')}: {row.get('reason')}")
    if report["ok"]:
        print("RESULT OK")
        return 0
    print("RESULT FAIL — venue/kitchen gap and/or same-direction stack")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
