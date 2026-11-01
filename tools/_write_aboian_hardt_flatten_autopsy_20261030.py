"""Aboian vs Hardt Kalshi flatten vs opportunities Poly/Kalshi log. Display only."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import opportunity_considerations as oc
from report_page_extras import FORCE_RELOAD_SCRIPT, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML
from write_orders_performance import table

ET = ZoneInfo("America/New_York")
STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "aboian_hardt_flatten_autopsy_20261030.html"
FIXTURE = Path("tools/fixtures/aboian_hardt_flatten_20261030.json")


def d4(x) -> str:
    return f"{Decimal(str(x)):.4f}"


def money(x) -> str:
    v = Decimal(str(x))
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.4f}"


def main() -> None:
    blob = json.loads(FIXTURE.read_text(encoding="utf-8"))
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    venues_now = oc.venues_label(blob["consider_row"])
    kitchen = table(
        [
            ("When ET", "date"),
            ("What kitchen showed", "text"),
            ("Venue", "text"),
            ("Side / step", "text"),
            ("HTTP", "text"),
            ("Confirm qty", "num"),
            ("Confirm px", "num"),
            ("After-fee", "num"),
            ("On the book now?", "text"),
        ],
        [
            [
                "2026-10-30 18:49:56",
                "Kalshi No Aboian (Sold Yes = buy No). Poly confirm qty 0 — not listed.",
                "kalshi",
                "No Valerio Aboian (Sold Yes = buy No)",
                "201",
                d4("1"),
                d4("0.6400"),
                d4("0.6562"),
                "No — flattened 5s later",
            ],
            [
                "2026-10-30 18:50:01",
                "Flatten Bought Yes on Kalshi. Poly still confirm qty 0 — not listed.",
                "kalshi",
                "Yes Valerio Aboian (flatten Bought Yes)",
                "201",
                d4("1"),
                d4("0.3600"),
                d4("0.3762"),
                "No — Yes+No cancel",
            ],
            [
                "2026-10-30 19:05:57",
                "Later new gap: Yes Hardt on Poly FOK",
                "polymarket",
                "Yes Nick Hardt (hard)",
                "200",
                d4("0"),
                d4("0.1500"),
                "",
                "Never a ticket",
            ],
        ],
        [
            "Round-trip",
            "Kalshi Yes+No on KXATPCHALLENGERMATCH-26OCT30ABOHAR-ABO",
            "kalshi only",
            "flatten filled",
            "",
            d4("2"),
            "",
            d4("1.0324"),
            "−$0.0324 (no position)",
        ],
    )
    ui_map = table(
        [
            ("When ET", "date"),
            ("Kalshi UI", "text"),
            ("Kitchen / API", "text"),
            ("Math", "text"),
        ],
        [
            [
                "2026-10-30 18:49:56",
                "Sold Yes 34.38¢ limit 36¢",
                "buy No @ 0.6400 qty 1, after-fee 0.6562, Yes-wire limit 0.36",
                "1 − 0.6562 = 0.3438. Delay vs confirm is OK.",
            ],
            [
                "2026-10-30 18:49:59",
                "Bought Yes 37.62¢ limit 36¢",
                "flatten buy Yes @ 0.3600 qty 1, after-fee 0.3762, limit 0.36",
                "0.3600 + 0.0162 fee = 0.3762. UI ~2s before kitchen stamp 18:50:01.",
            ],
        ],
    )
    venue = table(
        [
            ("Platform", "text"),
            ("Endpoint", "text"),
            ("Instrument", "text"),
            ("Rows", "num"),
            ("Qty still held", "num"),
            ("What that means", "text"),
        ],
        [
            [
                "Kalshi",
                "GET /trade-api/v2/portfolio/fills",
                blob["kalshi_ticker"],
                "2",
                d4("0"),
                "action=sell side=no @ 0.64 qty 1 (Sold Yes 34.38c all-in, limit 36c) then action=buy side=yes @ 0.36 qty 1 (Bought Yes 37.62c all-in, limit 36c). Real fills. Positions empty.",
            ],
            [
                "Kalshi",
                "GET /trade-api/v2/portfolio/positions",
                blob["kalshi_ticker"],
                "0",
                d4("0"),
                "Empty. Yes+No both filled = net zero. Not in Open now.",
            ],
            [
                "Polymarket US",
                "GET /v1/portfolio/activities TRADE",
                blob["poly_slug"],
                "0",
                d4("0"),
                "Empty. GET /v1/orders/{id} is often 404; activities is the fill read. Order DDZK92R012VC is HTTP 200 fill 0.",
            ],
            [
                "Polymarket US",
                "GET /v1/portfolio/positions",
                blob["poly_slug"],
                "0",
                d4("0"),
                "No Aboian/Hardt row. Eagles Yes and Collado-Osorio Yes are unrelated real tickets.",
            ],
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Aboian vs Hardt Kalshi flatten vs Poly log 2026-10-30</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.ok {{ background: #ecfdf3; border: 1px solid #86efac; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
.swipe-note {{ color: #555; font-size: 0.95em; }}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Aboian vs Hardt — Kalshi flatten, Poly never held</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}.
Did not commit. Did not start a second B. Did not leftover-GTC on A. Did not retune. Did not DailyRun.
Did not sell anything.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{blob["paul"]}</p>
<p>Follow-up: the row is Aboian vs Hardt. Kalshi UI later showed Sold Yes 34.38¢ limit 36¢
at 18:49:56 and Bought Yes 37.62¢ limit 36¢ at 18:49:59. Confirm against Kalshi fills and
Poly activities. Why did we log Yes polymarket / No kalshi when Poly fill was 0? Fix the
kitchen so it does not look like a Poly position. Do not list a platform on a lock pair
unless confirm qty &gt; 0. Label Sold Yes = buy No. Delay vs Kalshi UI is OK.</p>
<h2>In plain English</h2>
<p>We did trade this on Kalshi, then flattened, so Kalshi no longer shows a position.
Polymarket never had a TRADE, so that shop is empty. Kalshi’s “Sold Yes 34.38¢” is the
same ticket we log as buy No at 64¢ (after-fee 65.62¢; 100 − 65.62 = 34.38). “Bought Yes
37.62¢” is the flatten. The Venues column used to print the <em>intended</em> pair
(Yes Polymarket / No Kalshi) even when Polymarket fill was 0. It now names only shops
with confirm qty &gt; 0 and tags Kalshi No as Sold Yes = buy No. Net about
<strong>−3.24¢</strong>. Nothing left to sell.</p>
</div>

<div class="ok">
<p><strong>Each leg:</strong> Kalshi No (Sold Yes) real qty 1. Kalshi flatten Bought Yes
real qty 1. Polymarket Yes — no. Positions empty. Not Open now. Do not sell.</p>
<p>Venues column now: <code>{venues_now}</code></p>
</div>

<h2>Kitchen tape vs venue</h2>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>
{kitchen}
<p>Kalshi No used a Yes-wire limit of 36¢ (Sold Yes = buy No at 64¢). The fill confirm is
the No price 64¢. That is why the send row can print limit 0.36 and confirm @ 0.6400 on
the same contract <code>KXATPCHALLENGERMATCH-26OCT30ABOHAR-ABO</code>.</p>

<h2>Kalshi UI vs kitchen (same two fills)</h2>
{ui_map}

<h2>What the platforms still show</h2>
{venue}

<div class="warn">
<p><strong>Why it was logged with Polymarket.</strong> The Venues column printed the
intended lock pair (<code>Yes polymarket / No kalshi</code>) from yes_venue / no_venue.
Poly was never in the venue_return blob (confirm qty 0, no TRADE). Flatten is two Kalshi
settles that cancel. Quote vs fill: websocket No 0.53, book No 0.64, Yes-wire limit 0.36.
Kalshi UI lagged a couple of seconds; that delay is OK.</p>
</div>

<h2>What we changed</h2>
<ul>
<li>Same mapping on <code>opportunities.html</code> and this page: a lock-pair
Leg 1 / Leg 2 platform is listed only when confirm qty &gt; 0. Kalshi No is
<strong>Sold Yes = buy No</strong> (34.38¢ / limit 36¢). Unfilled Polymarket is omitted
(never sent / miss 0), not shown as a shop we hold.</li>
<li>Kitchen Type mapper (<code>kitchen_side_label</code>) uses the same Sold Yes = buy No
gloss for a Kalshi No seat.</li>
<li>A cluster cannot stay Open after <code>flatten_filled</code>. Poly fill 0 is a missed
send, not a ticket. Empty-book full flatten is not Open (Namigata 0.32 leftover still is).</li>
<li>Fixture tests in <code>tools/test_aboian_hardt_flatten_20261030.py</code>.</li>
</ul>

<p>Kitchen scoreboard: <a href="dashboard.html">dashboard.html</a> (no What you asked). Performance:
<a href="orders_performance.html">orders_performance.html</a>. Consideration log:
<a href="opportunities.html">opportunities.html</a>.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
