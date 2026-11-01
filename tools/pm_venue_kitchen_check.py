"""Automated venue-vs-kitchen P&L check for EVERY prediction shop.

Platforms: kalshi, polymarket, gemini, novig.

Sources (any combination):
  - Kitchen orders_performance.html "By venue" realized column
  - settled_pnl.json (venue-priced legs from live_pm_settle_reconcile)
  - kalshi_recon_dump / pm_recon_dump JSON (bank-true Kalshi settlements + raw pulls)

Fails when:
  - |kitchen By venue − settled_pnl by venue| > tolerance (any shop)
  - Kalshi dump settle P&L vs kitchen Kalshi gap > tolerance
  - Same-direction Kalshi Yes-A + No-B stacks (GIMPEN class)
  - --require-all-dumps and a shop dump section is missing

Does not place, cancel, or sell. No secrets required when inputs are on disk.

    python -u tools/pm_venue_kitchen_check.py --kitchen-html path/to/orders_performance.html
    python -u tools/pm_venue_kitchen_check.py --kitchen-html ... --settled-pnl ... --pm-dump ...
    python -u tools/pm_venue_kitchen_check.py --kalshi-dump ... --kitchen-pnl -0.90
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_same_direction as ksd  # noqa: E402
import kalshi_venue_kitchen_check as kalshi_check  # noqa: E402

VENUES = ("kalshi", "polymarket", "gemini", "novig")
DEFAULT_TOL = Decimal("0.50")


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).replace("$", "").replace(",", "").replace("−", "-").strip()
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


class _ByVenueParser(HTMLParser):
    """Pull the first 'By venue' sortable table: Venue / Realized $ (share)."""

    def __init__(self) -> None:
        super().__init__()
        self.in_by_venue = False
        self.seen_heading = False
        self.in_table = False
        self.in_tr = False
        self.in_td = False
        self.in_th = False
        self.cell = []
        self.headers: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []
        self.heading_buf = []
        self.in_h = False
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag in {"h1", "h2", "h3"}:
            self.in_h = True
            self.heading_buf = []
        elif tag == "table" and self.seen_heading and not self.in_table and not self.rows:
            self.in_table = True
            self.in_by_venue = True
        elif self.in_table and tag == "tr":
            self.in_tr = True
            self.row = []
        elif self.in_table and tag == "th":
            self.in_th = True
            self.cell = []
        elif self.in_table and tag == "td":
            self.in_td = True
            self.cell = []

    def handle_endtag(self, tag):
        if self.done:
            return
        if tag in {"h1", "h2", "h3"} and self.in_h:
            self.in_h = False
            title = re.sub(r"\s+", " ", "".join(self.heading_buf)).strip().lower()
            if title == "by venue":
                self.seen_heading = True
            elif self.seen_heading and self.rows:
                self.done = True
        elif tag == "th" and self.in_th:
            self.in_th = False
            self.headers.append(re.sub(r"\s+", " ", "".join(self.cell)).strip().lower())
        elif tag == "td" and self.in_td:
            self.in_td = False
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.row:
                self.rows.append(self.row)
        elif tag == "table" and self.in_table:
            self.in_table = False
            if self.rows:
                self.done = True

    def handle_data(self, data):
        if self.in_h:
            self.heading_buf.append(data)
        elif self.in_th or self.in_td:
            self.cell.append(data)


def parse_kitchen_by_venue(html_text: str) -> dict[str, Decimal]:
    parser = _ByVenueParser()
    parser.feed(html_text)
    realized_idx = None
    for i, header in enumerate(parser.headers):
        if "realized" in header:
            realized_idx = i
            break
    if realized_idx is None:
        # Fallback: 4th column in the known schema (0 venue, 1 fills, 2 fees, 3 realized).
        realized_idx = 3
    out: dict[str, Decimal] = {}
    for row in parser.rows:
        if not row:
            continue
        venue = str(row[0] or "").strip().lower()
        if venue not in VENUES:
            continue
        if realized_idx >= len(row):
            continue
        pnl = _dec(row[realized_idx])
        if pnl is None:
            continue
        out[venue] = pnl
    return out


def settled_pnl_by_venue(store: dict) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {v: Decimal("0") for v in VENUES}
    if not isinstance(store, dict):
        return out
    for item in store.values():
        if not isinstance(item, dict):
            continue
        venue = str(item.get("venue") or "").lower()
        if venue not in out:
            continue
        status = str(item.get("status") or "").lower()
        if status not in {"win", "lose", "void", "settled"} and item.get("pnl") in (None, ""):
            continue
        pnl = _dec(item.get("pnl"))
        if pnl is None:
            continue
        out[venue] += pnl
    return out


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pm_dump_sections(pack: dict) -> dict[str, dict]:
    """Normalize pm_recon_dump or bare kalshi dump into per-venue sections."""
    if not isinstance(pack, dict):
        return {}
    if pack.get("pack") == "pm_recon_dump" and isinstance(pack.get("venues"), dict):
        return {str(k).lower(): v for k, v in pack["venues"].items() if isinstance(v, dict)}
    if pack.get("pack") == "kalshi_recon_dump" or "settlements" in pack:
        return {"kalshi": pack}
    return {}


def analyze(
    *,
    kitchen_by_venue: dict[str, Decimal] | None = None,
    settled_by_venue: dict[str, Decimal] | None = None,
    kalshi_pack: dict | None = None,
    kitchen_kalshi_window_pnl: Decimal | None = None,
    tolerance: Decimal = DEFAULT_TOL,
    require_all_dumps: bool = False,
    present_dumps: set[str] | None = None,
) -> dict:
    kitchen_by_venue = dict(kitchen_by_venue or {})
    settled_by_venue = dict(settled_by_venue or {})
    present_dumps = set(present_dumps or set())
    if kalshi_pack is not None:
        present_dumps.add("kalshi")

    venue_rows = []
    gaps = []
    for venue in VENUES:
        kitchen = kitchen_by_venue.get(venue)
        settled = settled_by_venue.get(venue)
        gap = None
        over = False
        if kitchen is not None and settled is not None:
            gap = (settled - kitchen).quantize(Decimal("0.01"))
            over = abs(gap) > tolerance
            if over:
                gaps.append(venue)
        venue_rows.append(
            {
                "venue": venue,
                "kitchen_realized": money(kitchen) if kitchen is not None else None,
                "settled_pnl": money(settled) if settled is not None else None,
                "gap": money(gap) if gap is not None else None,
                "gap_over_tolerance": over,
                "dump_present": venue in present_dumps,
            }
        )

    missing_dumps = [v for v in VENUES if v not in present_dumps] if require_all_dumps else []

    kalshi_report = None
    stacks = []
    if kalshi_pack is not None:
        kalshi_report = kalshi_check.analyze(
            kalshi_pack,
            kitchen_pnl=kitchen_kalshi_window_pnl,
            tolerance=tolerance,
        )
        stacks = list(kalshi_report.get("same_direction_stacks") or [])

    ok = (
        not gaps
        and not missing_dumps
        and not stacks
        and (kalshi_report is None or kalshi_report.get("ok") or (
            # When window kitchen pnl omitted, still fail on stacks; gap_over only if supplied.
            not kalshi_report.get("same_direction_stacks")
            and not kalshi_report.get("gap_over_tolerance")
        ))
    )
    # Recompute ok clearly:
    kalshi_bad = False
    if kalshi_report is not None:
        if kalshi_report.get("same_direction_stacks"):
            kalshi_bad = True
        if kitchen_kalshi_window_pnl is not None and kalshi_report.get("gap_over_tolerance"):
            kalshi_bad = True
    ok = (not gaps) and (not missing_dumps) and (not kalshi_bad)

    return {
        "venues": venue_rows,
        "tolerance": money(tolerance),
        "attribution_gap_venues": gaps,
        "missing_dumps": missing_dumps,
        "same_direction_stacks": stacks,
        "kalshi_bank_true": kalshi_report,
        "ok": ok,
        "note": (
            "All platforms: kitchen By venue vs settled_pnl.json (venue-priced). "
            "Kalshi also compares recon dump settlements when provided. "
            "Same-direction stacks are Kalshi complementary Yes-A/No-B (not a lock)."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="All-platform PM venue vs kitchen check.")
    parser.add_argument("--kitchen-html", default="", help="orders_performance.html path")
    parser.add_argument("--settled-pnl", default="", help="settled_pnl.json path")
    parser.add_argument("--kalshi-dump", default="", help="kalshi_recon_dump_latest.json")
    parser.add_argument("--pm-dump", default="", help="pm_recon_dump_latest.json (all shops)")
    parser.add_argument("--kitchen-pnl", default="", help="Optional Kalshi window kitchen closed P&L")
    parser.add_argument("--tolerance", default=str(DEFAULT_TOL))
    parser.add_argument(
        "--require-all-dumps",
        action="store_true",
        help="Fail if any of kalshi/polymarket/gemini/novig dump sections is missing.",
    )
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    kitchen_by_venue: dict[str, Decimal] = {}
    if args.kitchen_html:
        path = Path(args.kitchen_html)
        if not path.is_file():
            print(f"MISSING kitchen html: {path}", flush=True)
            return 2
        kitchen_by_venue = parse_kitchen_by_venue(path.read_text(encoding="utf-8"))

    settled_by_venue: dict[str, Decimal] = {}
    if args.settled_pnl:
        path = Path(args.settled_pnl)
        if not path.is_file():
            print(f"MISSING settled_pnl: {path}", flush=True)
            return 2
        settled_by_venue = settled_pnl_by_venue(_load_json(path))

    present_dumps: set[str] = set()
    kalshi_pack = None
    if args.pm_dump:
        path = Path(args.pm_dump)
        if not path.is_file():
            print(f"MISSING pm dump: {path}", flush=True)
            return 2
        sections = _pm_dump_sections(_load_json(path))
        present_dumps |= set(sections)
        if "kalshi" in sections:
            kalshi_pack = sections["kalshi"]
    if args.kalshi_dump:
        path = Path(args.kalshi_dump)
        if not path.is_file():
            print(f"MISSING kalshi dump: {path}", flush=True)
            return 2
        kalshi_pack = _load_json(path)
        present_dumps.add("kalshi")

    if not kitchen_by_venue and not settled_by_venue and kalshi_pack is None:
        print("Need --kitchen-html and/or --settled-pnl and/or a dump.", flush=True)
        return 2

    kitchen_window = _dec(args.kitchen_pnl) if args.kitchen_pnl not in (None, "") else None
    report = analyze(
        kitchen_by_venue=kitchen_by_venue,
        settled_by_venue=settled_by_venue,
        kalshi_pack=kalshi_pack,
        kitchen_kalshi_window_pnl=kitchen_window,
        tolerance=Decimal(str(args.tolerance)),
        require_all_dumps=bool(args.require_all_dumps),
        present_dumps=present_dumps,
    )

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("venue          kitchen   settled_pnl   gap     dump")
    for row in report["venues"]:
        print(
            f"{row['venue']:<13} "
            f"{(row['kitchen_realized'] or '-'):>8} "
            f"{(row['settled_pnl'] or '-'):>12} "
            f"{(row['gap'] or '-'):>7} "
            f"{'yes' if row['dump_present'] else 'NO'}"
        )
    if report["attribution_gap_venues"]:
        print("ATTRIBUTION GAPS:", ", ".join(report["attribution_gap_venues"]))
    if report["missing_dumps"]:
        print("MISSING DUMPS:", ", ".join(report["missing_dumps"]))
    stacks = report.get("same_direction_stacks") or []
    print(f"same_dir_n    {len(stacks)}")
    for row in stacks[:8]:
        print(f"  STACK {row.get('event')}: {row.get('reason')}")
    if report.get("kalshi_bank_true") and report["kalshi_bank_true"].get("gap") is not None:
        kt = report["kalshi_bank_true"]
        print(
            f"kalshi_window venue={kt['venue']['venue_pnl_money']} "
            f"kitchen={kt.get('kitchen_pnl')} gap={kt.get('gap')}"
        )
    if report["ok"]:
        print("RESULT OK")
        return 0
    print("RESULT FAIL — attribution gap, missing dump, and/or same-direction stack")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
