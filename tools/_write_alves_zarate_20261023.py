"""Meligeni Alves vs Zarate B + lock autopsy HTML. Does not place orders."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "alves_zarate_20261023.html"

ASKED = (
    "Meligini Alves vs Zarate (tennis; spell Meligeni Alves vs Zarate). "
    "1. There were 3 brief points where Zarate went over 50. Did we capture those "
    "and make attempts that failed? 2. Looks like trades were 3 trades trying to "
    "buy the lock gap then sold to flatten. Is that correct? 3. Also: are we making "
    "more on the lock gap, or losing on both (B and lock)?"
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if total:
        cells = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    t0 = table(
        [
            ("Venue", "text"),
            ("Alves Yes ask at/just after T0", "num"),
            ("Zarate Yes ask at/just after T0", "num"),
            ("C (sum)", "num"),
            ("Dog (lower Yes)", "text"),
            ("Favorite", "text"),
            ("B T0 tickets?", "text"),
        ],
        [
            [
                "Kalshi",
                "0.80 then 0.81 at 11:00:02",
                "0.21 at 10:59:45 and 11:00:07",
                "1.01 / 1.02",
                "Carlos Maria Zarate",
                "Felipe Meligeni Alves",
                "Never sent. No watch row. No strategy_b.log line.",
            ],
            [
                "Polymarket US",
                "0.79",
                "0.22",
                "1.01",
                "Carlos Maria Zarate",
                "Felipe Meligeni Alves",
                "Never sent. B venue order prefers Kalshi when C is in band.",
            ],
            [
                "Novig",
                "0.80",
                "0.21",
                "1.01",
                "Carlos Maria Zarate",
                "Felipe Meligeni Alves",
                "Never sent. Novig orders can be live; B still did not arm this title.",
            ],
            [
                "Gemini",
                "—",
                "—",
                "—",
                "—",
                "—",
                "No Gemini market on this match (poller expected=false, 0 messages).",
            ],
        ],
        [
            "Listed T0 11:00 ET",
            "Alves ~80¢",
            "Zarate ~21¢",
            "in [0.95, 1.20]",
            "Zarate",
            "Alves",
            "0 B fills",
        ],
    )

    cross = table(
        [
            ("#", "num"),
            ("Clock ET", "text"),
            ("Venue", "text"),
            ("Zarate Yes last/ask", "num"),
            ("From below?", "text"),
            ("Prev tick", "num"),
            ("Duration", "text"),
            ("B IOC 50-cross?", "text"),
            ("Player / limit / HTTP / confirm qty", "text"),
            ("Denied why", "text"),
        ],
        [
            [
                "P1",
                "13:10:46–13:10:55",
                "Novig then Polymarket",
                "0.63 Novig / 0.52 Poly",
                "Yes",
                "0.46 / 0.50",
                "Novig 9.2s; Poly 0.9s + 0.51 flicker",
                "Never sent",
                "— / — / no POST / 0",
                "No Strategy B ticket on this title. Kalshi did not print Zarate Yes >0.50 here (still 0.45–0.48). B 50-cross would have been Kalshi Zarate, the T0 dog venue. Failed IOC vs never sent: never sent.",
            ],
            [
                "K1",
                "13:17:54–13:18:27",
                "Kalshi (Poly 0.62, Novig 0.645 same burst)",
                "0.60 peak",
                "Yes",
                "0.48",
                "32.9s, 6 Kalshi ticks",
                "Never sent",
                "Zarate Yes / would be live ask ~0.55–0.60 / no POST / 0",
                "Not from a B open match. Watch has no melzar row. Stage was not waiting_cross. Not absorbed-on-this-title. Not wrong-player IOC. B-open 2/2 was Machac (waiting_fav_dip) + Podrez (one-leg from 11:00 until postponed 13:42). Failed IOC vs never sent: never sent.",
            ],
            [
                "K2",
                "13:18:53",
                "Kalshi",
                "0.51",
                "Yes (0.50→0.51 flicker)",
                "0.50",
                "1 tick, 0s",
                "Never sent",
                "— / — / no POST / 0",
                "Brief spike between ticks. Never sent. Same 2/2 + no T0.",
            ],
            [
                "K3",
                "13:20:54–13:21:49",
                "Kalshi (Poly 0.63, Novig 0.735)",
                "0.61 peak",
                "Yes",
                "0.45",
                "54.2s, 10 Kalshi ticks",
                "Never sent",
                "Zarate Yes / ~0.55–0.61 / no POST / 0",
                "Never sent. No B match. Not a failed IOC.",
            ],
            [
                "K4",
                "13:22:44–13:23:54",
                "Kalshi (Poly 0.67, Novig 0.745)",
                "0.64 peak",
                "Yes",
                "0.43",
                "69.4s, 13 Kalshi ticks",
                "Never sent",
                "Zarate Yes / ~0.55–0.64 / no POST / 0",
                "Never sent. Overlaps lock attempt #1 (13:23:55), which is lock-bot Yes+No, not B 50-cross.",
            ],
            [
                "K5",
                "13:25:18–13:25:55",
                "Kalshi (Poly still over from K4 until 13:25:56; Novig 0.745)",
                "0.61 peak",
                "Yes on Kalshi",
                "0.44",
                "36.8s, 14 Kalshi ticks",
                "Never sent",
                "Zarate Yes / ~0.56–0.61 / no POST / 0",
                "Never sent. Fourth Kalshi burst, not only three. After lock #1 flatten.",
            ],
            [
                "after",
                "14:01:17",
                "Kalshi",
                "1.00 ask",
                "N/A (after)",
                "0.01",
                "1 tick",
                "Never sent",
                "— / — / no POST / 0",
                "Phase=after, market finalized. Not an in-play 50-cross. Alves won; Zarate result=no, last 0.01.",
            ],
        ],
        [
            "Tape",
            "13:10–13:29 in-play",
            "Kalshi 5 bursts + Poly/Novig 13:10",
            ">0.50",
            "from below on each burst",
            "≤0.50 between bursts",
            "brief",
            "0 IOCs",
            "confirm qty 0",
            "Never sent, not failed IOC",
        ],
    )

    lock = table(
        [
            ("#", "num"),
            ("Clock ET", "text"),
            ("Intended Yes", "text"),
            ("Intended No", "text"),
            ("Claim net vs 0.984", "text"),
            ("Sent?", "text"),
            ("HTTP + confirm", "text"),
            ("Leftover + flatten", "text"),
            ("Lock P&L with fees", "text"),
        ],
        [
            [
                "g1",
                "12:56:44–12:56:54",
                "Yes Zarate Poly @ 0.27 / Yes Alves Kalshi @ 0.69 (two claims)",
                "No Zarate Kalshi @ 0.69 / No Alves Poly @ 0.27",
                "0.97 then recheck 1.08 / 1.10 > 0.984",
                "Not sent (ghost claim)",
                "No order_io POST. Supervisor skip send gate over cap after book recheck.",
                "Never held",
                "$0.00",
            ],
            [
                "g2",
                "13:08:11–13:08:19",
                "Yes Zarate Kalshi @ 0.23 / Yes Alves Poly @ 0.72",
                "No Zarate Poly @ 0.72 / No Alves Kalshi @ 0.23",
                "0.96 then recheck 1.02 > 0.984",
                "Not sent (ghost claim)",
                "No order_io POST. Supervisor skip send gate over cap after book recheck.",
                "Never held",
                "$0.00",
            ],
            [
                "1",
                "13:23:55–13:25:01",
                "Yes Zarate on Kalshi @ 0.43 (trigger Yes 0.44)",
                "No Zarate on Polymarket @ 0.45 (BUY_LONG Alves Yes 0.45)",
                "0.85 ≤ 0.984",
                "Sent #1 simultaneous IOC",
                "Kalshi POST bid ZAR Yes 0.43 HTTP 201 fill_count 1.00 @ 0.4300 fee 0.0172, GET fill 1.00 @ 0.4300 fee_cost 0.0172 order 01a169ca-7f68-7fdc-af5c-829454a912af. Poly BUY_LONG D9AGJ1WG11MM HTTP 200 then cancel HTTP 200. Poly GET /v1/portfolio/activities HTTP 200 n=0 on slug. Confirm qty Poly 0.",
                "Leftover Kalshi Yes Zarate. Flatten Kalshi ask (Sold Yes = buy No) limit 0.42 / No quote 0.58 HTTP 201 fill 1.00 @ 0.4200 fee 0.0171. GET two prints 0.99+0.01 @ yes 0.42 / no 0.58 fee 0.0169+0.0002. Positions empty.",
                "−$0.0443",
            ],
            [
                "d",
                "13:25:17",
                "Yes Alves on Polymarket @ 0.39",
                "No Alves on Kalshi @ 0.44",
                "claim 0.85; recheck 1.16 > 0.984",
                "Not sent",
                "Denied: over cap after book recheck limit=0.56 other=0.58 gross=1.14 fee=0 other_fee=0.02 net=1.16",
                "—",
                "$0.00",
            ],
            [
                "2",
                "13:33:16–13:34:32",
                "Yes Alves on Polymarket @ 0.74",
                "No Alves on Kalshi @ 0.18 (ask Yes 0.82; trigger Kalshi Yes 0.18)",
                "0.98 ≤ 0.984",
                "Sent #2 simultaneous IOC",
                "Kalshi POST ask MEL HTTP 201 fill_count 1.00 average_fill_price 0.8300 fee 0.0099. GET sell / no / ask 1.00 @ yes 0.83 / no 0.17 fee_cost 0.0099 order 01a169d3-0ae8-7c3e-803a-7323b4bcb8db. Poly BUY_LONG 0.74 D9AMTWSG11N6 HTTP 200 cancel HTTP 200. Poly GET n=0.",
                "Leftover Kalshi No Alves (Sold Yes). Flatten buy Yes MEL bid 0.78 HTTP 201 fill 1.00 @ 0.7700 fee 0.0124. GET buy yes bid 1.00 @ 0.7700 fee 0.0124. Positions empty. Duplicate Zarate-wins claim at 13:33:16 skipped.",
                "+$0.0377",
            ],
            [
                "3",
                "13:39:59–13:41:13",
                "Yes Alves on Kalshi @ 0.66 (fill 0.65; trigger ws Yes 0.36 vs recheck 0.66)",
                "No Alves on Polymarket @ 0.24 (BUY_SHORT API 0.76)",
                "0.92 ≤ 0.984",
                "Sent #3 simultaneous IOC",
                "Kalshi POST bid MEL Yes 0.66 HTTP 201 fill 1.00 @ 0.6500 fee 0.0160 GET same order 01a169d9-3508-72c5-834a-8567b2801e1b. Poly BUY_SHORT D9AQXBVG11MV HTTP 200 cancel HTTP 200. Poly GET n=0.",
                "Leftover Kalshi Yes Alves. Flatten Kalshi ask Sold Yes = buy No limit 0.64 / No quote 0.36 HTTP 201 fill 1.00 @ 0.6400 fee 0.0162 GET sell no ask @ yes 0.64 / no 0.36. Positions empty.",
                "−$0.0422",
            ],
            [
                "later",
                "13:28:50–13:55:49",
                "Several Yes/No looks (see considerations)",
                "Same-settlement opposite",
                "0.93–0.99; some >0.984",
                "Not sent",
                "Missing size; after-fee 0.99 above 0.984; over cap after recheck; Orders stopped after a one-leg fill (latch from other titles, not a fourth send on this match)",
                "—",
                "$0.00",
            ],
        ],
        [
            "3 sent",
            "13:23–13:41",
            "Kalshi filled each time",
            "Poly empty each time",
            "Send only ≤ 0.984",
            "3 gap buys",
            "3 Poly empty cancels; 6 Kalshi GET fills (3 leftover + 3 flatten; ZAR flatten split 0.99+0.01)",
            "3 flatten filled. Confirm: 3-then-flatten.",
            "−$0.0488",
        ],
    )

    pnl = table(
        [
            ("Book", "text"),
            ("Tickets", "text"),
            ("Cash in / out with fees", "text"),
            ("Settlement", "text"),
            ("P&L with fees", "num"),
        ],
        [
            [
                "Strategy B (T0 ± 50-cross ± dip)",
                "0. No T0, no 50-cross, no fav dip.",
                "None",
                "Would have been Alves $1 / Zarate $0 if we had held T0. We did not.",
                "$0.00",
            ],
            [
                "Lock #1 Zarate Yes then flatten",
                "Buy Yes ZAR 0.43 fee 0.0172; sell Yes / buy No 0.42 / 0.58 fee 0.0171",
                "−0.4472 + 0.4029",
                "Flat before finalize. Kalshi positions 0. GET settlements n=0.",
                "−$0.0443",
            ],
            [
                "Lock #2 Alves No then flatten",
                "Sold Yes MEL 0.83 fee 0.0099 (= buy No 0.17); buy Yes 0.77 fee 0.0124",
                "+0.8201 − 0.7824",
                "Flat before finalize.",
                "+$0.0377",
            ],
            [
                "Lock #3 Alves Yes then flatten",
                "Buy Yes MEL 0.65 fee 0.0160; sell Yes / buy No 0.64 / 0.36 fee 0.0162",
                "−0.6660 + 0.6238",
                "Flat before finalize.",
                "−$0.0422",
            ],
            [
                "Lock total",
                "3 Kalshi leftovers + 3 Kalshi flattens. 0 Poly fills. 0 Gemini. 0 Novig.",
                "Venue GET fee_cost on all 7 fill rows (ZAR flatten is 2 rows)",
                "Alves won. Flattened, so winner does not change lock cash.",
                "−$0.0488",
            ],
        ],
        [
            "Combined",
            "B $0 + lock −$0.0488",
            "No B tickets; lock flattened",
            "Winner Felipe Meligeni Alves (Kalshi MEL result=yes, ZAR result=no, HTTP 200 finalized)",
            "−$0.0488",
        ],
    )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meligeni Alves vs Zarate — B 50-cross and lock — 23 Oct 2026</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Felipe Meligeni Alves vs Carlos Maria Zarate — Strategy B and lock bot</h1>
<p class="note">Written {esc(now)}. Times are America/New_York (EDT, UTC−4) on 2026-10-23. Research live. Not gold. Not DailyRun. Did not sell more. Did not GTC. Did not commit. No secrets. No second Strategy B. D stays 0.25. NET_MAX stays 0.984.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>Two different bots can touch the same tennis match. Strategy B, at the first trusted start (T0), tries to buy one Yes on each player (a Yes pays $1 if that man wins). Then it waits for the original underdog — the cheaper Yes at T0 — to print strictly above 50¢ from below, buys one more of him, then buys the original favorite only when those two extra tickets still lock about 25¢. Live D is 0.25. Size 1. Immediate or Cancel, not Good Till Cancel. After the Trungelliti fix, favorite/dog uses frozen Yes asks, not fill prices, and if the dog is already over 50¢ at T0 it waits for a down-print first.</p>
<p>The lock bot is separate. It tries to buy Yes on one venue and No on the other on the same man when the two prices plus fees are at or under 98.4¢, so the pair pays $1. If only one leg fills, it flattens: on Kalshi, selling Yes is the same cash as buying No. It is not Strategy B.</p>
<p>This page answers three things with venue fills, the lock look log, and in-match ticks: whether we tried those Zarate-over-50 moments; whether the three trades were gap-buys that then flattened; and whether lock is making money or both books are losing.</p>
</div>

<div class="callout warn">
<h2>Verdict</h2>
<ul>
<li><strong>Three Zarate &gt;50 moments — attempted or not?</strong> The tape captured them, plus more than three. Kalshi (the venue B would have used) has five in-play from-below bursts over 50¢, the three longest at 13:17:54 (peak 0.60, 33s), 13:20:54 (peak 0.61, 54s), and 13:22:44 (peak 0.64, 69s), then a fourth at 13:25:18 (peak 0.61, 37s). Novig/Poly also printed a 13:10:46 spike Kalshi never showed. <strong>We did not send a Strategy B 50-cross IOC on any of them.</strong> Not a failed IOC. Never sent. There is no B watch row, no <code>strategy_b.log</code> line, and no B fill on this title.</li>
<li><strong>Why never sent:</strong> B never bought T0 both-Yes here, so it was never in <code>waiting_cross</code>. Listed T0 is 11:00. Dog would have been Zarate (Kalshi Yes 0.21 vs Alves 0.80; C=1.01, in band, dog already below 50 so no wait-down-print). At 11:00 the two B slots were already full: Machac vs Khachanov <code>waiting_fav_dip</code>, and Podrez vs Zavatska T0-one-leg from 11:00:09 until postponed 13:42:06. Max open is 2. After 11:05 the T0 window is missed. When Podrez freed a slot at 13:42, Debru vs Arutiunian took it — not this match.</li>
<li><strong>Lock 3-then-flatten:</strong> <strong>Yes.</strong> Three simultaneous 1-contract IOC sends (13:23:55 Zarate Yes Kalshi + No Poly; 13:33:16 Alves No Kalshi + Yes Poly; 13:39:59 Alves Yes Kalshi + No Poly). Kalshi filled each time (HTTP 201, GET qty 1.00). Polymarket was empty each time (HTTP 200 then cancel HTTP 200; GET activities n=0). Each leftover was flattened on Kalshi (Sold Yes = buy No when the leftover was Yes; leftover No on #2 was covered by buying Yes). Positions empty. Earlier 12:56 and 13:08 claims never posted (recheck over 0.984).</li>
<li><strong>Making more on lock, or losing on both?</strong> Booked Strategy B is <strong>$0.00</strong> (no tickets — not a loss, not a win). Lock with Kalshi GET fees is <strong>−$0.0488</strong>. Combined <strong>−$0.0488</strong>. Cash prices without fees would have been about +4¢ on the three flattens; taker fees flipped lock to a small loss. We are <strong>not making more on lock</strong>. We are <strong>not losing on B</strong> either. Lock lost; B did not play. Winner: Meligeni Alves (Kalshi MEL <code>result=yes</code>, ZAR <code>result=no</code>, both finalized). Flattened, so the winner does not change lock cash.</li>
</ul>
</div>

<h2>Strategy B T0 — who is the dog</h2>
<p class="note">Listed start 11:00:00 ET (scheduled sports clock). First in-match Yes tick 11:00:02 Kalshi Alves 0.81, phase=during. Dog = lower T0 Yes ask, frozen at T0, not the live lead. Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{t0}

<h2>Zarate last/ask prints &gt; 0.50 — did B 50-cross?</h2>
<p class="note">In-match change-ticks from local tennis.jsonl. A burst is consecutive Yes asks &gt;0.50; it ends when the venue prints ≤0.50 again. B would 50-cross only the T0 dog (Zarate) on the T0 venue (Kalshi), from below, only if this title were open. Live B PID 37840. Click headers to sort.</p>
{SWIPE_NOTE_HTML}
{cross}
<p class="note">Novig flickered through 0.50 twenty-one times (many 0-second 0.505 prints). Those are captured; they are not B sends. B does not 50-cross Novig unless T0 was Novig. T0 here was never taken.</p>

<h2>Lock bot — every send on this title</h2>
<p class="note">NET_MAX 0.984. Size 1. IOC. Kalshi Sold Yes = buy No on flatten. Poly confirm is GET /v1/portfolio/activities on slug <code>aec-atp-felalv-carzar-2026-10-23</code> HTTP 200 n=0. Kalshi confirm is GET /trade-api/v2/portfolio/fills HTTP 200 n=7 (ZAR flatten split into 0.99+0.01). Click headers to sort.</p>
{SWIPE_NOTE_HTML}
{lock}

<h2>Combined P&amp;L with fees</h2>
<p class="note">B dollars are booked fills only. Missed 50-crosses are not booked as a loss. Lock cash uses Kalshi GET <code>yes_price_dollars</code> and <code>fee_cost</code>. Sell Yes receives the Yes price minus fee. Buy Yes pays Yes price plus fee.</p>
{SWIPE_NOTE_HTML}
{pnl}

<h2>What this is not</h2>
<ul>
<li>Not a failed Zarate 50-cross IOC. Zero B POSTs on KXATPCHALLENGERMATCH-26OCT23MELZAR and on the Poly slug.</li>
<li>Not three true locks. Three one-leg Kalshi fills, three Poly misses, three Kalshi flattens.</li>
<li>Not a second Strategy B, not a D change, not a NET_MAX change, not a GTC, not a new sell.</li>
<li>Ledger line “−$0.95 (win)” on lock #2 is wrong for flatten cash. Venue math is +3.77¢ with fees. This page uses venue fills.</li>
</ul>

<p class="note">Sources: Kalshi GET /trade-api/v2/portfolio/fills HTTP 200 n=7 on MEL/ZAR, GET positions 0, GET settlements 0, GET /trade-api/v2/markets HTTP 200 MEL result=yes last 0.99, ZAR result=no last 0.01, both finalized; Polymarket US GET /v1/portfolio/activities HTTP 200 n=0 and positions 0; Gemini POST /v1/prediction-markets/orders/history n_match=0; Novig GET /v3/portfolio/fills n=0. Local order_io.jsonl 6 POSTs (3 leftover + 3 flatten) + 3 Poly empty cancels; orders.jsonl claim/sent/filled/flatten_filled/skip; considerations.json 17 rows (3 sent, 14 denied); live_supervisor.log simultaneous send + flatten + skip gate; strategy_b.log 0 lines; strategy_b_watch.json no melzar row, currently_open Machac, Podrez postponed_at 13:42:06; price_memory 2026-10-23 tennis.jsonl; live_jobs tennis_melzar listed 11:00. Pulled {esc(now)}. No second Strategy B. D=0.25. NET_MAX=0.984. No GTC. No secrets. Did not sell.</p>

{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html_out, encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
