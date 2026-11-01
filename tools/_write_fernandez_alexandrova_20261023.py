"""Fernandez vs Alexandrova Strategy B autopsy HTML. Does not place orders."""
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
PAGE = STAMP / "fernandez_alexandrova_20261023.html"

ASKED = (
    "Fernandez vs Alexandrova, textbook Strategy B. 4:01 AM Yes Alexandrova 76.32c, "
    "Yes Fernandez 27c. 4:40 AM crossover Yes Fernandez 53.75c. 4:51 AM dip Yes "
    "Alexandrova 23.21c. Spent $1.80, guaranteed payout $2 → +$0.20. Without the dip "
    "they would have made 43c instead of 20c. Concern: live D=0.25 should guarantee "
    "at least 25c, they got 20c, Kalshi report 19c. Fees wrong? Anything we can do better?"
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
    fills = table(
        [
            ("Ticket", "text"),
            ("Player", "text"),
            ("Venue", "text"),
            ("Side", "text"),
            ("Qty", "num"),
            ("Wire", "num"),
            ("Fee", "num"),
            ("All-in", "num"),
            ("Limit sent", "num"),
            ("Order id", "text"),
            ("Sent ET", "date"),
            ("Venue fill ET", "date"),
            ("Source", "text"),
        ],
        [
            [
                "T0 favorite",
                "Ekaterina Alexandrova",
                "Kalshi",
                "Yes bid",
                "1",
                "0.7500",
                "0.0132",
                "0.7632",
                "0.7500",
                "01a167c7-73d8-7880-85c5-c8bfe0390cfe",
                "2026-10-23 04:01:23.951",
                "2026-10-23 04:01:27.730",
                "b-t0. GET fee_cost 0.013200 = POST average_fee_paid. Paul 76.32c is this all-in.",
            ],
            [
                "T0 dog",
                "Leylah Fernandez",
                "Kalshi",
                "Yes bid",
                "1",
                "0.2600",
                "0.0135",
                "0.2735",
                "0.2600",
                "01a167c7-8760-7288-9d02-bbcd2a99a148",
                "2026-10-23 04:01:23.976",
                "2026-10-23 04:01:32.740",
                "b-t0. GET fee_cost 0.013500. Paul 27c is this 27.35c all-in, rounded.",
            ],
            [
                "50-cross extra dog",
                "Leylah Fernandez",
                "Kalshi",
                "Yes bid",
                "1",
                "0.5200",
                "0.0175",
                "0.5375",
                "0.5200",
                "01a167eb-7e68-7317-99a5-e3fb2a317ea4",
                "2026-10-23 04:40:45.242",
                "2026-10-23 04:40:49.384",
                "b-cross. GET yes 0.5200. Paul 53.75c is wire plus fee. Watch stored cross_fill 0.52, cross_fee 0.",
            ],
            [
                "Favorite dip",
                "Ekaterina Alexandrova",
                "Kalshi",
                "Yes bid",
                "1",
                "0.2200",
                "0.0121",
                "0.2321",
                "0.2300",
                "01a167f5-3e80-7a9e-b93d-a95e45e35612",
                "2026-10-23 04:51:24.513",
                "2026-10-23 04:51:28.744",
                "b-fav. Sent 0.23, GET filled 0.22. Paul 23.21c is 0.22 + 0.0121. Watch fill_fee 0.",
            ],
        ],
        [
            "Whole book",
            "2 Yes Fernandez + 2 Yes Alexandrova",
            "Kalshi",
            "Yes×4",
            "4",
            "1.7500",
            "0.0563",
            "1.8063",
            "—",
            "four tickets, no fifth",
            "04:01–04:51",
            "settled Yes Fernandez",
            "Payout $2.00. GET P&amp;L +19.37c. Paul +20c. Kalshi 19c.",
        ],
    )
    waterfall = table(
        [
            ("Step", "text"),
            ("Cents", "num"),
            ("Running lock", "num"),
            ("What it is", "text"),
        ],
        [
            [
                "D=25 identity Paul expected",
                "+25.00",
                "25.00",
                "Extra-pair lock of 25c, treating T0 as a $1 pair. Live D is that extra-pair lock, not a whole-book all-in floor.",
            ],
            [
                "T0 wire vig (C − 1)",
                "−1.00",
                "24.00",
                "T0 Yes asks 0.75 + 0.26 = 1.01. Watch C=1.01. Legal in [0.95, 1.20].",
            ],
            [
                "Extra pair wire vs 0.75",
                "+1.00",
                "25.00",
                "Cross 0.52 + dip fill 0.22 = 0.74. One cent cheaper than 1 − D because the 0.23 limit filled at 0.22.",
            ],
            [
                "Kalshi taker fee T0 Alexandrova",
                "−1.32",
                "23.68",
                "GET fee_cost 0.013200. POST average_fee_paid 0.0132.",
            ],
            [
                "Kalshi taker fee T0 Fernandez",
                "−1.35",
                "22.33",
                "GET fee_cost 0.013500. POST 0.0135.",
            ],
            [
                "Kalshi taker fee 50-cross Fernandez",
                "−1.75",
                "20.58",
                "GET fee_cost 0.017500. POST 0.0175. This is the extra-pair fee live B stored as cross_fee 0.",
            ],
            [
                "Kalshi taker fee favorite dip Alexandrova",
                "−1.21",
                "19.37",
                "GET fee_cost 0.012100. POST 0.0121. Watch stored fill_fee 0.",
            ],
            [
                "Kalshi statement 19c",
                "−0.37 display",
                "19.00",
                "2.00 − 1.8063 = 0.1937. Two-decimal dollars print as $0.19. Not a fifth ticket. Positions GET empty after settlement.",
            ],
            [
                "Paul +20c / $1.80 spent",
                "+0.63 vs 19.37 display",
                "20.00",
                "He rounded the $1.8063 bill to $1.80, then $2 − $1.80. Same four fills.",
            ],
        ],
        [
            "GET cash P&amp;L",
            "+19.37",
            "19.37",
            "No extra Kalshi fee beyond the four fee_cost rows. Fees on GET match POST exactly.",
        ],
    )
    skip = table(
        [
            ("Book", "text"),
            ("Tickets", "text"),
            ("All-in cost", "num"),
            ("If Fernandez wins", "num"),
            ("If Alexandrova wins", "num"),
            ("This match (Fernandez won)", "num"),
        ],
        [
            [
                "Live B with the dip (what we did)",
                "2 Yes Fernandez + 2 Yes Alexandrova",
                "1.8063",
                "+0.1937",
                "+0.1937",
                "+0.1937 locked",
            ],
            [
                "Skip the dip after the 50-cross",
                "2 Yes Fernandez + 1 Yes Alexandrova",
                "1.5742",
                "+0.4258 (~43c)",
                "−0.5742 (~−57c)",
                "+0.4258 because Fernandez won",
            ],
            [
                "T0 only (no cross, no dip)",
                "1 Yes each",
                "1.0367",
                "−0.0367",
                "−0.0367",
                "−0.0367 (always $1 payout)",
            ],
        ],
    )
    books = table(
        [
            ("When", "date"),
            ("Venue", "text"),
            ("Yes Fernandez", "num"),
            ("Yes Alexandrova", "num"),
            ("Wire C / that ask", "num"),
            ("Legal B send then?", "text"),
            ("Cheapest?", "text"),
            ("Seen ET", "date"),
        ],
        [
            [
                "T0 04:01",
                "Kalshi",
                "0.26",
                "0.75",
                "1.01 (all-in 1.0367)",
                "Yes — this is the pair we sent",
                "Tied on wire with Polymarket. Kalshi first in VENUE_ORDER.",
                "2026-10-23 04:01:18.538 (recheck 04:01:23.851)",
            ],
            [
                "T0 04:01",
                "Polymarket US",
                "0.26",
                "0.75",
                "1.01 (est. all-in ~1.03, 1¢+1¢ taker)",
                "Yes, same-venue both-Yes. Not picked: C tie, Kalshi first.",
                "Same wire as Kalshi. Slightly cheaper all-in. GET activities 0 fills.",
                "2026-10-23 04:01:18.570",
            ],
            [
                "T0 04:01",
                "Novig",
                "0.26",
                "0.71",
                "0.97",
                "No. B did not send Novig until ~08:30 ET. PID at this T0 had Kalshi / Gemini / Polymarket only.",
                "Cheapest wire pair at T0. GET /v3/portfolio/fills 0 rows.",
                "2026-10-23 04:01:17.816 / 04:01:18.005",
            ],
            [
                "T0 04:01",
                "Gemini",
                "—",
                "—",
                "—",
                "No market. live_jobs gemini {}.",
                "—",
                "—",
            ],
            [
                "50-cross 04:40",
                "Kalshi",
                "0.52",
                "0.49",
                "Fernandez ask 0.52",
                "Yes — extra dog Yes. GET filled 0.52.",
                "Tied 0.52 with Polymarket and Novig.",
                "2026-10-23 04:40:43.669 (quote 04:40:45.125)",
            ],
            [
                "50-cross 04:40",
                "Polymarket US",
                "0.52",
                "0.49",
                "Fernandez ask 0.52",
                "Same wire. Not sent (already on Kalshi).",
                "Tied.",
                "2026-10-23 04:40:43.560",
            ],
            [
                "50-cross 04:40",
                "Novig",
                "0.52",
                "0.4850",
                "Fernandez ask 0.52",
                "Not a B send venue yet.",
                "Tied on the Fernandez ask we needed.",
                "2026-10-23 04:40:43.560",
            ],
            [
                "Dip 04:51",
                "Kalshi",
                "0.79",
                "0.23",
                "Alexandrova ask 0.23; GET fill 0.22",
                "Yes — ask 0.23 equals fav_target 0.23. Sent 0.23 IOC.",
                "Tied with Polymarket on the 0.23 ask.",
                "2026-10-23 04:51:23.640 (quote 04:51:24.404)",
            ],
            [
                "Dip 04:51",
                "Polymarket US",
                "0.78",
                "0.23",
                "Alexandrova ask 0.23",
                "Same wire. Not sent.",
                "Tied on the dip ask.",
                "2026-10-23 04:51:23.997",
            ],
            [
                "Dip 04:51",
                "Novig",
                "0.79",
                "0.2150",
                "Alexandrova ask 0.2150",
                "Not a B send venue yet. GET fills 0.",
                "Cheapest dip ask. 1.5c under Kalshi’s 0.23.",
                "2026-10-23 04:51:24.732 (0.7s after send)",
            ],
        ],
    )
    cap = table(
        [
            ("Rule", "text"),
            ("Number", "num"),
            ("This book", "text"),
        ],
        [
            [
                "Live wire cap: 1 − cross_fill − 0.25",
                "0.23",
                "cross_fill on the watch is 0.52 (GET wire 0.52). Target 0.23. Send limit 0.23. Not above the cap.",
            ],
            [
                "GET dip fill (wire)",
                "0.22",
                "Under the 0.23 cap. Confirm note: qty 1.00 @ 0.2200.",
            ],
            [
                "Paul’s all-in cross 0.5375 → 1 − 0.5375 − 0.25",
                "0.2125",
                "That is the fee-aware cap. Live B does not use all-in cross. 0.5375 is 0.52 + 0.0175 fee.",
            ],
            [
                "GET dip all-in",
                "0.2321",
                "Above 0.2125. Extra pair all-in 0.5375 + 0.2321 = 0.7696 vs 0.75. That is the leak, not a wire-cap miss.",
            ],
            [
                "extra_pair_net_ok on what B stored",
                "0.75",
                "0.52 + 0.23 + cross_fee 0 + Kalshi fav_fee 0 = 0.75. Allowed. POST average_fee_paid is not in fee_returned keys.",
            ],
        ],
    )
    d25 = table(
        [
            ("Slice", "text"),
            ("N", "num"),
            ("Note", "text"),
        ],
        [
            ["Frozen dense tennis books", "182", "Same freeze as D=25 / t0_plus_50_cross stamps. All OOS."],
            ["Settled", "119", "counts.json 2026-10-23 10:11 ET."],
            ["50-cross so a dip target existed", "76", "63.9% of settled."],
            ["Dip filled (third ticket)", "46", "60.5% of those 76. 38.7% of settled."],
            ["Dipped player (original favorite) then won", "3", "Lost 43, void 0."],
        ],
    )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fernandez vs Alexandrova Strategy B — 23 Oct 2026</title>
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
<h1>Leylah Fernandez vs Ekaterina Alexandrova — Strategy B</h1>
<p class="note">Written {esc(now)}. Times are America/New_York (EDT, UTC−4) on 2026-10-23 unless marked UTC. Research live. Not gold. Not DailyRun. One contract. No sells. No second Strategy B. D stays 0.25. No GTC. No secrets.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A Yes ticket pays $1 if that tennis player wins. Strategy B at the first trusted serve (T0) buys one Yes on each player if the two prices add up to something in the 95¢–$1.20 band. Then it waits for the original underdog (the cheaper Yes at T0) to print strictly above 50¢, buys one more of that underdog, then buys one more of the original favorite only when those two extra tickets still lock about 25¢. Live D is 0.25. Size is 1. Immediate or Cancel, not Good Till Cancel.</p>
<p>This match did the whole path: T0 both Yes, Fernandez through 50¢, then Alexandrova cheap enough on the wire. Fernandez won. You made about 20¢ on $1.80 spent. You asked why that is not 25¢, why Kalshi shows 19¢, and whether skipping the last ticket would have been better.</p>
</div>

<div class="callout ok">
<h2>Paul: disagree skip-dip as a rule. The 25¢ became 19.37¢ because Kalshi fees were ignored on the extra pair, not because the dip broke 1 − cross − 0.25 on the wire.</h2>
<ul>
<li><strong>Winner:</strong> Leylah Fernandez. Kalshi markets finalized: FER <code>result=yes</code>, ALE <code>result=no</code>. Four Kalshi Yes tickets, GET <code>/trade-api/v2/portfolio/fills</code> HTTP 200, n=4, all four order ids match. Polymarket, Gemini, Novig fills on this match: 0.</li>
<li><strong>Skip-dip:</strong> Disagree as a standing rule. Without the dip you hold 2× Fernandez + 1× Alexandrova. Because Fernandez won, that book pays <strong>+42.58¢</strong> (~your 43¢). If Alexandrova had won it pays <strong>−57.42¢</strong>. The dip locks ~19¢ either way. D=25 history on the frozen dense book: dip filled 46 times; the dipped player (original favorite) then won 3 and lost 43.</li>
<li><strong>Did 23.21¢ violate 1 − cross − 0.25?</strong> No on the live wire rule. Cross fill is 52¢, target 23¢, send 23¢, GET fill 22¢. Your 53.75¢ and 23.21¢ are all-in (wire plus Kalshi taker fee). All-in extra pair 76.96¢ vs 75¢ — that is the fee leak, not a send above the written wire cap.</li>
<li><strong>Cents that ate the 25¢:</strong> T0 wire vig 1.00¢, extra-pair wire 1.00¢ cheap (dip filled 22¢ not 23¢) so wire still 25.00¢, then four Kalshi fees 1.32 + 1.35 + 1.75 + 1.21 = 5.63¢ → <strong>+19.37¢</strong>.</li>
<li><strong>Kalshi 19¢ vs our 20¢:</strong> Same four fills. GET cash is $2.00 − $1.8063 = 19.37¢. Kalshi’s two-decimal line prints 19¢. Your $1.80 bill is 1.8063 rounded, then $2 − $1.80 = 20¢. No fifth ticket. GET <code>fee_cost</code> matches POST <code>average_fee_paid</code> on every row.</li>
<li><strong>One better, not a silent live change:</strong> Fee-aware dip. Send the favorite only if all-in cross + dip ≤ 0.75 (parse <code>average_fee_paid</code> / GET <code>fee_cost</code>, or subtract the known Kalshi taker formula). Keep the T0 C band on Yes asks [0.95, 1.20]. Do not retune C to all-in ≤ 1.00 this job (that would have skipped this T0 and Moutet). D stays 0.25. Not wired.</li>
</ul>
</div>

<h2>The four tickets</h2>
<p class="note">Click column headers to sort. Wire is GET <code>yes_price_dollars</code>. Fee is GET <code>fee_cost</code> (same as POST <code>average_fee_paid</code>). All-in is wire plus fee. Every fill is taker, qty 1.00, side yes, action buy.</p>
{SWIPE_NOTE_HTML}
{fills}

<h2>Fee waterfall: 25¢ → 20¢ → 19¢</h2>
<p class="note">Live D is a 25¢ lock on the extra post-cross pair, not a 25¢ all-in floor on the whole book. T0 C=1.01 already spends a penny versus $1. The extra pair on the wire was 74¢ (one cent better than 75¢). Fees then take 5.63¢.</p>
{SWIPE_NOTE_HTML}
{waterfall}

<h2>Did the dip break 1 − cross − 0.25?</h2>
<p>No, on the written live wire rule. Watch: <code>cross_fill=0.52</code>, <code>fav_target=0.23</code>, last_order pay 0.2300. GET filled 0.2200. 0.22 ≤ 0.23. Paul’s 0.5375 is the cross all-in; 1 − 0.5375 − 0.25 = 0.2125 is the fee-aware cap the bot does not use. Dip all-in 0.2321 is over that fee-aware cap and under the wire cap.</p>
{SWIPE_NOTE_HTML}
{cap}
<p>The freeze text says “after a fee recheck that keeps that extra pair a 25-cent lock.” The helper <code>extra_pair_net_ok</code> exists. For Kalshi, <code>leg_fee</code> is zero unless the payload contains <code>fee_cost</code> / <code>fee</code> / <code>taker_fees</code>. The POST puts the fee on <code>average_fee_paid</code>, which that walker does not read. Watch stored <code>cross_fee 0</code> and T0 <code>fill_fee 0</code>. So the recheck is a no-op on Kalshi. 0.52 + 0.23 + 0 + 0 = 0.75, send. All-in extra pair 0.7696. That is the 25¢ → 19¢ leak on the extra pair. It is not a dip sent above 1 − cross_fill − D.</p>

<h2>Without the dip</h2>
<p>That book is winner-dependent. This time the original dog won, so skip-dip looks better. Do not take that as a rule. On the 46 filled dips in D=25 history, the dipped player then won only 3 times. Skip-dip would have been the +43¢ world on the other 43, and about −57¢ on those 3. The dip is what locks the extra pair.</p>
{SWIPE_NOTE_HTML}
{skip}

<h2>D=25 history (dip filled, then who won)</h2>
<p class="note">From <code>drive/paul_experiments/strategy_b_D25_dip_come_back_win_20261023/counts.json</code>, written 2026-10-23 10:11 ET. Not this match’s P&amp;L. Primary dollars on that stamp are with fees.</p>
{SWIPE_NOTE_HTML}
{d25}

<h2>Were Kalshi prices the cheapest?</h2>
<p>At T0 the Yes asks were 26¢ / 75¢ on Kalshi and Polymarket (wire C=1.01). Novig printed Alexandrova at 71¢, wire C=0.97, but Strategy B could not send Novig until ~08:30 ET. Gemini had no market. At the 50-cross, Fernandez was 52¢ on Kalshi, Polymarket, and Novig. At the dip, Kalshi and Polymarket asked 23¢; Novig asked 21.50¢ a fraction of a second after the send. Kalshi filled 22¢. No other venue has a fill on this match.</p>
{SWIPE_NOTE_HTML}
{books}

<h2>Recommendation (research only — not wired)</h2>
<ul>
<li><strong>Do this next if you want the extra pair to stay a 25¢ all-in lock:</strong> fee-aware dip. Do not send unless all-in cross + dip ≤ 0.75. Concretely: persist GET <code>fee_cost</code> or POST <code>average_fee_paid</code> into <code>cross_fee</code>, and size the favorite from that, or reduce the dip limit by the known Kalshi taker fee <code>0.07 × p × (1 − p)</code>. This job does not edit live B. D stays 0.25.</li>
<li><strong>Do not silently tighten T0 to all-in C ≤ 1.00.</strong> T0 C band is on Yes asks, not all-in. This book was 1.01 asks / 1.0367 all-in. Moutet vs Paul was 1.01 asks / 1.0352 all-in. An all-in C ≤ 1.00 rule would have skipped both. Keep [0.95, 1.20] unless you want fewer T0s, not just a cleaner extra pair.</li>
<li><strong>Not a wire this turn.</strong> Dip was not sent above 1 − cross_fill − 0.25. The fee recheck failed to see Kalshi’s fee field. Report plus this proposal. No second Strategy B. No GTC. No sell.</li>
</ul>

<p class="note">Sources: Kalshi GET /trade-api/v2/portfolio/fills (HTTP 200, four fills on FER/ALE, all four order ids), GET /trade-api/v2/portfolio/positions (0 rows after settlement), GET /trade-api/v2/markets (FER result yes, ALE result no, status finalized); Polymarket US GET /v1/portfolio/activities and positions (0); Gemini POST /v1/prediction-markets/orders/history (0 match); Novig GET /v3/portfolio/fills (0). Local order_io.jsonl, orders.jsonl, strategy_b.log, strategy_b_watch.json, price_memory tennis.jsonl, live_jobs tennis_ferale. D=25 counts from strategy_b_D25_dip_come_back_win_20261023. Pulled {esc(now)}. No second Strategy B. D=0.25. No GTC. No secrets.</p>

{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html_out, encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
