"""One-shot writer for simultaneous_legs_novig_20261019.html. Not a live order."""
from __future__ import annotations

import html as html_lib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from report_page_extras import CACHE_META, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ASKED = (
    "i am thinking that perhaps the reason we are missing the second trade in most cases "
    "is because of the 2 second time lag between calls. what if we make them both simultaneously. "
    "if only one fills, then we make the second one as limit of the highest value we can and still "
    "be profitable. it sounds like all platforms make a limit call as anything under and up to the "
    "limit. also, we no longer need to make polymarket the first call since we have made some "
    "succesfull calls. AND finally, we should build novig in officially. that's a lot go get 'em"
)
PLAIN = (
    "We used to send one side of a lock, wait for the answer, then send the other. That wait was "
    "ordinary HTTP one after the other — not the Kalshi 2-second shard retry. Now both sides leave "
    "at the same time at the quoted prices that still keep the pair under 95 cents after fees. If "
    "only one side fills, we send one recovery on the missed venue at the highest still-profitable "
    "price given the actual fill. If neither fills, we do not stop. If recovery also misses, we "
    "stop. Polymarket is no longer forced first. Novig order code is wired, but live Novig orders "
    "stay off until a trading subaccount key is in secrets (the current key is management-only)."
)

ROWS = [
    (
        "Simultaneous first send",
        "Both legs IOC in parallel at quoted limits. Profit + balance rechecked before BOTH posts leave. No preferred first venue.",
    ),
    (
        "2 second lag",
        "Only Kalshi HTTP 404 insufficient_shard_balance / exchange user not found retries wait 2s between identical posts on that Kalshi thread. It does not delay the parallel partner.",
    ),
    (
        "Recovery",
        "If exactly one fills: three-step walk (websocket, book, midway) on the missed venue, capped at max profitable price from the actual fill + fees. Limit is a ceiling (fill at or better).",
    ),
    ("Neither fills", "both_unfilled. Latch not written. Same as before."),
    ("Both fill", "Done. Refresh balances."),
    (
        "One-leg after recovery miss",
        "orders_stopped.json latch. Phone ping on latch create and on each order HTTP sent.",
    ),
    (
        "Polymarket-first",
        "Removed. Yes/No matching unchanged. Logging order is alphabetical venue name only.",
    ),
    (
        "Novig quotes",
        "Still in the compare when fee is known. Pairs with Kalshi / Gemini / Polymarket allowed.",
    ),
    (
        "Novig orders",
        "Code wired (POST /v3/orders IOC, qty 100 native = $1, fee half-up millicent). NOVIG_ORDERS_ENABLED default False. Dry check: current secrets are a management key; need a funded trading subaccount key. No fake fills.",
    ),
    (
        "Residual one-leg risk",
        "Parallel fills can still leave one side filled if the other rejects or recovery misses. That is why the latch remains.",
    ),
]


def main() -> Path:
    path = STAMP / "simultaneous_legs_novig_20261019.html"
    body_rows = "".join(
        f"<tr><td>{html_lib.escape(a)}</td><td>{html_lib.escape(b)}</td></tr>" for a, b in ROWS
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Simultaneous legs and Novig</title>
<style>
body {{ margin: 0; padding: 16px 16px 48px; font: 16px/1.45 system-ui, Segoe UI, sans-serif; color: #0f172a; background: #fff; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
p {{ margin: 0.4rem 0 0.7rem; }}
.callout {{ border-left: 4px solid #1d4ed8; background: #f8fafc; padding: 10px 12px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Simultaneous lock legs and Novig orders</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. One contract per leg. Latch left alone on restart.</p>
<div class="callout"><h2>What you asked</h2><p>{html_lib.escape(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{html_lib.escape(PLAIN)}</p></div>

<h2>Process now</h2>
<p class="note">Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>
<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Topic<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">What changed<span class="sort-ind"></span></th>
</tr></thead>
<tbody>
{body_rows}
</tbody>
</table>
</div>

<h2>Limit semantics</h2>
<p>A limit is a ceiling. Kalshi and Polymarket say fill at the limit or better. Gemini docs do not promise improvement; our fills matched the limit. Using the max profitable limit on recovery is correct for “anything at or under the limit.” Fees stay on top of price for the net check (cap $0.95 after fees, gross under $1).</p>

<h2>Novig status (2026-10-19)</h2>
<ul>
<li><code>NOVIG_ORDERS_ENABLED</code> defaults to <strong>False</strong>.</li>
<li>Dry signed reads work: catalog, echo, account orders, management wallet balance.</li>
<li>The key in <code>secrets/novig_api_key.txt</code> / <code>novig_api_secret.txt</code> is a <strong>management</strong> key (account orders returns a map keyed by key id; subaccount balance returns <code>NOT_A_SUBACCOUNT_KEY</code>). Place requires a <strong>trading</strong> subaccount key.</li>
<li>Order path is implemented behind the flag: IOC, 100 native contracts per $1 lock leg, poll <code>GET /v3/orders/{{id}}</code> until terminal, fee coefficient × P × (1−P) half-up to $0.00001, balance check before send when readable.</li>
<li>Until a trading key is installed and the flag is turned on, Novig stays quote-only for locks. No test order was placed.</li>
</ul>

<h2>Code</h2>
<p><code>tools/live_lock_orders.py</code> (simultaneous + recovery), <code>tools/novig_live.py</code> (order client + flag), <code>tools/live_game_pollers.py</code> (pass Novig books into the lock path).</p>
<p class="note">Related: <a href="architecture.html">architecture.html</a>, <a href="one_leg_note.html">one_leg_note.html</a>, <a href="novig.html">novig.html</a>, <a href="orders.html">orders.html</a>.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")
    return path


if __name__ == "__main__":
    out = main()
    print(out)
