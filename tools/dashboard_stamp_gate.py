"""Gate: living dashboard.html must carry writer-emitted columns after rebuild.

Paul problem class (2026-11-04): PR #46 merged Size @ price + Gibson Poly
Yes-wire invert into main; git pull updated the writers; Drive dashboard.html
stayed on the pre-merge stamp OR rebuilt with empty Size @ price cells and
Gibson still on Yes-wire 0.84 / today +$2.40 (both-leg wins).

Fails when:
  - write_dashboard.TRADE_HEADERS is missing Size @ price (writer drift)
  - stamp dashboard.html exists and is missing Size @ price (stale stamp)
  - Trades today table lacks Size @ price header (column only on Full book)
  - A Lock gap trades-today rows omit Size @ price / show blank (not unknown)
  - stamp has Gibson/Oliynykova Poly Yes-wire 0.8400 (pre-invert booking)
  - today with-fee P&L for the six Gibson/Imamura/Teichmann legs is the
    false +$2.40 both-wins total, or Gibson pair is not ~+$0.01

Does not place, cancel, or sell. No secrets. No network.

    python -u tools/dashboard_stamp_gate.py
    python -u tools/dashboard_stamp_gate.py --dashboard-html path/to/dashboard.html
"""
from __future__ import annotations

import argparse
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP  # noqa: E402

SIZE_AT_PRICE = "Size @ price"
GIBSON_NEEDLES = ("gibson", "oliynykova")
# Pre-invert stamp showed Poly Yes-wire 0.8400 on Gibson SHORT (false ~1.67 lock).
FALSE_GIBSON_WIRE = re.compile(
    r"Gibson\s+vs\s+Oliynykova[\s\S]{0,800}?polymarket[\s\S]{0,400}?>0\.8400<",
    re.IGNORECASE,
)
CORRECTED_NOTE = "Corrected Gibson/Oliynykova lock"
# Drive failure mode: today KPI / A Lock gap both-wins sum ≈ +$2.40.
FALSE_TODAY_PNL = Decimal("2.40")
# Corrected day for the three 2026-11-03 A locks ≈ +$0.07.
EXPECTED_THREE_LOCK_PNL = Decimal("0.07")
THREE_LOCK_TOL = Decimal("0.08")
GIBSON_PAIR_TOL = Decimal("0.02")


def writer_has_size_at_price() -> bool:
    import write_dashboard as d

    return any(h[0] == SIZE_AT_PRICE for h in d.TRADE_HEADERS)


def stamp_has_size_at_price(html: str) -> bool:
    return SIZE_AT_PRICE in (html or "")


def _section_after_heading(html: str, heading: str) -> str:
    """HTML from <h2>Heading through the next <h2> (or end)."""
    text = html or ""
    pat = re.compile(
        rf"<h2[^>]*>\s*{re.escape(heading)}\s*</h2>([\s\S]*?)(?=<h2\b|$)",
        re.IGNORECASE,
    )
    m = pat.search(text)
    return m.group(1) if m else ""


def _table_headers(chunk: str) -> list[str]:
    first_row = re.search(r"<tr[^>]*>([\s\S]*?)</tr>", chunk or "", re.IGNORECASE)
    if not first_row:
        return []
    cells = re.findall(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", first_row.group(1), re.IGNORECASE)
    out = []
    for cell in cells:
        plain = re.sub(r"<[^>]+>", "", cell)
        plain = plain.replace("&amp;", "&").replace("&nbsp;", " ")
        out.append(re.sub(r"\s+", " ", plain).strip())
    return out


def _table_rows(chunk: str) -> list[list[str]]:
    rows = []
    for m in re.finditer(r"<tr[^>]*>([\s\S]*?)</tr>", chunk or "", re.IGNORECASE):
        cells = re.findall(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", m.group(1), re.IGNORECASE)
        plain = []
        for cell in cells:
            text = re.sub(r"<[^>]+>", "", cell)
            text = (
                text.replace("&amp;", "&")
                .replace("&nbsp;", " ")
                .replace("−", "-")
                .replace("–", "-")
            )
            plain.append(re.sub(r"\s+", " ", text).strip())
        if plain:
            rows.append(plain)
    return rows


def trades_today_has_size_at_price_column(html: str) -> bool:
    section = _section_after_heading(html, "Trades today")
    if not section:
        return False
    headers = _table_headers(section)
    return SIZE_AT_PRICE in headers


def _size_col_index(headers: list[str]) -> int:
    for i, h in enumerate(headers):
        if h == SIZE_AT_PRICE:
            return i
    return -1


def lock_gap_today_size_cells_ok(html: str) -> tuple[bool, str]:
    """A Lock gap rows in Trades today must expose Size @ price (value or unknown)."""
    section = _section_after_heading(html, "Trades today")
    if not section:
        return False, "Trades today section missing"
    rows = _table_rows(section)
    if not rows:
        return False, "Trades today table empty"
    headers = rows[0]
    size_i = _size_col_index(headers)
    if size_i < 0:
        return False, "Trades today missing Size @ price column"
    sys_i = next((i for i, h in enumerate(headers) if h.lower() == "system"), 1)
    checked = 0
    for row in rows[1:]:
        if len(row) <= max(size_i, sys_i):
            return False, "Trades today lock row shorter than Size @ price column"
        sys = row[sys_i]
        if "Lock gap" not in sys and not sys.strip().startswith("A"):
            continue
        checked += 1
        cell = row[size_i].strip()
        if cell in {"", "—", "-", "–", "&mdash;", "—".strip()}:
            return False, f"A Lock gap Size @ price blank/omitted ({cell!r}); want volume or unknown"
    if checked == 0:
        # No A rows today — column presence alone is enough.
        return True, "no A Lock gap rows today"
    return True, f"checked {checked} A Lock gap rows"


def stamp_has_stale_gibson_poly_wire(html: str) -> bool:
    """True when Gibson rows still show the pre-invert 0.84 Yes-wire booking.

    Corrected note alone does NOT clear this — Drive failed with note missing
    and wire still 0.84; a note next to 0.84 is still a fail.
    """
    text = html or ""
    low = text.lower()
    if not all(n in low for n in GIBSON_NEEDLES):
        return False
    return bool(FALSE_GIBSON_WIRE.search(text))


def _parse_money(text: str) -> Decimal | None:
    raw = (text or "").strip().replace(",", "").replace("−", "-").replace("–", "-")
    raw = raw.replace("$", "").replace("+", "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except Exception:
        return None


def today_window_html(html: str) -> str:
    m = re.search(
        r'<div[^>]*data-window="today"[^>]*>([\s\S]*?)</div>\s*<div[^>]*data-window="inception"',
        html or "",
        re.IGNORECASE,
    )
    return m.group(1) if m else ""


def today_a_lock_pnl(html: str) -> Decimal | None:
    """With-fee P&L for A Lock gap inside the Today window panel."""
    chunk = today_window_html(html)
    if not chunk:
        # Fall back: first A Lock gap P&L cell after Today heading.
        chunk = _section_after_heading(html, "Today")
    m = re.search(
        r"A\s+Lock\s+gap[\s\S]{0,400}?([+\-−]?\$\d+\.\d{2})",
        chunk or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    return _parse_money(m.group(1))


def today_kpi_pnl(html: str) -> Decimal | None:
    chunk = today_window_html(html)
    if not chunk:
        chunk = _section_after_heading(html, "Today")
    m = re.search(
        r"(?:Today with-fee P&amp;L|Today with-fee P&L|With-fee P&amp;L|With-fee P&L)"
        r"[\s\S]{0,120}?([+\-−]?\$\d+\.\d{2})",
        chunk or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    return _parse_money(m.group(1))


def gibson_pair_pnl_from_trades_today(html: str) -> Decimal | None:
    """Sum P&L if settled for Gibson rows in Trades today."""
    section = _section_after_heading(html, "Trades today")
    rows = _table_rows(section)
    if len(rows) < 2:
        return None
    headers = rows[0]
    match_i = next((i for i, h in enumerate(headers) if "match" in h.lower() or h.lower() == "game"), -1)
    pnl_i = next((i for i, h in enumerate(headers) if "p&l" in h.lower() or "pnl" in h.lower()), -1)
    if match_i < 0 or pnl_i < 0:
        return None
    total = Decimal("0")
    n = 0
    for row in rows[1:]:
        if len(row) <= max(match_i, pnl_i):
            continue
        if "gibson" not in row[match_i].lower():
            continue
        pnl = _parse_money(row[pnl_i])
        if pnl is None:
            continue
        total += pnl
        n += 1
    return total if n else None


def three_lock_games_present(html: str) -> bool:
    low = (html or "").lower()
    return (
        "gibson" in low
        and "oliynykova" in low
        and "imamura" in low
        and "teichmann" in low
    )


def check(*, dashboard_html: Path | None = None, require_stamp: bool = False) -> dict:
    """Return a report. ok=False means the gate failed."""
    path = dashboard_html or (DRIVE_STAMP / "dashboard.html")
    report: dict = {
        "ok": True,
        "writer_size_at_price": writer_has_size_at_price(),
        "stamp_path": str(path),
        "stamp_exists": path.is_file(),
        "stamp_size_at_price": None,
        "trades_today_size_at_price": None,
        "lock_gap_size_cells_ok": None,
        "stamp_stale_gibson_wire": None,
        "today_a_pnl": None,
        "today_kpi_pnl": None,
        "gibson_pair_pnl": None,
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
    report["trades_today_size_at_price"] = trades_today_has_size_at_price_column(html)
    size_ok, size_why = lock_gap_today_size_cells_ok(html)
    report["lock_gap_size_cells_ok"] = size_ok
    report["lock_gap_size_detail"] = size_why
    report["stamp_stale_gibson_wire"] = stamp_has_stale_gibson_poly_wire(html)
    report["today_a_pnl"] = today_a_lock_pnl(html)
    report["today_kpi_pnl"] = today_kpi_pnl(html)
    report["gibson_pair_pnl"] = gibson_pair_pnl_from_trades_today(html)

    if not report["stamp_size_at_price"]:
        report["ok"] = False
        report["failures"].append(
            "dashboard.html missing Size @ price — stamp is stale; "
            "git pull alone does not rebuild. Run: python tools/write_orders_performance.py "
            "or run_rebuild_kitchen_dashboard.bat"
        )
    if report["trades_today_size_at_price"] is False:
        report["ok"] = False
        report["failures"].append(
            "Trades today table missing Size @ price column "
            "(column must appear on A / lock-gap today rows, not only Full book)"
        )
    if not size_ok:
        report["ok"] = False
        report["failures"].append(
            f"Trades today A Lock gap Size @ price fail: {size_why}"
        )
    if report["stamp_stale_gibson_wire"]:
        report["ok"] = False
        report["failures"].append(
            "dashboard.html still shows Gibson Poly Yes-wire 0.84 — "
            "must be house cost 0.16 / Corrected Gibson/Oliynykova lock; rebuild from tape"
        )

    today_a = report["today_a_pnl"]
    today_kpi = report["today_kpi_pnl"]
    gibson_pair = report["gibson_pair_pnl"]
    if today_a is not None and abs(today_a - FALSE_TODAY_PNL) <= Decimal("0.02"):
        report["ok"] = False
        report["failures"].append(
            f"Today A Lock gap with-fee P&L is {today_a} (false both-wins $2.40 class); "
            f"expected ~+{EXPECTED_THREE_LOCK_PNL} for the three corrected locks"
        )
    if today_kpi is not None and abs(today_kpi - FALSE_TODAY_PNL) <= Decimal("0.02"):
        report["ok"] = False
        report["failures"].append(
            f"Today KPI with-fee P&L is {today_kpi} (false $2.40); "
            "not the corrected ~+$0.07 lock day"
        )
    if gibson_pair is not None and abs(gibson_pair) > GIBSON_PAIR_TOL:
        # Corrected Gibson pair is ~+$0.01; −$0.16/+0.17. Reject both-wins +0.33 and −0.84.
        if abs(gibson_pair - Decimal("0.01")) > GIBSON_PAIR_TOL:
            report["ok"] = False
            report["failures"].append(
                f"Gibson trades-today pair P&L sum is {gibson_pair}; "
                f"expected ~+0.01 (Poly −0.16 + Kalshi +0.17), not Yes-wire both-wins"
            )
    if three_lock_games_present(html) and today_a is not None:
        if abs(today_a - EXPECTED_THREE_LOCK_PNL) > THREE_LOCK_TOL:
            # Only fail when clearly the false $2.40 class or large miss after Gibson present.
            if today_a >= Decimal("1.00") or today_a <= Decimal("-0.50"):
                report["ok"] = False
                report["failures"].append(
                    f"Today A P&L {today_a} with Gibson/Imamura/Teichmann present; "
                    f"expected ~+{EXPECTED_THREE_LOCK_PNL} (±{THREE_LOCK_TOL}) for three locks"
                )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when living dashboard.html lags writer columns (Size @ price / Gibson / today P&L)."
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
        f"trades_today_size_at_price={report['trades_today_size_at_price']} "
        f"lock_gap_size_cells_ok={report['lock_gap_size_cells_ok']} "
        f"stamp_stale_gibson_wire={report['stamp_stale_gibson_wire']} "
        f"today_a_pnl={report['today_a_pnl']} "
        f"gibson_pair_pnl={report['gibson_pair_pnl']}",
        flush=True,
    )
    for fail in report["failures"]:
        print(f"FAIL: {fail}", flush=True)
    if report["ok"]:
        print(
            "RESULT PASS — dashboard stamp matches Size @ price / Gibson / today P&L gate",
            flush=True,
        )
        return 0
    print("RESULT FAIL — rebuild kitchen dashboard after pull", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
