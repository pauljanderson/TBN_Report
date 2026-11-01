#!/usr/bin/env python3
"""Backfill Wilder RSI(14) overbought/oversold onto TBN *_Closed CSVs.

Adds RSI14_AT_ENTRY (fill-bar numeric), RSI14_AT_TRIGGER (signal-bar numeric),
and RSI14_OB_OS (Overbought / Oversold / Neutral from the trigger bar)
using the same 14 / 70 / 30 definition as the trendline charts.

Usage:
  python tools/enrich_closed_rsi_ob_os.py
  python tools/enrich_closed_rsi_ob_os.py --path drive/VZ_LatestRun_Closed.csv
  python tools/enrich_closed_rsi_ob_os.py --latest-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "stock_analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_tbn import enrich_closed_csv_rsi14_ob_os  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_PREFIXES = (
    "BRT",
    "YH",
    "IND",
    "MTS",
    "WPBR",
    "RS",
    "SB",
    "MVCP",
    "VZ",
    "WRL",
    "RL",
    "CS",
    "KELL",
    "QULL",
    "PBR",
)


def _latest_stamped_closed(prefix: str) -> Path | None:
    best: Path | None = None
    best_ts = ""
    for p in DRIVE.glob(f"{prefix}_Closed_*.csv"):
        name = p.name
        if "LatestRun" in name or "fundscore" in name.lower():
            continue
        stem = p.stem  # e.g. VZ_Closed_260907094941
        parts = stem.split("_")
        ts = parts[-1] if parts else ""
        if ts.isdigit() and ts > best_ts:
            best_ts = ts
            best = p
    return best


def _default_targets(*, latest_only: bool) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for prefix in DEFAULT_PREFIXES:
        latest = DRIVE / f"{prefix}_LatestRun_Closed.csv"
        if latest.is_file() and latest not in seen:
            out.append(latest)
            seen.add(latest)
        if latest_only:
            continue
        stamped = _latest_stamped_closed(prefix)
        if stamped is not None and stamped not in seen:
            out.append(stamped)
            seen.add(stamped)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", action="append", default=[], help="Closed CSV to enrich (repeatable)")
    ap.add_argument("--latest-only", action="store_true", help="Only * _LatestRun_Closed.csv")
    ap.add_argument("--data-dir", default="", help="OHLC folder (default data/newdata/data)")
    args = ap.parse_args()
    data_dir = Path(args.data_dir) if str(args.data_dir).strip() else None
    paths = [Path(p) for p in args.path] if args.path else _default_targets(latest_only=args.latest_only)
    if not paths:
        print("No Closed CSVs found.", flush=True)
        return 1
    rc = 0
    for path in paths:
        if not path.is_file():
            print(f"SKIP missing {path}", flush=True)
            rc = 1
            continue
        try:
            stats = enrich_closed_csv_rsi14_ob_os(path, data_dir=data_dir)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {path.name}: {e}", flush=True)
            rc = 1
            continue
        print(
            f"OK {path.name}: filled {stats['filled']}/{stats['rows']} rows",
            flush=True,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
