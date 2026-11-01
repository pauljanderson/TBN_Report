"""Novig fee formula for Paul. Research HTML. Does not sell or start B."""
from __future__ import annotations

import html as html_lib
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import novig_live  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "novig_fees_20261027.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/novig_fees_20261027.html"
)
DOCS_CONCEPTS = "https://docs.novig.com/api/concepts/fees"
DOCS_FEES = "https://docs.novig.com/fees"
HELP = "https://support.novig.com/en/articles/16195057-fees-on-novig"

ASKED = (
    "Paul: “also, find out the novig fees please.” Today we skip or label fee unknown "
    "when Novig has no coefficient — Paul wants the real fee."
)
PLAIN = (
    "Novig does not hide the fee. The taker (the side that hits a resting order) pays "
    "c × price × (1 − price) per $1 contract. Yes and No cost the same at mirrored prices "
    "(40¢ Yes is the same fee as 60¢ No). Pregame sports are free. Live in-game sports "
    "use the market’s coefficient, which the catalog is printing as 0.06 today. After a "
    "fill, Novig’s fill list either names the fee it charged or omits it (that means $0, "
    "not unknown). We still skip a send if the market never names a coefficient — we do "
    "not guess 0."
)


def esc(value) -> str:
    return html_lib.escape(str("" if value is None else value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], caption: str = "") -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    cap = f"<p class=\"note\">{esc(caption)}</p>" if caption else ""
    return (
        f"{cap}{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def money(value: Decimal | None) -> str:
    if value is None:
        return "fee unknown"
    return live_lock_orders._net_text(value)


def sample_row(label: str, price: Decimal, charged: str, status: str, n_note: str) -> list[str]:
    fee = novig_live.taker_fee(price, "0.06", charged, status)
    after = (price + fee) if fee is not None else None
    return [
        esc(label),
        esc(format(price, "f")),
        esc("Yes or No — same"),
        esc(charged),
        esc(status),
        esc(n_note),
        esc(money(fee)),
        esc(money(after) if after is not None else "fee unknown"),
    ]


def write_page() -> Path:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    samples = table(
        [
            ("Ticket", "text"),
            ("Wire p", "num"),
            ("Yes vs No", "text"),
            ("charged", "text"),
            ("event.status", "text"),
            ("N ($1 contracts)", "text"),
            ("Taker fee", "num"),
            ("After-fee (all-in)", "num"),
        ],
        [
            sample_row("Live 1-contract @ 50¢ (docs example)", Decimal("0.50"), "WHEN_LIVE", "OPEN_INGAME", "1 (qty 100)"),
            sample_row("Live 1-contract @ 40¢ Yes", Decimal("0.40"), "WHEN_LIVE", "OPEN_INGAME", "1 (qty 100)"),
            sample_row("Live 1-contract @ 60¢ No (same fee as 40¢)", Decimal("0.60"), "WHEN_LIVE", "OPEN_INGAME", "1 (qty 100)"),
            sample_row("Live 1-contract @ 30¢ / 70¢", Decimal("0.30"), "WHEN_LIVE", "OPEN_INGAME", "1 (qty 100)"),
            sample_row("Live 1-contract @ 10¢", Decimal("0.10"), "WHEN_LIVE", "OPEN_INGAME", "1 (qty 100)"),
            sample_row("Pregame sports (ATP/NFL game line)", Decimal("0.50"), "WHEN_LIVE", "OPEN_PREGAME", "1 (qty 100)"),
            sample_row("Delayed / suspended", Decimal("0.50"), "WHEN_LIVE", "DELAYED", "1 (qty 100)"),
            sample_row("Eligible futures ALWAYS @ 50¢", Decimal("0.50"), "ALWAYS", "OPEN_PREGAME", "1 (qty 100)"),
            [
                esc("Missing coefficient"),
                esc("0.40"),
                esc("Yes or No"),
                esc("WHEN_LIVE"),
                esc("OPEN_INGAME"),
                esc("1"),
                esc("fee unknown — skip send"),
                esc("fee unknown"),
            ],
        ],
        "Click column headers to sort. House lock is one $1 contract (API qty 100). Docs example of 100 $1 contracts @ 50¢ is $1.50 — 100× this 1.5¢ row.",
    )

    schedule = table(
        [
            ("Kind", "text"),
            ("Leagues / sports", "text"),
            ("market.fee.charged", "text"),
            ("When the taker pays", "text"),
            ("Today’s c on catalog", "text"),
        ],
        [
            [
                esc("Game line (money / spread / total)"),
                esc("Any, including NFL, NCAAF, ATP, WTA"),
                esc("WHEN_LIVE"),
                esc("Only while event.status is OPEN_INGAME. Pregame $0."),
                esc("0.06"),
            ],
            [
                esc("Eligible futures"),
                esc("NFL, NCAAF, MLB, NBA, WNBA, NHL"),
                esc("ALWAYS"),
                esc("Every fill. Event never goes live."),
                esc("0.06"),
            ],
            [
                esc("Tennis / golf / UFC / F1 / NASCAR futures"),
                esc("ATP, WTA, PGA, UFC, F1, NASCAR"),
                esc("WHEN_LIVE (never goes live)"),
                esc("Never. Docs: read fee from the market, do not guess from this table."),
                esc("catalog"),
            ],
            [
                esc("Maker fill"),
                esc("All"),
                esc("—"),
                esc("$0. Resting order. We send IOC, so we are the taker."),
                esc("—"),
            ],
        ],
        "Click column headers to sort. Live ATP catalog this job: coefficient 0.06, charged WHEN_LIVE, makerCredit 0.25.",
    )

    wiring = table(
        [
            ("Place", "text"),
            ("Was", "text"),
            ("Now", "text"),
        ],
        [
            [
                esc("Pre-send pair_net / B all-in C"),
                esc("Skip / fee unknown if coefficient missing."),
                esc("c × p × (1 − p) from market.fee. GET /v3/catalog/markets/{id} if the list omitted it. Still skip if c is missing."),
            ],
            [
                esc("orders.jsonl after fill"),
                esc("Novig POST/order has no fee field. Tape said fee unknown."),
                esc("GET /v3/portfolio/fills `fee` persisted as fee / after_fee / fee_source=venue. Absent fee on a found fill is $0 uncharged."),
            ],
            [
                esc("Paul’s current fills GET"),
                esc("—"),
                esc("6 taker fills, all omitted `fee` → uncharged $0 (pregame / not live at match)."),
            ],
        ],
        "Click column headers to sort. Did not sell. Did not start a second B. Did not wire D NFL.",
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Novig fees — 27 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Novig fees</h1>
<p class="banner"><strong>Research live. Not gold. Not DailyRun.</strong> Written {esc(now)}.
Formula is from Novig’s docs and the live catalog. Missing coefficient is still fee unknown, not 0.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>The formula</h2>
<p class="note"><strong>Fee = c × P × (1 − P) × N</strong>. P is the fill price in (0, 1), not the limit.
c is <code>market.fee.coefficient</code>. N is the number of contracts that pay $1.00.
The API’s <code>qty</code> is 1-cent units, so N = qty / 100. Our 1-contract lock posts qty 100, so N = 1
and the dollar fee is c × P × (1 − P), half-up to $0.00001.</p>
<p class="note">Taker only. Maker pays $0. Yes vs No is the same number at P and 1 − P.
Sports (US prediction / CFTC venue): game lines are <code>WHEN_LIVE</code> (live in-game only).
Eligible futures are <code>ALWAYS</code>. Parlays / RFQ use 0.10 and are not on this send path.</p>
<p class="note">Sources:
<a href="{esc(DOCS_CONCEPTS)}">{esc(DOCS_CONCEPTS)}</a>,
<a href="{esc(DOCS_FEES)}">{esc(DOCS_FEES)}</a>,
<a href="{esc(HELP)}">{esc(HELP)}</a>.
API fields: <code>market.fee.coefficient</code>, <code>market.fee.charged</code>, fill <code>fee</code>.</p>
<p class="note">The help-center FAQ once says “0.03 for Live” at the bottom of a VWAP paragraph.
The schedule table and the v3 docs (since 15 Oct 2026) say live taker c = 0.06.
We read c from the market. Live ATP and NFL catalog this job: <code>0.06</code> / <code>WHEN_LIVE</code>.</p>

<h2>Schedule</h2>
{schedule}

<h2>Sample 1-contract tickets</h2>
{samples}

<h2>Wired into send + jsonl</h2>
{wiring}

<p class="note">Related: <a href="venue_fee_first_class_20261026.html">venue_fee_first_class_20261026.html</a>,
<a href="orders.html">orders.html</a>.</p>
<p class="tiny">Generator: <code>tools/_write_novig_fees_20261027.py</code>. Bookmark <code>{esc(FILE_URL)}</code>.
Sibling settled P&amp;L: <code>novig_live.taker_fee</code> before send;
<code>novig_live.fee_from_fills</code> / GET fills <code>fee</code> after fill (absent = $0 uncharged).</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


if __name__ == "__main__":
    path = write_page()
    print(path)
