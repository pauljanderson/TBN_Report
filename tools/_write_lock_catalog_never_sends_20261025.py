"""What catalog means, and why those looks never send.

Research only. Does not place, cancel, flatten, or sell. Does not print secrets.
Does not start a second live_strategy_b.py. Does not bump NET_MAX.
"""
from __future__ import annotations

import html as html_lib
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import opportunity_considerations  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

PAGE = STAMP / "lock_catalog_never_sends_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/lock_catalog_never_sends_20261025.html"
)
ASKED = (
    "what does catalog mean, and why would we skip those?"
)
PLAIN = (
    "Catalog is the phone book of saved games, plus a slow walker that reads those "
    "books over the public web. It is not the in-play helper sitting on a live game. "
    "We skip catalog rows because that walker is not allowed to buy — even at 0.97. "
    "The only send path is a live game poller, and that path still re-reads both books "
    "and posts one contract, thinner side first. Indianapolis vs Minnesota moneyline "
    "0.9800 at 13:29:43 was a true under-cap catalog look. A live helper on that same "
    "game had already seen cheaper pairs eight minutes earlier and skipped them because "
    "the three-open cap was full, so we do not claim 0.9800 would have sent."
)


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def write_page() -> Path:
    line = live_lock_orders.send_line()
    skip = opportunity_considerations.catalog_eligible_reason(Decimal("0.9800"))
    jobs = table(
        [("Job", "text"), ("Process / file", "text"), ("What it does", "text"), ("Sends?", "text")],
        [
            [
                esc("Catalog (the phone book)"),
                esc("Saved matched lists: sports_queue.json, cfb_game_list.json"),
                esc(
                    "Kalshi, Gemini, Polymarket US, and Novig tickers for the same game "
                    "(who wins, spread, total). Tennis lives on the live poller list, not this walk."
                ),
                esc("No"),
            ],
            [
                esc("Catalog scan (the walker)"),
                esc("overnight_scan.py via prediction_job_control “catalog scan”"),
                esc(
                    "Walks those saved lists with public REST GETs. Logs cheap pairs. "
                    "Recent pids: 30972 (job_status now), 64264 (0.99 / ghost-cap reload). "
                    "Paul also named 60364."
                ),
                esc("Never"),
            ],
            [
                esc("Live poller (in-play helper)"),
                esc("live_game_pollers.py --poll-one, started by the supervisor"),
                esc(
                    "One helper per game that has started and is still inside a typical length "
                    "(about 3.5 hours for NFL). Websocket ticks; 5-second HTTP if the stream is down."
                ),
                esc("Yes, if every send gate still passes"),
            ],
        ],
    )
    look = table(
        [
            ("Time ET", "date"),
            ("Game", "text"),
            ("Bet", "text"),
            ("Venues", "text"),
            ("Yes / No", "text"),
            ("Sizes", "text"),
            ("Send-check net", "num"),
            ("Source", "text"),
            ("Logged skip", "text"),
            ("If a live poller had the same quote", "text"),
        ],
        [
            [
                esc("2026-10-25 13:29:43"),
                esc("Indianapolis vs Minnesota"),
                esc("moneyline, Minnesota wins"),
                esc("Yes Kalshi / No Polymarket"),
                esc("0.57 / 0.39"),
                esc("68894.67 / 13386.58"),
                esc("0.9800"),
                esc("catalog scan"),
                esc(
                    "This is the catalog scan; it never sends. Live pollers send when "
                    "after-fee cost is at or under 0.984 (from NET_MAX). After-fee cost "
                    "on this look is 0.98."
                ),
                esc(
                    "Net 0.9800 was under the then-0.984 cap, and both sizes were ≥ 1. "
                    "That is not enough to send. Same-game live looks at 13:21:59 with "
                    "cheaper nets (0.89440, 0.95440) were denied “Already have 3 open "
                    "lock pair(s); max_open_locks=3.” REST recheck before send can still "
                    "fail. Do not claim this would have sent."
                ),
            ],
            [
                esc("2026-10-25 13:44:27"),
                esc("San Francisco vs Atlanta"),
                esc("spread, SF 10.5"),
                esc("Yes Novig / No Kalshi"),
                esc("0.38 / 0.59"),
                esc("3736 / 5322"),
                esc("0.98414"),
                esc("catalog scan"),
                esc("catalog never sends, and unrounded net was over the then-0.984 cap"),
                esc(
                    "Live would also skip on net: 0.98414 > 0.984. Cap is 0.99 now; "
                    "this page does not retro-send."
                ),
            ],
        ],
    )
    send = table(
        [("Gate", "text"), ("Catalog scan", "text"), ("Live poller send path", "text")],
        [
            [
                esc("Who runs it"),
                esc("overnight_scan.py, one process walking saved lists"),
                esc("live_game_pollers.py --poll-one, one process per in-play game"),
            ],
            [
                esc("Quotes"),
                esc("Public REST GET (Gemini event, then Kalshi, then Poly, then Novig)"),
                esc("Websocket on each tick; HTTP seed; ~5s HTTP fallback if the stream is down"),
            ],
            [
                esc("How often"),
                esc(
                    "As fast as paced HTTP allows (Gemini about 1/s, Kalshi about 2/s) "
                    "across the whole list. Under-$1 watches re-pull every 120 seconds, max 3."
                ),
                esc("Every book update (~0.05s burst collapse). Supervisor looks for new live games about every 60s."),
            ],
            [
                esc("REST book recheck before send"),
                esc("No — it never sends, so it never rechecks for an order"),
                esc("Yes, both books, immediately before either HTTP leaves"),
            ],
            [
                esc("1 contract, sequential hard-first"),
                esc("No"),
                esc("Yes. Thinner REST ask first. Easy leg only if hard filled and the gap is still legal."),
            ],
            [
                esc("After-fee cap (NET_MAX)"),
                esc("Logged if ≤ 0.99; still denied as catalog"),
                esc(f"Must be ≤ live send line ({line}) after fees"),
            ],
            [
                esc("Open-slot / leftover / halt"),
                esc("Not applied (no send)"),
                esc("Applied. Ghost 3-open was a real live deny on Indianapolis at 13:21."),
            ],
            [
                esc("Code gate"),
                esc("record_catalog() sets source=catalog scan and always logs denied"),
                esc("execute_locks() from _maybe_lock_orders() only"),
            ],
        ],
    )
    body = f"""
<h1>What catalog means, and why we skip those</h1>
<p class="note">America/New_York. Research only. Not gold. Not DailyRun. Did not sell. Did not bump the send cap. Did not start a second Tennis crossover. Live send cap now is <strong>{esc(line)}</strong>.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>
<p class="note">Related: <a href="opportunities.html">opportunities.html</a> ·
<a href="lock_098_deny_rounding_20261025.html">lock_098_deny_rounding_20261025.html</a> ·
<a href="lock_ghost_open_cap_20261025.html">lock_ghost_open_cap_20261025.html</a> ·
<a href="job_status.html">job_status.html</a>. Click column headers to sort.</p>
<h2>One sentence</h2>
<p>Catalog is the saved list of games plus a public-web walker that only logs prices; we skip those rows because that walker is not the buyer.</p>
<h2>The two jobs</h2>
{jobs}
<h2>Why catalog never sends</h2>
<p>Not because the quote failed a send check. The catalog process never calls the order sender. The overnight scan file says public GETs only, no orders. The log helper <code>record_catalog</code> stamps <code>source = catalog scan</code> and writes denied with this sentence:</p>
<blockquote>{esc(skip)}</blockquote>
<p>That is supervisor design: one process refreshes the phone book; a different process (in-play pollers) is the only send path. Catalog quotes can be older because they are paced REST over the whole list, not a live stream, and there is no 1-contract REST recheck or hard-first on that pass — those steps exist only on the send path. Catalog is not wrongly blocking a live in-play look: a live helper still runs <code>execute_locks</code> on its own.</p>
<h2>When a look actually sends</h2>
{send}
<h2>The rows Paul saw</h2>
{look}
<p class="note">Send-check net is Yes ask + No ask + documented taker fees on Gemini / Polymarket / Novig. Kalshi is $0 on that check. Compare is Decimal, not rounded to cents first. The Indianapolis catalog fingerprint still stored net as 0.98; the send-check value is 0.9800.</p>
<p class="tiny">Updated {esc(opportunity_considerations._now())}. Live send line {esc(line)}. {esc(FILE_URL)}</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>What catalog means — 25 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
blockquote {{ background: #fff7ed; border-left: 4px solid #fdba74; margin: 0 0 12px; padding: 10px 12px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
{body}
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    page = report_page_extras.inject_report_page_extras(page)
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def main() -> None:
    path = write_page()
    print(path)


if __name__ == "__main__":
    main()
