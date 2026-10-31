"""Pohle vs Kostina Polymarket autopsy HTML. Display/report only. No live orders."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report_page_extras import FORCE_RELOAD_SCRIPT, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML
from write_orders_performance import table

STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "pohle_kostina_poly_autopsy_20261028.html"

SLUG = "aec-itfwo-vicpoh-arikos-2026-10-28"
OID_POHLE_T0 = "DCCXJ38G11MQ"
OID_KOST_T0 = "DCCXJ77G11MV"
OID_CROSS_1 = "DCEHKNGG11N6"
OID_CROSS_2 = "DCEJABR011N2"


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
            ("Kitchen P&L (ticker=no)", "num"),
            ("Venue-true P&L (Pohle won)", "num"),
        ],
        [
            [
                "T0 Pohle",
                OID_POHLE_T0,
                "BUY_LONG",
                "Yes Victoria Pohle",
                "initial Hi lock",
                d4("0.5300"),
                d4("0.5300"),
                d4("0.5300"),
                d4("0.0200"),
                d4("0.5500"),
                d4("0.5300"),
                d4("0.0200"),
                money("-0.55"),
                money("0.45"),
            ],
            [
                "T0 Kostina",
                OID_KOST_T0,
                "BUY_SHORT",
                "Yes Arina Kostina",
                "initial low lock",
                d4("0.5200"),
                d4("0.4800"),
                d4("0.4800"),
                d4("0.0100"),
                d4("0.4900"),
                d4("0.5200"),
                d4("0.0100"),
                money("0.47"),
                money("-0.49"),
            ],
            [
                "Crossover 09:56",
                OID_CROSS_1,
                "BUY_SHORT",
                "Yes Arina Kostina",
                "crossover lock",
                d4("0.4700"),
                d4("0.5300"),
                d4("0.5300"),
                d4("0.0200"),
                d4("0.5500"),
                d4("0.5300"),
                d4("0.0200"),
                money("0.45"),
                money("-0.55"),
            ],
            [
                "Crossover 09:57",
                OID_CROSS_2,
                "BUY_SHORT",
                "Yes Arina Kostina",
                "crossover lock",
                d4("0.4800"),
                d4("0.5200"),
                d4("0.5200"),
                d4("0.0200"),
                d4("0.5400"),
                d4("0.4800"),
                d4("0.0200"),
                money("0.50"),
                money("-0.54"),
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
            d4("2.0600"),
            d4("0.0700"),
            d4("2.1300"),
            d4("2.0600"),
            d4("0.0700"),
            money("0.87"),
            money("-1.13"),
        ],
    )
    scan = table(
        [
            ("Game", "text"),
            ("Slug", "text"),
            ("Filled legs", "num"),
            ("Stored result / px", "text"),
            ("Venue result / px", "text"),
        ],
        [
            ["Victoria Pohle vs. Arina Kostina", SLUG, "4", "no / 0", "yes / 1.0000"],
            ["Clement Tabur vs. Filippo Romano", "aec-atp-cletab-filrom-2026-10-26", "1", "no / 0", "yes / 1.0000"],
            ["Matej Dodig @ Marco Trungelliti Quarterfinals", "aec-atp-martru-matdod-2026-10-23", "3", "no / 0", "yes / 1.0000"],
            ["Jasika vs Kim", "aec-atp-omajas-taekim-2026-10-25", "1", "no / 0", "yes / 1.0000"],
            ["Nagal vs Sanchez Quilez", "aec-atp-sumnag-alequi-2026-10-20", "1", "no / 0", "yes / 1.0000"],
            ["Griekspoor vs Schoenhaus", "aec-atp-talgri-maxsch-2026-10-18", "1", "no / 0", "yes / 1.0000"],
            ["Paris vs Faucon", "aec-atp-tompar-romfau-2026-10-25", "1", "no / 0", "yes / 1.0000"],
            ["Enzo Lima vs. Bruno Vieira Alves Malacarne Bruno", "aec-itfme-enzlim-bruno-2026-10-25", "2", "no / 0", "yes / 1.0000"],
            ["Santillan vs Malkamaki (slug pausan-basmal)", "aec-itfme-pausan-basmal-2026-10-21", "3", "no / 0", "yes / 1.0000"],
            ["Fery vs Gojo", "aec-atp-artfer-borgoj-2026-10-20", "1", "yes / 1", "no / 0.0000"],
            ["Onclin vs Struff", "aec-atp-gauonc-janstr-2026-10-21", "1", "yes / 1", "no / 0.0000"],
            ["Casanova vs Bueno", "aec-atp-hercas-gonbue-2026-10-19", "1", "yes / 1", "no / 0.0000"],
            ["Alves vs Pereira", "aec-atp-matalv-josper-2026-10-19", "1", "yes / 1", "no / 0.0000"],
            ["Arnaldi vs Musetti", "aec-atp-matarn-lormus-2026-10-18", "1", "yes / 1", "no / 0.0000"],
            ["Kokoa Nakao vs. Minori Natsuka", "aec-utr-nakkok-natmin-2026-10-22", "4", "yes / 1", "no / 0.0000"],
            ["Osborne vs Hinojosa Gomez", "aec-wta-aleosb-jeshin-2026-10-25", "1", "yes / 1", "no / 0.0000"],
        ],
        ["16 inverted Polymarket tickers", "", "27", "kitchen", "venue GET"],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Pohle vs Kostina Polymarket autopsy 2026-10-28</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.bad {{ background: #fdecec; border: 1px solid #e8b4b4; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
.swipe-note {{ color: #555; font-size: 0.95em; }}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Pohle vs Kostina — Polymarket autopsy</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}. Same class of bug as Shimizu vs Hsu. Did not commit. Did not start a second B. Did not retune C=1.05, D=0.25, leftover GTC, or stake.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: “you have the wrong winner here again. can you go back and make sure all of the matches have the correct winner? Now we need to go back and regenerate all the reports again”</p>
<h2>In plain English</h2>
<p>We showed the wrong player as the winner on some Polymarket tennis games, so P&amp;L was backwards. Victoria Pohle beat Arina Kostina 1–6, 6–1, 6–2 at ITF W15 Essen. The kitchen paid three Kostina tickets and marked Pohle a loss. Polymarket’s Yes=Pohle market settled at $1. We checked every settled live ticket against the platform and rebuilt the pages. Venue fill + venue settle is the source of truth.</p>
</div>

<div class="bad">
<p><strong>Winner: Victoria Pohle.</strong> Independent: ITF W15 Essen R16, 28 Oct 2026, 1–6 6–1 6–2
(<a href="https://womenstennis.de/turnierort/essen">womenstennis.de Essen</a>).
Venue: <code>GET /v1/markets/{SLUG}</code> <code>settlementPx=1.0000</code>, <code>result=yes</code>,
<code>MARKET_STATE_EXPIRED</code>. Yes = Victoria Pohle. Stored tape said <code>result=no</code> / <code>settlementPx=0</code>.</p>
</div>

<h2>Four fills — kitchen vs venue</h2>
<p>Click column headers to sort. {SWIPE_NOTE_HTML.replace('<p class="swipe-note">', '').replace('</p>', '')}</p>
{rec}

<h2>What went wrong</h2>
<ul>
<li><strong>Winner inverted.</strong> One-slug tennis moneyline, Yes = Pohle. Kitchen used stored ticker <code>result=no</code> (a SHORT-resolution / tape_rebuild guess) so the three Kostina BUY_SHORT tickets paid $1 and Pohle LONG lost. Venue Yes token is $1.</li>
<li><strong>Backfill skipped the live GET.</strong> After Shimizu, Poly refetch was skipped when a row already had any settlementPx. Fake <code>0</code> from tape_rebuild blocked the real <code>1.0000</code>.</li>
<li><strong>Two shorts stored Yes-wire cash.</strong> T0 Kostina charged 0.48+0.01; we stored 0.52+0.01. 09:57 charged 0.52+0.02; we stored 0.48+0.02. Quote 0.48 vs avg 0.52 sat inside a 5-cent “near” band so house cash kept the Yes-wire.</li>
</ul>
<p>Venue-true book: Pohle T0 <strong>+0.45</strong>, Kostina T0 <strong>−0.49</strong>, 09:56 <strong>−0.55</strong>, 09:57 <strong>−0.54</strong>. Net <strong>−1.13</strong>. Kitchen was <strong>+0.87</strong> ($2.00 too high: four inverted $1 payouts, two of them with the nickel cash swap).</p>

<h2>Full-tape scan (Polymarket filled tickers vs live market GET)</h2>
<p>89 Polymarket tickers with stored settles. 16 disagreed with the venue GET. Kalshi/Gemini/Novig were not this inversion (named contract + debit). Click headers to sort.</p>
{scan}

<h2>Code lock</h2>
<ul>
<li><code>poly_house_cash</code> picks the venue field closest to the house quote, including the Yes-wire complement. A nickel gap is not a match.</li>
<li>Poly POSITION_RESOLUTION ignores <code>beforePosition</code> size. Market result is settlementPx / afterPosition.</li>
<li>Every dashboard rebuild re-GETs filled Polymarket markets. <code>live_market_get</code> + settlementPx beats tape_rebuild / close_hook.</li>
</ul>
<p>Kitchen scoreboard: <a href="dashboard.html">dashboard.html</a>. Sibling autopsies:
<a href="shimizu_hsu_poly_autopsy_20261028.html">Shimizu/Hsu</a>,
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
