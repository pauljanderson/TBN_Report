#!/usr/bin/env python3
"""Write pending low-volume exit report (next session open) as CSV."""
from __future__ import annotations

import argparse
import shutil
from datetime import date, datetime
from pathlib import Path

from sell_report_lib import (
    DEFAULT_DATA_DIR,
    find_pending_low_vol_sells,
    write_sell_report_csv,
)

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "Drive"
DEFAULT_POSITIONS = ROOT / "gettarget_positions.csv"
DEFAULT_GETTARGET = ROOT / "getTarget_output.csv"


def main() -> None:
    p = argparse.ArgumentParser(description="Pending sell report (sell_on_low_vol, next open)")
    p.add_argument("--positions", type=Path, default=DEFAULT_POSITIONS)
    p.add_argument("--gettarget", type=Path, default=DEFAULT_GETTARGET)
    p.add_argument("--drive", type=Path, default=DRIVE)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--as-of", default=None, help="As-of date YYYY-MM-DD (default: getTarget AsOfDate or today)")
    p.add_argument("--ind-sell-on-low-vol", type=float, default=None, help="Override IND threshold from audit")
    p.add_argument("--brt-sell-on-low-vol", type=float, default=None, help="Override BRT threshold from audit")
    p.add_argument("-o", "--output", type=Path, default=None)
    p.add_argument(
        "--no-copy-latest",
        action="store_true",
        help="Do not copy to Drive/Sell_Report_Latest.csv",
    )
    args = p.parse_args()

    as_of = None
    if args.as_of:
        as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()

    overrides: dict[str, float] = {}
    if args.ind_sell_on_low_vol is not None:
        overrides["IND"] = float(args.ind_sell_on_low_vol)
    if args.brt_sell_on_low_vol is not None:
        overrides["BRT"] = float(args.brt_sell_on_low_vol)

    pending, thresholds, as_of_resolved = find_pending_low_vol_sells(
        positions_path=args.positions,
        gettarget_path=args.gettarget,
        drive_dir=args.drive,
        as_of_date=as_of,
        data_dir=args.data_dir,
        thresholds=overrides or None,
    )

    out = args.output or (args.drive / f"Sell_Report_{datetime.now():%Y%m%d_%H%M%S}.csv")
    write_sell_report_csv(pending, out)
    print(f"Wrote {out} ({len(pending)} pending sell(s); as-of {as_of_resolved})")
    print(f"  IND sell_on_low_vol={thresholds.get('IND', 0)}  BRT sell_on_low_vol={thresholds.get('BRT', 0)}")

    if not args.no_copy_latest:
        latest = args.drive / "Sell_Report_Latest.csv"
        latest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, latest)
        print(f"Copied to {latest}")


if __name__ == "__main__":
    main()
