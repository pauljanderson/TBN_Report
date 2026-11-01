"""Missing-shop skip: omit that venue vs skip the whole game.

Display only. Does not sell. Does not start a second B. Does not leftover-GTC A.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prediction_paths import DRIVE_STAMP as STAMP
from report_page_extras import (
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
)
from write_orders_performance import table

ET = ZoneInfo("America/New_York")
OUT = STAMP / "missing_shop_skip_gaps_20261030.html"

PAUL = (
    "i don't understand this. The exception is the catalog walker (not live tennis): "
    "it still requires both a Kalshi and a Gemini ticker before it even looks at "
    "Polymarket or Novig. Blank Gemini there skips the whole catalog game. Tennis "
    "is not on that walk. any of the 4 platforms can be used at any time. explain "
    "this or lighten the rule."
)


def esc(value) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %I:%M %p ET")
    sys_table = table(
        [
            ("Letter", "text"),
            ("System", "text"),
            ("Omit missing shop? (correct)", "text"),
            ("Missing shop kills the whole game?", "text"),
            ("Wait for all 4 shops?", "text"),
            ("Where", "text"),
        ],
        [
            [
                "A live",
                "Lock gap sender + poller",
                "Yes",
                "No",
                "No",
                "has_quote_venues = at least one shop. Extras pair any two shops that have a ticker. Two shops, same settlement.",
            ],
            [
                "A catalog",
                "overnight_scan.scan_one",
                "Yes — matches live",
                "No",
                "No",
                "Fetch Kalshi if present, Gemini if present, then Poly/Novig. Blank shop omitted. Tennis is not in this walk (SPORT_ORDER has no tennis); tennis uses live A.",
            ],
            [
                "B",
                "Tennis crossover",
                "Yes",
                "No",
                "No",
                "Empty Gemini ticker list → no Gemini books. Cheapest Yes per player among shops that have both names.",
            ],
            [
                "C",
                "College football favorite",
                "Yes",
                "No",
                "No",
                "collect_quotes only loads tickers that exist; cheapest Yes among those quotes.",
            ],
            [
                "D",
                "T0 spreads",
                "Yes",
                "No",
                "No",
                "Same collect_quotes. Gemini tennis spreads only if Gemini listed -S.",
            ],
            [
                "E",
                "Tennis T0 dog",
                "Yes",
                "No",
                "No",
                "Same tennis list as B. Gemini omitted when the catalog has no Gemini ticker.",
            ],
            [
                "F",
                "Tennis T0 spread",
                "Yes",
                "No",
                "No",
                "Cheapest spread Yes in [0.20, 0.50) among shops that listed a spread.",
            ],
            [
                "G",
                "Soccer T0 total",
                "Yes",
                "No",
                "No",
                "Cheapest Points Total Yes among shops that listed a total. Tennis is off G.",
            ],
        ],
    )
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>Missing shop skip — catalog matches live — 30 Oct 2026</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
.ok {{ background: #edf8f0; border: 1px solid #9fd0b0; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
pre {{ background: #0f172a; color: #e2e8f0; padding: 12px 14px; overflow: auto; font-size: 0.85em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Missing shop: skip that shop, not the whole game</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {esc(now)}.
Did not commit. Did not start a second B. Did not leftover-GTC A. Did not touch
fee-unknown job b5f50fae or C=1.10456 skip job 0e8158f4.</p>

<div class="callout">
<h2>What you asked</h2>
<p>Paul: “{esc(PAUL)}”</p>
<h2>In plain English</h2>
<p>The catalog walker used to work like an old Kalshi-versus-Gemini phone book:
if either number was missing, it hung up and never dialed Polymarket US or
Novig. Live already treats the four shops as one pool — any two that list the
same question can pair, and a missing shop is simply left out. Catalog now
matches that. Blank Gemini (or blank Kalshi) omits that shop, not the whole
game. A lock still needs two shops and the same settlement, not all four.</p>
<p>Tennis is a separate sentence: it is not on the catalog sport list
(<code>SPORT_ORDER</code>), so tennis gaps already go through live A. This job
did not reload tennis live A and did not start a second B.</p>
</div>

<div class="ok">
<p><strong>Rule lightened (Fri 30 Oct 2026 ~11:04 PM ET).</strong>
<code>overnight_scan.scan_one</code> no longer requires both a Kalshi ticker
and a Gemini ticker before it looks at Polymarket or Novig. It fetches
whichever of those two have a ticker, then merges Poly/Novig the same way live
does. <code>prediction_pair_scan.scan_game</code> had the same hang-up (no
Gemini ticker → skip without fetching Kalshi); it now fetches Kalshi if
present and still merges Poly/Novig. Empty Gemini tennis stays omit-Gemini,
not omit-game.</p>
</div>

<h2>Yes / no by system</h2>
<p>Click column headers to sort.</p>
{sys_table}

<h2>A live — omit the missing shop (correct)</h2>
<p>Poller will quote a game when <em>any</em> shop already has a book. Gemini
blank is not a skip.</p>
<pre>def has_quote_venues(game: dict, scan) -&gt; bool:
    """{esc("True when at least one venue we already poll has a book for this game.")}"""
    k_tickers, g_tickers = scan.tickers_of(game)
    if k_tickers or g_tickers:
        return True
    ... polymarket_markets / novig_markets ...
    return False</pre>
<p><code>live_lock_sender</code> runs whatever candidates the poller wrote. The
Kalshi-vs-Gemini compare is only one pair type. Poly and Novig extras attach
independently:</p>
<pre>def _compared(...):
    result = scan.compare_payloads(game, kalshi_events, gemini_events)
    extra = polymarket_us_live.polymarket_candidates(...)
    extra.extend(novig_live.novig_candidates(...))
    if extra:
        result["candidates"] = list(result.get("candidates") or []) + extra
    return result</pre>
<pre>if kalshi_views:
    rows.extend(_pair_rows(scan, game, "kalshi", kalshi_views, "polymarket", pm_views))
if gemini_views:
    rows.extend(_pair_rows(scan, game, "gemini", gemini_views, "polymarket", pm_views))</pre>
<p>Same pattern for Novig, plus Poly+Novig. Empty Gemini views → those Gemini
rows are not built; Kalshi+Poly still is. Send gate is two distinct shops, not
four:</p>
<pre>def _pair_legs_ok(legs: list[dict]) -&gt; bool:
    """{esc("True when both legs are distinct order venues (Kalshi/Gemini/Polymarket/Novig-when-live).")}"""
    if len(legs) != 2:
        return False
    venues = [str(leg.get("venue") or "") for leg in legs]
    if venues[0] == venues[1]:
        return False</pre>
<p>Module note at the top of <code>live_lock_orders.py</code>: “A qualifying pair
is any two of Kalshi, Gemini, Polymarket, and Novig.”</p>

<h2>A catalog — now the same any-two-of-four rule as live</h2>
<pre>k_tickers, g_tickers = tickers_of(game)
# Blank Kalshi or blank Gemini omits that shop only.
kalshi_events, gemini_events = fetch_pair(game, k_tickers, g_tickers)
polymarket = _read_polymarket(game, kalshi_events, gemini_events)
novig = _read_novig(game, kalshi_events, gemini_events, sport)
result = compare_payloads(game, kalshi_events, gemini_events)
_merge_extra(game, kalshi_events, gemini_events, result, polymarket, novig)</pre>
<p>The old AND-gate
<code>if not k_tickers or not g_tickers: return “A ticker is blank on one venue…”</code>
is gone. An empty Gemini list is a no-op Gemini fetch, then Poly/Novig still
merge. Two shops with the same settlement are still required to send
(<code>live_lock_orders._pair_legs_ok</code> + <code>same_settlement_candidate</code>).
<code>SPORT_ORDER</code> is still pro football, baseball, soccer, golf,
motorsports, mma, hockey, chess — plus college football on its own list.
Tennis is not on that walk; tennis live A was not reloaded.</p>

<h2>B — omit Gemini, still T0 on the shops that exist</h2>
<pre>k_tickers, g_tickers = scan.tickers_of(game) if game else ([], [])
...
if "gemini" in want:
    for ticker in g_tickers:          # empty list → no Gemini HTTP
        gemini_events.append(scan.fetch_gemini_event(ticker))
...
if len(players) &lt; 2:
    continue                         # skip that venue, not the match
...
def pick_cheapest_legs(books):
    """{esc("Min Yes ask per player across venues. Cross-platform pair allowed.")}"""
    ...
    if not _sendable_venue(venue):
        continue
    ...
    if len(best) &lt; 2:
        return None                  # need two players, not four shops</pre>

<h2>C D E F G — same quote collector</h2>
<p><code>live_t0_yes.collect_quotes</code> loads Kalshi/Gemini only for tickers
that exist, then Poly search and Novig from the game. Cheapest Yes
(<code>best_venue_yes</code> / <code>pick_cheapest_spread_yes</code> /
<code>pick_cheapest_total_yes</code>) ranks among quotes that are present.
None of these wait for four shops.</p>
<pre>k_tickers, g_tickers = live_game_pollers.tickers_for_quotes(game, scan, sport)
gemini_events = [scan.fetch_gemini_event(t) for t in g_tickers]
kalshi_events = [scan.fetch_kalshi_event(t) for t in k_tickers]</pre>

<h2>Tennis + Gemini 0 book</h2>
<p>Gemini tennis catalog empty means <code>g_tickers = []</code>. Live A can still
lock Kalshi Yes vs Poly No (same player / same settlement). B/E/F can still T0
on Kalshi+Poly. Tennis is not on the catalog walk, so this lighten is for
college football / NFL / soccer / the other catalog sports: a blank Gemini
ticker no longer drops a Kalshi+Poly (or Kalshi+Novig) gap there either.
Tennis live A is unchanged.</p>

<p class="note">Sources: live_lock_sender.py, live_lock_orders.py, live_game_pollers.py,
overnight_scan.py scan_one / pair_contracts / SPORT_ORDER, polymarket_us_live.polymarket_candidates,
novig_live.novig_candidates, live_strategy_b.py pick_cheapest_legs, live_t0_yes.collect_quotes,
prediction_pair_scan.scan_game. Did not sell. Did not start a second B.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
