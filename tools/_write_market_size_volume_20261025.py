"""Market size / $ volume report. Research only. Does not send. Does not print secrets."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "market_size_volume_20261025.html"
ASKED = (
    "Do we know how big the market is when we place a bet? Kalshi sometimes shows "
    "$ vol. Polymarket UI does not. Can we fetch this?"
)


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
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
    now = datetime.now(ET)
    rows = [
        [
            "Kalshi",
            "<code>yes_ask_size_fp</code> / REST book size → <code>quote_size</code>",
            "Contracts at the touch (can we fill 1 now)",
            "Yes. Lock hard-first and Poly size-skip already use REST ask size.",
            "Yes. Catalog GET <code>/trade-api/v2/markets?event_ticker=</code> and orderbook GET we already call.",
        ],
        [
            "Kalshi",
            "<code>volume_fp</code>",
            "$ notional, lifetime traded (the Kalshi $ vol on the market object)",
            "Catalog slim already kept it; the send quote did not. Views now pass it through.",
            "Yes. Same market GET. Live BER/ETC example: volume_fp 260.05 / 402.13.",
        ],
        [
            "Kalshi",
            "<code>volume_24h_fp</code>",
            "$ notional, last 24 hours",
            "No until this job (slim dropped it). Now kept on catalog slim.",
            "Yes. Same GET. Live BER/ETC: 236.76 / 119.13. Not a separate API.",
        ],
        [
            "Kalshi",
            "<code>open_interest_fp</code>",
            "$ notional open interest (contracts still open, not the same as $ vol)",
            "Catalog slim kept it; send quote did not. Views now pass it through.",
            "Yes. Same GET. Live BER/ETC: 259.71 / 400.13.",
        ],
        [
            "Kalshi",
            "<code>liquidity</code> / integer <code>volume</code>",
            "—",
            "No",
            "Not on the live market object we fetched today. Dollar fields are the <code>_fp</code> names.",
        ],
        [
            "Polymarket US",
            "<code>ask_size</code> / book qty → <code>quote_size</code>",
            "Contracts at the touch",
            "Yes. REST book + FOK size-skip.",
            "Yes. <code>GET gateway.polymarket.us/v1/markets/{slug}/book</code> we already call.",
        ],
        [
            "Polymarket US",
            "<code>volume</code> / <code>volume24hr</code> / <code>liquidity</code> / <code>openInterest</code>",
            "Traded $ / 24h $ / liquidity / OI if the venue returns them",
            "No. US sports UI hides them. Our US catalog dump has none of these keys.",
            "Not confirmed on Polymarket US. Public gamma/CLOB is a different product "
            "(<code>clob.polymarket.com</code>, documented in polymarket_us_live.py as not used). "
            "US GET <code>/v1/markets/{slug}</code> is the helper we already have for status/mark; "
            "job_status reads bid/ask only. One tennis slug 404’d. Send now logs those keys "
            "<em>if</em> that GET returns them; empty if not.",
        ],
        [
            "Gemini",
            "Book ask size → <code>quote_size</code>",
            "Contracts at the touch",
            "Yes. REST <code>/v1/book/{symbol}</code>.",
            "Yes. Same book GET.",
        ],
        [
            "Gemini",
            "<code>volume</code> / <code>volume24h</code> (event)",
            "Event-level traded volume (payload_keys on the event GET we already call)",
            "No. Event dump listed the keys; values were not copied onto the send spec.",
            "Yes, on <code>GET /v1/prediction-markets/events/{ticker}</code>. This job now stores "
            "the values on the event dict. Not an extra send GET (spec has the contract symbol, not the event ticker).",
        ],
        [
            "Novig",
            "Book qty → <code>ask_size</code> / <code>quote_size</code>",
            "Contracts at the touch (native qty / 100 so size 1 pays $1)",
            "Yes. REST catalog book.",
            "Yes. <code>GET /v3/catalog/markets/{id}/book</code>.",
        ],
        [
            "Novig",
            "volume / open interest",
            "—",
            "No",
            "Not in novig_live catalog parser, and not in the in-repo Novig dumps.",
        ],
    ]
    headers = [
        ("Venue", "text"),
        ("Field", "text"),
        ("Units", "text"),
        ("Already in our quote?", "text"),
        ("Can fetch?", "text"),
    ]
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Market size / volume — 25 Oct 2026</title>
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
<h1>Market size / volume at send</h1>
<p class="banner"><strong>Research only. Not gold. Not DailyRun.</strong>
Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}.
Did not sell. Did not change C_HI, FOK, E, or 50-cross gates.
Did not start a second <code>live_strategy_b.py</code>. Did not hidden-spawn B
(logging is in the shared send helper, so lock / C / D / E pick it up on next send
after those processes reload the module).</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>There are three different “how big” numbers, and they are easy to mix up.</p>
<ul>
<li><strong>Touch size</strong> — how many contracts are sitting at the best ask right now.
That answers “can we fill 1.” We already have this at send from the REST book
(<code>quote_size</code>). Lock hard-first and Polymarket size-skip already use it.</li>
<li><strong>Traded $ volume</strong> — how many dollars have actually changed hands
(lifetime or last 24 hours). That is the Kalshi “$ vol” on the market page.
It is not the same as the size showing on the book.</li>
<li><strong>Open interest</strong> — how many contracts are still open. Also not the
same as $ vol or touch size.</li>
</ul>
<p>Kalshi’s public market GET that we already call returns dollar volume and open
interest. Polymarket’s sports UI hides volume; the US API we use is not the public
gamma/CLOB book, and our US dumps do not carry those fields. Gemini’s event GET
lists volume keys. Novig’s catalog in this repo does not.</p>
</div>

<h2>Direct answers</h2>
<ol>
<li><strong>Do we know size at send?</strong> Yes — REST ask size in contracts
(<code>quote_size</code> / Kalshi <code>yes_ask_size_fp</code>). That is depth at the
touch, not lifetime $ volume.</li>
<li><strong>Can we fetch Kalshi $ vol?</strong> Yes. Field names on the market object
from <code>GET /trade-api/v2/markets</code> (same list GET overnight_scan already
calls, and the single-ticker GET <code>/trade-api/v2/markets/{{ticker}}</code> used
for closed-status): <code>volume_fp</code> (lifetime $), <code>volume_24h_fp</code>
(24h $), <code>open_interest_fp</code> (OI $). Quoted from a live fetch of
<code>KXATPMATCH-26OCT25BERETC</code> and from <code>slim_kalshi</code> in overnight_scan.
No <code>liquidity</code> field on that object today.</li>
<li><strong>Can we fetch Polymarket volume?</strong> Touch size yes. Traded $ volume
not confirmed on Polymarket US. Public gamma often has <code>volume</code> /
<code>volume24hr</code> / <code>liquidity</code> / <code>openInterest</code>; that is a
different host. US catalog dump (polymarket_us_markets.jsonl) has none of those keys.
Send will log them if the US market GET we already have a helper for returns them.</li>
<li><strong>Gemini:</strong> event GET we already call has <code>volume</code> and
<code>volume24h</code> in payload_keys; now stored on the event dict. Not on the send
quote (contract symbol ≠ event ticker).</li>
<li><strong>Novig:</strong> book size yes; no volume / OI field in the in-repo catalog
parser or dumps.</li>
<li><strong>Logging:</strong> Wired in <code>live_lock_orders._begin_order_post</code>
and <code>record_send_skip</code>. Next send/skip writes venue, ticker, ask_size, and
volume / OI when that GET returns them. One extra Kalshi/Poly market GET at send/skip,
cached 60s. Not a new polling loop. Strategy B was not reloaded this job.</li>
</ol>

<h2>Fields (click column headers to sort)</h2>
{table(headers, rows)}

<h2>What is not this</h2>
<p class="note">The Oct 22 GTC pages said this repo did not store a cumulative
venue-volume field and should not invent one. That was about picking a “highest volume”
venue from displayed size. Kalshi <code>volume_fp</code> was already on the market GET;
we were keeping it in the catalog slim and then dropping it on the send quote. This
page does not invent a new API. It names the official fields on GETs we already call.</p>
<p class="tiny">Sources: overnight_scan.slim_kalshi / fetch_kalshi_event,
live_lock_orders.fetch_book_ask and missed_market_closed,
polymarket_us_live (GATEWAY, not clob.polymarket.com),
gemini event payload_keys, novig_live.parse_market.
Live Kalshi GET 2026-10-25 for KXATPMATCH-26OCT25BERETC.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8")
    return PAGE


if __name__ == "__main__":
    path = write_page()
    print(path)
