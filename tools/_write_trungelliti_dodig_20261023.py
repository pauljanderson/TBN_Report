"""Trungelliti vs Dodig Strategy B autopsy HTML. Does not place orders."""
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
PAGE = STAMP / "trungelliti_dodig_20261023.html"

ASKED = (
    "At 5:03 on Polymarket: Yes Trungelliti at 0.43, Yes Dodig at 0.63, then another "
    "Yes Dodig at 0.63 also at 5:03 — why the duplicate? During the game Trungelliti "
    "surpassed Dodig. We should have bought Yes Dodig around 0.51. Dodig also fell "
    "below 0.51 − 0.25 = 0.26. Had we bought Trungelliti at 0.51 or above, we would "
    "have bought another Yes Dodig at that low price. That should have netted ~$0.25 "
    "and instead they lost $0.63 because of the duplicate and missing later buys."
)
ASKED_FOLLOWUP = (
    "WHY did we 50-cross the wrong player (Dodig at 0.61, 5:03:51 IOC filled) instead of "
    "waiting for Trungelliti > 0.50? What makes sure that never happens again? WHY did we "
    "not try Trungelliti > 0.50 at 5:19 (and not try Dodig ≤ 0.23 later)? What makes sure "
    "that doesn't happen again? Please fix the code."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


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
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def main(b_pid: str = "", checked: str = "") -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    b_pid = b_pid or "see job_status"
    checked = checked or now
    chrono = table(
        [
            ("Time ET", "date"),
            ("Venue", "text"),
            ("Side", "text"),
            ("Price / cash", "num"),
            ("Qty", "num"),
            ("HTTP", "num"),
            ("Confirm", "text"),
            ("Reason", "text"),
        ],
        [
            [
                "2026-10-23 05:00:00",
                "listed",
                "match start",
                "",
                "",
                "",
                "",
                "Trusted clock 05:00:00 ET (seconds=00). T0 window 5 minutes. America/New_York, UTC−4.",
            ],
            [
                "2026-10-23 05:03:24.118",
                "Strategy B",
                "open match",
                "C quotes 1.02",
                "",
                "",
                "",
                "PID 12236 (started 22 Oct 23:51 ET). Game key tennis_01a1602ead877e239640734d, title Matej Dodig @ Marco Trungelliti Quarterfinals. Stage waiting_t0 then fire. MAX_OPEN_B had a free slot. Latch ignored. Novig not a B send venue yet.",
            ],
            [
                "2026-10-23 05:03:24.636",
                "Polymarket US book",
                "Yes Trungelliti / Yes Dodig",
                "0.41 / 0.61",
                "1 / 1",
                "",
                "recheck=book",
                "IOC limits set from this book. Same Yes asks on Kalshi and Novig at this second. Gemini had no market.",
            ],
            [
                "2026-10-23 05:03:24.734",
                "Polymarket US",
                "Yes Marco Trungelliti BUY_LONG",
                "limit 0.41",
                "1",
                "200",
                "qty 1.0000 @ 0.4100 (tape 1, match)",
                "T0 both-Yes, order D93BC89011N2, TIME_IN_FORCE_IMMEDIATE_OR_CANCEL. Venue fill 05:03:29.319 UTC+0 = 05:03:29 ET, qty 1, wire 0.41, cost 0.43 (fee 0.02).",
            ],
            [
                "2026-10-23 05:03:24.765",
                "Polymarket US",
                "Yes Matej Dodig BUY_SHORT",
                "Yes 0.61 / wire limit 0.39",
                "1",
                "200",
                "qty 2.0000 @ 0.4100 (tape 1, mismatch — bug)",
                "T0 other Yes, order D93BDNCG11TB, IOC. Venue fill 05:03:35.092 UTC+0, qty 1, wire 0.39, cost 0.63. Confirm summed Trungelliti+Dodig on the slug.",
            ],
            [
                "2026-10-23 05:03:42 / 05:03:48",
                "strategy_b.log",
                "T0 posts logged",
                "",
                "",
                "200 / 200",
                "after GET /v1/portfolio/activities",
                "Log stamps are after venue confirm (~18s), not a second process.",
            ],
            [
                "2026-10-23 05:03:51.500",
                "Polymarket US",
                "Yes Matej Dodig BUY_SHORT (b-cross)",
                "Yes 0.61 / wire 0.39",
                "1",
                "200",
                "qty 2.0000 @ 0.4100 (tape 1, mismatch)",
                "False 50-cross. Bot had labeled Dodig the dog because fill_px on both legs was 0.41. Dodig Yes ask was already 0.61 &gt; 0.50, so it bought another Dodig immediately. Order D93BJMM091KJ, IOC.",
            ],
            [
                "2026-10-23 05:03:55.475 UTC+0 = 05:03:55 ET",
                "Polymarket US venue",
                "Yes Matej Dodig BUY_SHORT fill",
                "cost 0.63",
                "1",
                "",
                "trade D93BJMMG51KR aggressor D93BJMM091KJ",
                "This is Paul’s second 0.63 ticket. Not a double fill of one HTTP. Not extra-Yes-on-dip. Not two B processes.",
            ],
            [
                "2026-10-23 05:19:31",
                "Polymarket US tape",
                "Yes Marco Trungelliti",
                "0.52",
                "",
                "",
                "no IOC",
                "First live original-dog print &gt; 0.50. Live B should have IOCd extra Trungelliti here, then waited for original-favorite Dodig at 1−0.52−0.25 = 0.23. Never sent.",
            ],
            [
                "2026-10-23 06:04:51 / 06:05:04",
                "Kalshi / Polymarket",
                "Yes Matej Dodig",
                "0.26",
                "",
                "",
                "no IOC",
                "Dodig Yes ≤ 0.26. Live target after a 0.52 cross is 0.23, so 0.26 is still 3¢ too high; Dodig later printed 0.01. No favorite-dip IOC was armed — B was already absorbed after the false cross.",
            ],
            [
                "2026-10-23 06:35–06:39",
                "Polymarket US",
                "settlement window",
                "Trungelliti last 0.99 / Dodig 0.01",
                "",
                "",
                "positions GET 0 rows",
                "Market endDate 2026-10-23T10:39:51Z (06:39 ET). Trungelliti won. GET /v1/portfolio/positions no longer lists the slug.",
            ],
        ],
    )
    books = table(
        [
            ("Venue", "text"),
            ("Yes Trungelliti", "num"),
            ("Yes Dodig", "num"),
            ("C (sum)", "num"),
            ("On B send list at 5:03?", "text"),
            ("What B did", "text"),
        ],
        [
            ["Kalshi", "0.41", "0.61", "1.02", "Yes (first in VENUE_ORDER)", "Not sent. B opened the Novig-titled duplicate event without this Kalshi ticker."],
            ["Gemini", "—", "—", "—", "Yes, but no market", "live_health expected.gemini=false. History 0 rows on this match."],
            ["Polymarket US", "0.41", "0.61", "1.02", "Yes", "Sent. All-in cost 0.43 + 0.63 after 2¢ fees. Paul UI 0.43 / 0.63 is cost, not the raw Yes ask."],
            ["Novig", "0.41", "0.61", "1.02", "No (added ~08:30 ET, PID 30456)", "Quoted, never sent. GET /v3/portfolio/fills 0 rows. PID at 5:03 was 12236, Kalshi/Gemini/Poly only."],
        ],
    )
    cross = table(
        [
            ("When ET", "date"),
            ("What live B requires", "text"),
            ("Tried?", "text"),
            ("Market", "text"),
            ("Limit", "text"),
            ("IOC vs GTC", "text"),
            ("Fill / miss", "text"),
            ("Deny / why", "text"),
        ],
        [
            [
                "05:03:51",
                "Wrong: extra original-dog Yes after dog &gt; 0.50. Dog was really Trungelliti 0.41, not Dodig 0.61.",
                "Yes, but on the wrong player",
                "Polymarket aec-atp-martru-matdod-2026-10-23",
                "Yes Dodig 0.61 (wire 0.39)",
                "IOC",
                "Fill 1, cost 0.63",
                "Favorite/dog inverted from BUY_SHORT fill_px 0.41. Stored C=0.82. Immediate cross because “dog” already &gt; 0.50.",
            ],
            [
                "05:19:31",
                "Actual: original dog Trungelliti Yes &gt; 0.50, then extra Trungelliti Yes (one IOC).",
                "No",
                "Polymarket (also Kalshi 0.53 at 05:19:34)",
                "would have been ~0.52",
                "would be IOC",
                "not sent",
                "Stage was waiting_fav_dip on Trungelliti as fake favorite, then absorbed at 0.94. Extra-Yes-on-dip is DISMISS and was not wired.",
            ],
            [
                "06:04:51 onward",
                "Actual: original favorite Dodig at ≤ 1−cross−0.25 (0.23 if cross=0.52). Paul said 0.51−0.25=0.26.",
                "No",
                "Kalshi 0.26 then Poly 0.26; later 0.01",
                "≤0.23 live / 0.26 in Paul’s wording",
                "would be IOC",
                "not sent",
                "Never armed. B note: absorbed after cross; no fav dip. Did not try “buy Dodig at 0.51” either.",
            ],
            [
                "never",
                "Paul’s wording “buy Yes Dodig around 0.51” after Trungelliti surpassed him",
                "No",
                "—",
                "0.51 Dodig",
                "—",
                "not sent",
                "Live B does not buy the new dog at 0.51. It buys extra original-dog (Trungelliti) when he prints &gt; 0.50, then original-favorite Dodig cheap (≈0.24).",
            ],
        ],
    )
    pnl = table(
        [
            ("Book", "text"),
            ("Tickets", "text"),
            ("All-in cost (venue cost)", "num"),
            ("Pays if Trungelliti wins", "num"),
            ("Pays if Dodig wins", "num"),
            ("Net if Trungelliti wins", "num"),
        ],
        [
            ["Actual (venue)", "1× Yes Trungelliti + 2× Yes Dodig", "1.69 (0.43+0.63+0.63)", "1.00", "2.00", "−0.69"],
            ["Actual without fees", "same three fills", "1.63 (0.41+0.61+0.61)", "1.00", "2.00", "−0.63"],
            ["Intended T0 only", "1× Trungelliti + 1× Dodig", "~1.06 Poly all-in / 1.02 Kalshi", "1.00", "1.00", "−0.06 Poly / −0.02 Kalshi"],
            ["Intended live extras", "T0 both + extra Trungelliti ~0.52 + extra Dodig ≤0.23", "T0 ~1.06 + extra pair ≤0.75", "2.00", "2.00", "T0 vig loss plus extra-pair +0.25 before fees"],
        ],
    )
    guards = table(
        [
            ("Guard now in live_strategy_b.py", "text"),
            ("What it stops", "text"),
            ("Trungelliti check", "text"),
        ],
        [
            [
                "Favorite/dog/C from frozen T0 <code>yes_ask</code> only. Never <code>fill_px</code>, never Polymarket BUY_SHORT Yes-wire 1−p.",
                "Labeling Dodig the dog because both fills printed 0.41.",
                "T0 Yes 0.41 / 0.61 → dog=Trungelliti, favorite=Dodig, C=1.02 even if Dodig fill_px is 0.41 and fee all-in is 0.63.",
            ],
            [
                "50-cross IOC only on the T0 dog, first time that dog’s Yes goes through 0.50 from below. If the T0 dog is already &gt;0.50, wait for a print ≤0.50 then the next up-cross. Refuse if the spec is the T0 favorite.",
                "Immediate extra Yes Dodig at 0.61 because the mislabeled “dog” was already above 50¢.",
                "After T0, Dodig still 0.61 does not send. Trungelliti 0.52 at 5:19 arms <code>b-cross</code> on Trungelliti.",
            ],
            [
                "Favorite dip arms only after a 50-cross on the T0 dog. Target is 1 − cross_fill − 0.25. A false favorite-cross is rewound to waiting-dog-cross; not marked absorbed. Do not sell.",
                "Stage stuck on waiting_fav_dip / “absorbed after cross,” so the real dog never gets an IOC and Dodig ≤0.23 never arms.",
                "False Dodig 0.61 extra is rewound. Trungelliti 0.52 then sets fav dip at 0.23 for Dodig.",
            ],
            [
                "Polymarket confirm keeps only trades whose aggressor order id is this IOC. No order id → qty 0, never sum both seats on the slug.",
                "Dodig T0 confirm qty 2 @ 0.41 (Trungelliti fill + Dodig fill).",
                "Each of D93BC89011N2 / D93BDNCG11TB / D93BJMM091KJ confirms qty 1.",
            ],
        ],
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trungelliti vs Dodig autopsy — 23 Oct 2026</title>
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
<h1>Marco Trungelliti vs Matej Dodig — Strategy B autopsy</h1>
<p class="note">Written {esc(now)}. Times are America/New_York (EDT, UTC−4) on 2026-10-23 unless marked UTC. Research live. Not gold. Not DailyRun. One contract. No sells. No second Strategy B. No secrets.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<p>{esc(ASKED_FOLLOWUP)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A Yes ticket pays $1 if that tennis player wins. Strategy B at the first trusted serve (T0) buys one Yes on each player if the two prices add up to something in the 95¢–$1.20 band. Then it waits for the <strong>original underdog</strong> (the cheaper Yes at T0) to print strictly above 50¢, buys one more of that underdog, then buys one more of the <strong>original favorite</strong> only when he is cheap enough that those two extra tickets still lock in 25¢. Live D is 0.25. Size is 1. Orders are Immediate or Cancel (fill now or cancel), not Good Till Cancel. Extra-Yes-on-dip is dismissed and is not wired.</p>
<p>If T0 was Dodig 0.61 Yes ask / 0.63 all-in (favorite) and Trungelliti 0.41 / 0.43 (dog), the 50-cross is <strong>Trungelliti above 50¢</strong>, then buy <strong>Dodig</strong> at 1 − 0.52 − 0.25 = 0.23 — not “buy Dodig at 0.51.” Buying Dodig at 0.51 would be treating him as the dog after the lead changed. Live B does not do that.</p>
<p>What we actually did: at 5:03 AM ET we bought Yes Trungelliti (Polymarket cost 0.43) and Yes Dodig (cost 0.63), then 27 seconds later bought a <strong>second</strong> Yes Dodig (cost 0.63) because the bot thought Dodig was the underdog. Trungelliti later did print above 50¢ (5:19), and Dodig later printed 0.26 then 0.01. We did not buy those. Trungelliti won. The extra Dodig ticket paid $0.</p>
<p>This page is the autopsy plus the code fix. D=0.25, max two open B matches, size 1, IOC, no sells, one Strategy B process. Live B PID {esc(b_pid)}. Status Checked {esc(checked)}.</p>
</div>

<div class="callout warn">
<h2>Verdict</h2>
<ul>
<li><strong>Were 0.43 / 0.63 the best Yes asks across venues?</strong> No. Those are Polymarket <em>all-in costs</em> (0.41 + 2¢ fee, 0.61 + 2¢ fee). The Yes asks at 5:03:24 ET were <strong>0.41 / 0.61 on Kalshi, Novig, and Polymarket</strong>. Gemini had no market. No venue was cheaper on the raw Yes. Kalshi has no 2¢ taker fee, so Kalshi was the better T0; B did not send Kalshi because it opened a duplicate Novig-titled event that only had Polymarket legs.</li>
<li><strong>Why the duplicate Dodig?</strong> Two HTTP IOCs, two venue fills — not one fill shown twice, not inventory netting, not two B processes (only PID 12236), not extra-Yes-on-dip. T0 Yes Dodig filled, then a false 50-cross bought another Yes Dodig at the same 0.61 because favorite/dog was inverted from Polymarket BUY_SHORT <code>fill_px</code>.</li>
<li><strong>Did we try the live 50-cross / favorite dip?</strong> We tried a 50-cross IOC at 5:03:51, but on the wrong player (Dodig at 0.61, IOC, filled). We did not try Trungelliti &gt; 0.50 at 5:19, and we did not try Dodig ≤ 0.23 later. We did not try “buy Dodig at 0.51.”</li>
<li><strong>P&amp;L:</strong> Venue costs 0.43 + 0.63 + 0.63 = <strong>$1.69</strong>. Trungelliti won (Poly last 0.99 / 0.01, market end 06:39 ET), so payout $1.00, net <strong>−$0.69</strong>. Your −$0.63 is the extra Dodig ticket (or the three wires 0.41+0.61+0.61 minus $1, fees omitted). Intended extra-pair lock is about +$0.25 before T0 vig, not what we got.</li>
<li><strong>Bugs fixed in code (not committed):</strong> T0 favorite/dog/C uses frozen Yes asks, not BUY_SHORT wire <code>fill_px</code>. 50-cross is only the T0 dog, from below. A false favorite-cross is rewound so the real dog can still fire. Polymarket confirm is this order’s aggressor id only. Regression replay is in <code>tools/test_live_strategy_b.py</code>. Live B reloaded after this fix; PID {esc(b_pid)}.</li>
</ul>
</div>

<h2>Why the wrong player, and what the code now does</h2>
<p><strong>Why Dodig at 0.61, not a wait for Trungelliti &gt; 0.50.</strong> After T0 both filled, favorite/dog was taken from <code>fill_px</code>. Trungelliti BUY_LONG filled at Yes 0.41. Dodig was BUY_SHORT; his Yes ask was 0.61 but <code>fill_px</code> stored 0.41 (Yes-wire / confirm last-price from the other seat on the slug). 0.41 ≥ 0.41 labeled Trungelliti the favorite and Dodig the dog. Stored C=0.82. The next tick rechecked the “dog” — Dodig — still 0.61 &gt; 0.50 and sent <code>b-cross</code> IOC D93BJMM091KJ, filled.</p>
<p><strong>What makes sure that never happens again.</strong> <code>yes_ask</code> is frozen from the book at send. <code>fill_px</code> is stored separately and is never used to name favorite/dog or C. Every open tick re-labels from those T0 Yes asks. <code>maybe_cross</code> will not send if the spec is the T0 favorite. If the T0 dog is already above 50¢, B waits for a down-print then the next up-cross — it does not buy extra immediately.</p>
<p><strong>Why Trungelliti &gt; 0.50 at 5:19 never fired (and Dodig ≤ 0.23 never armed).</strong> The false Dodig 50-cross moved the match to waiting_fav_dip (fake favorite = Trungelliti, target 1−0.61−0.25=0.14). <code>maybe_cross</code> only runs in the waiting-50-cross stages, so Trungelliti 0.52 at 5:19:31 never got an IOC. The real favorite dip (Dodig at 1−0.52−0.25=0.23) was never armed. Later the note became “absorbed after cross.” Extra-Yes-on-dip is dismissed and was not wired.</p>
<p><strong>What makes sure that doesn't happen again.</strong> A 50-cross must be on the T0 dog before the favorite dip is armed. If a stored match already has a false favorite-cross, live code rewinds it to waiting for the T0 dog and does not mark absorbed. It does not sell the extra favorite Yes. Replay test: T0 0.41/0.61, BUY_SHORT Dodig fill_px 0.41 → dog=Trungelliti, no immediate Dodig IOC, Trungelliti 0.52 arms the 50-cross, then Dodig dip at 0.23.</p>
{SWIPE_NOTE_HTML}
{guards}

<h2>Chronology</h2>
<p class="note">Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{chrono}

<h2>Other-venue Yes book at 5:03</h2>
{SWIPE_NOTE_HTML}
{books}

<h2>50-cross and favorite-dip attempts</h2>
{SWIPE_NOTE_HTML}
{cross}

<h2>P&amp;L actual vs intended</h2>
{SWIPE_NOTE_HTML}
{pnl}

<h2>Duplicate root cause</h2>
<p>After T0 both filled, <code>mark_t0_results</code> set favorite/dog from <code>fill_px</code>. Trungelliti BUY_LONG fill was 0.41. Dodig BUY_SHORT fill_px was also 0.41 — either the Yes-wire 0.39 rounded/polluted by confirm last-price 0.41 from the Trungelliti trade. 0.41 ≥ 0.41 labeled Trungelliti favorite and Dodig dog. Stored C = 0.82. The next tick rechecked the “dog” (Dodig) Yes ask still 0.61 &gt; 0.50 and sent <code>b-cross</code>.</p>
<p>Confirm GET /v1/portfolio/activities had no order-id filter. It summed every recent TRADE on <code>aec-atp-martru-matdod-2026-10-23</code>, so the Dodig T0 confirm said qty 2 @ 0.41 (Trungelliti 1 + Dodig 1). Tape qty was 1 on each HTTP. Venue aggressor ids match the three order ids: D93BC89011N2, D93BDNCG11TB, D93BJMM091KJ. Three posts, three fills.</p>
<p>Not the cause: MAX_OPEN_B 2/2 (this match opened), <code>orders_stopped</code> latch (B ignores it), postponed, mid-game T0 block, extra-Yes-on-dip, a second <code>live_strategy_b.py</code>, or GTC (all three were IOC).</p>

<h2>Live Strategy B vs Paul’s wording</h2>
<p>Live freeze (unchanged D=0.25, NET_MAX untouched): T0 both-Yes, C in [0.95, 1.20], each Yes in (0.10, 0.90), only near a trusted start. Then original dog Yes &gt; 0.50, then original favorite at 1 − cross_fill − 0.25. SIZE=1. MAX_OPEN_B_MATCHES=2. Extra-Yes-on-dip DISMISS. IOC. Venue confirm qty ≥ 1 is fill truth. B may send Novig as of ~08:30 ET PID 30456; at 5:03 B was PID 12236, Kalshi / Gemini / Polymarket only.</p>
<p>Paul’s “buy Dodig at 0.51” after Trungelliti surpassed him is the new-dog read. Live B would have bought extra <strong>Trungelliti</strong> at 0.52, then <strong>Dodig</strong> at about 0.23. The 0.26 print is the right <em>idea</em> for that dip; the live cap after a 0.52 cross is 0.23, and Dodig did trade through that later (0.01).</p>

<p class="note">Sources: Polymarket US GET /v1/portfolio/activities (3 TRADE rows, aggressor order ids), GET /v1/portfolio/positions (0 rows after settlement); Kalshi GET /trade-api/v2/portfolio/fills (0 on KXATPCHALLENGERMATCH-26OCT23TRUDOD); Gemini POST /v1/prediction-markets/orders/history (0 on this match); Novig GET /v3/portfolio/fills (0). Local strategy_b.log, strategy_b_watch.json, orders.jsonl, order_io.jsonl, price_memory tennis ticks. Code: live_strategy_b.py, venue_fill_confirm.py. Tests: test_live_strategy_b.py, test_venue_fill_confirm.py.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8")
    print("wrote", PAGE)


if __name__ == "__main__":
    b_pid = ""
    checked = ""
    try:
        import prediction_job_control

        snap = prediction_job_control.snapshot()
        row = snap.get("strategy_b") or {}
        b_pid = str((row or {}).get("pid") or "")
        checked = str(snap.get("checked") or "")
    except Exception:
        pass
    main(b_pid=b_pid, checked=checked)
