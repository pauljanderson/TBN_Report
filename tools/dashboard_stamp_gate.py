"""Gate: living dashboard.html must carry writer-emitted columns after rebuild.

Paul problem class (2026-11-04): PR #46 merged Size @ price + Gibson Poly
Yes-wire invert into main; git pull updated the writers; Drive dashboard.html
stayed on the pre-merge stamp (rebuilt 2026-11-03 21:13 ET). Opening the
latest HTML after pull alone looked like the fix never landed.

Fails when:
  - write_dashboard.TRADE_HEADERS is missing Size @ price (writer drift)
  - stamp dashboard.html exists and is missing Size @ price (stale stamp)
  - stamp has Gibson/Oliynykova rows still showing Poly Yes-wire 0.84 as cost
    without the corrected-lock note (pre-invert stamp)

Does not place, cancel, or sell. No secrets. No network.

    python -u tools/dashboard_stamp_gate.py
    python -u tools/dashboard_stamp_gate.py --dashboard-html path/to/dashboard.html
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP  # noqa: E402

SIZE_AT_PRICE = "Size @ price"
GIBSON_NEEDLES = ("gibson", "oliynykova")
# Pre-fix stamp showed Poly Yes-wire 0.8400 on Gibson SHORT (false ~1.67 lock).
FALSE_GIBSON_WIRE = re.compile(
    r"Gibson\s+vs\s+Oliynykova[\s\S]{0,400}?polymarket[\s\S]{0,200}?>0\.8400<",
    re.IGNORECASE,
)
CORRECTED_NOTE = "Corrected Gibson/Oliynykova lock"


def writer_has_size_at_price() -> bool:
    import write_dashboard as d

    return any(h[0] == SIZE_AT_PRICE for h in d.TRADE_HEADERS)


def stamp_has_size_at_price(html: str) -> bool:
    return SIZE_AT_PRICE in (html or "")


def stamp_has_stale_gibson_poly_wire(html: str) -> bool:
    """True when Gibson rows still show the pre-invert 0.84 Yes-wire booking."""
    text = html or ""
    low = text.lower()
    if not all(n in low for n in GIBSON_NEEDLES):
        return False
    if CORRECTED_NOTE in text:
        return False
    return bool(FALSE_GIBSON_WIRE.search(text))


def check(*, dashboard_html: Path | None = None, require_stamp: bool = False) -> dict:
    """Return a report. ok=False means the gate failed."""
    path = dashboard_html or (DRIVE_STAMP / "dashboard.html")
    report: dict = {
        "ok": True,
        "writer_size_at_price": writer_has_size_at_price(),
        "stamp_path": str(path),
        "stamp_exists": path.is_file(),
        "stamp_size_at_price": None,
        "stamp_stale_gibson_wire": None,
        "failures": [],
    }
    if not report["writer_size_at_price"]:
        report["ok"] = False
        report["failures"].append(
            "write_dashboard.TRADE_HEADERS missing Size @ price — writer regression"
        )

    if not path.is_file():
        if require_stamp:
            report["ok"] = False
            report["failures"].append(f"missing stamp dashboard.html: {path}")
        return report

    html = path.read_text(encoding="utf-8", errors="replace")
    report["stamp_size_at_price"] = stamp_has_size_at_price(html)
    report["stamp_stale_gibson_wire"] = stamp_has_stale_gibson_poly_wire(html)

    if not report["stamp_size_at_price"]:
        report["ok"] = False
        report["failures"].append(
            "dashboard.html missing Size @ price — stamp is stale; "
            "git pull alone does not rebuild. Run: python tools/write_orders_performance.py "
            "or run_rebuild_kitchen_dashboard.bat"
        )
    if report["stamp_stale_gibson_wire"]:
        report["ok"] = False
        report["failures"].append(
            "dashboard.html still shows Gibson Poly Yes-wire 0.84 without "
            "Corrected Gibson/Oliynykova lock — rebuild kitchen HTML from tape"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when living dashboard.html lags writer columns (Size @ price / Gibson)."
    )
    parser.add_argument(
        "--dashboard-html",
        default="",
        help="Path to dashboard.html (default: Drive stamp).",
    )
    parser.add_argument(
        "--require-stamp",
        action="store_true",
        help="Fail when dashboard.html is missing (trading-PC gate).",
    )
    args = parser.parse_args(argv)
    path = Path(args.dashboard_html) if args.dashboard_html else None
    report = check(dashboard_html=path, require_stamp=bool(args.require_stamp))
    print(
        f"writer_size_at_price={report['writer_size_at_price']} "
        f"stamp_exists={report['stamp_exists']} "
        f"stamp_size_at_price={report['stamp_size_at_price']} "
        f"stamp_stale_gibson_wire={report['stamp_stale_gibson_wire']}",
        flush=True,
    )
    for fail in report["failures"]:
        print(f"FAIL: {fail}", flush=True)
    if report["ok"]:
        print("RESULT PASS — dashboard stamp matches Size @ price writer", flush=True)
        return 0
    print("RESULT FAIL — rebuild kitchen dashboard after pull", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
