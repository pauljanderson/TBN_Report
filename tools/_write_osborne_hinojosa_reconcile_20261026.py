"""Osborne vs Hinojosa Gomez: tape vs orders_performance vs venue fill-history.

Research only. Does not sell, start a second B, commit, print secrets,
wire D NFL, bump stake, or turn A on.
"""
from __future__ import annotations

import html as html_lib
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
PAGE = STAMP / "osborne_hinojosa_reconcile_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/osborne_hinojosa_reconcile_20261026.html"
)

ASKED = (
    "Paul: help reconcile Alexandra Osborne vs Jessica Hinojosa Gomez. What did we buy. "
    "What does orders_performance show we bought. What does each venue think we bought. "
    "Do they match? Why / why not? What can we do to prevent this discrepancy. "
    "Every order we sent on this match (system A/B/E, venue, side, ticker/slug, limit, "
    "wire, fee, after-fee, HTTP, confirm qty, order ids, times ET). What "
    "orders_performance.html currently shows (system, filled, settled, P&L). Venue GET "
    "fill-history + positions for those ids/markets. Match table: tape vs performance "
    "page vs each venue. Gaps: Poly empty activities, positions GET, Kalshi 201 empty, "
    "HTML grouping, fee 0 vs 1.75¢, wrong system label, postponed. Prevent: only count "
    "confirm qty≥1; rebuild performance from venue ids not labels; don’t glue B fills "
    "onto A claims. If a live bug, fix it (display/count). Do not invent API."
)
PLAIN = (
    "One tennis match, two shops. System A tried to lock “Osborne wins” by buying Yes "
    "on Polymarket and No on Kalshi so one of those two tickets must pay $1. Three "
    "earlier looks were skipped because the pair was too expensive after a book recheck. "
    "The 3:19 PM ET try filled both. Osborne lost; Kalshi No paid $1 and the Polymarket "
    "Yes paid $0. All-in we spent about 102.7¢ for a $1 payout, so we lost about 2.7¢. "
    "That is a true lock, not a leftover. Kalshi’s Yes page would show this as Sold Yes "
    "at 11¢ — that is our buy No at 89¢. The performance page already has those two "
    "tickets. The local Kalshi cash tracker only subtracted 11¢ (the Yes-wire) instead "
    "of 89.7¢ after fee; that count bug is now fixed so the next No fill debits the "
    "real No cash."
)

PREVENT_ASKED = (
    "Paul’s prevent question: this should never have sent if pair_net used house No cash "
    "0.89 not Yes-wire 0.07 (Sold Yes at 7¢). Confirm live_lock_orders pair_net / leg_fee / "
    "contract_cost / qualifies for Kalshi No uses 1−Yes-wire (or no_price_dollars) once, "
    "after-fee, unrounded Decimal, vs NET_MAX 0.99. If send still treats No as 7¢, fix it "
    "and reload one lock supervisor. Leave B. Do not sell, second B, commit, secrets, D NFL, "
    "bump stake, leftover GTC. Sibling bc97ac6b false-sent TB-CAR — do not revert. Merge "
    "with fee-first-class (average_fee_paid) and hard-then-easy HTML hold. If send path is "
    "already correct, say how this 1.0269 pair passed. HTML addendum. ntfy. Return: would "
    "this pair send today? yes/no. What pair_net would print. Lock pid if reloaded."
)
PREVENT_PLAIN = (
    "We asked whether the robot treated the Kalshi No ticket as 7¢ (the Sold-Yes price) "
    "so 7¢ plus 12¢ looked like a bargain under the 99¢ send cap. It did not. The 3:19 PM "
    "look used No 93¢ plus Polymarket Yes 6¢ and still counted Kalshi’s fee as $0, which "
    "printed 99¢ and sent. Kalshi filled at 89¢. By then Polymarket had moved to 14¢. The "
    "robot then treated the Kalshi fill as 11¢ (the Yes-wire) so the second ticket still "
    "looked cheap. True all-in was 89¢ + 0.69¢ fee + 12¢ + 1¢ = 102.69¢. Today the Kalshi "
    "fee is first-class, fill cash is 89¢ once, and this pair’s pair_net is 1.0269, which "
    "does not send."
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


def write_page(pids: dict | None = None) -> Path:
    sent = table(
        [
            ("Time ET", "date"),
            ("System / step", "text"),
            ("Venue", "text"),
            ("House side", "text"),
            ("Ticker / slug", "text"),
            ("Limit", "text"),
            ("Wire", "text"),
            ("Fee", "text"),
            ("After-fee", "text"),
            ("HTTP", "text"),
            ("Confirm qty", "num"),
            ("Confirm note", "text"),
            ("Order id", "text"),
        ],
        [
            [
                esc("2026-10-26 15:19:22.015"),
                esc("A / hard"),
                esc("kalshi"),
                esc("No Alexandra Osborne (POST ask = sell Yes)"),
                esc("KXWTACHALLENGERMATCH-26OCT25OSBHIN-OSB"),
                esc("No pay 0.9300 → POST ask 0.0700"),
                esc("0.8900 (Yes-wire 0.1100)"),
                esc("0.0069 (POST average_fee_paid = GET fee_cost)"),
                esc("0.8969"),
                esc("201"),
                esc("1.00"),
                esc("kalshi fills GET qty 1.00 @ 0.8900"),
                esc("01a179a7-e628-7aef-9600-afe97ae29d38"),
            ],
            [
                esc("2026-10-26 15:21:01.304"),
                esc("A / easy"),
                esc("polymarket"),
                esc("Yes Alexandra Osborne (BUY_LONG)"),
                esc("aec-wta-aleosb-jeshin-2026-10-25"),
                esc("0.140 FOK"),
                esc("0.1200"),
                esc("0.0100 (commission)"),
                esc("0.1300"),
                esc("200"),
                esc("1"),
                esc("polymarket activities GET empty; this-order cumQuantity 1 @ 0.1200"),
                esc("DB9ZWXWG11MV"),
            ],
        ],
        "Only two HTTP sends. B and E did not post on this match. Client order id "
        "77a2f52f-9ca5-44f6-aaef-16e5ebea3bb2. Kalshi ts_ms → 15:20:09 ET. Poly createTime 15:21:40 ET.",
    )

    skips = table(
        [
            ("Time ET", "date"),
            ("Event", "text"),
            ("System", "text"),
            ("Net / reason", "text"),
            ("Posted?", "text"),
        ],
        [
            [
                esc("14:26:56"),
                esc("claim + skip"),
                esc("A"),
                esc("net 0.9800 → over cap recheck net 1.0100 (Poly Yes 0.32 + Kalshi No 0.64)"),
                esc("no"),
            ],
            [
                esc("14:27:49"),
                esc("claim + skip"),
                esc("A"),
                esc("net 0.9300 → over cap recheck net 1.0400 (Poly Yes 0.28 + Kalshi No 0.64)"),
                esc("no"),
            ],
            [
                esc("14:40:08"),
                esc("claim + skip"),
                esc("A"),
                esc("net 0.9800 → over cap recheck net 1.0200 (Poly Yes 0.11 + Kalshi No 0.86)"),
                esc("no"),
            ],
            [
                esc("several T0 stamps"),
                esc("B t0 skip"),
                esc("B"),
                esc("t0_allin_c_over_105 / fee unknown — never an order"),
                esc("no"),
            ],
        ],
        "Ghost leftover row on the performance page is these three A claim+skips glued by bet_key. No HTTP.",
    )

    perf = table(
        [
            ("Page", "text"),
            ("System / role", "text"),
            ("Filled", "text"),
            ("Settled", "text"),
            ("Sides / venues", "text"),
            ("Limits shown", "text"),
            ("Fill / fee / after-fee", "text"),
            ("P&L", "text"),
        ],
        [
            [
                esc("orders_performance.html true lock"),
                esc("A Lock gap / true lock"),
                esc("yes, 2 legs, both filled lock"),
                esc("venue-settled / Paul history (not still-open)"),
                esc("kalshi No / polymarket Yes"),
                esc("0.0700 / 0.1400 (POST ask / Poly limit)"),
                esc("0.8900 / 0.1200 ; 0.0069 / 0.0100 ; 0.8969 / 0.1300"),
                esc("−$0.03 (loss) = −$0.0269"),
            ],
            [
                esc("orders_performance.html ghost"),
                esc("A Lock gap / leftover lock (A)"),
                esc("no — never held"),
                esc("never held"),
                esc("(none)"),
                esc(""),
                esc(""),
                esc("blank; note ghost claim: no order_io HTTP"),
            ],
            [
                esc("orders.html 1429 / 1430"),
                esc("A Lock gap"),
                esc("yes / both filled"),
                esc("n/a (send tape)"),
                esc("Kalshi No + Poly Yes"),
                esc("No 0.9300 (shown) / Poly 0.140"),
                esc("0.1100 (cash 0.8900) + 0.0069 = 0.8969 ; Poly 0.1200 + 0.0100 = 0.1300"),
                esc("pair after-fee 0.8969 / 0.1300"),
            ],
            [
                esc("job_status Positions"),
                esc("—"),
                esc("not listed"),
                esc("correctly absent: both books empty / expired / finalized"),
                esc(""),
                esc(""),
                esc(""),
                esc(""),
            ],
        ],
        "Click headers to sort. Performance limits print the Kalshi POST ask 7¢; orders.html converts that to No pay 93¢.",
    )

    venues = table(
        [
            ("Venue", "text"),
            ("Endpoint", "text"),
            ("HTTP", "text"),
            ("Qty", "text"),
            ("Avg / cash", "text"),
            ("Fee", "text"),
            ("Ids", "text"),
            ("Open now?", "text"),
        ],
        [
            [
                esc("Kalshi"),
                esc("GET /trade-api/v2/portfolio/fills"),
                esc("200 n=1"),
                esc("1.00"),
                esc("yes_price 0.1100 / no_price 0.8900"),
                esc("fee_cost 0.006900"),
                esc("order 01a179a7-e628-7aef-9600-afe97ae29d38 trade 07249f38-4a01-9a57-efd9-fe4c5be0cf49"),
                esc("positions GET 0 (settled)"),
            ],
            [
                esc("Kalshi"),
                esc("GET /trade-api/v2/markets/{ticker}"),
                esc("200 / 200"),
                esc("—"),
                esc("OSB last 0.01 result=no finalized; HIN last 0.99 result=yes finalized"),
                esc(""),
                esc("KXWTACHALLENGERMATCH-26OCT25OSBHIN-OSB / -HIN"),
                esc("finalized — Osborne lost, Hinojosa won"),
            ],
            [
                esc("Kalshi"),
                esc("GET /trade-api/v2/portfolio/settlements"),
                esc("200 n=0"),
                esc("0 rows"),
                esc(""),
                esc(""),
                esc("ticker filter on OSBHIN event"),
                esc("P&L from lock math + market result, not a settlement row"),
            ],
            [
                esc("Polymarket US"),
                esc("GET /v1/portfolio/activities"),
                esc("200 n=1 now (empty at send confirm)"),
                esc("1.0000"),
                esc("0.1200"),
                esc("$0.01 on this-order FILL"),
                esc("aggressor DB9ZWXWG11MV isAggressor true"),
                esc("positions GET 0 eof; book MARKET_STATE_EXPIRED"),
            ],
            [
                esc("Gemini"),
                esc("POST /v1/prediction-markets/orders/history"),
                esc("200"),
                esc("0 match"),
                esc(""),
                esc(""),
                esc("no send on this match"),
                esc("n/a"),
            ],
            [
                esc("Novig"),
                esc("GET /v3/portfolio/fills"),
                esc("200 n_page=2"),
                esc("0 match"),
                esc(""),
                esc(""),
                esc("no send on this match"),
                esc("n/a"),
            ],
        ],
        "Pulled 2026-10-26 20:44 ET. Fill-history confirm is truth. Did not invent endpoints.",
    )

    match = table(
        [
            ("What", "text"),
            ("Tape", "text"),
            ("Performance page", "text"),
            ("Venue now", "text"),
            ("Match?", "text"),
        ],
        [
            [
                esc("Kalshi No Osborne qty"),
                esc("confirm 1.00; POST fill_count 1.00"),
                esc("1.0000"),
                esc("fills GET count_fp 1.00 same order id"),
                esc("Yes"),
            ],
            [
                esc("Kalshi No cash / fee"),
                esc("filled price 0.8900; POST fee 0.0069"),
                esc("fill 0.8900 fee 0.0069 after-fee 0.8969"),
                esc("no_price 0.8900 fee_cost 0.006900; action sell / ask / outcome no"),
                esc("Yes on the pages. Local cash debit was −0.11 (bug, fixed)"),
            ],
            [
                esc("Poly Yes Osborne qty"),
                esc("HTTP 200 ≠ fill; this-order cumQuantity 1 / aggressor FILL"),
                esc("1.0000"),
                esc("activities GET qty 1.0000 aggressor DB9ZWXWG11MV (empty at 15:21 confirm)"),
                esc("Yes — empty activities did not override cumQuantity"),
            ],
            [
                esc("Poly cash / fee"),
                esc("avgPx 0.1200 + commission 0.0100 = 0.1300"),
                esc("0.1200 / 0.0100 / 0.1300"),
                esc("TRADE price 0.1200"),
                esc("Yes. Local debit −0.1300 matches"),
            ],
            [
                esc("System label"),
                esc("bet_key lock (not tennis-b); step hard/easy"),
                esc("A Lock gap / true lock"),
                esc("n/a"),
                esc("Yes. Not glued to B. B only skipped T0."),
            ],
            [
                esc("Still open / postponed"),
                esc("both filled lock, no leftover"),
                esc("venue-settled; ghost never held"),
                esc("Kalshi finalized; Poly EXPIRED; both position lists empty"),
                esc("Yes. Empty positions GET did not drop an OPEN fill — market is expired/final"),
            ],
            [
                esc("Kalshi 201 empty"),
                esc("fill_count 1.00, not 0"),
                esc("counted as fill"),
                esc("GET qty 1.00"),
                esc("N/A — this was not an empty 201"),
            ],
            [
                esc("Fee 0 vs 1.75¢"),
                esc("0.0069 = 0.07 × 0.11 × 0.89"),
                esc("0.0069 / Poly 0.0100"),
                esc("fee_cost 0.006900"),
                esc("Yes. Not the 1.75¢ Bobichon-49¢ fee. 0 on sent.wire fields; pages rebuild from order_io"),
            ],
            [
                esc("Winner / P&L"),
                esc("lock 0.8969 + 0.1300 = 1.0269 vs $1 → −0.0269"),
                esc("−$0.03 (loss)"),
                esc("Osborne result=no so Kalshi No pays $1, Poly Yes pays $0"),
                esc("Yes"),
            ],
        ],
        "Click headers to sort. Sold Yes on Kalshi is our buy No.",
    )

    prevent = table(
        [
            ("Rule", "text"),
            ("This match", "text"),
            ("Shipped?", "text"),
        ],
        [
            [
                esc("Only count confirm qty ≥ 1"),
                esc("Kalshi GET 1.00 and Poly this-order cumQuantity 1. HTTP 201/200 alone is not the ticket."),
                esc("Already live in venue_fill_confirm / filled_contracts"),
            ],
            [
                esc("Empty Poly activities must not override cumQuantity"),
                esc("Confirm note kept qty 1 @ 0.12. Hours later activities GET found the same aggressor id."),
                esc("Already live (Guajardo leftover path)"),
            ],
            [
                esc("Empty Poly positions GET must not drop a confirmed fill while OPEN"),
                esc("Positions 0 because MARKET_STATE_EXPIRED / Kalshi finalized, not because the fill vanished mid-match."),
                esc("Already the still-open rule on orders_performance / job_status Positions"),
            ],
            [
                esc("Kalshi 201 fill_count 0 = empty"),
                esc("Not this row. fill_count 1.00 and GET 1.00."),
                esc("Already live"),
            ],
            [
                esc("Rebuild performance from venue ids, not labels"),
                esc("Clustered on bet_key tennis/osbhin. Order ids match GET. No B fill glued onto the A claim."),
                esc("order_ledger groups by bet_key so B/C/D/E are not glued onto a prior lock claim"),
            ],
            [
                esc("Kalshi Sold Yes = buy No; fees wire vs after-fee"),
                esc("Pages used No cash 0.89 + fee 0.0069. Local cash inverted confirm 0.89 back to 0.11 and skipped the 0.89 debit."),
                esc("Fixed this job: live_lock_orders._kalshi_no_house_cash. Next No fill debits confirm/no_price, not 1 − that price"),
            ],
            [
                esc("Performance Kalshi No limit shows POST ask 7¢"),
                esc("orders.html already converts to No pay 93¢. Ledger still prints 0.0700 / 0.1400."),
                esc("Noted. Did not rebuild orders_performance.html (sibling owns a false-SENT opportunities autopsy)"),
            ],
            [
                esc("pair_net must use house No cash, not POST Yes-wire 7¢"),
                esc("Claim used No 0.93 + Poly Yes 0.06, Kalshi fee $0, printed 0.9900. Fill all-in 1.0269. POST ask 0.07 was the order wire, not the cap input."),
                esc("Cap path already used pay. Funds/cost still used limit 7¢ — fixed this pass (_leg_cash_price). Fee-first-class + fill invert already live."),
            ],
        ],
    )

    pid = pids if isinstance(pids, dict) else {}
    lock_pid = pid.get("lock") or pid.get("supervisor") or "not reloaded this pass"
    b_pid = pid.get("b") or pid.get("strategy_b") or "left in place"

    prevent_net = table(
        [
            ("Look", "text"),
            ("Kalshi No cash", "num"),
            ("Poly Yes", "num"),
            ("Kalshi fee", "num"),
            ("Poly fee", "num"),
            ("pair_net", "num"),
            ("Send vs 0.99?", "text"),
        ],
        [
            [
                esc("3:19 claim (websocket)"),
                esc("0.9300"),
                esc("0.0600"),
                esc("0 (bug then; formula now 0.0046)"),
                esc("0.0100"),
                esc("0.9900 then; 1.0046 today"),
                esc("Sent then / no today"),
            ],
            [
                esc("Fill (venue truth)"),
                esc("0.8900"),
                esc("0.1200"),
                esc("0.0069 (average_fee_paid)"),
                esc("0.0100"),
                esc("1.0269"),
                esc("No today"),
            ],
            [
                esc("Counterfactual: No as POST 7¢"),
                esc("0.0700 Yes-wire"),
                esc("0.1200"),
                esc("0.0046"),
                esc("0.0100"),
                esc("0.2046"),
                esc("Would send — this was not the cap input"),
            ],
        ],
        "Click column headers to sort. pair_net is unrounded Decimal vs NET_MAX 0.99.",
    )

    body = f"""
<h1>Osborne vs Hinojosa Gomez — tape vs shops</h1>
<p class="tiny">Stamp drive/paul_experiments/prediction_market_arb_exhaustive_20261017/. Fill-history confirm is truth. Did not sell. Did not start a second B. Did not bump stake. Did not wire D NFL. Did not turn A on. {esc(FILE_URL)}</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="verdict">
<p><strong>Tickets match. P&amp;L matches. Local Kalshi cash did not.</strong> We bought two $1 tickets on Alexandra Osborne: Kalshi <em>No</em> 1 @ 89¢ + 0.69¢ fee, Polymarket <em>Yes</em> 1 @ 12¢ + 1¢ fee. All-in 102.69¢ vs $1 → <strong>−2.69¢</strong> (page prints −$0.03). Jessica Hinojosa Gomez won (Kalshi OSB result=no, HIN result=yes, both finalized). System A only. The local Kalshi wallet subtracted 11¢ (Yes-wire) instead of 89.69¢; that count is now fixed. Empty Poly activities at send time did not wipe the fill. Empty position lists now are expired/final, not an open-market drop.</p>
</div>

<h2>What we bought</h2>
<ul>
<li><strong>Kalshi No Alexandra Osborne</strong> — 1 contract, No cash 89¢, fee 0.69¢, after-fee 89.69¢. POST was ask/sell Yes at 7¢ (No pay limit 93¢), filled Yes-wire 11¢. Kalshi Sold Yes = our buy No. Order <code>01a179a7-e628-7aef-9600-afe97ae29d38</code>.</li>
<li><strong>Polymarket Yes Alexandra Osborne</strong> — 1 contract @ 12¢ + $0.01 taker = 13¢. FOK limit 14¢. Order <code>DB9ZWXWG11MV</code>, aggressor FILL id <code>DB9ZWXX011KR</code>.</li>
<li>Gemini: none. Novig: none. B/E: none posted.</li>
</ul>

<h2>Every order we sent</h2>
{sent}

<h2>Looks that never posted</h2>
{skips}

<h2>What orders_performance.html shows</h2>
{perf}

<h2>What each venue thinks</h2>
{venues}

<h2>Match table</h2>
{match}

<h2>Why the cash number was 11¢</h2>
<ul>
<li>Live confirm overlay stores house No cash: <code>kalshi fills GET qty 1.00 @ 0.8900</code>.</li>
<li><code>_actual_fill_cash</code> then did 1 − 0.89 for every Kalshi No, which is correct only for Yes-wire <code>average_fill_price</code> 0.11. Doing it again on the confirm price debited <strong>0.11</strong> at 15:21:01 ET.</li>
<li>Poly debit −0.1300 is right. Performance / orders.html never used that inverted 11¢ as the lock cost; they rebuilt from order_io Yes-wire → No 0.89 + <code>average_fee_paid</code> 0.0069.</li>
<li>Fix: prefer confirm <code>avg_price</code> and <code>no_price_dollars</code> as house cash; invert only Yes-wire. Test <code>test_kalshi_no_confirm_avg_is_house_cash_not_yes_wire</code>.</li>
</ul>

<h2>Prevent / fix shipped</h2>
{prevent}

<div class="callout">
<h2>What you asked (prevent)</h2>
<p>{esc(PREVENT_ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PREVENT_PLAIN)}</p>
</div>

<div class="verdict">
<p><strong>Would this pair send today? No.</strong> pair_net on the fill is <strong>1.0269</strong> vs cap 0.99.
Cap path already used house No cash (claim 93¢, not POST 7¢). Kalshi fee was $0 at send (now first-class).
After the 89¢ fill, easy Poly 14¢ passed because fill cash was inverted to 11¢ (fixed 6272d9f9).
Funds/cost still treated No as the 7¢ POST ask — fixed this pass (<code>_leg_cash_price</code>).
Lock supervisor reloaded, pid {esc(str(lock_pid))}. B left ({esc(str(b_pid))}). Did not sell, second B, commit, D NFL, leftover GTC.
Did not revert bc97ac6b. Hard-then-easy HTML hold kept (no orders.html rewrite between IOCs).</p>
</div>

<h2>How 1.0269 passed, and what pair_net prints now</h2>
{prevent_net}
<p class="note">Related: <a href="venue_fee_first_class_20261026.html">venue_fee_first_class_20261026.html</a>. Catalog execute was not this send (live hard-then-easy, pid 76700).</p>

<p class="tiny">Written {esc(datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"))}. Sources: orders.jsonl, order_io.jsonl, venue_cash_drift.jsonl, orders.html, orders_performance.html / ledger.csv, Kalshi fills/positions/settlements/markets, Polymarket US activities/positions/book, Gemini history, Novig fills. Research only. Not gold. Not DailyRun.</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Osborne vs Hinojosa Gomez reconcile 26 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 14px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
.verdict {{ background: #fefce8; border: 1px solid #facc15; padding: 10px 12px; margin: 8px 0 16px; }}
ul {{ margin-top: 0.3rem; }}
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
    print(write_page())


if __name__ == "__main__":
    main()
