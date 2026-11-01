"""Polymarket hist inventory vs live US Yes-ask tape — 30 Oct 2026.

Report only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not DailyRun.
Does not retune. Does not rewrite dashboard.html. Does not start a hist pull.
"""
from __future__ import annotations

import html as html_mod
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
PAGE = STAMP / "poly_hist_inventory_20261030.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/poly_hist_inventory_20261030.html"
)

ASKED = (
    "Paul just got the Kalshi inventory (T0 Yes-ask + settle, no in-play on hist). "
    "He now asks: what do we have from polymarket?"
)
PLAIN = (
    "Polymarket history on disk is the opening last-trade on the global Central Limit "
    "Order Book (CLOB — the public world book at clob.polymarket.com), plus who won, "
    "for both named sides. It is not the Yes ask (the price you pay to buy Yes), and "
    "it does not keep the price as the game unfolds. Polymarket US is a different shop "
    "(gateway.polymarket.us). The live poller writes US Yes-ask ticks from mid-October "
    "2026, mostly tennis. You cannot test an in-play dip or gain on the hist book today. "
    "You can on that live US tape for those October games. This is not mixed with Kalshi "
    "or with sportsbooks."
)


def esc(text) -> str:
    return html_mod.escape("" if text is None else str(text))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], *, total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    foot = ""
    if total:
        foot = (
            '<tr class="total-row">'
            + "".join(f"<td>{cell}</td>" for cell in total)
            + "</tr>"
        )
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}{foot}</tbody></table></div>"
    )


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    yes = "yes"
    no = "no"

    schema_tbl = table(
        [("Field", "text"), ("What it is", "text"), ("On hist row?", "text")],
        [
            ["slug / game", "Event slug, e.g. atp-augeraliassime-vs-musetti-2025-10-08 or nfl-ne-sea-2026-09-10", yes],
            ["sport / league", "Sport name plus league (ATP, NFL, EPL, …)", yes],
            ["kind", "moneyline, spread, or Points Total (one primary line per event)", yes],
            ["both players", "Two rows per market (each named outcome, own CLOB token)", yes],
            ["T0 clock", "gameStartTime unix; stored as clock / t0_ts", yes],
            ["Beginning odds", "Last CLOB trade at or just before that clock (px / t0_a). Not Yes-ask, not bid", "last-trade only"],
            ["Ask / bid", "Not stored on hist. Live US tape stores Yes-ask (and No as $1 minus bid when sized)", no + " on hist"],
            ["Settlement", "outcomePrices 0 or 1 → settled_px / fav_won", yes],
            ["In-play path", "Not stored. n=62 is how many last-trade points the API returned in a 1-hour T0 window; we keep one px", no],
            ["CLOB vs US", "Hist = global CLOB. Live poller = Polymarket US. Catalog dumps of both exist (17 Oct), not a T0 book", "hist = CLOB"],
        ],
    )

    cov_rows = [
        ["ATP", "tennis", "ML / spread / total", "2,050", "9,183", "165", "2025-10-08 .. 2026-03-15"],
        ["WTA", "tennis", "ML / spread / total", "2,050", "9,967", "145", "2025-10-12 .. 2026-04-21"],
        ["NHL", "hockey", "ML / spread / total", "1,681", "9,775", "79", "2025-10-02 .. 2026-10-29"],
        ["NBA", "basketball", "ML / spread / total", "1,607", "8,843", "83", "2025-10-02 .. 2026-10-29"],
        ["CFB", "college football", "ML / spread / total", "1,343", "5,998", "0", "2026-08-27 .. 2026-10-29"],
        ["MLB", "baseball", "ML / spread / total", "2,050", "4,506", "10", "clocks from 2024-07-29; last-trade book 2025-04-02 .. 2025-09-20"],
        ["MLS", "soccer", "ML / spread / total", "2,050", "2,780", "0", "2025-08-09 .. 2026-10-21"],
        ["WNBA", "basketball", "ML / spread / total", "684", "2,716", "24", "2025-05-16 .. 2026-10-27"],
        ["EPL", "soccer", "ML / spread / total", "1,869", "2,692", "6", "2025-08-15 .. 2026-10-25"],
        ["UFC", "mma", "ML / total", "705", "2,350", "180", "2025-09-30 .. 2026-11-07"],
        ["UCL", "soccer", "ML / spread / total", "1,466", "2,046", "4", "2025-08-19 .. 2026-10-21"],
        ["NFL", "pro football", "ML / spread / total", "463", "1,144", "34", "2026-08-07 .. 2026-10-27"],
        ["PGA", "golf", "ML", "113", "110", "8", "2026-07-30 .. 2026-10-22"],
        ["NCAAB", "basketball", "events only", "20", "0", "—", "no t0 jsonl"],
    ]
    cov_tbl = table(
        [
            ("League", "text"), ("Sport", "text"), ("Bet types kept", "text"),
            ("Events on disk", "num"), ("T0 last-trade N", "num"),
            ("Missing last-trade", "num"), ("Span", "text"),
        ],
        [[esc(c) for c in row] for row in cov_rows],
        total=["All (ex NCAAB t0)", "—", "—", "—", "62,110", "738", "books entry_date 2025-04-02 .. 2026-10-29"],
    )

    sample_tbl = table(
        [
            ("Slug", "text"), ("What", "text"), ("T0 last-trade", "text"),
            ("Settle", "text"), ("Stored timestamps", "num"), ("Note", "text"),
        ],
        [
            [
                "atp-augeraliassime-vs-musetti-2025-10-08",
                "ATP tennis moneyline, Shanghai, both players",
                "Auger-Aliassime 0.485 / Musetti 0.515 (~57s before 02:00 UTC 8 Oct 2025)",
                "Auger-Aliassime 1, Musetti 0",
                "1",
                "n=62 is the API window count, not a saved path",
            ],
            [
                "nfl-ne-sea-2026-09-10",
                "NFL moneyline, Patriots vs Seahawks, both teams",
                "Patriots 0.385 / Seahawks 0.615",
                "Patriots 0, Seahawks 1",
                "1",
                "2026 season hist. Preseason slugs start 7 Aug 2026",
            ],
            [
                "aec-nfl-phi-was-2026-11-01",
                "Eagles vs Commanders, Polymarket US live (not hist)",
                "Not in hist (game still open, listed 1 Nov 2026)",
                "Not settled",
                "309",
                "Live US Yes-ask: Eagles 0.2925 / Commanders 0.7100 at 08:26 ET 30 Oct. Pregame ticks 25–30 Oct, not in-play",
            ],
        ],
    )

    live_tbl = table(
        [("Tape", "text"), ("What", "text"), ("N", "text"), ("Span", "text")],
        [
            [
                "hist/books_poly.json",
                "Global CLOB last-trade at T0 + settle. One row per named side. venue=polymarket",
                "62,110 sides / 14,570 games",
                "entry_date 2025-04-02 .. 2026-10-29",
            ],
            [
                "hist/poly/t0/*.jsonl",
                "Same sides before the book filter. 62,848 token rows; 62,110 have both px and settle",
                "13 league files; ncaab missing",
                "clocks 2024-07-29 .. 2026-11-07 (UFC clocks include future)",
            ],
            [
                "Live shards raw/price_memory/2026-10-21..30",
                "Polymarket US Yes-ask (and No). Venue field says Polymarket. Poller is polymarket.us, not CLOB hist",
                "5,908,671 ticks; 16,092 keys with 2+ timestamps; 176 with 1. Tennis 5.89M, NFL 16,816",
                "21 Oct 11:34 ET .. 30 Oct 09:04 ET",
            ],
            [
                "Archive raw/price_memory.jsonl",
                "Older live ticks, same Yes-ask schema. Read-only",
                "758,250 Polymarket ticks (379,125 Yes)",
                "18 Oct 16:08 ET .. 21 Oct 11:31 ET",
            ],
            [
                "price_last_games",
                "Latest snapshot per game, not a path",
                "807 of 998 files have a Polymarket quote (775 tennis, 32 NFL)",
                "as of this morning",
            ],
            [
                "Catalog dumps (17 Oct)",
                "Open-market phone books, not T0 hist. US: bestAskQuote, no CLOB tokens. Intl: bestAsk + clobTokenIds",
                "US 83,553 / intl 143,039",
                "fetched 17 Oct 2026",
            ],
        ],
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Polymarket hist inventory 30 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.hold {{ background: #fef3c7; border-color: #f59e0b; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>What we have from Polymarket</h1>
<p class="note">Written {esc(now)}. Inventory of files on disk. Did not sell tickets,
start a second Tennis crossover (B), DailyRun, retune, rewrite dashboard.html, or start
a hist pull. Click column headers to sort.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>

<div class="callout hold">
<h2>Same shape as the Kalshi answer</h2>
<ul>
<li><strong>Beginning odds:</strong> yes — last CLOB trade at kickoff, not the Yes ask.</li>
<li><strong>Ending results:</strong> yes — each named side settles 0 or 1.</li>
<li><strong>Throughout-game fluctuations:</strong> no on hist (0 stored paths of 2+ timestamps).
Yes on the live Polymarket US Yes-ask tape for mid–late October, mostly tennis.</li>
<li><strong>N:</strong> 62,110 hist sides (14,570 games). Live US tape ~6.7M Polymarket ticks
(archive + shards).</li>
<li><strong>Holes:</strong> no in-play on hist; last-trade not ask; global CLOB not Polymarket US;
NCAAB has events and no T0; ATP/WTA/MLB/MLS event lists cap at 2,050; ATP hist ends 15 Mar 2026
and WTA 21 Apr 2026; no ITF/Challenger/Bundesliga/Serie A/La Liga/Ligue 1; only the primary
moneyline / spread / Points Total per event; NFL hist is the 2026 season only.</li>
</ul>
</div>

<h2>Can we test an in-play dip or gain on Poly hist today?</h2>
<p>No. Hist is T0 last-trade → settle only. In-play Yes-ask dips live on the Polymarket US
poller tape from 18 Oct 2026, tennis-heavy, not on <code>books_poly.json</code>.</p>

<h2>One hist row</h2>
<p class="note">Source <code>hist/poly/t0/*.jsonl</code> folded into
<code>hist/books_poly.json</code> (N=62,110, source=poly_clob_last_trade,
t0_label=last CLOB trade at/just before gameStartTime (not ask)).
<code>end_ts</code> equals <code>t0_ts</code> on every book row. Do not mix with
<code>books_kalshi.json</code>.</p>
{schema_tbl}

<h2>N by league</h2>
<p class="note">T0 last-trade N is coverage n_t0 (a last-trade print at/before clock).
Primary moneyline, spread, and Points Total only. Event lists for ATP, WTA, MLB, and MLS
stop at 2,050 (pager cap). Click column headers to sort.</p>
{cov_tbl}

<h2>Sample slugs</h2>
<p class="note">aec-nfl-phi-was is not in hist. It is on the live US tape as a pregame
game, listed 1 Nov 2026.</p>
{sample_tbl}

<h2>Last-trade vs Yes-ask, CLOB vs US</h2>
<p>Prior work was right: Poly hist is last-trade, not ask. The live poller tape is
Yes-ask on Polymarket US (the Yes pay is the sized Yes ask; the No pay is $1 minus a
sized Yes bid). The venue field on that tape still says <code>Polymarket</code>.</p>
{live_tbl}

<h2>Holes</h2>
<ul>
<li>Zero hist markets with a saved path of 2+ timestamps. 62,110 T0-only.</li>
<li>College basketball (NCAAB): 20 event rows, 8 moneylines, no t0 file.</li>
<li>ATP hist ends 15 Mar 2026; WTA 21 Apr 2026. October tennis in-play is live tape only.</li>
<li>No ITF, Challenger, Bundesliga, Serie A, La Liga, or Ligue 1 on Poly hist.</li>
<li>Extra spread/total lines, team totals, and first-half markets sit on event jsonl and
were not candled into T0.</li>
<li>738 t0 token rows lack a last-trade print or a settle (UFC missing 180 is the largest hole).</li>
<li>Oct 17 catalog dumps are open books, not a second hist T0 series.</li>
</ul>
<p class="tiny">hist dir
<code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/hist/</code>.
books_poly.json mtime 2026-10-30 05:26 local; coverage.json same morning.
Live shards under <code>raw/price_memory/</code>; last quotes under
<code>raw/price_last_games/</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html, encoding="utf-8")
    print(PAGE)
    print(FILE_URL)


if __name__ == "__main__":
    main()
