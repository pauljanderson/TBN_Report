"""Note: in-match Yes/No change-ticks for every live sport. No orders."""
from __future__ import annotations

import html as html_lib
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP, RAW_DIR
from report_page_extras import CACHE_META, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML

PAGE = DRIVE_STAMP / "inmatch_tick_collection_20261021.html"
ET = ZoneInfo("America/New_York")
ASKED = (
    "Start tracking ALL ticks during ALL games (ALL sports) so we have data to look back on."
)
PLAIN = (
    "Until today we mostly kept a live price tape during a tennis match when that match was on "
    "Kalshi (men's ATP or ATP Challenger) and also on Polymarket US. Other books often went quiet "
    "once the game started, so later research said the price “never dipped” when we simply were not "
    "looking. We now keep every Yes/No price change while a game is live, for every sport we already "
    "watch, on every book we already poll. Same-price repeats are not stored every fraction of a "
    "second. This is a lookback tape. It does not send more orders."
)


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def main() -> Path:
    now = datetime.now(ET).strftime("%Y-%m-%d %I:%M:%S %p") + " Eastern Time"
    head = "".join(
        [
            th("Sport", "text"),
            th("Venues", "text"),
            th("When we collect", "text"),
            th("Notes", "text"),
        ]
    )
    body_rows = [
        (
            "Tennis (ATP, ATP Challenger, WTA)",
            "Kalshi, Polymarket US, Novig ATP/WTA",
            "Kalshi+Polymarket twins stay until the job deadline (8:00 AM ET Thu 22 Oct 2026), including before start. Unmatched Kalshi/Polymarket/Novig books are quoted in-match (about 5 minutes before listed start through a typical 5-hour match).",
            "Gemini does not list tennis. Novig Challenger is not in the Novig catalog we poll, so that venue is skipped honestly. Doubles are skipped. Upcoming unmatched books wait until they go live rather than opening hundreds of idle pollers.",
        ),
        (
            "Pro football (NFL)",
            "Kalshi, Gemini, Polymarket US, Novig",
            "Listed start through about 3.5 hours",
            "One venue is enough. We no longer require Kalshi and Gemini together.",
        ),
        (
            "College football",
            "Kalshi, Gemini, Polymarket US, Novig",
            "Listed start through about 4 hours",
            "Same as NFL. Catalog scan still writes pre-match quotes.",
        ),
        (
            "Other catalog sports (baseball, soccer, hockey, MMA, …)",
            "Kalshi, Gemini, Polymarket US, Novig when that book exists",
            "Listed start through a typical length (about 2.5–5 hours)",
            "If a venue has no in-play book, that venue is skipped. We still store ticks on the books that exist.",
        ),
    ]
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(col)}</td>" for col in row) + "</tr>"
        for row in body_rows
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>In-match ticks, all sports</title>
{CACHE_META}
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
h1 {{ margin-top: 0; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>In-match ticks for every live sport</h1>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<h2>What changed</h2>
<p>Live pollers used to spawn for tennis mainly when a Kalshi ATP or ATP Challenger moneyline had exactly one Polymarket US twin. A worker also skipped a game unless Kalshi and Gemini tickers were both present (unless Polymarket was already attached). Those two gates are lifted for quoting. The leftover 20-second watch and the lock-order path are the same. The order-stop latch was not touched. Novig orders stay off.</p>
<p><code>price_memory.remember_books</code> still writes a Yes or No row when the pay-price <strong>changes</strong>. The same price is stored again only if it is more than 20 seconds old, so a busy websocket does not copy the same quote thousands of times. HTTP fallback, if a socket is down, is about every 5 seconds — we cap the interval, we do not drop a sport.</p>
<h2>Where the files go</h2>
<ul>
<li>Raw ticks stay on this PC only: <code>{esc(RAW_DIR / "price_memory.jsonl")}</code> (already about 1.85 GB). Not Google Drive.</li>
<li>Latest price per contract: <code>{esc(RAW_DIR / "price_last.json")}</code></li>
<li>HTML and status stay under Drive: <code>{esc(DRIVE_STAMP)}</code>, including <a href="job_status.html">job_status.html</a>.</li>
</ul>
<h2>Sports and venues</h2>
<p>Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{body}
</tbody>
</table>
</div>
<h2>Disk caveat</h2>
<p>Change-ticks for every live game will grow <code>price_memory.jsonl</code>. That file must stay local. Python cache is pointed at <code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/__pycache__</code> via <code>PYTHONDONTWRITEBYTECODE=1</code>. This page does not place an order. Research only. Not gold. Not DailyRun.</p>
<p class="note">Written {esc(now)}. ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. NFL is National Football League.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)
    return PAGE


if __name__ == "__main__":
    main()
