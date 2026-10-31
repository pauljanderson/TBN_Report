"""GTC / stop feasibility note for lock leftover and Strategy B.

Research only. Does not place or cancel orders.
"""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "gtc_stop_feasibility_20261022.html"


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def rows_html(rows: list[list[str]]) -> str:
    out = []
    for row in rows:
        cells = "".join(f"<td>{esc(cell)}</td>" for cell in row)
        out.append(f"<tr>{cells}</tr>")
    return "".join(out)


def main() -> None:
    venue_head = "".join(
        th(label, "text")
        for label in (
            "Venue",
            "GTC resting limit?",
            "IOC (what we use)?",
            "Stop / trigger / buy only if last reaches X?",
            "Notes",
        )
    )
    venue_rows = [
        [
            "Kalshi",
            "Yes. Official create-order time_in_force includes good_till_canceled. Without expiration_time that is a true good-til-canceled rest. Optional expiration_time on that same TIF is a timed rest; GTT is not a valid API value.",
            "Yes. Live body already sends time_in_force=immediate_or_cancel (1 contract). Also fill_or_kill.",
            "No native buy-stop on create order. The V2 body is a priced limit (side bid/ask). Margin exit triggers are reduce-only on an existing margin position, not “buy if last prints 51”.",
            "Live builder: kalshi_order_body. Cancel path already exists. post_only stays false if we ever rest a leftover hedge we want to take when the ask is at/under the cap.",
        ],
        [
            "Gemini (predictions)",
            "Yes. timeInForce=good-til-cancel (schema default). Repo already used that string on a non-live probe (makerOrCancel true, then cancel). Live lock still sends immediate-or-cancel.",
            "Yes. Live gemini_order_payload: orderType=limit, timeInForce=immediate-or-cancel. Also fill-or-kill.",
            "Yes, documented stop-limit. orderType=stop-limit plus stopPrice. For a buy, docs require stopPrice >= last trade and stopPrice <= price. That can wait for last to reach 51, then rest/take a limit at price. Trigger is last reaching stopPrice, not “ask sits at 51”. Never posted live in this repo.",
            "Same POST /v1/prediction-markets/order we already use. makerOrCancel true is post-only (refuses a take). Leftover hedge should keep makerOrCancel off so it can take at/under the cap.",
        ],
        [
            "Polymarket US",
            "Yes on the path we already post: POST /v1/orders tif=TIME_IN_FORCE_GOOD_TILL_CANCEL. Official consumer SDK also lists GOOD_TILL_DATE, IMMEDIATE_OR_CANCEL, FILL_OR_KILL.",
            "Yes. Live polymarket_order_body: type=ORDER_TYPE_LIMIT, tif=TIME_IN_FORCE_IMMEDIATE_OR_CANCEL.",
            "Not on the consumer create we use. SDK type is ORDER_TYPE_LIMIT or ORDER_TYPE_MARKET only. STOP / STOP_LIMIT plus stopPrice exist on a different institutional insert-order host (api.prod.polymarketexchange.com / FIX). That is not our live path. Do not invent a stop field on /v1/orders.",
            "Live cancel is POST /v1/order/{id}/cancel with marketSlug. participateDontInitiate is already false (not post-only).",
        ],
        [
            "Novig",
            "Yes. Official tif includes GTC (rests until filled or cancelled). Also GTT (needs ttl ms), FOK, PO (post only).",
            "Yes. Live novig_live.order_body sends tif=IOC, qty=100 native = one $1 contract.",
            "No stop/trigger field on POST /v3/orders. Documented body is outcomeId, price, qty, tif, optional ttl/clientId.",
            "Strategy B never sends Novig. Lock bot only posts when NOVIG_ORDERS_ENABLED is already True plus a trading key. A 201 means queued, not resting — rest is the open event.",
        ],
    ]

    asked = (
        "Does each venue have a good-til-canceled order type? If so: "
        "(1) Lock-bot 2-legged fill — if both legs fill and there is a gap, done, keep looking. "
        "If one leg fills and the other does not, find the venue with the most volume for that game "
        "and place a GTC at the price we want (recovery hedge). "
        "(2) Strategy B D=25 — buy both Yes at T0 (today). Then monitor volume; the venue with the "
        "most volume for the game gets two GTC orders. Is there an order type “buy this, but only if "
        "it reaches this price” — e.g. if the dog Yes reaches 51, then buy. He does not want a GTC "
        "limit at 51 because that would fill immediately at the high ask. If no such trigger exists, "
        "keep today’s ping-and-wait and place the order when it happens in real time. Then place a GTC "
        "at the equivalent low price hoping the current favorite drops enough to lock 25c profit. "
        "Does this make sense? What can we do? Venues: Kalshi, Gemini (predictions), Polymarket US, "
        "Novig. Live lock uses IOC 1 contract. B never sends Novig."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GTC / stop feasibility 2026-10-22</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.warn {{ background: #fef2f2; padding: 10px 12px; border: 1px solid #f87171; margin: 12px 0; }}
.ok {{ background: #f0fdf4; padding: 10px 12px; border: 1px solid #86efac; margin: 12px 0; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Good-til-canceled and stop orders (research only)</h1>
<p class="note">America/New_York. Written {esc(datetime.now(ET).isoformat(timespec="seconds"))}. Research / feasibility only. Not gold. Not DailyRun. This page does not place or cancel orders. Immediate-or-cancel (IOC) is fill now or cancel. Good-til-canceled (GTC) is a resting limit. Click column headers to sort.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(asked)}</p>
<h2>In plain English</h2>
<p>A GTC is a limit that sits on the book until it fills or we cancel it. IOC is what live lock and Strategy B send today: one contract, take it now or the leftover dies. A stop / trigger is different: “do not even become a live bid until the last trade hits 51.” All four venues can rest a GTC limit. Only Gemini’s prediction API, on the same order path we already use, documents a buy stop-limit. Kalshi and Novig do not. Polymarket US has stops on a different institutional host, not on the <code>POST /v1/orders</code> body we send.</p>
<p>Lock leftover: if one IOC filled and flatten also missed, a 1-contract GTC on the missed hedge at the max profitable price can sit and wait. Strategy B: a GTC buy at 51 on the dog is the wrong tool — that is an aggressive limit and fills now if the dog is already cheaper. The right GTC is the cheap bid on the favorite. The 50-cross still needs a trigger or today’s ping-and-wait.</p>
</div>
<div class="warn">
<p><strong>No live GTC in this pass.</strong> No second Strategy B process. Size stays 1. Lock bot still both-or-flatten. Net cap stays NET_MAX (0.984 after documented fees) on the lock bot, and 1 − 0.25 on a Strategy B extra pair. Do not sell. Do not wire DailyRun.</p>
</div>

<h2>Per venue</h2>
<p class="note">Field names are from official docs plus the live bodies in <code>tools/live_lock_orders.py</code> / <code>novig_live.order_body</code>. Click headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>{venue_head}</tr></thead>
<tbody>{rows_html(venue_rows)}</tbody>
</table></div>

<h2>Does the plan make sense?</h2>
<div class="ok">
<p><strong>Yes, with the 25¢ math on the favorite, not on the dog.</strong> Lock profit 0.25 means favorite Yes GTC at about <code>1 − dog_fill − 0.25</code>, not a GTC at 51 on the dog. Example: dog extra fills at 0.51 → favorite dip target is 0.24. A GTC <em>buy</em> at 0.24 rests while the favorite is still expensive. A GTC buy at 0.51 on a dog already offered at 0.35 takes ~0.35 now.</p>
</div>

<h2>Lock leftover GTC</h2>
<p>If the venue supports a resting GTC, one 1-contract GTC on the missed hedge at the max profitable price (<code>NET_MAX − fill − fees</code>) on the highest-size venue is coherent. Set the limit <em>at</em> the cap, not above it. A buy limit cannot fill worse than its price; if we set the limit too high we can take an ask that blows the cap. If we set it at the cap it may rest unfilled until the ask comes down. Fees are estimated at send; a later cheaper fill is better cash, not worse.</p>
<p><strong>Volume proxy:</strong> this repo does not store a cumulative venue-volume field. The tape already has displayed takeable size (<code>yes_size</code> / <code>no_size</code> / <code>quote_size</code>). That is size showing on the book, not traded volume. Do not invent a volume API field. If we must pick one venue, use that displayed size. Strategy B still never sends Novig.</p>
<p>Still flatten first. GTC leftover only after the IOC flatten miss. Cancel the rest if the game resolves or is postponed. Today’s leftover watch already stops on resolved / postponed; a resting GTC would need that same cancel (paths already exist per venue).</p>

<h2>Strategy B two GTCs</h2>
<p><strong>Stop / trigger buy at 51 on the dog:</strong> a limit GTC at 0.51 is not “wait for 51.” If the ask is already ≤ 0.51 it fills now (Paul is right). If the dog last is 0.35, a GTC buy at 0.51 is an aggressive limit that fills now at ~0.35. To wait for 51 you need a stop-limit with a trigger, or keep ping-and-wait. Gemini documents <code>orderType=stop-limit</code> + <code>stopPrice</code> (buy: stopPrice ≥ last and ≤ price). Kalshi create-order has no stop. Novig has no stop. Polymarket US consumer create has no stop. Recommendation: keep realtime ping for the 50-cross everywhere except a later paper-only Gemini stop-limit test.</p>
<p><strong>Resting GTC on the favorite at the dip target (low price):</strong> this is the correct GTC. A buy limit at the cheap price (0.24 if we need 1 − 0.51 − 0.25) will rest until the ask falls to that price. It will not fill immediately if the favorite is still expensive. That can replace today’s fav-dip IOC ping <em>on that one order only</em>.</p>
<p>If no stop exists (Kalshi, Polymarket US path we use, Novig): keep ping-and-wait for the 50-cross, plus optional GTC on the favorite dip only. Do not pre-place two GTCs as a pair of 51 and “low.”</p>

<h2>What we can do now vs later</h2>
<p>Now: this note only. Live stays IOC 1 contract.</p>
<ol>
<li>TIF strings are already confirmed from official docs and from the live bodies (no live GTC sent).</li>
<li>Later, leftover GTC only after IOC flatten miss. Size 1. Still NET_MAX. Still both-or-flatten. Cancel if resolved / postponed.</li>
<li>Later, Strategy B: optional resting GTC on the favorite dip target only. Keep ping for the 50-cross. Gemini stop-limit is a separate paper test, still size 1, still flatten the extra if one leg of the extra pair fills and the other misses.</li>
<li>Do not start a second <code>live_strategy_b.py</code>. Do not wire DailyRun.</li>
</ol>
<p>Acronyms: GTC is good-til-canceled. GTD / GTT is good-til-date or good-til-time. IOC is immediate-or-cancel. FOK is fill-or-kill. TIF is time-in-force. T0 is the open used here. D=25 is a 25-cent lock on the extra post-cross pair. NET_MAX is the lock-bot after-fee cap ($0.984). CLOB is central limit order book.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)


if __name__ == "__main__":
    main()
