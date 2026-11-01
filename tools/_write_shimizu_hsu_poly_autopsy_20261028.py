"""Shimizu vs Hsu Polymarket autopsy HTML. Display/report only. No money-code patch."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report_page_extras import FORCE_RELOAD_SCRIPT, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML
from write_orders_performance import table

STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "shimizu_hsu_poly_autopsy_20261028.html"

SLUG = "aec-atp-yutshi-yuhhsu-2026-10-27"
EVENT = "tennis_shimizhsu_2026_10_27"
OID_SHIM_T0 = "DC618AJG51MQ"
OID_HSU_T0 = "DC618E1G11N2"
OID_CROSS = "DC6CX7F011KJ"


def d4(x) -> str:
    return f"{Decimal(str(x)):.4f}"


def money(x) -> str:
    v = Decimal(str(x))
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.4f}"


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rec = table(
        [
            ("Leg", "text"),
            ("Poly order id", "text"),
            ("Intent", "text"),
            ("Kitchen label", "text"),
            ("Type", "text"),
            ("Poly avgPx (Yes-wire)", "num"),
            ("Poly commissionSpreadPx", "num"),
            ("Poly cash (what he paid)", "num"),
            ("Poly fee", "num"),
            ("Poly after-fee", "num"),
            ("Our stored cash", "num"),
            ("Our stored fee", "num"),
            ("Our after-fee", "num"),
            ("Dashboard after-fee", "num"),
            ("Qty", "num"),
            ("Confirm after send", "text"),
            ("Dashboard P&L (ticker=yes)", "num"),
            ("Venue-true P&L (Hsu won)", "num"),
        ],
        [
            [
                "T0 Shimizu",
                OID_SHIM_T0,
                "BUY_LONG",
                "Yes Yuta Shimizu",
                "initial low lock",
                d4("0.4600"),
                d4("0.4600"),
                d4("0.4600"),
                d4("0.0200"),
                d4("0.4800"),
                d4("0.4600"),
                d4("0.0200"),
                d4("0.4800"),
                d4("0.4800"),
                "1",
                "GET /v1/portfolio/activities qty 1 @ 0.4600",
                money("0.52"),
                money("-0.48"),
            ],
            [
                "T0 Hsu",
                OID_HSU_T0,
                "BUY_SHORT",
                "Yes Yu-Hsiou Hsu",
                "initial Hi lock",
                d4("0.4500"),
                d4("0.5500"),
                d4("0.5500"),
                d4("0.0100"),
                d4("0.5600"),
                d4("0.4500"),
                d4("0.0100"),
                d4("0.4600"),
                d4("0.4600"),
                "1",
                "GET /v1/portfolio/activities qty 1 @ 0.4500 (Yes-wire, not cash)",
                money("-0.46"),
                money("0.44"),
            ],
            [
                "Crossover Shimizu",
                OID_CROSS,
                "BUY_LONG",
                "Yes Yuta Shimizu",
                "crossover lock",
                d4("0.6000"),
                d4("0.6000"),
                d4("0.6000"),
                d4("0.0200"),
                d4("0.6200"),
                d4("0.6000"),
                d4("0.0200"),
                d4("0.6200"),
                d4("0.6200"),
                "1",
                "activities empty; tape GET cumQuantity 1 @ 0.6000",
                money("0.38"),
                money("-0.62"),
            ],
        ],
        [
            "Book",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            d4("1.6100"),
            d4("0.0500"),
            d4("1.6600"),
            d4("1.5100"),
            d4("0.0500"),
            d4("1.5600"),
            d4("1.5600"),
            "3",
            "",
            money("0.44"),
            money("-0.66"),
        ],
    )
    clocks = table(
        [
            ("Clock (America/New_York)", "text"),
            ("Source", "text"),
            ("Shimizu Yes", "num"),
            ("Hsu house / Yes-wire", "text"),
            ("What happened", "text"),
        ],
        [
            ["00:01:02.180", "orders.jsonl sent_at T0 Shimizu", "0.4600", "n/a", "BUY_LONG fill 1 @ avgPx 0.4600 fee 0.0200. Confirm activities @ 0.4600"],
            ["00:01:02.216", "orders.jsonl sent_at T0 Hsu", "Yes-wire 0.4500", "quote 0.55 / spread 0.5500 cash", "BUY_SHORT fill 1. Confirm activities @ 0.4500. Stored cash 0.4500"],
            ["00:02:56", "strategy_b.log + venue_cash_drift", "", "Hsu debit −0.4700", "T0 HTTP logged late. Watch Hsu fill_px 0.45 fill_fee 0.02 → 0.47 tracker"],
            ["00:20:00–00:23:50", "price_memory tennis.jsonl", "<0.5000", "", "No B-cross send; Shimizu Yes still under 50¢"],
            ["00:23:57.410", "price_memory first ≥0.50", "0.5200", "Hsu Yes 0.4900", "T0-dog Shimizu first print through 50¢. No skip/send tape yet"],
            ["00:24:03.038", "price_memory", "0.5300", "Hsu Yes 0.4800", "Paul’s 12:23 AM at 53¢"],
            ["00:26:20.966", "price_memory", "0.6300", "Hsu Yes 0.3800", "Same pair the send used, 39s before REST send"],
            ["00:26:57.414", "price_memory", "0.6200", "Hsu Yes 0.3900", "Paul’s 12:26 at 62¢"],
            ["00:26:59.999", "orders.jsonl cross send", "dog Yes 0.63", "fav Yes 0.38; all-in C=1.05", "Only cross tape for this game: action=send reason=ok"],
            ["00:27:00.289", "orders.jsonl fill", "0.6000 + fee 0.0200 = 0.6200", "", "HTTP 200 fill 1; dashboard 00:27"],
            ["02:27:10", "settled_pnl.json ticker", "", "", "close_hook:removed stored result=yes (wrong vs settlementPx 0)"],
            ["12:48:13", "settled_pnl.json tickets", "", "", "tape_rebuild: two Shimizu wins + Hsu loss using ticker yes"],
        ],
    )
    pnl = table(
        [
            ("Accounting slice", "text"),
            ("Cash", "num"),
            ("What it is", "text"),
        ],
        [
            ["Dashboard three-row P&L", money("0.44"), "+0.52 −0.46 +0.38; ticker result=yes so both Shimizu Yes pay +1"],
            ["Paul Polymarket screen net", money("-0.60"), "He read Hsu cash 0.56, Hsu won, Shimizu lost"],
            ["Dashboard minus Paul screen", d4("1.04"), "The $1.04 he quoted"],
            ["Inverted $1 payout (wrong winner)", d4("1.00"), "We paid ourselves +1 on Shimizu and 0 on Hsu; venue is the reverse"],
            ["Hsu cash understated (0.46 vs 0.56)", d4("0.10"), "1−p: stored Yes-wire 0.45 instead of spread 0.55; fee 0.01 same"],
            ["Inverted payout + Hsu cash error", d4("1.10"), "Venue-exact book if Hsu won: −0.48 +0.44 −0.62 = −0.66"],
            ["Dashboard +0.44 minus venue-true −0.66", d4("1.10"), "Why this page is $1.10 not $1.04: his screen used 0.56 Hsu and the T0 94¢ story used our 46+48"],
            ["Paul screen −0.60 vs venue-true −0.66", d4("0.06"), "His T0 lock story was 94¢ both-Yes; venue T0 was 0.48+0.56=1.04 after fee"],
            ["Our venue_cash_drift Hsu debit", money("-0.47"), "Local wallet tracker at 00:02:56 ET; not Poly’s 0.56. 0.01 off stored 0.46"],
        ],
    )
    scan = table(
        [
            ("Scan", "text"),
            ("Count", "num"),
            ("Note", "text"),
        ],
        [
            ["Filled Polymarket BUY_SHORT in order_io.jsonl", "122", "ORDER_STATE_FILLED. 1 bad JSON line skipped"],
            ["Hsu-shaped: commissionSpreadPx > avgPx", "60", "Cash field is spread (this game: 0.55 vs 0.45)"],
            ["Varaksina-shaped: avgPx > spread", "60", "Prior rule: cash = avgPx. Blind spread rewrite would invert these"],
            ["avgPx = spread", "2", ""],
            ["Books rewritten this job", "0", "List only. No silent tape rewrite"],
        ],
    )
    options = table(
        [
            ("#", "text"),
            ("Layer", "text"),
            ("Option", "text"),
            ("Touches money?", "text"),
            ("What Paul gets", "text"),
            ("Recommend?", "text"),
        ],
        [
            [
                "A",
                "Display only",
                "Kitchen shows Yes-wire + house cash as two columns; leave ledger as-is",
                "No",
                "He can see 0.45 vs 0.55. P&L stays wrong until settlement is fixed.",
                "No — quality is money",
            ],
            [
                "B",
                "Ledger fill cash",
                "For Hsu-shaped fills, store commissionSpreadPx 0.5500 as cash. Do not globally swap every SHORT to spread (Varaksina is the other shape). Prefer venue debit/notional.",
                "Yes (fill cost)",
                "Hsu stores 0.5500. Confirm-after-send must not overwrite with Yes-wire 0.4500.",
                "Yes, with C",
            ],
            [
                "C",
                "Settlement source",
                "Winner from marketData.stats.settlementPx / POSITION_RESOLUTION, not ticker result=yes",
                "Yes (who gets $1)",
                "settlementPx 0.0000 = Shimizu Yes lost = Hsu won. Both Shimizu tickets −cost.",
                "Yes, with B",
            ],
            [
                "D",
                "Confirm-after-send",
                "Keep GET activities/tape, but map BUY_SHORT price to house cash; never store complement as cost",
                "Yes if it overwrites cash",
                "These three confirms ran. Hsu confirm wrote 0.4500 Yes-wire. That is the trap.",
                "Yes — required or B is undone",
            ],
            [
                "E",
                "Venue-fill + venue-settle SoT",
                "After every fill and at redeem, copy Polymarket trades + settlementPx. Never estimate.",
                "Yes (source of truth)",
                "Dashboard P&L = Poly P&L. No 1−p. No inverted winner.",
                "Yes — pick this",
            ],
        ],
    )
    tests = table(
        [
            ("Test", "text"),
            ("Status this job", "text"),
            ("What it locks", "text"),
        ],
        [
            [
                "test_poly_book_settlement_px_zero_is_no",
                "FAIL (expected)",
                "Book settlementPx 0.0000 must parse as result=no. Production parser does not.",
            ],
            [
                "test_hsu_buy_short_cash_is_spread_0_55_not_avgpX_0_45",
                "FAIL (expected)",
                "Venue cash for DC618E1G11N2 is 0.5500. polymarket_fill still returns 0.4500.",
            ],
            [
                "test_hsu_won_shimizu_yes_tickets_lose",
                "PASS",
                "If result=no and Hsu cash were 0.55, book P&L is −0.6600.",
            ],
            [
                "test_wrong_ticker_yes_would_invert_winner",
                "FAIL (expected)",
                "Stored ticker result=yes inverts the $1. Parser still would not emit no from this book.",
            ],
            [
                "test_type_column_uses_quote_not_short_wire",
                "PASS",
                "Type is Hi lock / low / crossover from quote_price, not 1−p.",
            ],
        ],
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Shimizu vs Hsu Polymarket autopsy 2026-10-28</title>
<style>
body {{ font-family: Georgia, serif; max-width: 1100px; margin: 24px auto; padding: 0 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
.bad {{ background: #fdecec; border: 1px solid #e8b4b4; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
ol.problems li {{ margin: 8px 0; }}
{SORTABLE_TH_CSS}
.swipe-note {{ color: #555; font-size: 0.95em; }}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Shimizu vs Hsu — Polymarket autopsy</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}. Exact numbers only. Live send/settlement money logic was not patched. No commit.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Dashboard P&amp;L for Yuta Shimizu vs Yu-Hsiou Hsu disagrees with Polymarket by <strong>$1.04</strong>, and the winner is inverted. Walk this game. Add the Type column from the types already named. Why was crossover late. How can we show two Shimizu wins if Shimizu lost. Hsu 0.46 vs Poly 0.56. Confirm each bet with the platform after send. Exact problems. Fix options plus a recommendation. Tests against regressions. Quality is money.</p>
<h2>In plain English</h2>
<p>We bought three Polymarket tickets on one ATP tennis game. Two at lock (one name each), one later when Shimizu’s Yes price crossed 50 cents. Hsu actually won the match. Polymarket paid the Hsu ticket and the two Shimizu tickets are losses. Our kitchen paid the two Shimizu tickets and treated Hsu as the loss. We also booked Hsu’s cost as 46 cents when Polymarket charged 56 cents. That is why the scoreboard and the venue do not match. This page is the receipt, the options, and the tests. It does not change live betting.</p>
</div>

<h2>Walk the game</h2>
<p><strong>The match.</strong> ATP Challenger Ningbo, round of 16, 27 Oct 2026: Yuta Shimizu vs Yu-Hsiou Hsu. Hsu won 7–5, 3–6, 6–4 (<a href="https://www.atptour.com/en/scores/current-challenger/ningbo/7343/results">ATP Challenger Ningbo results</a>). Polymarket market <code>{SLUG}</code> is a one-slug tennis moneyline: Yes = Shimizu. Book <code>settlementPx = 0.0000</code>, <code>MARKET_STATE_EXPIRED</code>. Yes Shimizu is worth $0. Hsu won on the venue too.</p>
<p><strong>Lock (T0), 00:01:02 ET.</strong> System B bought both names on Polymarket, quantity 1 each, FOK converted to IOC, both HTTP 200 fill 1.</p>
<ul>
<li>Yes Shimizu BUY_LONG at 46¢ + 2¢ fee = <strong>48¢</strong>. Matches his screen.</li>
<li>Yes Hsu BUY_SHORT. We sent the API Yes-wire 45¢, which is the correct Polymarket short ticket for a 55¢ house cost. Polymarket charged <strong>55¢ + 1¢ fee = 56¢</strong>. We stored 45¢ + 1¢ = 46¢. That is his 10¢ gap.</li>
</ul>
<p>His reading “94¢ both-Yes, one side pays $1 → +6¢” used our stored 46+48. Venue lock after fee was 48+56 = <strong>$1.04</strong> before the late ticket. A true both-Yes lock at those prints was already a small expected loss to fees, not +6¢.</p>
<p><strong>Crossover, 00:27:00 ET.</strong> System B does not buy more of the T0 favorite. It waits for the T0 <em>underdog</em> Yes (Shimizu, locked at 46¢) to print through 50¢ from below, then REST-rechecks both books. Gates: dog ask &gt; 50¢, favorite Yes strictly below the dog Yes, all-in C (both Yes + documented taker fees) ≤ 1.05. Memory first saw Shimizu 52¢ at 00:23:57 (Hsu Yes 49¢). Paul’s 53¢ is 00:24:03. The only cross tape for this game is send at 00:26:59.999: dog Yes 0.63, fav Yes 0.38, all-in C = 1.05. Fill 60¢ + 2¢ fee = 62¢ at 00:27:00.289. His 12:26 at 62¢ and dashboard 00:27 match the fill. No skip row was taped. The late part is the 3m 3s from first 50¢ memory tick to REST send, while the book moved 52¢ → 63¢ — not a skipped name.</p>
<p><strong>Who got paid.</strong> Hsu won. Venue: Shimizu T0 −48¢, Hsu T0 +44¢ (get $1, paid 56¢), crossover −62¢. Net <strong>−66¢</strong>. Kitchen used ticker <code>result=yes</code> (Shimizu won): +52¢, −46¢, +38¢. Net <strong>+44¢</strong>.</p>

<div class="bad">
<p><strong>Winner: Yu-Hsiou Hsu.</strong> Independent: ATP score 7–5 3–6 6–4. Venue: <code>settlementPx 0.0000</code> on a Yes=Shimizu market. Both Shimizu Yes tickets are lost bets (−cost). Hsu Yes is the win (+1 − cost).</p>
</div>

<h2>Three fills — Polymarket truth | our ledger | dashboard</h2>
<p>Click column headers to sort. Cash to 4 decimals. Qty is 1 share each.</p>
{rec}

<h2>Dashboard +$0.44 vs Poly −$0.60: the $1.04</h2>
{pnl}
<p>Paul’s $1.04 is exact for <em>dashboard +0.44 minus his screen −0.60</em>. Split: <strong>$1.00</strong> inverted winner + <strong>$0.10</strong> Hsu cash (0.46 vs 0.56) = <strong>$1.10</strong> versus venue-true −0.66. The extra 6¢ is his screen net (−0.60) versus venue-true (−0.66): T0 both-Yes at 46+48 vs venue 48+56.</p>

<h2>Hsu 0.46 vs Poly 0.56</h2>
<p>Not a cloned fill id. Same order <code>{OID_HSU_T0}</code>. Not fee vs average (fee is 0.01 both sides). It is <strong>1−p</strong>:</p>
<ul>
<li>Polymarket US <code>price.value</code> is Yes. BUY_SHORT cash is often <code>1 − Yes</code>.</li>
<li>Fill payload: <code>avgPx = 0.4500</code> (Yes-wire), <code>commissionSpreadPx = 0.5500</code> (house cash).</li>
<li>We sent API 0.450 correctly for a 55¢ short. House quote was already 0.55 (<code>quote_price</code>).</li>
<li><code>polymarket_fill</code> stores cash = avgPx (Varaksina rule: spread is the Yes wire). Hsu is the other shape: spread is the cash.</li>
<li><code>_polymarket_fill_cash</code> then keeps avgPx because it matches the sent limit within 5¢ (0.45 vs 0.45). Complement 0.55 is 10¢ away, so it does not invert.</li>
<li>Confirm-after-send ran and wrote activities price 0.4500 — still Yes-wire. It did not save us.</li>
<li>Kitchen label “Yes Yu-Hsiou Hsu” is the house side. The number next to it is the Yes-wire, not the dollars paid.</li>
<li>Local <code>venue_cash_drift</code> debited Hsu <strong>−0.4700</strong> at 00:02:56 ET. That is our tracker, not Poly 0.56.</li>
</ul>

<h2>Why two Shimizu wins if Shimizu lost</h2>
<p>Labels are “Yes Yuta Shimizu” twice (T0 + crossover) plus “Yes Yu-Hsiou Hsu” once. Settlement used ticker <code>result=yes</code> stored at 02:27:10 ET via <code>close_hook:removed</code>. On a Yes=Shimizu market, yes means Shimizu won. Both Shimizu rows get +1 − cost. Hsu gets −cost. ATP and <code>settlementPx 0</code> say the opposite. Prior “doubled Shimizu” labeling was changed to Yes {{player}}; the $1 still went to the wrong name because the result bit is still yes.</p>
<p>Parser note: <code>open_count_sync._poly_payload_fields</code> does not read <code>marketData.stats.settlementPx</code>. <code>Decimal(str({{...}}))</code> on a dict also fails. So even with the book in hand, production settlement would not have seen 0.0000 as no.</p>

<h2>Crossover delay 00:20–00:28 ET</h2>
{clocks}
<p>Not a wrong-player send: watch <code>t0_dog_player = Yuta Shimizu</code>, <code>t0_fav_player = Yu-Hsiou Hsu</code>, <code>cross_player = Yuta Shimizu</code>. T0 both filled (HTTP 200). Memory already showed the send pair 0.63 / 0.38 at 00:26:20.966, 39 seconds before REST send. <code>extras_cross_ready</code> failures (ask still ≤50¢ on the REST book) are silent — they do not write a skip row. There is no <code>cross_fav_not_below_dog</code> skip for this game. First taped cross action is send.</p>

<h2>Post-send confirm — it ran on all three</h2>
<ul>
<li><code>{OID_SHIM_T0}</code> BUY_LONG: activities GET qty 1 @ 0.4600. Stored 0.4600. Correct for long.</li>
<li><code>{OID_HSU_T0}</code> BUY_SHORT: activities GET qty 1 @ 0.4500. Stored 0.4500 Yes-wire. Wrong cash (should be 0.5500).</li>
<li><code>{OID_CROSS}</code> BUY_LONG: activities GET empty, then tape <code>cumQuantity 1 @ 0.6000</code>. Stored 0.6000. Correct for long; activities lagged.</li>
</ul>
<p>What is stored: limit as sent, avgPx as Yes-wire, fee from the fill, qty 1. Confirm does not currently map BUY_SHORT to house cash. It did not invent a second fill id.</p>

<h2>Type column</h2>
<p>He named A hard/easy/flatten, B T0 hi/low/cross/leftover, C/D 0.50–0.90, E underdog T0. <code>tools/order_types.py</code> already had those labels. Dashboard Type is in place, display-only, no P&amp;L math. Cached rows for this game: Hsu T0 = <strong>initial Hi lock</strong> (quote 0.55), Shimizu T0 = <strong>initial low lock</strong> (quote 0.46), late Shimizu = <strong>crossover lock</strong>. B T0 hi/low uses <code>quote_price</code> / Yes-ask, not the stored SHORT wire, so Hsu is not labeled “low” from 0.45. <code>orders_performance.html</code> already has an Order type column in the generator; this job did not regenerate that page (the writer refetches settlement). Type on that page waits for the next performance rebuild after he picks a settlement option.</p>

<h2>Other settled Poly B T0 / BUY_SHORT</h2>
{scan}
<p>This job does not rewrite those books. Hsu-shaped (spread &gt; avgPx) is not the Varaksina shape (avgPx already house cash, spread the Yes wire). One field rule will break the other book. Option E copies what Polymarket charged on that fill, per order. Winner inversion is a separate settlement-source bug: ticker <code>result=yes/no</code> vs <code>settlementPx</code>.</p>

<h2>Exact problems</h2>
<ol class="problems">
<li><strong>Winner inverted.</strong> Stored ticker result=yes (Shimizu). ATP + Polymarket settlementPx 0.0000 = Hsu won. Kitchen paid both Shimizu Yes tickets.</li>
<li><strong>BUY_SHORT cash stored as Yes-wire.</strong> Hsu avgPx 0.4500 vs commissionSpreadPx 0.5500. Dashboard 0.46 after fee vs Poly 0.56.</li>
<li><strong>Confirm-after-send used the same Yes-wire.</strong> All three confirms ran. Hsu confirm wrote 0.4500, locking the wrong cash.</li>
<li><strong>Settlement parser ignores settlementPx.</strong> Book stats were available; production fields do not read them.</li>
<li><strong>Dashboard P&amp;L ≠ venue P&amp;L.</strong> +0.4400 vs venue-true −0.6600 (Paul screen −0.6000). Quality is money.</li>
<li><strong>Crossover send is REST-recheck of the T0 dog, not the first 50¢ memory tick.</strong> 52¢ at 00:23:57 became a 63¢ send / 60¢ fill at 00:27:00. No skip tape. Late vs his 12:23 screen, not a skipped name.</li>
<li><strong>Type column was missing</strong> even though order types existed. Fixed this job on the dashboard only.</li>
<li><strong>122 filled Poly BUY_SHORT rows in this stamp:</strong> 60 Hsu-shaped (spread &gt; avgPx), 60 Varaksina-shaped (avgPx &gt; spread), 2 equal. A single-field rewrite would invert half the book. Not rewritten here.</li>
</ol>

<h2>Options + recommendation</h2>
<p>He must be able to choose. Live money code is unchanged until he does.</p>
{options}
<div class="warn">
<p><strong>Recommendation: E = B + C + D.</strong> Venue fill + venue settle as source of truth. Never estimate. For <em>this</em> Hsu fill, cash is <code>commissionSpreadPx</code> 0.5500, not avgPx 0.4500 — but 60 other SHORT fills are the Varaksina shape, so do not globally swap to spread. Copy what Polymarket charged on that order (fill notional / wallet debit / position cost) and what it paid at redeem (<code>settlementPx</code> / POSITION_RESOLUTION). Confirm must not overwrite house cash with Yes-wire. Then Hsu T0 is a win +0.4400, both Shimizu Yes are losses, book −0.6600, and the kitchen matches Polymarket. Display-only (A) is not enough. Do not retune C=1.05, D NFL, leftover GTC, or bump stake to paper over this.</p>
</div>

<h2>Tests added</h2>
<p>Fixture <code>tools/fixtures/shimizu_hsu_poly_20261028.json</code> (recorded venue payloads). Runner <code>tools/test_shimizu_hsu_poly_autopsy.py</code>. Production money code not patched, so venue-truth tests fail today on purpose.</p>
{tests}

<p>Event <code>{EVENT}</code>. Slug <code>{SLUG}</code>. Fill ids {OID_SHIM_T0}, {OID_HSU_T0}, {OID_CROSS}.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
