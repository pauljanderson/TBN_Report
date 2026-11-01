"""Chin vs Kuhar Polymarket autopsy HTML. Display/report only. No live orders."""
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
OUT = STAMP / "chin_kuhar_poly_autopsy_20261029.html"
FIXTURE = Path("tools/fixtures/chin_kuhar_poly_20261028.json")
SLUG = "aec-itfme-johchi-matkuh-2026-10-28"


def d4(x) -> str:
    return f"{Decimal(str(x)):.4f}"


def money(x) -> str:
    v = Decimal(str(x))
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.4f}"


def main() -> None:
    blob = json.loads(FIXTURE.read_text(encoding="utf-8"))
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    rec = table(
        [
            ("Kitchen row (Paul)", "text"),
            ("Poly order id", "text"),
            ("Intent", "text"),
            ("Poly completed orders", "text"),
            ("Venue qty", "num"),
            ("Kitchen cash", "num"),
            ("Venue debit", "num"),
            ("Fee", "num"),
            ("Kitchen P&L", "num"),
            ("Venue-true P&L (Kuhar won)", "num"),
        ],
        [
            [
                "07:59:58 initial Hi Yes Matt Kuhar 0.74 fill 1 win +$0.25",
                "DCCWHE2G11M3",
                "BUY_SHORT",
                "TRADE 0.90+0.10 @ 0.26 (No / debit), GET /v1/orders 404",
                d4("1"),
                d4("0.7400"),
                d4("0.2600"),
                d4("0.0100"),
                money("0.25"),
                money("0.73"),
            ],
            [
                "07:59:58 initial low Yes John Chin 0.27 fill 1 loss −$0.28",
                "DCCWHAK011MM",
                "BUY_LONG",
                "TRADE executions sum qty 1 @ 0.27",
                d4("1"),
                d4("0.2700"),
                d4("0.2700"),
                d4("0.0100"),
                money("-0.28"),
                money("-0.28"),
            ],
        ],
        [
            "Book (2 real fills; not a ghost)",
            "",
            "",
            "positions empty after settle",
            d4("2"),
            d4("1.0100"),
            d4("0.5300"),
            d4("0.0200"),
            money("-0.03"),
            money("0.45"),
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Chin vs Kuhar Polymarket autopsy 2026-10-29</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.bad {{ background: #fdecec; border: 1px solid #e8b4b4; padding: 12px 16px; margin: 16px 0; }}
.ok {{ background: #ecfdf3; border: 1px solid #86efac; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
.swipe-note {{ color: #555; font-size: 0.95em; }}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>John Chin vs Matt Kuhar — Polymarket autopsy</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}.
Did not commit. Did not start a second B. Did not leftover-GTC on A. Did not retune. Did not bump stake.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: John Chin vs Matt Kuhar kitchen rows also do not match his Polymarket orders page.
Why out of sync? What can you do? What prevents this and anything like it in the future?</p>
<h2>In plain English</h2>
<p>Matt Kuhar beat John Chin. We bought both sides at the start: Yes Chin at 27¢, and
the other side as a Polymarket short that kitchen labeled “Yes Kuhar 74¢.” Polymarket’s
orders page shows that second ticket as a 26¢ No, which is what we actually paid.
Kitchen then paid the Kuhar ticket as if we had spent 75¢, so it showed only a 25¢ win.
The real win on that short is about 73¢. Winner was not flipped. The two pages disagreed
because kitchen used the Yes price as the cost instead of the venue debit.</p>
</div>

<div class="ok">
<p><strong>Winner: Matt Kuhar</strong> 4–6 6–1 6–1 at ITF M15 Pembroke R32, 28 Oct 2026
(<a href="https://umpiry.com/match/2026-10-28/chin-vs-kuhar-m15-pembroke-r32">match card</a>;
<a href="https://kalshi.com/markets/kxitfmatch/itf-mens-match/kxitfmatch-26oct28chikuh?op_market_ticker=KXITFMATCH-26OCT28CHIKUH-KUH">Kalshi recap</a>).
Polymarket slug <code>{SLUG}</code> Yes = John Chin, <code>settlementPx=0.0000</code>
(Chin lost → Kuhar won). Positions GET empty after settle (normal).
GET <code>/v1/orders/{{id}}</code> is 404 — completed fills live on
<code>GET /v1/portfolio/activities</code> TRADE rows (Chin qty 1 @ 0.27, Kuhar SHORT qty 1 @ 0.26).
Not a kitchen ghost: both HTTP 200 fills are on Poly.</p>
</div>

<h2>Poly vs kitchen, row by row</h2>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{rec}
<p>If Kuhar won and kitchen had used Yes-wire cost: Yes Kuhar +$0.25 and Yes Chin −$0.28
(kitchen). Venue debit: SHORT 0.26 + fee 0.01 pays $1 → <strong>+$0.73</strong>, Chin LONG
still <strong>−$0.28</strong>. Book <strong>+$0.45</strong> vs kitchen <strong>−$0.03</strong>
($0.48 = 0.74 − 0.26, the Yes-wire vs debit swap). Chin did <em>not</em> win — this is not
the Pohle/Kostina/Maloney inverted-winner class. Winner matches. Cash does not.</p>

<h2>Why they were out of sync</h2>
<ul>
<li><strong>Yes-wire vs debit, not an inverted winner.</strong> Official + Kalshi: Kuhar won.
Tape <code>settlementPx=0.0000</code> / result=no on Yes=Chin is correct. Kitchen’s win/loss
labels (Kuhar win, Chin loss) match. Paul’s Poly orders page shows BUY_SHORT @ 0.26, not
“Yes Kuhar 0.74.”</li>
<li><strong>Kitchen stored the Yes ask as cash on the short.</strong> Watch fill_px was already
0.26; orders.jsonl <code>limit_price=0.260</code> / <code>quote_price=0.74</code>. Rebuild
<code>poly_house_cash</code> used the 0.74 quote as the hint and kept Yes-wire. P&amp;L became
1 − 0.75 = +$0.25 instead of 1 − 0.27 = +$0.73.</li>
<li><strong>Watch still said postponed.</strong> B marked <code>closed without settlement</code>
at 10:46 ET. Rebuild later stamped win/loss from tape, still using the 0.74 cash. Not a missing
fill.</li>
</ul>

<h2>What we did / what prevents this again</h2>
<ul>
<li><code>poly_house_cash</code>: when a BUY_SHORT kitchen quote is the $1 complement of the
posted debit (Kuhar 0.74 vs limit 0.26), use the venue debit. Tests:
<code>test_chin_kuhar_poly_autopsy.py</code> plus a Chin/Kuhar row on the sibling reconciler tests.</li>
<li><strong>Reused the sibling’s one-process reconciler</strong>
(<code>tools/live_pm_settle_reconcile.py</code>), did not start a second copy.
<code>debit_hint</code> already takes the cheaper of quote/limit and the $1 complement, so this
SHORT prices at 0.26. It re-GETs Poly (and Kalshi via <code>fetch_market_result</code>) for
open / postponed / unreconciled / missed-send kitchen games every ~90s. Confirm-0 cannot be a
won ticket. Venue qty 0.02 stays 0.02.</li>
<li>Dashboard / orders_performance rebuilt from venue-true cash + binary
<code>settlementPx</code> only. Dashboard has no What you asked block.</li>
</ul>

<p>Kitchen scoreboard: <a href="dashboard.html">dashboard.html</a> (no What you asked). Performance:
<a href="orders_performance.html">orders_performance.html</a>.
Siblings: <a href="duhan_lakshmanan_poly_autopsy_20261029.html">Duhan/Lakshmanan</a>,
<a href="pohle_kostina_poly_autopsy_20261028.html">Pohle/Kostina</a>,
<a href="moreno_herrera_poly_autopsy_20261029.html">Moreno/Herrera</a>.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    _ = blob
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
