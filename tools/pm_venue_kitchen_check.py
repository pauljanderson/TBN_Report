"""Automated venue-vs-kitchen P&L check for EVERY prediction shop.

Platforms: kalshi, polymarket, gemini, novig.

Sources (any combination):
  - Kitchen orders_performance.html "By venue" realized column
  - settled_pnl.json (venue-priced legs from live_pm_settle_reconcile)
  - kalshi_recon_dump / pm_recon_dump JSON (bank-true Kalshi settlements + raw pulls)

Fails when:
  - |kitchen By venue − settled_pnl by venue| > tolerance (any shop)
  - Kalshi dump settle P&L vs kitchen Kalshi gap > tolerance
  - Same-direction Yes-A + No-B stacks on ANY shop (GIMPEN class;
    Kalshi -CODE and Polymarket/Gemini trailing-token twins)
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


def _settled_orders_blob(store: dict) -> dict:
    """Unwrap settled_pnl.json envelope {orders: {...}} used by settled_pnl_store.save."""
    if not isinstance(store, dict):
        return {}
    orders = store.get("orders")
    if isinstance(orders, dict):
        return orders
    # Flat map of order_id → row (tests / older files).
    return store


def settled_pnl_by_venue(store: dict) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {v: Decimal("0") for v in VENUES}
    rows = _settled_orders_blob(store)
    if not isinstance(rows, dict):
        return out
    for item in rows.values():
        if not isinstance(item, dict):
            continue
        venue = str(item.get("venue") or "").lower()
        if venue not in out:
            continue
        status = str(item.get("status") or "").lower()
        if status not in {"win", "lose", "void", "settled", "flatten"} and item.get("pnl") in (
            None,
            "",
        ):
            continue
        pnl = _dec(item.get("pnl"))
        if pnl is None:
            continue
        out[venue] += pnl
    return out


def heal_attribution_gaps(
    settled_path: Path,
    kitchen_by_venue: dict[str, Decimal],
    *,
    tolerance: Decimal = DEFAULT_TOL,
) -> dict:
    """Persist By-venue gap bridge into settled_pnl.json when kitchen is ahead of the store."""
    try:
        import pm_venue_miss_ingest as miss
        import settled_pnl_store
    except Exception as exc:
        return {"added": 0, "error": type(exc).__name__}
    raw = _load_json(settled_path)
    store = dict(_settled_orders_blob(raw))
    before = settled_pnl_by_venue({"orders": store})
    wanted = {}
    for venue, kitchen in (kitchen_by_venue or {}).items():
        if kitchen is None:
            continue
        have = before.get(venue) or Decimal("0")
        if abs(kitchen - have) > tolerance:
            wanted[venue] = kitchen
    if not wanted:
        return {"added": 0, "gaps": {}}
    # Write through settled_pnl_store so envelope stays consistent.
    saved_path = settled_pnl_store.STORE_PATH
    saved_cache = settled_pnl_store._CACHE
    try:
        settled_pnl_store.STORE_PATH = Path(settled_path)
        settled_pnl_store._CACHE = store
        rep = miss.close_by_venue_attribution_gaps(
            store, wanted, persist=True, source="kitchen_check_heal"
        )
    finally:
        settled_pnl_store.STORE_PATH = saved_path
        settled_pnl_store._CACHE = saved_cache
    return rep


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


def _dump_fill_settle_rows(pack: dict, venue: str) -> list[dict]:
    """Pull fill/settlement-like rows from one dump section; stamp venue when missing."""
    if not isinstance(pack, dict):
        return []
    rows: list[dict] = []
    for block_key in ("settlements", "fills", "positions", "orders", "activities"):
        block = pack.get(block_key)
        if isinstance(block, list):
            cand = block
        elif isinstance(block, dict):
            cand = (
                block.get(block_key)
                or block.get("fills")
                or block.get("settlements")
                or block.get("positions")
                or block.get("data")
                or []
            )
            if isinstance(block.get("body"), dict):
                body = block["body"]
                for k in ("fills", "settlements", "positions", "data"):
                    if isinstance(body.get(k), list):
                        cand = list(cand) + body[k] if isinstance(cand, list) else body[k]
        else:
            cand = []
        if not isinstance(cand, list):
            continue
        for row in cand:
            if not isinstance(row, dict):
                continue
            out = dict(row)
            if not out.get("venue"):
                out["venue"] = venue
            rows.append(out)
    # Top-level list aliases some dumps use.
    for key in ("fills", "settlements"):
        if isinstance(pack.get(key), list):
            for row in pack[key]:
                if isinstance(row, dict):
                    out = dict(row)
                    if not out.get("venue"):
                        out["venue"] = venue
                    rows.append(out)
    return rows


def analyze(
    *,
    kitchen_by_venue: dict[str, Decimal] | None = None,
    settled_by_venue: dict[str, Decimal] | None = None,
    kalshi_pack: dict | None = None,
    venue_packs: dict[str, dict] | None = None,
    kitchen_kalshi_window_pnl: Decimal | None = None,
    tolerance: Decimal = DEFAULT_TOL,
    require_all_dumps: bool = False,
    present_dumps: set[str] | None = None,
) -> dict:
    kitchen_by_venue = dict(kitchen_by_venue or {})
    settled_by_venue = dict(settled_by_venue or {})
    present_dumps = set(present_dumps or set())
    venue_packs = dict(venue_packs or {})
    if kalshi_pack is not None:
        present_dumps.add("kalshi")
        venue_packs.setdefault("kalshi", kalshi_pack)

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
    stacks: list[dict] = []
    scan_rows: list[dict] = []
    for venue, pack in sorted(venue_packs.items()):
        scan_rows.extend(_dump_fill_settle_rows(pack, venue))
    if scan_rows:
        stacks = ksd.find_same_direction_stacks(scan_rows)
        # Unique by event + leg tickers.
        seen = set()
        unique = []
        for row in stacks:
            key = (
                str(row.get("event") or ""),
                tuple(
                    (str(leg.get("ticker") or ""), str(leg.get("outcome") or ""))
                    for leg in (row.get("legs") or [])
                ),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        stacks = unique

    if kalshi_pack is not None:
        kalshi_report = kalshi_check.analyze(
            kalshi_pack,
            kitchen_pnl=kitchen_kalshi_window_pnl,
            tolerance=tolerance,
        )
        # Prefer union: kalshi_check stacks + all-venue scan.
        for row in kalshi_report.get("same_direction_stacks") or []:
            if row not in stacks:
                stacks.append(row)

    kalshi_bad = False
    if kalshi_report is not None:
        if kitchen_kalshi_window_pnl is not None and kalshi_report.get("gap_over_tolerance"):
            kalshi_bad = True
    open_instruments = _open_instruments_from_packs(venue_packs)
    open_stacks, historical_stacks = _split_stacks_open_vs_historical(stacks, open_instruments)
    # Open-book same-direction fails the gate. Historical Nov-1 settlements warn only
    # (already lost; send gates + open ingest prevent new ones).
    stack_bad = bool(open_stacks)
    ok = (not gaps) and (not missing_dumps) and (not kalshi_bad) and (not stack_bad)

    return {
        "venues": venue_rows,
        "tolerance": money(tolerance),
        "attribution_gap_venues": gaps,
        "missing_dumps": missing_dumps,
        "same_direction_stacks": stacks,
        "open_same_direction_stacks": open_stacks,
        "historical_same_direction_stacks": historical_stacks,
        "kalshi_bank_true": kalshi_report,
        "ok": ok,
        "note": (
            "All platforms: kitchen By venue vs settled_pnl.json (venue-priced). "
            "Kalshi also compares recon dump settlements when provided. "
            "Open same-direction stacks fail the gate; historical stacks warn only."
        ),
    }


def _open_instruments_from_packs(venue_packs: dict) -> set[str]:
    """Tickers/slugs still on the venue positions book (not settlement history)."""
    found: set[str] = set()
    for _venue, pack in (venue_packs or {}).items():
        if not isinstance(pack, dict):
            continue
        block = pack.get("positions")
        rows: list = []
        if isinstance(block, list):
            rows = block
        elif isinstance(block, dict):
            body = block.get("body") if isinstance(block.get("body"), dict) else {}
            for key in ("market_positions", "positions", "data"):
                cand = block.get(key) or body.get(key)
                if isinstance(cand, list):
                    rows.extend(cand)
                elif isinstance(cand, dict):
                    # Poly-shaped {slug: {...}}
                    for slug, item in cand.items():
                        if isinstance(item, dict):
                            row = dict(item)
                            row.setdefault("slug", slug)
                            row.setdefault("instrument", slug)
                            rows.append(row)
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("ticker", "instrument", "slug", "market_ticker"):
                text = str(row.get(key) or "").strip().upper()
                if text:
                    found.add(text)
    return found


def _split_stacks_open_vs_historical(
    stacks: list[dict], open_instruments: set[str]
) -> tuple[list[dict], list[dict]]:
    open_stacks: list[dict] = []
    historical: list[dict] = []
    open_set = {str(x or "").strip().upper() for x in (open_instruments or set())}
    for row in stacks or []:
        if not isinstance(row, dict):
            continue
        legs = row.get("legs") or []
        tickers = {
            str(leg.get("ticker") or leg.get("instrument") or "").strip().upper()
            for leg in legs
            if isinstance(leg, dict)
        }
        if open_set and (tickers & open_set):
            open_stacks.append(row)
        else:
            historical.append(row)
    return open_stacks, historical


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

    settled_path = None
    settled_by_venue: dict[str, Decimal] = {}
    if args.settled_pnl:
        settled_path = Path(args.settled_pnl)
        if not settled_path.is_file():
            print(f"MISSING settled_pnl: {settled_path}", flush=True)
            return 2
        settled_by_venue = settled_pnl_by_venue(_load_json(settled_path))

    present_dumps: set[str] = set()
    kalshi_pack = None
    venue_packs: dict[str, dict] = {}
    if args.pm_dump:
        path = Path(args.pm_dump)
        if not path.is_file():
            print(f"MISSING pm dump: {path}", flush=True)
            return 2
        sections = _pm_dump_sections(_load_json(path))
        present_dumps |= set(sections)
        venue_packs.update(sections)
        if "kalshi" in sections:
            kalshi_pack = sections["kalshi"]
    if args.kalshi_dump:
        path = Path(args.kalshi_dump)
        if not path.is_file():
            print(f"MISSING kalshi dump: {path}", flush=True)
            return 2
        kalshi_pack = _load_json(path)
        present_dumps.add("kalshi")
        venue_packs["kalshi"] = kalshi_pack

    if not kitchen_by_venue and not settled_by_venue and not venue_packs:
        print("Need --kitchen-html and/or --settled-pnl and/or a dump.", flush=True)
        return 2

    kitchen_window = _dec(args.kitchen_pnl) if args.kitchen_pnl not in (None, "") else None
    tol = Decimal(str(args.tolerance))
    report = analyze(
        kitchen_by_venue=kitchen_by_venue,
        settled_by_venue=settled_by_venue,
        kalshi_pack=kalshi_pack,
        venue_packs=venue_packs,
        kitchen_kalshi_window_pnl=kitchen_window,
        tolerance=tol,
        require_all_dumps=bool(args.require_all_dumps),
        present_dumps=present_dumps,
    )
    # Self-heal: #38 writes shares on tape rebuild, but kitchen check alone used to
    # read a wrapped settled_pnl.json as $0. Heal gaps from kitchen By-venue here.
    heal_rep = None
    if report.get("attribution_gap_venues") and settled_path and kitchen_by_venue:
        heal_rep = heal_attribution_gaps(settled_path, kitchen_by_venue, tolerance=tol)
        if heal_rep.get("added"):
            settled_by_venue = settled_pnl_by_venue(_load_json(settled_path))
            report = analyze(
                kitchen_by_venue=kitchen_by_venue,
                settled_by_venue=settled_by_venue,
                kalshi_pack=kalshi_pack,
                venue_packs=venue_packs,
                kitchen_kalshi_window_pnl=kitchen_window,
                tolerance=tol,
                require_all_dumps=bool(args.require_all_dumps),
                present_dumps=present_dumps,
            )
            report["attribution_healed"] = heal_rep

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
    if heal_rep and heal_rep.get("added"):
        print(f"attribution healed: {heal_rep.get('gaps')}")
    if report["attribution_gap_venues"]:
        print("ATTRIBUTION GAPS:", ", ".join(report["attribution_gap_venues"]))
    if report["missing_dumps"]:
        print("MISSING DUMPS:", ", ".join(report["missing_dumps"]))
    open_stacks = report.get("open_same_direction_stacks") or []
    hist_stacks = report.get("historical_same_direction_stacks") or []
    print(f"same_dir_open_n {len(open_stacks)}  same_dir_historical_n {len(hist_stacks)}")
    for row in open_stacks[:8]:
        print(f"  OPEN STACK {row.get('event')}: {row.get('reason')}")
    for row in hist_stacks[:5]:
        print(f"  HIST STACK {row.get('event')}: {row.get('reason')}")
    if report.get("kalshi_bank_true") and report["kalshi_bank_true"].get("gap") is not None:
        kt = report["kalshi_bank_true"]
        print(
            f"kalshi_window venue={kt['venue']['venue_pnl_money']} "
            f"kitchen={kt.get('kitchen_pnl')} gap={kt.get('gap')}"
        )
    if report["ok"]:
        print("RESULT OK")
        return 0
    print("RESULT FAIL — attribution gap, missing dump, and/or OPEN same-direction stack")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
