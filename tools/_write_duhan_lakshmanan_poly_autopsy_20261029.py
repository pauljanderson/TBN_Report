"""Duhan vs Lakshmanan Polymarket autopsy HTML. Display/report only. No live orders."""
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
OUT = STAMP / "duhan_lakshmanan_poly_autopsy_20261029.html"
FIXTURE = Path("tools/fixtures/duhan_lakshmanan_poly_20261028.json")
SLUG = "aec-itfme-chiduh-arylak-2026-10-28"


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
            ("House 1?", "text"),
            ("Cash (debit)", "num"),
            ("Fee", "num"),
            ("Kitchen label", "text"),
            ("Venue-true P&L (Lakshmanan won)", "num"),
        ],
        [
            [
                "04:21:17 crossover Yes Lakshmanan 0.48 fill 0.02 missed send",
                "DC9R5HV011TB",
                "BUY_SHORT",
                "TRADE 0.02 @ 0.48 PARTIALLY_FILLED (on Poly orders page)",
                d4("0.02"),
                "no",
                d4("0.4800"),
                d4("0"),
                "missed send (confirm 0) / house ≥1",
                money("0.0104"),
            ],
            [
                "04:02:08 crossover Yes Lakshmanan 0.46 fill 0 missed send",
                "DC9FDBMG11N6",
                "BUY_SHORT",
                "not listed — FOK 0, POST cumQuantity 0",
                d4("0"),
                "no",
                "",
                "",
                "missed send (confirm 0) — correct",
                "",
            ],
            [
                "03:02:48 initial low Yes Lakshmanan 0.28 fill 1 win +$0.71",
                "DC8MDY5011TB",
                "BUY_SHORT",
                "TRADE executions sum qty 1 @ Yes-wire 0.72",
                d4("1"),
                "yes",
                d4("0.2800"),
                d4("0.0100"),
                "settled win +$0.71",
                money("0.71"),
            ],
            [
                "03:02:48 initial Hi Yes Duhan 0.73 fill 1 loss −$0.74",
                "DC8MDRS011R3",
                "BUY_LONG",
                "TRADE executions sum qty 1 @ 0.73",
                d4("1"),
                "yes",
                d4("0.7300"),
                d4("0.0100"),
                "settled loss −$0.74",
                money("-0.74"),
            ],
        ],
        [
            "Book (3 real tickets; 1 ghost FOK)",
            "",
            "",
            "POSITION_RESOLUTION qtyBought 1.02 / qtySold 1.02",
            d4("2.02"),
            "",
            "",
            d4("0.0200"),
            "kitchen T0 −$0.03; leftover missed",
            money("-0.0196"),
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Duhan vs Lakshmanan Polymarket autopsy 2026-10-29</title>
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
<h1>Chirag Duhan vs Aryan Lakshmanan — Polymarket autopsy</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}.
Did not commit. Did not start a second B. Did not leftover-GTC on A. Did not retune. Did not bump stake.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: kitchen rows for Chirag Duhan vs Aryan Lakshmanan look different from his Polymarket orders page.
Call Poly for completed orders and reconcile. Also: aren't you supposed to do this at the end of each match?
Should we start a separate process that resolves/settles open matches not yet reconciled?
How did you reconcile this match and how does Poly have something different?</p>
<h2>In plain English</h2>
<p>Aryan Lakshmanan won. We bought Yes Duhan 1, Yes Lakshmanan 1 at the start (a cheap both-sides lock that still costs a little extra after fees), then tried two extra Lakshmanan bets after the 50¢ crossover. One extra never filled. The other filled only 0.02 of a contract. Kitchen called that 0.02 a missed send because a “full” house bet is 1 contract. Polymarket’s orders page still shows the 0.02. We pulled the venue book, put the 0.02 on the ledger as a real tiny ticket, and started one background checker so this does not wait on a person the next time a match ends overnight.</p>
</div>

<div class="ok">
<p><strong>Winner: Aryan Lakshmanan</strong> (ITF Men, 28 Oct 2026).
Polymarket slug <code>{SLUG}</code> Yes = Chirag Duhan, <code>settlementPx=0.0000</code> (Duhan lost).
Kalshi <code>KXITFMATCH-26OCT28DUHLAK</code> Lakshmanan result=yes, Duhan result=no.
Positions GET empty after settle (normal). POSITION_RESOLUTION <code>qtyBoughtDecimal=1.0200</code> /
<code>qtySoldDecimal=1.0200</code> realized <strong>−$0.0004</strong> before the two $0.01 T0 fees.
GET <code>/v1/orders/{{id}}</code> is 404 for all four ids — completed orders live on
<code>GET /v1/portfolio/activities</code> TRADE rows, not that GET.</p>
</div>

<h2>Poly vs kitchen, row by row</h2>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>
{rec}
<p>T0 both-Yes with fees: Duhan LONG −$0.74 + Lakshmanan SHORT +$0.71 = <strong>−$0.03</strong> (all-in 1.03 vs $1).
The 0.02 leftover SHORT at 0.48 is <strong>+$0.0104</strong>. Venue-true book <strong>−$0.0196</strong>.
Kitchen that treated 0.02 as a miss stopped at the T0 −$0.03. Poly’s −$0.0004 realized is the same three tickets without the two cent fees (T0 wires 0.73+0.28=1.01 vs $1, leftover +0.0104 ≈ flat).</p>

<h2>Why they differ</h2>
<ul>
<li><strong>FOK 0 vs 0.02 vs house ≥1.</strong> Polymarket Fill-or-Kill can print a partial. House fill is still 1 contract. Ledger now treats any venue qty &gt; 0 as a ticket. 0.02 is a real 0.02 fill, not house 1 and not a ghost.</li>
<li><strong>04:02 FOK 0 is not on Poly’s orders page.</strong> HTTP 200, cumQuantity 0, never a TRADE row. Kitchen missed-send is right. Confirm-0 is never a won ticket.</li>
<li><strong>04:21 0.02 IS on Poly’s orders page</strong> as BUY_SHORT 0.02 @ 0.48 (PARTIALLY_FILLED). Kitchen showed 0.48 / fill 0.02 / missed send because house ≥1. Store had even used Yes-ask 0.52 as cash; venue debit is 0.48.</li>
<li><strong>T0 both-Yes vs Poly.</strong> Kitchen labels both legs “Yes” (Duhan LONG, Lakshmanan SHORT that pays if Lakshmanan wins). Poly shows BUY_LONG Duhan 1 @ 0.73 and BUY_SHORT 1 @ 0.72 Yes-wire (house debit 0.28). Same two tickets. P&amp;L −$0.74 / +$0.71 matches.</li>
</ul>

<h2>How kitchen reconciled this match</h2>
<p><code>write_orders_performance</code> rebuilds from the tape + <code>settled_pnl_store</code>.
<code>venue_fill_confirm</code> is the post-send GET (activities). The game-complete hook is
<code>orders_performance_refresh.maybe_after_game_complete</code> via B
<code>note_settled_holds</code> / <code>_note_b_stage</code> when a touched match goes
done / absorbed / settled, and via the supervisor’s once-a-minute
<code>note_snapshot_closes</code>.</p>
<p>B did send T0 both and two extras. The 0.02 leftover set <code>extra_stuck</code> and left the match
in the 50-cross stage. <code>note_settled_holds</code> only ran when no match was still “waiting 50-cross.”
An extra_stuck leftover counted as waiting, so the end-of-match settle hook did not run on this
row while that flag was on. T0 win/loss landed later from a tape rebuild (settled_pnl
<code>tape_rebuild</code> 2026-10-29 14:59 ET) after the market was already expired
(watch note: <code>expired; settled/expired/final/void is not open</code>). That rebuild
priced the two house-1 tickets and still treated 0.02 as a miss on the old house ≥1 rule.
Watch stage is now <code>done</code>.</p>

<h2>Did the end-of-match hook run?</h2>
<p><strong>The hook exists. It did not settle this leftover at match end.</strong> Cause: Poly partial 0.02 →
<code>extra_stuck</code> → still counted as an open 50-cross → B skipped <code>note_settled_holds</code>.
Not a postponed path. Poly was expired. Not “skip because missed-send” on T0 (those two were house 1).
Overnight the leftover stayed a kitchen miss until a later tape rebuild. Fix: extra_stuck is no longer
an armed 50-cross, so the hook runs, plus a separate one-process reconciler (below).</p>

<h2>Separate reconciler</h2>
<p>Yes. <code>tools/live_pm_settle_reconcile.py</code> — one process, started with the other jobs via
<code>prediction_job_control.ensure_settle_reconcile</code> (never a second copy, never a second B).
Every ~90s it lists kitchen open / postponed / unreconciled / missed-send rows, REST-pulls Poly
activities + market settlement, and writes venue qty/cash/settle into <code>settled_pnl.json</code>.
Confirm-0 cannot be marked won. Qty 0.02 is shown as 0.02.
This run started pid <strong>47084</strong> at 2026-10-29 15:33:24 ET. Tennis crossover stayed pid 38792.</p>

<p>Kitchen scoreboard: <a href="dashboard.html">dashboard.html</a> (no What you asked). Performance:
<a href="orders_performance.html">orders_performance.html</a>.
Sibling: <a href="moreno_herrera_poly_autopsy_20261029.html">Moreno/Herrera 0.3 leftover</a>.</p>
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
