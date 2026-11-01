"""GTC plan go / no-go for Paul. Research only. Does not place or cancel orders."""
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
from report_page_extras import (
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "gtc_plan_readiness_20261022.html"
BRANCH = "cursor/spotify-year-playlist-sync-674a"

ASKED = (
    "OK. that looks good. are we ready to go with our GTC plan? "
    "(1) Lock-bot 2-leg: both fill → done. One fill → after flatten miss, GTC on "
    "highest-volume venue at the hedge price we want (NET_MAX − fill − fees), 1 contract. "
    "(2) Strategy B D=25: T0 both Yes (today). Then two GTCs on the highest-volume venue. "
    "Buy dog only if it reaches 51 — that is not a GTC limit at 51 (fills now if cheaper). "
    "Only Gemini docs a stop-limit. Favorite-dip GTC at ~1 − dog_fill − 0.25 can rest. "
    "Else ping-and-wait for the 50-cross. Previously: hold GTC until data is accurate."
)

PLAIN = (
    "A good-til-canceled (GTC) order sits on the book until it fills or we cancel it. "
    "Immediate-or-cancel (IOC) is what live lock and Strategy B send today: take it now "
    "or the leftover dies. The plan is two later slices, not a live wire tonight. "
    "Slice one would rest a 1-contract hedge after flatten also misses. Slice two would "
    "rest a cheap bid on the favorite after Strategy B already bought both Yes at the "
    "open (T0) and then bought the dog on a 50-cross. A GTC buy at 51 cents on the dog "
    "is the wrong tool: if the dog is already cheaper, that limit fills now. Only Gemini "
    "documents a stop-limit, and that stays paper-only. We did not place a GTC, start a "
    "second Strategy B, or sell. Head is the Spotify playlist branch, not main."
)


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
    head = "".join(
        th(label, "text")
        for label in ("Slice", "Ready?", "Evidence", "Blocker")
    )
    rows = [
        [
            "Leftover GTC after flatten miss",
            "No — first slice later",
            "Feasibility page already confirmed GTC time-in-force (TIF) on Kalshi, Gemini predictions, Polymarket US, and Novig. Live leftover watch today still sends one IOC, 1 contract, cheapest qualifying opposite under NET_MAX (0.984 after documented fees). Flatten-first is already live. Per-venue cancel helpers exist (_cancel).",
            "Not wired. Resting GTC is never sent. Cancel-on-resolve for a resting order id does not exist (watch only stops IOC retries). Still-open is not fully venue-history backed. Head is "
            + BRANCH
            + ", not main — do not edit live_lock_orders.py here. Wait for Paul to say “wire leftover GTC” on the trading branch.",
        ],
        [
            "B favorite-dip GTC",
            "No — second slice",
            "Correct GTC: a buy limit at about 1 − dog_fill − 0.25 rests while the favorite is still expensive. Example: dog extra at 0.51 → favorite dip about 0.24. That can replace today’s favorite-dip IOC ping on that one order only. Strategy B still never sends Novig.",
            "Not wired. Comes after leftover GTC, and only with cancel-on-resolve. The 50-cross still needs today’s ping-and-wait. Do not pre-place two GTCs as a 51 + low pair.",
        ],
        [
            "B dog-51 stop",
            "Never as a resting GTC limit",
            "Paul is right: a GTC buy at 0.51 fills now if the ask is already ≤ 0.51 (dog at 0.35 would take ~0.35). Kalshi create-order has no stop. Novig has no stop. Polymarket US POST /v1/orders is limit/market only; STOP lives on a different institutional host we do not use. Gemini documents orderType=stop-limit plus stopPrice on the same prediction order path; never posted live in this repo.",
            "Do not rest a 51-cent GTC. Keep ping-and-wait for the 50-cross. Gemini stop-limit is paper-only, size 1, later, not this job.",
        ],
        [
            "Volume venue pick",
            "Partial — displayed size only",
            "Repo has takeable size on the tape (yes_size / no_size / quote_size). Leftover watch already ranks qualifying opposites by cheapest after-fee net, not by volume. Strategy B never sends Novig.",
            "No cumulative traded-volume field. Do not invent a volume API. If we must pick one venue, use displayed size as a proxy and say so. Not a live picker today.",
        ],
        [
            "Cancel on resolve / postpone",
            "No",
            "Leftover watch stops IOC retries when a venue reports a real resolved/settled status (missed_market_closed → resolved_first). Strategy B mark_postponed stops extras/cross/dip and leaves holdings. Per-venue cancel paths exist for IOC leftover / Gemini probe.",
            "Stopping a watch is not canceling a resting GTC. Postpone does not cancel an order id. A live leftover GTC needs: persist order id, cancel on resolve, cancel on postpone, and cancel if we flatten later. That loop is not written. Required before any live rest.",
        ],
        [
            "1 contract",
            "Yes as freeze (already live)",
            "live_lock_orders.SIZE is 1. Strategy B extras are 1. Gemini GTC probe (ORDERS_ENABLED false) used quantity 1 then cancel. Plan stays 1.",
            "None on size. Does not make the GTC wire ready.",
        ],
        [
            "NET_MAX",
            "Yes as freeze (already live)",
            "NET_MAX is 0.984 after documented fees. Leftover GTC limit would be at NET_MAX − fill − fees, not above it. A later cheaper fill is better cash. Strategy B extra pair cap is 1 − 0.25.",
            "None on the cap. Fees are estimated at send. Does not make the GTC wire ready.",
        ],
        [
            "Flatten-first",
            "Yes as today’s rule; GTC after miss not wired",
            "If exactly one IOC fills, flatten the filled contract on that same venue/instrument. Leftover watch starts only if flatten also misses. Both fill → done, keep looking. Neither fill → no latch.",
            "GTC is only after that flatten miss. Wiring GTC must not skip flatten or replace both-or-flatten. Not a reason to go live on the full plan.",
        ],
        [
            "Data / ledger honest enough",
            "No",
            "Paul: hold GTC until data is accurate. Fill-history audit called official APIs: Kalshi GET /portfolio/fills, Gemini POST /v1/prediction-markets/orders/history, Polymarket US GET /v1/portfolio/activities (TRADE), Novig GET /v3/portfolio/fills (empty). Performance page still shows 38 tape-vs-venue mismatches. Still-open on fresh GET: Polymarket US Urso and Tixhon only. Kalshi positions GET 0 rows. Taverna vs Bueno Kalshi settlement unknown (gone from positions, no payout pasted).",
            "38 mismatches plus unknown Taverna P&L and logging gaps (Poly splits, missing filled events, ghost B stages) are not “accurate enough” to rest live GTC. Still-open must stay venue-history backed before slice one.",
        ],
    ]

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GTC plan readiness 2026-10-22</title>
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
<h1>GTC plan readiness — not ready to go live</h1>
<p class="note">America/New_York. Written {esc(datetime.now(ET).isoformat(timespec="seconds"))}. Research / go-no-go only. Not gold. Not DailyRun. This page does not place, cancel, flatten, or sell. Git HEAD this job: <code>{esc(BRANCH)}</code> (Spotify playlist). Trading GTC must be implemented on <code>main</code>, not here. Click column headers to sort. Immediate-or-cancel (IOC) is fill now or cancel. Good-til-canceled (GTC) is a resting limit.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="warn">
<p><strong>Full plan: not ready to go live.</strong> Dog GTC at 51: never as a resting limit. Gemini stop-limit is paper-only. Leftover GTC after flatten miss is the first live slice — only after cancel-on-resolve exists, still-open is venue-history backed, and you say “wire leftover GTC” on the trading branch. Strategy B favorite-dip GTC is the second slice; ping stays for the 50-cross. No live GTC this job. No second Strategy B. Size stays 1. Net cap stays NET_MAX.</p>
</div>

<h2>Checklist</h2>
<p class="note">Nine slices of the plan. Ready means that slice can go live now, not that the math is coherent. Click headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>{rows_html(rows)}</tbody>
</table></div>

<h2>Verdict</h2>
<div class="ok">
<p><strong>No / not yet.</strong> The earlier feasibility note still stands: GTC limits exist on all four venues, and a cheap favorite-dip rest is the right GTC. That is not the same as wiring it.</p>
<ol>
<li><strong>Do not go live on the full plan.</strong></li>
<li><strong>Never rest a GTC buy at 51 on the dog.</strong> That fills now if cheaper. Keep ping-and-wait for the 50-cross. Gemini stop-limit stays paper-only.</li>
<li><strong>First live slice, when you say wire it on <code>main</code>:</strong> leftover GTC after flatten miss, 1 contract, limit at NET_MAX − fill − fees, highest displayed size (not invented volume), only after cancel-on-resolve/postpone is real and still-open is venue-history backed.</li>
<li><strong>Second slice:</strong> Strategy B favorite-dip GTC at about 1 − dog_fill − 0.25. Ping remains for the 50-cross.</li>
</ol>
</div>

<h2>Branch</h2>
<p>HEAD is <code>{esc(BRANCH)}</code>. Prediction GTC was not implemented on this branch. <code>tools/live_lock_orders.py</code> was not edited this job. Say “wire leftover GTC” if you want implementation next — on <code>main</code>, not Spotify.</p>

<p class="note">Acronyms: GTC is good-til-canceled. IOC is immediate-or-cancel. TIF is time-in-force. T0 is the open used here. D=25 is a 25-cent lock on the extra post-cross pair. NET_MAX is the lock-bot after-fee cap ($0.984).</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    html_out = inject_report_page_extras(page)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(html_out, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)


if __name__ == "__main__":
    main()
