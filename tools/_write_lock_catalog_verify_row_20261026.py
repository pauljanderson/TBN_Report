"""Catalog REST recheck starts immediately in parallel; hands books if still a gap.

Research only. Does not sell. Does not print secrets. Does not start a second
live_strategy_b.py. Does not bump NET_MAX. Does not wire D NFL. Dual-leg
simultaneous send is not this path.
"""
from __future__ import annotations

import html as html_lib
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import opportunity_considerations  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

PAGE = STAMP / "lock_catalog_verify_row_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/lock_catalog_verify_row_20261026.html"
)
ASKED = opportunity_considerations.ASKED_VERIFY
ASKED_NOW = opportunity_considerations.ASKED_VERIFY_NOW
PLAIN = (
    "The 3-second wait was the catalog writing the first row, then reading Kalshi’s book, "
    "then reading Novig’s book, and Novig was also waiting its turn three times (half a second "
    "each). That is why a 0.9900 look reprinted as 0.9950. Now both books are requested at the "
    "same instant the cheap look is seen — no waiting in line, no “write this row and check on "
    "the next loop.” The two timestamps differ by the HTTP round trip, in milliseconds. If those "
    "live books are still at or under 99 cents after fees, they are handed to the same one-contract "
    "hard-first send the live helper uses (lock switch on, room under the open-pair cap, local cash). "
    "No second book download. If the gap already closed, catalog still does not send. HTTP 429 is "
    "named on the row and is not retried."
)


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def write_page() -> Path:
    line = live_lock_orders.send_line()
    catalog_reason = opportunity_considerations.catalog_eligible_reason(Decimal("0.9300"))
    still = opportunity_considerations._catalog_verify_reason(
        Decimal("0.9300"), Decimal("0.9200"), [], still_gap=True
    )
    handed = opportunity_considerations._catalog_verify_reason(
        Decimal("0.9900"), Decimal("0.9900"), [], still_gap=True, handed=True
    )
    closed = opportunity_considerations._catalog_verify_reason(
        Decimal("0.9300"), Decimal("1.0500"), [], still_gap=False
    )
    limited = opportunity_considerations._catalog_verify_reason(
        Decimal("0.9300"),
        None,
        ["kalshi book empty (book http 429)"],
        still_gap=None,
    )
    missing = opportunity_considerations._catalog_verify_reason(
        Decimal("0.9300"),
        None,
        ["Missing order fields for yes (kalshi): kalshi_ticker."],
        still_gap=None,
    )
    rows = table(
        [
            ("When", "text"),
            ("Source", "text"),
            ("Trigger", "text"),
            ("Yes / No asks", "text"),
            ("After-fee net", "num"),
            ("Decision", "text"),
            ("Reason", "text"),
            ("Sends?", "text"),
        ],
        [
            [
                esc("Catalog look (first row)"),
                esc("catalog scan"),
                esc("catalog scan"),
                esc("catalog Yes / No from the walk"),
                esc("0.9300"),
                esc("denied"),
                esc(catalog_reason),
                esc("Never"),
            ],
            [
                esc("Same breath (second row) — both book GETs in parallel"),
                esc("catalog verify"),
                esc("REST recheck"),
                esc("live REST asks + sizes"),
                esc("0.9200 if still a gap; 1.0500 if the gap closed"),
                esc("denied"),
                esc(still + "  /  " + closed),
                esc("Not from the walk. If still ≤ cap, books go to hard-first execute."),
            ],
            [
                esc("Still ≤ 0.99 after the parallel GET"),
                esc("catalog verify"),
                esc("REST recheck"),
                esc("REST books already in hand"),
                esc("0.9900"),
                esc("denied on this row; execute may send"),
                esc(handed),
                esc("Hard-first, 1 contract, no second book GET. Not dual simultaneous."),
            ],
            [
                esc("REST GET 429"),
                esc("catalog verify"),
                esc("REST recheck"),
                esc("catalog asks kept; live books not returned"),
                esc("0.9300 (catalog net, because the live net was not computed)"),
                esc("denied"),
                esc(limited),
                esc("Never"),
            ],
            [
                esc("Cannot build a book GET"),
                esc("catalog verify"),
                esc("REST recheck"),
                esc("catalog asks kept"),
                esc("0.9300"),
                esc("denied"),
                esc(missing),
                esc("Never"),
            ],
        ],
    )
    freeze = table(
        [("Knob", "text"), ("Value", "text")],
        [
            [esc("Catalog walk POSTs"), esc("No. overnight_scan.py is still public GETs only.")],
            [esc("Verify GET"), esc("Starts immediately when the look is seen. Both legs in parallel. No venue_pace sleep. No Novig 429 retry.")],
            [esc("What caused the 3s"), esc("Write catalog row, then Kalshi book, then Novig book. Novig paid the 0.50s slot three times (fetch_book_ask + inner wait + novig_live._get).")],
            [esc("New latency"), esc("max(Kalshi GET, Novig GET) HTTP round trip. Millisecond timestamps.")],
            [esc("If still ≤ cap"), esc("Hand REST books to execute_locks(skip_book_recheck=True). Hard-first, 1 contract, lock.on, MAX_OPEN, local cash.")],
            [esc("If gap closed"), esc("Catalog does not send.")],
            [esc("Live send path"), esc("live_game_pollers.py --poll-one → live_lock_orders.execute_locks (also parallel book recheck now)")],
            [esc("Verify API"), esc("Same public book GET as live pollers (fetch_book_ask / _live_from_book). Not a wallet GET.")],
            [esc("lock.net_max"), esc(line)],
            [esc("Verify log cap"), esc("Catalog-verify rows may print over 0.99 so a closed gap is visible")],
            [esc("429"), esc("Named on the verify row. No retry. No Kalshi wallet call.")],
            [esc("Strategy B"), esc("Left in place. This job does not start a second B.")],
            [esc("D NFL"), esc("Not wired.")],
            [esc("Sell"), esc("No.")],
        ],
    )
    body = f"""
<h1>Catalog verify row after a lock-looking scan</h1>
<p class="note">America/New_York. Research only. Not gold. Not DailyRun. Did not sell. Did not bump the send cap. Did not start a second Tennis crossover. Did not wire D NFL. Live send cap is <strong>{esc(line)}</strong>.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p><p>{esc(ASKED_NOW)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>
<p class="note">Log: <a href="opportunities.html">opportunities.html</a>. Prior catalog note: <a href="lock_catalog_never_sends_20261025.html">lock_catalog_never_sends_20261025.html</a>. Click column headers to sort.</p>
<h2>What you will see</h2>
<p>A lock-neighborhood catalog look (after-fee at or under 0.99 that would have been a send if live, or near the cap) still writes the catalog-scan denied row. Both live books are requested in parallel at that same instant. A second row is written from that REST GET. Newest-first on the page, that verify row sits just above the catalog row. If the live net is still at or under the cap, those books are handed to hard-first execute with no second download. Missing size, a closed contract, or a flipped Gemini No does not trigger the extra GET.</p>
{rows}
<h2>Freeze</h2>
{freeze}
<p class="tiny">Updated {esc(opportunity_considerations._now())}. Live send line {esc(line)}. {esc(FILE_URL)}</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Catalog verify row — 26 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
{body}
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    page = report_page_extras.inject_report_page_extras(page)
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def main() -> None:
    path = write_page()
    print(path)


if __name__ == "__main__":
    main()
