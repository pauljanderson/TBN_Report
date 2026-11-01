"""Bobichon vs Kelm: Paul's Kalshi/Poly screenshots vs our tape.

Research only. Does not sell, start a second B, commit, print secrets,
wire D NFL, bump stake, or retune B C=1.05.
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
PAGE = STAMP / "bobichon_kelm_venue_reconcile_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/bobichon_kelm_venue_reconcile_20261026.html"
)
AUTOPSY = "tennis_ten_match_autopsy_20261026.html"
GTC = "lock_missed_leg_gtc_20261024.html"
CATALOG = "lock_catalog_verify_row_20261026.html"
BLESSING = "bobichon_kelm_rebuild_blessing_20261026.html"

ASKED = (
    "Paul pasted Kalshi order history (Matisse Bobichon) and a Polymarket “You bought” card "
    "and asked: does this match our tape, and how do we tighten to get more of these A locks. "
    "His read: original buy Yes @49 after-fee turned out 50.75, not in the autopsy after-fee "
    "column. Guess flatten sell 6 min later on Kalshi at 52.75 (screenshot is 52.26 avg — "
    "reconcile). What was the Kelm Yes price we could not get that made us flatten the "
    "Bobichon Yes? Then textbook gap fill: Poly Yes 0.27 + sold Yes Kalshi 49.25. He assumes "
    "sold-Yes = our “buy No”. About 2 min between filling both A legs. Paid off. B made 1.5c, "
    "A made 23.75c. Both great. A execution unusual. Does this match? What can we do to "
    "tighten and guarantee more of these A transactions? Follow-up from the da312d3e tape: "
    "one frozen try — do not rebuild orders.html / orders_performance / opportunities between "
    "the hard IOC and the easy IOC. Rebuild after both attempts. Do not wire leftover GTC, "
    "dual simultaneous, or retune B C=1.05."
)
PLAIN = (
    "Two shops, one tennis match. System B tried to buy both winners on Kalshi at the start "
    "bell. It got Bobichon and missed Kelm, then dumped the leftover by selling Bobichon Yes "
    "(Kalshi’s Yes page shows that as Sold Yes; our send is buy No / ask). System A later "
    "bought “Bobichon wins” on Polymarket and the opposite on Kalshi so one of those two "
    "tickets must pay $1. Paul’s screenshots are the same four tickets. The autopsy’s 49¢ "
    "after-fee was the wire only — Kalshi’s 50.75 already includes the fee. About two minutes "
    "of that A lock was the bot rewriting the order pages after the first fill, which sat on "
    "the second send. That rewrite now waits until both tries are done. We still cannot "
    "guarantee the next fill; this is one row."
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


def _pid_note(pids: dict | None) -> str:
    row = pids if isinstance(pids, dict) else {}
    lock = row.get("lock") or row.get("supervisor") or ""
    b = row.get("b") or row.get("strategy_b") or ""
    bits = []
    if lock:
        bits.append(f"Lock supervisor pid {lock} after reload-lock.")
    if b:
        bits.append(f"One B pid {b} left in place.")
    if bits:
        bits.append("Did not start a second B. Did not sell. lock.net_max stays 0.99.")
    return " ".join(bits)


def write_page(pids: dict | None = None) -> Path:
    map_rows = table(
        [
            ("Paul UI", "text"),
            ("UI time EDT", "date"),
            ("UI avg / cost / fee / limit", "text"),
            ("Our system / step", "text"),
            ("Our send stamp ET", "date"),
            ("HTTP done / Kalshi ts", "date"),
            ("API side / ticker", "text"),
            ("POST fill / fee", "text"),
            ("GET confirm", "text"),
            ("Order id", "text"),
            ("Match?", "text"),
        ],
        [
            [
                esc("Bought Yes Matisse Bobichon"),
                esc("14:40:16"),
                esc("50.75¢ / $0.51 / $0.02 / Limit 60¢ Taker"),
                esc("B / b-t0"),
                esc("14:34:32.035 (quote stamp)"),
                esc("order_io 14:40:18; Kalshi ts_ms → 14:40:16"),
                esc("bid (buy Yes) / BOBKEL-BOB"),
                esc("wire 0.4900 + average_fee_paid 0.0175 = 0.5075"),
                esc("fills GET qty 1.00 @ 0.4900 (no fee in that note)"),
                esc("01a1745d-0680-77c7-820c-bf77357ab3df"),
                esc("Yes — 50.75 is 49¢ + 1.75¢ fee. Autopsy after-fee 0.49 was wrong."),
            ],
            [
                esc("Sold Yes Matisse Bobichon"),
                esc("14:46:03"),
                esc("52.26¢ / $0.52 / $0.02 / Limit 49¢ Taker"),
                esc("B / flatten"),
                esc("14:41:16.536 (quote stamp)"),
                esc("order_io 14:46:05; Kalshi ts_ms → 14:46:03"),
                esc("ask (sell Yes = buy No) / BOBKEL-BOB"),
                esc("Yes-wire 0.5400 + fee 0.0174; No cash 0.46"),
                esc("fills GET qty 1.00 @ 0.4600 (No price = 1 − 0.54)"),
                esc("01a17462-51f8-7a90-bd57-e1ab3ad79b23"),
                esc("Yes — UI Sold Yes 52.26 = 54¢ − 1.74¢ fee. Same ticket as buy No @ 46¢."),
            ],
            [
                esc("Sold Yes Matisse Bobichon"),
                esc("15:33:00"),
                esc("49.25¢ / $0.49 / $0.02 / Limit 34¢ Taker"),
                esc("A / easy"),
                esc("15:31:23.969 (quote stamp)"),
                esc("order_io 15:33:02; Kalshi ts_ms → 15:33:00"),
                esc("ask (sell Yes = buy No) / BOBKEL-BOB"),
                esc("Yes-wire 0.5100 + fee 0.0175; No cash 0.49"),
                esc("fills GET qty 1.00 @ 0.4900"),
                esc("01a1748d-4de0-70ae-ae4c-3ea62b42ef50"),
                esc("Yes — UI 49.25 = 51¢ − 1.75¢. Paul is right that Sold Yes is our buy No."),
            ],
            [
                esc("Poly You bought Matisse Bobichon"),
                esc("3:30 PM"),
                esc("$0.27 @ 26% to win $1"),
                esc("A / hard"),
                esc("15:29:33.438 (quote stamp)"),
                esc("order_io 15:30:05; createTime 15:30:03 ET"),
                esc("BUY_LONG / Yes / aec-atp-matbob-yankel-2026-10-25"),
                esc("confirm cumQuantity 1 @ 0.2600 + $0.01 taker = $0.27"),
                esc("activities GET empty; this-order qty 1 kept"),
                esc("DANGJ0Y011MV"),
                esc("Yes — 26% wire, $0.27 is after the 1¢ Poly taker."),
            ],
        ],
        "Click column headers to sort. Limits uniquely map the three Kalshi rows (60¢ / 49¢ / 34¢). "
        "Kalshi UI Created equals Kalshi ts_ms, not our 14:34 quote stamp. 22 Oct fill-history pull "
        "does not contain these 25 Oct ids; POST average_fee_paid and fills GET on the live confirm are the fee tape.",
    )

    kelm = table(
        [
            ("Clock ET", "date"),
            ("What", "text"),
            ("Number", "text"),
            ("Source", "text"),
        ],
        [
            [
                esc("14:34:30–31"),
                esc("REST both Yes books"),
                esc("BOB ask 0.60 size 12; KEL ask 0.41 size 174"),
                esc("order_io kind=book HTTP 200"),
            ],
            [
                esc("14:34:32.035"),
                esc("B T0 decision / quote stamp (both legs)"),
                esc("all-in C=1.0437 under $1.05. ThreadPool both HTTP."),
                esc("orders.jsonl sent_at; live_strategy_b send_t0_both"),
            ],
            [
                esc("14:35:31"),
                esc("Kelm Yes HTTP 201"),
                esc("bid 0.4100 IOC, fill_count 0.00, remaining cancelled"),
                esc("order_io; order 01a17458-a568-7b46-9326-22fbead76204"),
            ],
            [
                esc("14:35:31"),
                esc("Kelm fills GET"),
                esc("empty → confirm 0. We do not pretend it filled."),
                esc("orders.jsonl confirm_note"),
            ],
            [
                esc("14:40:16–18"),
                esc("Bobichon Yes HTTP 201 (the other T0 thread)"),
                esc("bid 0.6000 filled 0.4900 fee 0.0175"),
                esc("Kalshi UI 14:40:16; order_io 14:40:18"),
            ],
            [
                esc("14:41:16"),
                esc("Flatten book, then send stamp"),
                esc("No ask quoted 0.5100 size 10.10 → POST ask (sell Yes) 0.4900"),
                esc("orders.jsonl flatten; kalshi_order_body no → ask at 1−pay"),
            ],
            [
                esc("14:46:03–05"),
                esc("Flatten HTTP 201"),
                esc("Yes-wire 0.5400 fee 0.0174; GET No 0.4600"),
                esc("Kalshi UI Sold Yes 52.26"),
            ],
        ],
        "Kelm miss vs flatten. The price we could not get is Kelm Yes 41¢. HTTP accepted the order; fill-history qty is 0.",
    )

    gap = table(
        [
            ("Clock ET", "date"),
            ("A lock step", "text"),
            ("Detail", "text"),
        ],
        [
            [
                esc("15:29:26"),
                esc("Trigger"),
                esc("Kalshi Yes websocket 0.3300"),
            ],
            [
                esc("15:29:32–33"),
                esc("Claim + hard-first decision"),
                esc("Poly Yes 0.29 size 58 then easy Kalshi No 0.66 size 21643. Supervisor: hard-first send."),
            ],
            [
                esc("15:30:03–05"),
                esc("Poly HTTP 200"),
                esc("FOK BUY_LONG 0.29. POST executions snapshot still NEW/cumQuantity 0. UI 3:30 PM."),
            ],
            [
                esc("15:30:05 → 15:31:23"),
                esc("Hard confirm + ledger/page"),
                esc("this-order cumQuantity 1 @ 0.2600 (activities GET empty, qty kept). Then _complete_order_post rebuilds orders.html / opportunities.html before the easy IOC leaves. Supervisor “order sent” Poly at 15:31:23."),
            ],
            [
                esc("15:31:23"),
                esc("Easy REST book"),
                esc("Kalshi No quote 0.6600 size 97.33. Limit posted as ask 0.3400 (1 − 0.66)."),
            ],
            [
                esc("15:33:00–02"),
                esc("Kalshi easy HTTP 201"),
                esc("IOC filled immediately at Yes-wire 0.51 (No 0.49), not a 2-minute rest. UI Created 15:33:00."),
            ],
            [
                esc("15:34:19"),
                esc("Supervisor “order sent” Kalshi"),
                esc("Confirm + another page rebuild after the fill."),
            ],
            [
                esc("15:36:39"),
                esc("Both legs filled"),
                esc("True A lock. Later claims skipped over cap or duplicate. No second lock send."),
            ],
        ],
        "Paul’s ~2 min is Poly 3:30 PM vs Kalshi 15:33 Created. That is sequential hard-then-easy plus blocking HTML rebuild, not a GTC leftover and not typical same-second dual IOC.",
    )

    pnl = table(
        [
            ("Book", "text"),
            ("Wire", "text"),
            ("Venue fee", "text"),
            ("All-in", "text"),
            ("Vs $1", "text"),
            ("Paul’s number", "text"),
            ("Who was wrong", "text"),
        ],
        [
            [
                esc("B buy Yes"),
                esc("0.4900"),
                esc("POST average_fee_paid 0.0175 (UI Fees $0.02)"),
                esc("0.5075 = UI 50.75¢"),
                esc(""),
                esc("50.75 after-fee"),
                esc("Autopsy after-fee 0.49 missed the fee. Kalshi UI was right."),
            ],
            [
                esc("B flatten sell Yes / buy No"),
                esc("Yes 0.5400 / No 0.4600"),
                esc("0.0174 (UI $0.02)"),
                esc("No debit 0.4774; UI Sold Yes avg 52.26 = 54 − 1.74"),
                esc(""),
                esc("Guess 52.75; screenshot 52.26"),
                esc("52.26 is 54¢ minus fee. Not 52.75. Same ticket as No @ 46¢."),
            ],
            [
                esc("B round-trip"),
                esc("0.49 + 0.46 = 0.95 → +5¢ before fees"),
                esc("0.0175 + 0.0174 = 0.0349"),
                esc("0.9849"),
                esc("+1.51¢"),
                esc("1.5c; also 50.75 vs 52.26"),
                esc("Both 1.51¢ all-in. Extra $0.02+$0.02 would double-count if 50.75/52.26 already include fees. Not break-even, not negative."),
            ],
            [
                esc("A Poly Yes"),
                esc("0.2600"),
                esc("$0.01 taker (UI $0.27 @ 26%)"),
                esc("0.2700"),
                esc(""),
                esc("$0.27 @ 26%"),
                esc("Match. 0.26 wire, 0.27 after-fee."),
            ],
            [
                esc("A Kalshi No / Sold Yes"),
                esc("Yes 0.5100 / No 0.4900"),
                esc("0.0175"),
                esc("No debit 0.5075; UI Sold Yes 49.25 = 51 − 1.75"),
                esc(""),
                esc("Sold Yes 49.25 as the No cost"),
                esc("49.25 is net proceeds of the sell, not the cash we paid for No."),
            ],
            [
                esc("A lock (hold to $1 one-side payout)"),
                esc("0.26 + 0.49 = 0.75"),
                esc("0.01 + 0.0175 = 0.0275"),
                esc("0.7775"),
                esc("+22.25¢"),
                esc("23.75c = 27 + 49.25"),
                esc("Paul added sell-Yes avg as a cost. Autopsy ~24¢ skipped Kalshi fee. All-in is +22.25¢."),
            ],
        ],
        "Fees from Kalshi POST average_fee_paid and Poly $0.01 taker on the 26¢ fill. Settlement file for 25 Oct was not in the 22 Oct fill-history pull; these are fill+fee vs $1, not an invented winner.",
    )

    tighten = table(
        [
            ("Option", "text"),
            ("Evidence on this row / prior stamps", "text"),
            ("Call", "text"),
        ],
        [
            [
                esc("Leftover GTC at missed easy ask"),
                esc("This A easy filled. GTC would not have changed it. Prior lock one-legs: 15/32 = 46.9% ask came back; cancel-on-resolve still missing. See " + GTC + "."),
                esc("HOLD — already researched. Not wired."),
            ],
            [
                esc("Faster easy-leg after hard fill"),
                esc("Poly HTTP 15:30:05 → easy HTTP 15:33:02. Supervisor hard-first at 15:29:33, Poly “order sent” 15:31:23 after confirm + _complete_order_post page rebuild. Easy still filled because ask 34¢ was through the book. Tiny N=1."),
                esc("Wired this job — hold orders.html / opportunities / orders_performance until after both IOCs (or flatten/abort). Latency bug, not a strategy knob. Does not guarantee the next fill."),
            ],
            [
                esc("Catalog-verify already hands books"),
                esc("This send was websocket trigger + REST recheck at 15:29:33, then hard-first. Catalog verify is a different on-ramp and already live. See " + CATALOG + "."),
                esc("HOLD — already on. Not the 2-minute gap."),
            ],
            [
                esc("Don’t dual simultaneous"),
                esc("A is already sequential hard-first (this row). B T0 is ThreadPool both-Yes: Kelm HTTP 14:35:31 confirm 0, Bobichon HTTP 14:40:18. Intended simultaneous; ledger/page lock serialized them. Kelm miss is a stale 41¢ IOC, not an A miss."),
                esc("HOLD for A (already sequential). Do not retune B C=1.05 from the Kelm miss."),
            ],
            [
                esc("Retune B C=1.05 / bump stake / second B / wire D NFL"),
                esc("Send C=1.0437 was under the freeze. Fees on the fill are a report hole, not a cap hole on this send."),
                esc("HOLD."),
            ],
        ],
        "We cannot guarantee more A locks. One complementary fill with a 34¢ sell-Yes limit is not a horse-race.",
    )

    body = f"""
<h1>Bobichon vs Kelm — venue screenshots vs tape</h1>
<p class="tiny">Stamp drive/paul_experiments/prediction_market_arb_exhaustive_20261017/. Tape: orders.jsonl, order_io.jsonl, live_supervisor.log, live_strategy_b.send_t0_both, live_lock_orders.kalshi_order_body. Fill-history confirm is truth. Did not sell. Did not start a second B. Did not retune C=1.05. {esc(FILE_URL)}</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="verdict">
<p><strong>Match: yes, all four tickets.</strong> Kalshi UI Created times are Kalshi’s <code>ts_ms</code>, not our quote stamps. Sold Yes is buy No: POST <code>side=ask</code>, price = 1 − No pay. After-fee 50.75 is Kalshi right / autopsy wrong (fee omitted). Kelm miss is Yes bid 41¢, HTTP 201, confirm 0. B all-in about <strong>+1.51¢</strong>. A all-in about <strong>+22.25¢</strong> (not 23.75¢). A’s 2 minutes is hard-then-easy plus a blocking page rebuild, not a resting GTC. HOLD leftover GTC and C=1.05. Wired: HTML rebuild waits until after both A IOCs. We cannot guarantee the next one.</p>
</div>

<h2>Portfolio leftover</h2>
<p>The Kalshi card still showing <strong>No: Matisse Bobichon</strong>, 1 share, cost $0.51, avg 50.75¢, $0.00 mark, is the <em>A lock’s Kalshi No</em> (49¢ wire + 1.75¢ fee). B’s Yes was flattened: buy Yes then sell Yes nets to cash, not a leftover Yes. Del Pino vs Leite on the same page still shows both Yes tickets — that is B leftover-Yes, a different match; ignore except as contrast.</p>

<h2>Four screenshot rows vs our tape</h2>
{map_rows}

<h2>Why the autopsy after-fee column said 0.49</h2>
<ul>
<li>Live confirm note is <code>kalshi fills GET qty 1.00 @ 0.4900</code> — price only, no <code>fee_cost</code> copied into that string.</li>
<li>Kalshi POST puts the fee on <code>average_fee_paid</code> (0.0175 / 0.0174 / 0.0175). <code>fee_returned</code> / <code>leg_fee</code> only walk <code>fee_cost</code>, <code>taker_fees</code>, <code>taker_fee_dollars</code>, <code>fees</code>, <code>fee</code> — not <code>average_fee_paid</code>. Kalshi fee on the send tape is stored as 0 unless GET has <code>fee_cost</code>.</li>
<li>The ten-match autopsy generator then hardcoded fee 0 / after-fee = fill px. That is the hole. Same hole can zero Kalshi fees in orders_performance when it uses <code>leg_fee</code> on the POST body. This job fixes the autopsy numbers and this page; it does not change live <code>fee_returned</code> (that would start charging Kalshi fee into the send cap).</li>
</ul>

<h2>Kelm Yes miss — the price that made us flatten</h2>
{kelm}
<p>We posted <strong>buy Yes Kelm at 41¢</strong> (book 0.41, displayed size 174) about 59 seconds after that quote. Kalshi said 201 and <code>fill_count 0.00</code>. Flatten is not a Kelm hedge; it dumps the Bobichon Yes we did get. The 41¢ ask was gone by HTTP time. Dual T0 threads plus ledger/page lock meant Bobichon’s 201 did not land until 14:40:16.</p>

<h2>A lock path — the 2-minute gap</h2>
{gap}
<p>Hard fill then leftover/easy miss then a later fill is <em>not</em> this tape: one easy IOC, attempt 1, filled. Unusual vs same-second dual IOC: yes — freeze is sequential hard-first, and HTML rebuild sat on the easy send. The 34¢ Sold Yes limit (No pay 66¢) was deep through the market, so when it finally posted it still took 51¢ Yes / 49¢ No.</p>

<h2>Follow-up: was that wait a blessing?</h2>
<p>Paul asked whether the blocking <code>orders.html</code> rebuild was a blessing that let us wait and get lucky. Book tape: <strong>not a blessing</strong>. Kalshi REST at 15:29:33 already had Yes bid 34¢ size 21,643 (still 97 at 15:31:23). Immediate easy would have filled at No 66¢ after-fee 67.57¢ — worse than the 15:33 No 49¢ after-fee 50.75¢, but a fill, not a miss. The cheaper 15:33 print is book timing after 15:31:23; websocket is silent 15:29:26–15:38:34 so we cannot show the wait caused the 51¢ bid. Did not add a 2-minute sleep. Detail: <a href="{esc(BLESSING)}">{esc(BLESSING)}</a>.</p>

<h2>P&amp;L with fees</h2>
{pnl}

<h2>Tighten / more A locks</h2>
{tighten}
<p class="note">Prior GTC stamp: <a href="{esc(GTC)}">{esc(GTC)}</a>. Catalog verify: <a href="{esc(CATALOG)}">{esc(CATALOG)}</a>. Ten-match autopsy (fees corrected on this match): <a href="{esc(AUTOPSY)}">{esc(AUTOPSY)}</a>. Rebuild-wait book tape: <a href="{esc(BLESSING)}">{esc(BLESSING)}</a>.</p>

<p class="tiny">Written {esc(datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"))}. {esc(_pid_note(pids))} Research only. Not gold. Not DailyRun. Tiny N=1 complementary A lock.</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Bobichon vs Kelm venue reconcile 26 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 14px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
.verdict {{ background: #f0fdf4; border: 1px solid #86efac; padding: 10px 12px; margin: 8px 0 16px; }}
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
