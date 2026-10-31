"""Eala vs Shnaider + Pohankova missed-send autopsy. Display only. No live orders."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from report_page_extras import FORCE_RELOAD_SCRIPT, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML
from write_orders_performance import table

ET = ZoneInfo("America/New_York")
STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "eala_shnaider_pohankova_autopsy_20261030.html"
FIXTURE = Path("tools/fixtures/eala_shnaider_pohankova_20261030.json")


def d4(x) -> str:
    return f"{Decimal(str(x)):.4f}"


def money(x) -> str:
    v = Decimal(str(x))
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.4f}"


def main() -> None:
    blob = json.loads(FIXTURE.read_text(encoding="utf-8"))
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    ui = blob["kalshi_ui"]
    misses = table(
        [
            ("When ET", "date"),
            ("Match", "text"),
            ("Step", "text"),
            ("Venue", "text"),
            ("Side", "text"),
            ("REST quote", "num"),
            ("Limit", "num"),
            ("Ask size at recheck", "num"),
            ("Lag s", "num"),
            ("HTTP", "text"),
            ("Confirm qty", "num"),
            ("Confirm note", "text"),
            ("Why fill 0", "text"),
        ],
        [
            [
                "2026-10-30 01:38:00",
                "Pohankova vs Parks",
                "hard (initial lock)",
                "polymarket",
                "Yes Mia Pohankova",
                d4("0.680"),
                d4("0.680"),
                d4("17625.7300"),
                d4("0.205"),
                "200",
                d4("0"),
                "polymarket activities GET empty",
                "Fill-or-kill (FOK). Book printed 17k at REST; 0.2s later FOK killed with fill 0. Then hard_miss_abort — no easy leg, no leftover.",
            ],
            [
                "2026-10-30 06:47:20",
                "Eala vs Shnaider",
                "easy (second lock leg)",
                "polymarket",
                "Yes Alexandra Eala",
                d4("0.130"),
                d4("0.130"),
                d4("13592.1000"),
                d4("0.205"),
                "200",
                d4("0"),
                "polymarket activities GET empty",
                "FOK. Hard Kalshi No already filled. Easy Poly 13¢ vanished between REST recheck and send. Not a ticket.",
            ],
            [
                "2026-10-30 06:54:45",
                "Eala vs Shnaider",
                "hard (NEW lock after flatten)",
                "polymarket",
                "Yes Alexandra Eala",
                d4("0.070"),
                d4("0.070"),
                d4("8950.0000"),
                d4("0.247"),
                "200",
                d4("0"),
                "polymarket activities GET empty",
                "FOK on a new gap. Flatten had already closed the 06:47 one-leg, so A stayed on. Not leftover-GTC. hard_miss_abort.",
            ],
        ],
    )
    kalshi = table(
        [
            ("When ET", "date"),
            ("Kitchen row", "text"),
            ("Kalshi action", "text"),
            ("Order id", "text"),
            ("Trade px (not all-in)", "num"),
            ("Fee", "num"),
            ("After-fee / Kalshi statement", "num"),
            ("Kalshi UI line", "text"),
            ("Kitchen if directional (Eala lost)", "num"),
            ("Venue flatten book", "num"),
        ],
        [
            [
                "2026-10-30 06:47:18",
                "initial lock No Alexandra Eala",
                "sell Yes / buy No",
                "01a18c6b-cef0-71b6-96e9-466e5a1a4dbb",
                d4("0.8300"),
                d4("0.0099"),
                d4("0.8399"),
                "Sold Yes 16.01¢ Limit 17¢ Taker ($0.16 + $0.01 fee)",
                money("0.1601"),
                money("0"),
            ],
            [
                "2026-10-30 06:47:21",
                "flatten Yes Alexandra Eala",
                "buy Yes",
                "01a18c6b-d6c0-7c80-a026-11d74753c8e5",
                d4("0.1800"),
                d4("0.0104"),
                d4("0.1904"),
                "Bought Yes 19.04¢ Limit 18¢ Taker ($0.19 + $0.01 fee)",
                money("-0.1904"),
                money("-0.0303"),
            ],
        ],
        [
            "Kalshi round-trip (sold Yes 16.01, bought Yes 19.04)",
            "",
            "buy + sell same ticker",
            "",
            "",
            d4("0.0203"),
            d4("1.0303"),
            "lost ~3¢ on the pair",
            money("-0.0303"),
            money("-0.0303"),
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Eala vs Shnaider missed send + Kalshi flatten autopsy 2026-10-30</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.ok {{ background: #ecfdf3; border: 1px solid #86efac; padding: 12px 16px; margin: 16px 0; }}
.bad {{ background: #fdecec; border: 1px solid #e8b4b4; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
.swipe-note {{ color: #555; font-size: 0.95em; }}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Eala vs Shnaider + Pohankova vs Parks — missed send and Kalshi −3¢</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}.
Did not commit. Did not start a second B. Did not leftover-GTC on A. Did not retune. Did not DailyRun.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Today's kitchen rows are mostly missed sends. Explain what missed send means and why it happens.
Also Kalshi shows they lost ~3 cents on Eala/Shnaider while kitchen may disagree. Why the discrepancy,
and why are we not verifying/validating with the platform after settlement date/time? Tighten this up.</p>
<h2>In plain English</h2>
<p>A missed send is: we posted an order, the venue said HTTP OK, and then confirmed it filled
<strong>zero</strong> contracts. There is no ticket and no win or loss. That is normal for Polymarket
fill-or-kill (FOK) when the cheap ask disappears in the fraction of a second between our REST recheck
and the send. The three Poly rows today (Pohankova 68¢, Eala 13¢, Eala 7¢) are that — not a kitchen
bug. The Kalshi −3¢ is a different story: we bought No Eala, the Poly lock leg missed, so we flattened
by buying Yes Eala on Kalshi. Sold Yes at 16.01¢ all-in and bought Yes at 19.04¢ all-in is a closed
round-trip of <strong>−3.03¢</strong> no matter who won the match. Kitchen had marked both Kalshi
fills “settled” with a blank P&amp;L because it was waiting on a match winner instead of booking the
flatten the way Kalshi’s statement already does. After a flatten (or after a game settles) we now
pull Kalshi fills and Poly activities and overwrite kitchen to that venue number.</p>
</div>

<div class="ok">
<p><strong>Missed send</strong> = HTTP 200 (Poly) or 201 (Kalshi) and confirm fill qty 0. No ticket.
Typical for Poly FOK on a thin ask that vanished between REST recheck and send. Confirm lives on
<code>GET /v1/portfolio/activities</code> TRADE rows (GET <code>/v1/orders/{{id}}</code> is often 404).
Empty activities = fill 0. House fill is still 1 contract; a real 0.02 leftover is a ticket, fill 0 is not.</p>
</div>

<h2>The three Poly misses</h2>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{misses}
<ul>
<li><strong>Pohankova 68¢ (01:38:00)</strong> — hard leg Yes Pohankova FOK fill 0. Activities empty.
Quote still 68¢ with 17k size 0.205s earlier. Price moved or the ask was gone at send. Then
<code>hard_miss_abort</code>: no Kalshi easy leg, no leftover. Polymarket later expired
<code>settlementPx=1.0000</code> (Pohankova won). We did not have a ticket.</li>
<li><strong>Eala 13¢ (06:47:20)</strong> — easy second lock after Kalshi No filled. Same FOK pattern
(0.205s lag, activities empty). This miss is why we flattened.</li>
<li><strong>Eala 7¢ (06:54:45)</strong> — a <em>new</em> lock attempt seven minutes after flatten
filled. A stays on after a successful flatten (the leftover latch is only written when flatten also
misses). New gap, Poly FOK miss, <code>hard_miss_abort</code>. Not leftover-GTC. Not an incorrect
re-arm of the closed one-leg.</li>
</ul>

<h2>Why Kalshi shows −3¢ and kitchen disagreed</h2>
{SWIPE_NOTE_HTML}
{kalshi}
<p>Sequence: 06:47:18 buy Kalshi No Eala at 83¢ + 0.99¢ fee = <strong>83.99¢ all-in</strong>
(Kalshi UI: Sold Yes 16.01¢ = 100 − 83.99). 06:47:20 Poly lock miss. 06:47:21 flatten buy Kalshi Yes
at 18¢ + 1.04¢ fee = <strong>19.04¢ all-in</strong>. Round-trip: 16.01 − 19.04 = <strong>−3.03¢</strong>.
Fees are inside those all-in numbers; do not add the two 1¢ fee lines on top.</p>
<p>If kitchen instead settled each ticket on “who won”: Poly Yes-Eala <code>settlementPx=0</code>
(Eala lost) would pay No +16.01¢ and charge Yes −19.04¢, which still nets −3.03¢ but looks like a
big win and a big loss. Kitchen actually showed <strong>settled with blank P&amp;L</strong> because
the Kalshi market was still <code>active</code> (no winner yet) and the settle reconciler only
pulled Polymarket slugs. Flatten cash is known the moment Yes+No both fill — we do not need the
match to finish.</p>

<h2>What we changed</h2>
<ul>
<li><code>tools/live_pm_settle_reconcile.py</code> now pulls Kalshi fills (no 120s window), Poly
activities, and Gemini/Novig when those venues have tickets. After a flatten or a settled market it
overwrites kitchen to venue qty / all-in cash / net P&amp;L.</li>
<li>A Kalshi buy+sell (or kitchen <code>step=flatten</code>) on the same ticker books
<strong>venue net P&amp;L</strong> on the flatten close (−3.03¢) and $0 on the origin. It will not
later rewrite those two tickets as independent directional win/lose.</li>
<li>House cash is the contract price (18¢ / 83¢). After-fee is the Kalshi statement (19.04 / 83.99).
If a feed hands 19.04 plus a 1.04 fee, we split — we do not store 19.04 and then add the fee again.</li>
<li>Poly fill 0 stays a missed send, never a ticket. Tests:
<code>tools/test_eala_shnaider_pohankova_autopsy.py</code>.</li>
</ul>

<p>Kitchen scoreboard: <a href="dashboard.html">dashboard.html</a> (no What you asked). Performance:
<a href="orders_performance.html">orders_performance.html</a>.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    _ = ui
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
