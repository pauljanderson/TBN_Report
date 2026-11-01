"""Moreno vs Herrera Polymarket autopsy HTML. Display/report only. No live orders."""
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
OUT = STAMP / "moreno_herrera_poly_autopsy_20261029.html"
FIXTURE = Path("tools/fixtures/moreno_herrera_poly_20261028.json")
SLUG = "aec-utr-morale-cartho-2026-10-28"


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
            ("Leg", "text"),
            ("Poly order id", "text"),
            ("Intent", "text"),
            ("Kitchen label", "text"),
            ("Venue qty", "num"),
            ("House 1?", "text"),
            ("Cash (debit)", "num"),
            ("Fee", "num"),
            ("After-fee", "num"),
            ("Kitchen", "text"),
            ("Venue-true P&L (Moreno won)", "num"),
        ],
        [
            [
                "T0 Hi Moreno",
                "DCFF2ZM011N2",
                "BUY_LONG",
                "Yes Moreno, Alejandro",
                d4("0.3"),
                "no",
                d4("0.8500"),
                d4("0"),
                d4("0.2550"),
                "missed send / confirm 0",
                money("0.045"),
            ],
            [
                "T0 low Herrera",
                "DCFF326G11R3",
                "BUY_SHORT",
                "Yes Cardona Herrera, Thomas",
                d4("1"),
                "yes",
                d4("0.1600"),
                d4("0.0100"),
                d4("0.1700"),
                "fill 1 postponed",
                money("-0.17"),
            ],
            [
                "Flatten (buy Yes to unwind Herrera)",
                "DCFGAH0011N2",
                "BUY_LONG",
                "Yes Moreno, Alejandro",
                d4("1"),
                "yes",
                d4("0.8600"),
                d4("0.0100"),
                d4("0.8700"),
                "fill 1 postponed",
                money("0.13"),
            ],
        ],
        ["Book (3 tickets)", "", "", "", d4("2.3"), "", d4("1.2750"), d4("0.0200"), d4("1.2950"), "kitchen $0.30 payout only", money("0.005")],
    )
    ui = table(
        [
            ("Poly US history row", "text"),
            ("What it is", "text"),
            ("Should settle", "text"),
        ],
        [
            ["Won +$0.30", "Redeem of the 0.3 T0 LONG (prints 0.06+0.07+0.10+0.07). UI shows payout, not profit.", "win +0.045 after cost 0.255"],
            ["Bought $0.11 / Bought $0.14", "Same 0.3 fill split in the trade list (0.13×0.85≈$0.11 and 0.17×0.85≈$0.14).", "already in the +$0.30 redeem"],
            ["Bought $0.87", "Flatten BUY_LONG 1 @ 0.86 + fee 0.01", "win +0.13"],
            ["Bought $0.17", "T0 BUY_SHORT Herrera 1 @ 0.16 + fee 0.01 (Yes-wire 0.84)", "lose −0.17"],
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Moreno vs Herrera Polymarket autopsy 2026-10-29</title>
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
<h1>Moreno vs Herrera — Polymarket autopsy</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}. Same class as Pohle/Kostina: kitchen vs venue settlement. Did not commit. Did not start a second B. Did not leftover-GTC on A. Did not retune C=1.05, D=0.25, or B 1.05/0.25. Did not bump stake.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: game HAS ended and Polymarket HAS settled. We bought 4 different bets, 3 should have won, kitchen only settled $0.30. Screenshot: Polymarket US portfolio history for jollycobra4517. Kitchen rows marked postponed: flatten Yes Moreno 0.86 fill 1; initial low Yes Herrera 0.16 fill 1; initial Hi Yes Moreno 0.85 fill 0.3 HTTP 200 confirm 0 missed send. Guess: many marked postponed have actually settled — check them ALL.</p>
<h2>In plain English</h2>
<p>The tennis match finished. Polymarket already paid. We had a 0.3 leftover on Moreno plus a 1-and-1 flatten lock (Moreno vs Herrera). Kitchen called the game postponed and treated the 0.3 fill as a missed send, so the only number it showed was the $0.30 payout on that leftover. The other tickets were still sitting on “Bought.” We re-pulled every postponed kitchen row against the venue and rebuilt the scoreboard.</p>
</div>

<div class="ok">
<p><strong>Winner: Alejandro Moreno</strong> 2–1 (3–6, 6–4, 7–6) at UTR PTT Knoxville Men 05, 28 Oct 2026,
Goodfriend Tennis Center Court 03
(<a href="https://sports.cobracasino.com/tennis/moreno-alejandro-cardona-herrera-thomas-m-431717544">match card</a>).
Venue: slug <code>{SLUG}</code> Yes = Moreno, Alejandro, <code>settlementPx=1.0000</code>,
<code>MARKET_STATE_EXPIRED</code>. Positions GET empty (normal after settle). Activities POSITION_RESOLUTION realized <strong>$0.025</strong> before fees (qty bought 1.3 / sold 1.3).</p>
</div>

<h2>The four Poly US rows vs three kitchen tickets</h2>
<p>Click column headers to sort. {SWIPE_NOTE_HTML.replace('<p class="swipe-note">', '').replace('</p>', '')}</p>
{ui}
<p>Paul’s “4 bets, 3 should have won” is the UI split: $0.11 + $0.14 (the 0.3 leftover) + $0.87 flatten should win; $0.17 Herrera should lose. The Won +$0.30 line is the leftover redeem, not a fourth independent ticket.</p>

<h2>Three venue fills — kitchen vs house</h2>
{rec}
<p>Venue-true with-fee: leftover <strong>+0.045</strong> + flatten <strong>+0.13</strong> + Herrera <strong>−0.17</strong> = <strong>+0.005</strong>. Kitchen showed only the <strong>$0.30</strong> gross payout on the 0.3 share. Poly realized $0.025 is the same book without the two $0.01 fees.</p>

<h2>What went wrong</h2>
<ul>
<li><strong>Watch stuck postponed.</strong> B marked <code>closed without settlement</code> at 14:01 ET when the market closed before a 0/1 px. Rebuild skipped re-GET because the settlement row was already postponed. The live GET already had <code>settlementPx=1.0000</code>.</li>
<li><strong>0.3 fill treated as confirm 0.</strong> House fill is 1 contract. Ledger <code>qty_is_fill</code> required ≥ 1, so the leftover was a missed send. Poly FOK still printed 0.06+0.07+0.10+0.07 = 0.3. B correctly skipped flattening that leftover as 1, then flattened the Herrera 1 by buying Yes Moreno 1 @ 0.86.</li>
<li><strong>Missed-send vs won ticket.</strong> A confirm-0 row must never be stamped win/loss. The 0.3 leftover is a real ticket (qty &gt; 0), not a miss.</li>
<li><strong>BUY_SHORT cash.</strong> Herrera Yes-wire 0.84; house debit is quote 0.16 + fee 0.01 = 0.17. Same invert rule as Pohle/Kostina: binary settlementPx only; ignore ticker result=yes.</li>
</ul>

<h2>Code lock (so this does not keep happening)</h2>
<ul>
<li>Rebuild always re-GETs venue settle, including rows labeled postponed. <code>live_market_get</code> + settlementPx beats watch postponed / close_hook.</li>
<li>Kitchen postponed only if the venue is still <strong>open</strong> AND (start is still in the future OR the venue officially postponed). Closed-without-settlement is not postponed.</li>
<li>Ledger fill is venue qty &gt; 0. House fill is still qty ≥ 1. Flatten of a 0.3 holding cannot post or mark house 1.</li>
<li>Tests: <code>test_moreno_herrera_poly_autopsy.py</code> (fixture from live Poly history), postponed-but-settled scan, 0.3 vs 1 flatten mismatch, missed-send is not a won/lost ticket.</li>
</ul>
<h2>Postponed-but-settled scan (this rebuild)</h2>
<p>19 kitchen rows that were still labeled postponed had a binary venue settle. Rebuild flipped them. Click headers to sort.</p>
<p class="swipe-note">Swipe sideways to see more columns.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Game<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Was<span class="sort-ind"></span></th>
<th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Venue result<span class="sort-ind"></span></th>
</tr></thead><tbody>
<tr><td>Rodriguez Taverna vs Bueno</td><td>period=SUS</td><td>yes</td></tr>
<tr><td>Vivian Wolff vs. Stefani Webb</td><td>start moved</td><td>yes</td></tr>
<tr><td>Tsuki Shibutani vs. Ayane Takagi</td><td>closed without settlement</td><td>yes</td></tr>
<tr><td>Aaron Funk vs. Sergey Petrov</td><td>closed without settlement</td><td>no</td></tr>
<tr><td>David Tixhon vs. Carles Cordoba</td><td>period=SUS</td><td>yes</td></tr>
<tr><td>Veronika Podrez vs. Katarina Zavatska</td><td>closed without settlement</td><td>no</td></tr>
<tr><td>Sara Saito vs. Ariana Arseneault</td><td>closed without settlement</td><td>no</td></tr>
<tr><td>Barry - Sato vs. Stevens - Thompson</td><td>closed without settlement</td><td>yes</td></tr>
<tr><td>Viktorija Golubic @ Maya Joint</td><td>start moved</td><td>yes</td></tr>
<tr><td>Heide vs Pucinelli de Almeida</td><td>period=SUS</td><td>yes</td></tr>
<tr><td>Junri Namigata vs. Natsuki Yoshimoto</td><td>closed without settlement</td><td>yes</td></tr>
<tr><td>Killian Van Roost vs. Carmelo Gasparo Morticella</td><td>closed without settlement</td><td>no</td></tr>
<tr><td>Doga Turkmen vs. Anna Snigireva</td><td>period=SUS</td><td>yes</td></tr>
<tr><td>Sebastien Cudny vs. Alex Galstyan</td><td>closed without settlement</td><td>no</td></tr>
<tr><td>Patricio Llanes Echavarria vs. Edgar Hipolito Cruz Vazquez</td><td>closed without settlement</td><td>yes</td></tr>
<tr><td>Del Pino vs Leite</td><td>closed without settlement</td><td>no</td></tr>
<tr><td>John Chin vs. Matt Kuhar</td><td>closed without settlement</td><td>no</td></tr>
<tr><td>Alejandro Moreno vs. Thomas Cardona Herrera</td><td>closed without settlement</td><td>yes</td></tr>
</tbody></table></div>

<p>Kitchen scoreboard: <a href="dashboard.html">dashboard.html</a> (no What you asked). Performance:
<a href="orders_performance.html">orders_performance.html</a>.
Siblings: <a href="pohle_kostina_poly_autopsy_20261028.html">Pohle/Kostina</a>,
<a href="venue_truth_fix_20261028.html">venue truth</a>.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
