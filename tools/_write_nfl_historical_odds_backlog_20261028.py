"""NFL/CFB historical odds backlog options. Research HTML only.

Does not place, cancel, or sell. Does not print secrets.
Does not touch live_game_pollers or live_strategy_b send paths.
Does not retune live systems. Does not regenerate the mixed decile.
Not gold. Not DailyRun.
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

import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "nfl_historical_odds_backlog_20261028.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/nfl_historical_odds_backlog_20261028.html"
)
DECILE = "sport_league_t0_decile_20261027.html"

ASKED = (
    "Paul: “is there any way for you to get these betting odds from a historical "
    "perspective? let's say for pro football, moneyline, spreads and or points total? "
    "I know we've only been tracking for less than 2 weeks. but having a bigger backlog "
    "of data that we could run the decile report on would be helpful.”"
)
PLAIN = (
    "The decile page asks: when a named side was listed at 10 cents, 40 cents, 80 cents "
    "at the start of the game, how often did that side actually win, after the taker fee? "
    "Today that start price (T0) is the last Yes <em>ask</em> we stored at a trusted kickoff "
    "clock on Kalshi, Gemini, Polymarket, or Novig — not a sportsbook moneyline, and not "
    "the live A–E kitchen. We have only been writing that tape since 17 Oct 2026, so NFL "
    "moneyline is still a handful of tickets. This page is the shopping list for a bigger "
    "backlog: which venues already publish old game-start prices for free, which ones cost "
    "money, and which numbers would be the wrong kind of odds if we dropped them into the "
    "same table. We did not buy a paid dump. We did not mix sportsbook closes into the "
    "decile. Research only. Not gold. Not DailyRun."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], caption: str = "") -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    cap = f'<p class="note">{caption}</p>' if caption else ""
    return (
        f"{cap}{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def write_page() -> Path:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")

    current = table(
        [
            ("League", "text"),
            ("Bet type", "text"),
            ("N settled named Yes", "num"),
            ("Wins", "num"),
            ("Win%", "num"),
            ("N with fee", "num"),
            ("Note", "text"),
        ],
        [
            [esc("NFL"), esc("Moneyline"), "7", "3", "42.9", "7", esc("tiny N")],
            [esc("NFL"), esc("Spread"), "114", "19", "16.7", "114", esc("many alternate lines")],
            [esc("NFL"), esc("Points Total"), "138", "52", "37.7", "138", esc("over/under on combined score")],
            [esc("NFL"), esc("ALL bet types"), "259", "74", "28.6", "259", esc("sum of the three rows")],
            [esc("CFB"), esc("Moneyline"), "38", "17", "44.7", "38", ""],
            [esc("CFB"), esc("Spread"), "469", "130", "27.7", "469", ""],
            [esc("CFB"), esc("Points Total"), "267", "87", "32.6", "267", ""],
            [esc("CFB"), esc("ALL bet types"), "774", "234", "30.2", "774", esc("sum of the three rows")],
            [esc("ALL sports"), esc("ALL bet types"), "1720", "542", "31.5", "1614", esc("Novig in win% only; P&L omits undocumented fee")],
        ],
        "Click column headers to sort. From sport_league_t0_decile_20261027.html written 2026-10-28 16:34 ET. "
        "Each row is one named Yes after one-venue pick. Points Total is the points market, not a subtotal of Spread plus Moneyline.",
    )

    fields = table(
        [
            ("Field", "text"),
            ("What it is", "text"),
            ("Used in the decile?", "text"),
        ],
        [
            [esc("sport / league"), esc("pro football → NFL; college football → CFB"), esc("Yes")],
            [esc("kind"), esc("moneyline, spread, total (shown as Points Total), team_total"), esc("Yes (team total not in this NFL slice)")],
            [esc("number"), esc("Spread or total line (3.5, 47.5). Empty on moneyline."), esc("Grain only")],
            [esc("venue"), esc("Kalshi, Gemini, Polymarket, Novig. One venue per game-line-side; documented-fee first."), esc("Yes")],
            [esc("t0_fav / t0_a / t0_b"), esc("Named Yes ask at T0, 0–1 dollars."), esc("Yes — this is the decile price")],
            [esc("t0_ts / clock / t0_source"), esc("Trusted kickoff: Kalshi/Gemini occurrence, else listed/feed with seconds=00."), esc("Yes")],
            [esc("t0_label"), esc("last two-sided Yes ≤ clock, or mixed pre-start + first in-game"), esc("Audit")],
            [esc("skip"), esc("no_trusted_clock, clock_hides_match, no_t0_quotes, t0_50_50"), esc("Dropped")],
            [esc("off_a / off_b / result"), esc("Settlement: Kalshi result, Gemini resolutionSide, Polymarket closed 0/1"), esc("Win/loss")],
            [esc("documented taker fee"), esc("Kalshi/Gemini 0.07×p×(1−p); Polymarket theta; Novig omitted from $ P&L"), esc("With-fee P&L")],
        ],
        "Click column headers to sort. Source: tools/t0_all_games_stats.py assign_t0_prices / pick_trusted_clock, "
        "tools/_write_sport_league_t0_decile_20261027.py explode_cover_yes_sides + pick_one_side.",
    )

    t0def = table(
        [
            ("Piece", "text"),
            ("This tape", "text"),
            ("Lookalike that is NOT T0", "text"),
        ],
        [
            [
                esc("Clock"),
                esc("Kalshi/Gemini occurrence (odd seconds still count), else listed/feed timestamp whose seconds are 00."),
                esc("First competitive two-sided Yes. Tape-resume after a quiet hour. Polymarket 23:12:40Z feed stamp."),
            ],
            [
                esc("Price"),
                esc("Last two-sided Yes ask at or before that clock; else mixed pre-start + first in-game quotes."),
                esc("Last trade. Sportsbook American close. Daily OHLC close. 12-hour candle."),
            ],
            [
                esc("Side"),
                esc("Named Yes (favorite and dog). Both cover-Yes on a two-sided line."),
                esc("Buy-No inverted. Sportsbook favorite juice. Consensus line from five books."),
            ],
            [
                esc("Win"),
                esc("That named Yes settled YES on the same venue market."),
                esc("Team won the game but this spread/total lost. Sportsbook graded a different number."),
            ],
        ],
        "Click column headers to sort.",
    )

    venues = table(
        [
            ("Venue", "text"),
            ("Historical game-start Yes ask?", "text"),
            ("Free this week?", "text"),
            ("What we actually fetched", "text"),
            ("Fit for this decile", "text"),
        ],
        [
            [
                esc("Kalshi"),
                esc("Yes — 1-minute candlesticks include yes_ask OHLC. Clock = occurrence_datetime, else expected_expiration_time."),
                esc("Yes. Public, no auth. GET /historical/trades also public for fills before the cutoff."),
                esc("Cutoff 2026-08-29T00:00:00Z (markets/trades). 488 settled KXNFLGAME events from 2025-07-31 through 2026-10-26. Nested 2026 KC–SEA: 2 ML, 26 spread, 21 Points Total markets. 2025 PHI game lives on GET /historical/markets (live nested markets empty). 680 live 1-min candles around KC–SEA. Historical 60-min candles on 2025-09-21 PHI."),
                esc("Best match. Same Yes ask, same result field, same fee formula."),
            ],
            [
                esc("Polymarket (global CLOB / Gamma / Data API v2)"),
                esc("Partial — price history is last-trade p, not Yes ask. startTime on the event is a kickoff. 1-min windows work; interval=max 12-hour buckets are too coarse for T0."),
                esc("Yes. gamma-api.polymarket.com and clob.polymarket.com, no auth."),
                esc("NFL series_id 12185: 463 closed events, start 2026-08-07 to 2026-10-27, 64,854 nested markets (props included). CLOB prices-history startTs/endTs returned 21,491 1-min points for one token. Data API v2 interval=max was 12-hour (66 points). CLOB interval=max was empty."),
                esc("Separate tape, labeled last-trade. Do not blend with Kalshi T0 ask. Live kitchen is Polymarket US, not clob.polymarket.com."),
            ],
            [
                esc("Novig"),
                esc("Candles yes (1m/5m/1h/1d) on signed GET /v3/history/markets/{id}/candles. Public daily CSV is daily OHLC close, not kickoff ask."),
                esc("Public CSVs yes (data.novig.com, 2026-08-03 through 2026-10-27). Minute candles need the key we already have; no new card."),
                esc("index.json: 86 trade dates, 85 market dates. 2026-10-25 markets.csv: 262,780 rows, 10,939 NFL (820 TOTAL, 808 SPREAD, mostly player props)."),
                esc("Signed 1-min candles could be a Novig-only T0 cousin. Daily CSV close is not T0. Still no documented fee on the current decile, so Novig stays win% only until the fee row is wired."),
            ],
            [
                esc("Gemini"),
                esc("No documented sports prediction-market candlesticks. GET /v2/klines is crypto reference indices. GET /v1/trades/{symbol} is spot crypto, 7-day window."),
                esc("List settled events is a public status filter (active / approved / under_review / settled). Settled football returned HTTP 503 today."),
                esc("Active sports list works. Settled american_football: 503 Service temporarily unavailable. User order history is authenticated fills only, not the public book."),
                esc("Keep the live tape. Do not pretend Gemini has a free NFL T0 archive."),
            ],
        ],
        "Click column headers to sort. Docs fetched 2026-10-28: docs.kalshi.com/getting_started/historical_data, "
        "docs.polymarket.com/api-reference/markets/get-prices-history, docs.polymarket.com/api-reference/markets/get-a-tokens-price-history, "
        "docs.novig.com/public-data/overview, developer.gemini.com/prediction-markets/market-data.",
    )

    books = table(
        [
            ("Source", "text"),
            ("NFL ML / spread / Points Total history?", "text"),
            ("Cost (published)", "text"),
            ("Mismatch vs Kalshi T0 Yes ask", "text"),
            ("Use in this decile?", "text"),
        ],
        [
            [
                esc("The Odds API historical snapshots"),
                esc("Yes. Featured h2h / spreads / totals from 2020-06-06; 10-min then 5-min snapshots from 2022-09. Opening/closing reconstructed from first and last pre-game snapshot."),
                esc("Historical archive is Business $99/mo (published 2026-07-03). Free tier: 25 req/day, current NFL/NBA/MLB moneyline only, no history."),
                esc("Sportsbook American (or decimal) close ≠ 0–1 Yes ask. Juice, hold, and which book you pick all move the number. A −150 favorite is not a 0.60 Kalshi Yes."),
                esc("No. Separate sportsbook study only."),
            ],
            [
                esc("SportsDataIO"),
                esc("Yes. NFL pre-game / in-play / futures from 2019; opening and closing plus line movement. Archive key for props/futures older than 30 days."),
                esc("Paid. Sales / custom. No public self-serve dollar amount on the historical-odds page."),
                esc("Same sportsbook ≠ prediction-market T0 problem. Their own docs: archive is coverage history, not a full as-of book for every correction."),
                esc("No. Separate sportsbook study only."),
            ],
            [
                esc("Covers Sports Odds History"),
                esc("Website archive of sportsbook lines / results (opening numbers in recap prose). Not a documented bulk API."),
                esc("Free to browse; scraping is not a clean PIT feed."),
                esc("Consensus sportsbook line, not a Kalshi Yes ask at occurrence."),
                esc("No."),
            ],
            [
                esc("Already in this repo"),
                esc("No paid sportsbook dump. No parquet. Local price_memory.jsonl (1.87 GB archive through 2026-10-21 11:34 ET) plus dated shards 2026-10-21–28. Settlement cache is this October only."),
                esc("Already paid with disk, not a card."),
                esc("This is the current T0 tape, not a backlog."),
                esc("Already in the decile. Do not mix in sportsbook files later without a source flag."),
            ],
        ],
        "Click column headers to sort. Odds API: https://the-odds-api.com/historical-odds-data/ and https://theoddsapi.com/pricing. "
        "SportsDataIO: https://sportsdata.io/historical-odds and https://sportsdata.io/help/historical-data-integration-guide. "
        "Covers: https://www.covers.com/sportsoddshistory/.",
    )

    week = table(
        [
            ("Job", "text"),
            ("Bet types", "text"),
            ("Est. seasons / N", "text"),
            ("T0-like?", "text"),
            ("Effort", "text"),
        ],
        [
            [
                esc("1. Kalshi NFL moneyline T0 reconstruct (do this first)"),
                esc("Moneyline only, both named Yes"),
                esc("~1.25 seasons (2025-07-31 preseason through 2026-10-26). 488 settled events × 2 sides ≈ 976 named Yes."),
                esc("Yes. 1-min yes_ask.close at occurrence_datetime or expected_expiration_time. result=yes/no is settlement."),
                esc("One throttled public crawl. We already 429’d when we went too fast. Recent games: live candlesticks. Pre-2026-08-29: GET /historical/markets + /historical/markets/{ticker}/candlesticks."),
            ],
            [
                esc("2. Kalshi NFL primary spread + Points Total"),
                esc("One main spread and one main total per game, both sides — not every alternate line"),
                esc("457 settled spread events + 457 Points Total events. Primary-only ≈ 900–1,000 Yes each (~1,800 combined). All-alts on KC–SEA were 26 spread + 21 total for one game, so all-alts would be ~10k–12k spread Yes."),
                esc("Yes, same candle recipe. Freeze “primary” as the line nearest 50¢ at T0 so we do not change the grain later."),
                esc("Same crawl, more tickers. Still free. Label alternate-line books as a third freeze if Paul wants them."),
            ],
            [
                esc("3. Kalshi CFB same recipe"),
                esc("Moneyline, then primary spread / Points Total"),
                esc("KXNCAAFGAME settled: at least 200 events on one page (cursor still open). KXNCAAFSPREAD ≥200. 2026 season titles back through mid-October; full 2025 CFB likely similar to NFL once paged."),
                esc("Yes."),
                esc("Same as NFL. Do not pool CFB into NFL rows."),
            ],
            [
                esc("4. Polymarket 2026 NFL last-trade tape (flagged)"),
                esc("Filter Gamma NFL series 12185 to moneyline / spread / Points Total; drop player props and first-TD"),
                esc("463 closed events, 2026-08-07 to 2026-10-27. After dropping props, on the order of a 2026 season of games (not 2025)."),
                esc("No — last-trade, and global CLOB ≠ Polymarket US. Only a T0 cousin if we take the last p at startTime with 1-min fidelity, never 12-hour interval=max."),
                esc("Free. Write a second HTML, not a silent append to sport_league_t0_decile."),
            ],
            [
                esc("5. Novig public daily CSV / signed 1-min candles"),
                esc("NFL SPREAD and TOTAL are in the CSV; player props dominate row counts"),
                esc("Public files from 2026-08-03 (about 12 weeks). One Sunday: 808 NFL SPREAD + 820 NFL TOTAL rows (many alts)."),
                esc("Daily close ≠ T0. Signed 1-min candles (key already on disk) could be Novig-T0. Do not print keys."),
                esc("Optional. Win% only on the current fee rules until Novig P&L is documented on this tape."),
            ],
            [
                esc("6. Sportsbook historical (Odds API / SportsDataIO)"),
                esc("ML, spread, Points Total opening and closing"),
                esc("Odds API: NFL from mid-2020. SportsDataIO: from 2019. Years of games, hundreds per season."),
                esc("No. Sportsbook close ≠ Kalshi T0 Yes ask."),
                esc("Do not buy this week. If Paul wants a sportsbook calibration page later, new stamp, new flag, never mixed into this decile."),
            ],
        ],
        "Click column headers to sort. N is named Yes sides, the same grain as the decile (both teams / over and under), not unique games. "
        "We did not regenerate the decile with mixed data in this job.",
    )

    rec = table(
        [
            ("#", "num"),
            ("Source", "text"),
            ("Bet type", "text"),
            ("Do", "text"),
            ("Do not", "text"),
        ],
        [
            [
                "1",
                esc("Kalshi candlesticks"),
                esc("NFL moneyline first, then primary spread, then Points Total. CFB after NFL ML looks sane."),
                esc("Reconstruct T0 as last yes_ask.close at occurrence_datetime or expected_expiration_time. Keep result as win. New stamp, research-only."),
                esc("Do not drop this into sport_league_t0_decile without a source=kalshi_hist_candle column. Do not retune live D/C/stake."),
            ],
            [
                "2",
                esc("Polymarket CLOB 1-min (2026)"),
                esc("NFL ML / spread / Points Total on series 12185, props stripped"),
                esc("Second tape. Label last-trade and global CLOB vs US."),
                esc("Do not use interval=max 12-hour points as T0. Do not blend with Kalshi Yes ask."),
            ],
            [
                "3",
                esc("Sportsbooks (Odds API, SportsDataIO, Covers)"),
                esc("Any"),
                esc("Leave on the shelf unless Paul asks for a separate sportsbook calibration page."),
                esc("Do not mix a DraftKings close or a consensus open into the prediction-market decile. That would answer a different question with the same 0–9 / 40–49 labels."),
            ],
        ],
        "Click column headers to sort.",
    )

    cites = table(
        [
            ("Doc", "text"),
            ("URL", "text"),
            ("What it proved today", "text"),
        ],
        [
            [esc("Kalshi historical data"), esc("https://docs.kalshi.com/getting_started/historical_data"), esc("Live vs historical partition; cutoff fields")],
            [esc("Kalshi historical trades"), esc("https://docs.kalshi.com/api-reference/historical/get-historical-trades"), esc("Public, no auth, pre-cutoff fills")],
            [esc("Kalshi candlesticks"), esc("https://docs.kalshi.com/api-reference/market/get-market-candlesticks"), esc("yes_ask OHLC; 1 / 60 / 1440 min")],
            [esc("Polymarket CLOB prices-history"), esc("https://docs.polymarket.com/api-reference/markets/get-prices-history"), esc("market=token, startTs/endTs, fidelity minutes")],
            [esc("Polymarket Data API v2 prices"), esc("https://docs.polymarket.com/api-reference/markets/get-a-tokens-price-history"), esc("12-hour permanent series; 1-min only recent")],
            [esc("Novig public CSVs"), esc("https://docs.novig.com/public-data/overview"), esc("Daily trades + markets OHLC at data.novig.com")],
            [esc("Novig candles"), esc("https://docs.novig.com/api/catalog"), esc("Signed 1m candles, 4096-interval cap")],
            [esc("Gemini PM market data"), esc("https://developer.gemini.com/prediction-markets/market-data"), esc("No sports historical candles; klines are crypto")],
            [esc("Odds API historical"), esc("https://the-odds-api.com/historical-odds-data/"), esc("Paid snapshots from 2020; NFL ML/spread/totals")],
            [esc("Odds API pricing"), esc("https://theoddsapi.com/pricing"), esc("History on Business $99/mo; free = current ML only")],
            [esc("SportsDataIO historical odds"), esc("https://sportsdata.io/historical-odds"), esc("NFL from 2019; paid / sales")],
        ],
        "Click column headers to sort. Live probes also hit api.elections.kalshi.com, gamma-api.polymarket.com, clob.polymarket.com, data-api.polymarket.com, data.novig.com, api.gemini.com.",
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>NFL historical odds backlog — can we grow the T0 decile?</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.keep {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
ol.rec {{ padding-left: 1.2rem; }}
ol.rec li {{ margin: 0.35rem 0; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>NFL historical odds backlog — options for a bigger T0 decile</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. Did not retune live systems.
Did not touch live_game_pollers or live_strategy_b send paths. Did not buy a paid dump. Did not regenerate
<a href="{esc(DECILE)}">{esc(DECILE)}</a> with mixed data.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{PLAIN}</p></div>

<div class="keep">
<h2>Recommendation (three bullets)</h2>
<ol class="rec">
<li><strong>Kalshi 1-minute Yes ask at kickoff</strong> is the only free source that matches this decile’s T0
(named Yes ask at a trusted clock, same <code>result</code> settlement, same fee). Start with NFL moneyline
(~976 named Yes, 2025 season plus 2026 through 26 Oct). Then freeze a primary spread and a primary Points Total.
New stamp. Do not silently append to the live tape.</li>
<li><strong>Polymarket 2026 last-trade history</strong> is a useful second tape (Gamma NFL series + CLOB 1-minute
windows), but it is last-trade on the global book, not Polymarket US Yes ask. Keep it flagged. Never average it
into Kalshi T0 bands.</li>
<li><strong>Do not mix sportsbook opening/closing lines</strong> (Odds API, SportsDataIO, Covers) into this decile.
A DraftKings close is a different product: American odds, juice, a different clock. If we want that study later,
it is a new page with an explicit sportsbook flag — and it costs money we did not spend this week.</li>
</ol>
</div>

<div class="warn">
<p><strong>Mismatch, in one line:</strong> sportsbook close ≠ Kalshi T0 Yes ask.
Mixing them into the same 0–9 / 40–49 / 90–99 table without a source flag would make win% look like
calibration of our tape when it is really a different market.</p>
</div>

<h2>1. What the current decile tape actually stores</h2>
<p class="note">Tape name <code>research_named_yes_t0</code>. Not the live A–E kitchen.
Tick span on the all-game stats page: <strong>2026-10-17 20:55 ET through 2026-10-28 16:18 ET</strong>
(~11 days, less than two weeks). Streamed 17.95 million lines / 8.60 million Yes ticks.
Settled unique-game-side tickets on the decile: 1,720 of 10,698 picked sides.
Every T0 is after 2024-01-01, so there is no in-sample row. Annualized rate of return is omitted on
this tape because average hold is a fraction of a day (house formula would overflow).</p>
{current}

<h2>T0 definition (this tape)</h2>
{t0def}

<h2>Fields on each book</h2>
{fields}

<h2>2. Can the four venues give historical game-start Yes prices?</h2>
{venues}

<p class="note">Kalshi routing that worked today: settled events still list on
<code>GET /trade-api/v2/events?series_ticker=KXNFLGAME&amp;status=settled</code> (docs: old events stay on
the original events endpoint). Nested markets for a <em>recent</em> game come back on that event.
A 2025-09-21 game returned zero nested markets on the live event; the two Philadelphia/Los Angeles
Yes contracts were on <code>GET /historical/markets?event_ticker=…</code>, and 60-minute
<code>GET /historical/markets/{{ticker}}/candlesticks</code> returned yes_ask OHLC.
<code>occurrence_datetime</code> was present on the 2026 KC–SEA moneyline (2026-10-26T03:20:00Z) and
missing on the 2025 PHI market — there use <code>expected_expiration_time</code> (2025-09-21T20:00:00Z),
which is the same :00 listed clock the live tape already trusts.</p>

<h2>3. Sportsbook historical lines — available, paid, wrong grain</h2>
{books}

<h2>4. Practical backlog we can build this week without a credit card</h2>
{week}

<p class="note">Local files already on disk, not a new purchase: <code>local/…/raw/price_memory.jsonl</code>
(1.87 GB, frozen 2026-10-21 11:34 ET), dated shards 2026-10-21–28 (pro_football.jsonl is large on NFL
Sundays: 228 MB on 2026-10-25), <code>odds_cross_settlements_20261020.json</code> (NFL 1,249 rows / 63 games,
occurrence 2026-10-18 to 2026-10-20 in that cache; CFB 4,766 rows / 349 games), plus this week’s
per-game <code>nfl_*_kalshi.json</code> / <code>nfl_*_gemini.json</code> snapshots. No parquet.
No Odds API dump. Those local files do not add seasons; they are the two-week tape.</p>

<h2>5. If we reconstruct a T0-like snapshot — years and N</h2>
<p class="note">Kalshi listed NFL single-game markets for the 2025 season (Week 1 markets posted
29 May 2025; first settled GAME ticker in the archive walk is 2025-07-31 preseason). Public event
list today: 488 settled <code>KXNFLGAME</code> from 2025-07-31 through 2026-10-26. That is one full
NFL season plus 2026 through late October, including preseason. Gemini and Novig do not add extra
years for free. Polymarket NFL series 12185 closed events start 2026-08-07 (2026 season, not 2025).
Sportsbook vendors go back to 2019–2020 but are the wrong price type.</p>

<div class="callout">
<p><strong>Headcount if we freeze Kalshi primary lines only</strong> (both named Yes, ML + one spread +
one Points Total): about <strong>2,800 NFL tickets</strong> over ~1.25 seasons — roughly 10× today’s
NFL N=259, and enough to put several deciles above N=20. All alternate Kalshi lines would be much
larger (one KC–SEA game already had 26 spread + 21 total markets) and would change the grain of the
current tape, so that is a different freeze. CFB is at least another 200 settled moneyline events
still paging. Polymarket 2026 last-trade, separately labeled, is on the order of one NFL season after
props are dropped.</p>
</div>

<h2>Recommendation table</h2>
{rec}

<h2>Docs and live probes</h2>
{cites}

<p class="tiny">Generator: <code>tools/_write_nfl_historical_odds_backlog_20261028.py</code>.
Decile left untouched: <a href="{esc(DECILE)}">{esc(DECILE)}</a>.
File URL {esc(FILE_URL)}. Did not sell, start a second B, bump stake, wire D NFL, leftover GTC,
or retune C=1.05. Did not commit.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    return PAGE


def main() -> int:
    path = write_page()
    print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
