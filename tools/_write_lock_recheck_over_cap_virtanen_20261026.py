"""Virtanen over-cap recheck autopsy. Research HTML only. Does not send."""
from __future__ import annotations

import html as html_lib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import opportunity_considerations  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

PAGE = STAMP / "lock_recheck_over_cap_virtanen_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/lock_recheck_over_cap_virtanen_20261026.html"
)

ASKED = (
    "Paul has many “over cap after book recheck” denials. Asks if we’d be better making "
    "individual calls to get prices on each side across all venues. Then: what went wrong "
    "on this look, and how did No size 34568.88 at 0.29 become an unknown size at 0.33?"
)
ROW = (
    "2026-10-26T14:47:34-04:00 tennis Martineau vs Virtanen moneyline Otto Virtanen wins  "
    "Yes kalshi / No polymarket  0.67  0.29  6063  34568.88  0.9700  denied  over cap after "
    "book recheck limit=0.68 other=0.33 gross=1.01 fee=0 other_fee=0.02 net=1.0300 cap gross "
    "under 1 net at or under 0.99"
)
PLAIN = (
    "This look was the in-play tennis helper, not the catalog walker. Websocket said "
    "Kalshi Yes 67¢ and Polymarket US No 29¢, after-fee 97¢, with thousands of contracts "
    "showing. Before any buy, we always download both live books. Kalshi Yes had ticked "
    "to 68¢. The Polymarket No ask — the same long-side offer as Martineau Yes — had "
    "walked from 29¢ to 33¢. 68¢ + 33¢ + a 2¢ Polymarket taker fee = $1.03, over the 99¢ "
    "send line, so nothing was posted. 34,568.88 was the websocket size on that 29¢ offer, "
    "not dollars and not stacked worse prices. The 33¢ REST offer still had size "
    "(37,676.90). We just never wrote that size on the skip line. Extra per-side HTTP "
    "calls would not have kept 29¢: eight seconds after the tick, REST still showed 29¢; "
    "forty-four seconds later that offer was gone. HOLD on the fetch path. Live already "
    "downloads both books in parallel. Skip lines now name both REST sizes."
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
    clock = table(
        [("When (ET)", "date"), ("What", "text"), ("Source", "text"), ("Price / size", "text")],
        [
            [
                esc("14:45:41.242"),
                esc("Polymarket US Martineau Yes ask (Virtanen No) prints 0.29"),
                esc("Websocket tick"),
                esc("0.2900; displayed size 34568.88 contracts on the live compare"),
            ],
            [
                esc("14:45:48.020"),
                esc("Claim 1: Martineau Yes Poly / No Kalshi, net 0.9700"),
                esc("Live poller pid 53584"),
                esc("Poly Yes 0.29 + Kalshi No 0.67"),
            ],
            [
                esc("14:45:49"),
                esc("REST recheck claim 1"),
                esc("GET Kalshi MAR orderbook + GET Poly book"),
                esc("Poly offer still 0.29 size 31956.78. Kalshi No ask 0.74 (1 − Yes bid 0.26). Denied."),
            ],
            [
                esc("14:46:30.903"),
                esc("Claim 2 (Paul’s row): Virtanen Yes Kalshi / No Poly, net 0.9700"),
                esc("Same live poller, still the 14:45:41 Poly print"),
                esc("Kalshi Yes 0.67 size 6063 + Poly No 0.29 size 34568.88"),
            ],
            [
                esc("14:46:32"),
                esc("Kalshi VIR orderbook GET"),
                esc("REST /orderbook"),
                esc("No bid 0.32 size 27351.52 → Yes ask 0.68"),
            ],
            [
                esc("14:46:33"),
                esc("Polymarket US book GET"),
                esc("REST /v1/markets/…/book"),
                esc("Best offer 0.33 size 37676.90. 0.29 offer gone."),
            ],
            [
                esc("14:46:33.187"),
                esc("Skip: over cap after book recheck"),
                esc("orders.jsonl"),
                esc("limit=0.68 other=0.33 gross=1.01 fee=0 other_fee=0.02 net=1.0300"),
            ],
            [
                esc("14:47:34"),
                esc("Opportunities row timestamp Paul quoted"),
                esc("considerations.json"),
                esc("Same deny; first-look sizes kept; REST Poly size not written"),
            ],
        ],
    )
    books = table(
        [
            ("Book", "text"),
            ("When", "date"),
            ("Field used", "text"),
            ("Best", "num"),
            ("Size at that level", "num"),
            ("Next levels", "text"),
        ],
        [
            [
                esc("Poly offers (Virtanen No = Martineau Yes ask, BUY_LONG)"),
                esc("14:45:49"),
                esc("offers[0] px.value / qty"),
                esc("0.29"),
                esc("31956.78"),
                esc("0.30 / 31809.49; 0.31 / 4640; 0.32 / 2828; 0.33 / 1058"),
            ],
            [
                esc("Poly offers"),
                esc("14:46:33"),
                esc("offers[0] px.value / qty"),
                esc("0.33"),
                esc("37676.90"),
                esc("0.34 / 33233.97; 0.35 / 41119.60. No 0.29 offer left."),
            ],
            [
                esc("Poly bids (Yes bid; 1 − bid would be BUY_SHORT No)"),
                esc("14:46:33"),
                esc("bids[0] (not used for this No)"),
                esc("0.32"),
                esc("40928.23"),
                esc("1 − 0.32 = 0.68. That is not the 0.33 we logged."),
            ],
            [
                esc("Kalshi VIR Yes (1 − no_dollars best bid)"),
                esc("14:46:32"),
                esc("orderbook_fp.no_dollars best"),
                esc("0.68"),
                esc("27351.52"),
                esc("Websocket first look was 0.67 size 6063"),
            ],
        ],
    )
    counts = table(
        [
            ("Window", "text"),
            ("Over-cap-after-recheck skips", "num"),
            ("Kalshi + Polymarket US", "num"),
            ("Other pairs", "num"),
            ("Typical gross move (median ¢)", "num"),
            ("Mean ¢", "num"),
            ("Max ¢", "num"),
        ],
        [
            [
                esc("Today 2026-10-26 ET"),
                esc("29"),
                esc("29 (all tennis)"),
                esc("0"),
                esc("5"),
                esc("6.9"),
                esc("16"),
            ],
            [
                esc("Last 24 hours (orders.jsonl)"),
                esc("547"),
                esc("55"),
                esc("492 (mostly Kalshi/Novig and Gemini NFL overnight)"),
                esc("— (today tennis median 5¢)"),
                esc("—"),
                esc("—"),
            ],
        ],
    )
    today = table(
        [
            ("Time", "date"),
            ("Game", "text"),
            ("Pair (claim order)", "text"),
            ("First-look net", "num"),
            ("Recheck net", "num"),
            ("Gross move ¢", "num"),
        ],
        [
            [esc("14:24:46"), esc("Darderi vs Arnaldi"), esc("kalshi / polymarket"), esc("0.9900"), esc("1.0300"), esc("4")],
            [esc("14:25:21"), esc("Darderi vs Arnaldi"), esc("kalshi / polymarket"), esc("0.9800"), esc("1.0300"), esc("5")],
            [esc("14:25:50"), esc("Darderi vs Arnaldi"), esc("polymarket / kalshi"), esc("0.9800"), esc("1.0300"), esc("5")],
            [esc("14:26:08"), esc("Hu vs Sousa Salazar"), esc("kalshi / polymarket"), esc("0.9900"), esc("1.0200"), esc("3")],
            [esc("14:26:46"), esc("Hu vs Sousa Salazar"), esc("polymarket / kalshi"), esc("0.9900"), esc("1.0100"), esc("2")],
            [esc("14:26:57"), esc("Osborne vs Hinojosa Gomez"), esc("polymarket / kalshi"), esc("0.9800"), esc("1.0100"), esc("4")],
            [esc("14:27:26"), esc("Dencheva vs Knutson"), esc("polymarket / kalshi"), esc("0.9600"), esc("1.0100"), esc("5")],
            [esc("14:27:50"), esc("Osborne vs Hinojosa Gomez"), esc("polymarket / kalshi"), esc("0.9300"), esc("1.0400"), esc("11")],
            [esc("14:28:08"), esc("Dencheva vs Knutson"), esc("kalshi / polymarket"), esc("0.9600"), esc("1.0300"), esc("7")],
            [esc("14:29:09"), esc("Dencheva vs Knutson"), esc("polymarket / kalshi"), esc("0.9600"), esc("1.0200"), esc("6")],
            [esc("14:29:39"), esc("Dencheva vs Knutson"), esc("kalshi / polymarket"), esc("0.9600"), esc("1.0200"), esc("6")],
            [esc("14:39:55"), esc("Darderi vs Arnaldi"), esc("kalshi / polymarket"), esc("0.8800"), esc("1.0300"), esc("15")],
            [esc("14:40:08"), esc("Osborne vs Hinojosa Gomez"), esc("polymarket / kalshi"), esc("0.9800"), esc("1.0200"), esc("4")],
            [esc("14:40:13"), esc("Plekhanova vs Tran"), esc("kalshi / polymarket"), esc("0.9800"), esc("1.0400"), esc("6")],
            [esc("14:40:25"), esc("Darderi vs Arnaldi"), esc("polymarket / kalshi"), esc("0.8700"), esc("1.0300"), esc("16")],
            [esc("14:41:22"), esc("Darderi vs Arnaldi"), esc("kalshi / polymarket"), esc("0.9100"), esc("1.0200"), esc("11")],
            [esc("14:41:49"), esc("Plekhanova vs Tran"), esc("polymarket / kalshi"), esc("0.9800"), esc("1.0200"), esc("4")],
            [esc("14:42:03"), esc("Dencheva vs Knutson"), esc("kalshi / polymarket"), esc("0.9600"), esc("1.0200"), esc("6")],
            [esc("14:42:16"), esc("Darderi vs Arnaldi"), esc("polymarket / kalshi"), esc("0.9000"), esc("1.0400"), esc("14")],
            [esc("14:42:45"), esc("Dencheva vs Knutson"), esc("polymarket / kalshi"), esc("0.9600"), esc("1.0400"), esc("8")],
            [esc("14:44:11"), esc("Dencheva vs Knutson"), esc("kalshi / polymarket"), esc("—"), esc("1.0200"), esc("—")],
            [esc("14:45:03"), esc("Dencheva vs Knutson"), esc("polymarket / kalshi"), esc("0.9600"), esc("1.0100"), esc("5")],
            [esc("14:45:08"), esc("Johnson vs Berkieta"), esc("kalshi / polymarket"), esc("0.8700"), esc("1.0000"), esc("13")],
            [esc("14:45:49"), esc("Martineau vs Virtanen (Martineau Yes)"), esc("polymarket / kalshi"), esc("0.9700"), esc("1.0400"), esc("7")],
            [esc("14:46:10"), esc("Johnson vs Berkieta"), esc("polymarket / kalshi"), esc("0.8700"), esc("1.0200"), esc("15")],
            [esc("14:46:33"), esc("Martineau vs Virtanen (Virtanen Yes) — this row"), esc("kalshi / polymarket"), esc("0.9700"), esc("1.0300"), esc("5")],
            [esc("14:48:47"), esc("Darderi vs Arnaldi"), esc("kalshi / polymarket"), esc("0.9900"), esc("1.0100"), esc("2")],
            [esc("15:05:00"), esc("Fullana vs Ayala"), esc("polymarket / kalshi"), esc("0.9800"), esc("1.0300"), esc("5")],
            [esc("15:05:27"), esc("Fullana vs Ayala"), esc("kalshi / polymarket"), esc("0.9800"), esc("1.0200"), esc("5")],
        ],
    )
    design = table(
        [("Question", "text"), ("Answer", "text")],
        [
            [
                esc("Would a separate REST GET per side per venue have kept 0.29?"),
                esc("No. One Poly book already has bids and offers. One Kalshi orderbook already has yes_dollars and no_dollars. At 14:46:33 the 0.29 offer was gone."),
            ],
            [
                esc("Was 0.29 a wrong field (Yes vs 1−Yes, mid vs ask)?"),
                esc("No. Websocket and the 14:45:49 REST book both showed offers[0]=0.29. Recheck used BUY_LONG yes ask, not 1−bid (that would have been 0.68)."),
            ],
            [
                esc("Was 34568.88 aggregated depth?"),
                esc("No. Top-of-book offer qty only. REST 8s later was 31956.78 at the same 0.29. Not notional dollars."),
            ],
            [
                esc("Why was 0.33 size unknown?"),
                esc("Logging hole: skip kept the Kalshi first-look spec (ask_size 6063) and discarded the Poly REST qty 37676.90. Not a missing book."),
            ],
            [
                esc("Individual per-side GETs vs current path"),
                esc("HOLD. Current path is websocket compare, then one REST book per leg, already in parallel. Extra GETs add latency and would not have saved this fill."),
            ],
            [
                esc("Did we change live fetch?"),
                esc("No fetch change. Did not revert the parallel GET. Skip reason now includes limit_size and other_size."),
            ],
        ],
    )
    freeze = table(
        [("Knob", "text"), ("Value", "text")],
        [
            [esc("Look source"), esc("Live poller tennis_marvir_2026_10_26 pid 53584. Not catalog.")],
            [esc("Poly instrument"), esc("aec-atp-matmar-ottvir-2026-10-26 (long = Martineau, short = Virtanen)")],
            [esc("Poly No cash"), esc("Virtanen No = Martineau Yes ask. Intent BUY_LONG. price.value is always Yes.")],
            [esc("Kalshi Yes cash"), esc("1 − best no_dollars bid on KXATPCHALLENGERMATCH-26OCT26MARVIR-VIR")],
            [esc("Live send"), esc("REST both books before every send; 1 contract; sequential hard-first after recheck")],
            [esc("Cap"), esc("Net ≤ 0.99 after fees, unrounded Decimal, display ≥4 decimals. Gross must be under 1.")],
            [esc("Parallel GET"), esc("Already in _live_pair_from_books / catalog verify. Not reverted.")],
            [esc("Catalog POST"), esc("Not added here. Catalog execute handoff left as the sibling left it.")],
            [esc("D NFL / stake / sell / second B"), esc("Not touched.")],
        ],
    )
    body = f"""
<h1>Virtanen lock: 0.29 with size became 0.33 with no size</h1>
<p class="note">America/New_York. Research only. Not gold. Not DailyRun. Did not sell. Did not bump the send cap. Did not start a second Tennis crossover. Did not wire D NFL.</p>
<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<p><strong>Row (quoted):</strong> {esc(ROW)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Verdict</h2>
<p><strong>Book moved. HOLD on fetch.</strong> First look 0.29 was a real Polymarket US offer. Recheck 0.33 was the new best offer, same field (Yes ask / BUY_LONG), 44 seconds later. 34,568.88 was top-of-book contracts on the websocket 0.29, not dollars, not stacked worse levels. The 0.33 offer had 37,676.90 contracts; we threw that number away on the skip line. Individual per-side per-venue GETs would not have kept 0.29. Live fetch was not changed. Skip lines now print both REST sizes.</p>

<h2>This look</h2>
<p>Live poller, not catalog. Quotes 0.67 / 0.29 were websocket asks (Kalshi Yes at 14:46:30, Poly No still the 14:45:41 tick). Recheck was two public book GETs: Kalshi <code>orderbook_fp.no_dollars</code> best bid → Yes ask 0.68, and Polymarket US <code>marketData.offers[0]</code> → 0.33 size 37676.90. HTTP 200. No POST.</p>
{clock}

<h2>What 0.29 / 34568.88 actually were</h2>
<p>Polymarket US tennis moneyline is one instrument. Long = Matteo Martineau, short = Otto Virtanen. Buying Virtanen No is buying the long side (Martineau Yes) at the Yes ask, intent <code>ORDER_INTENT_BUY_LONG</code>. Cash is the ask, not 1 − Yes. Size is that offer’s <code>qty</code> (contracts), not notional, not summed worse levels.</p>
<p>Websocket at 14:45:41: Martineau Yes / Virtanen No both 0.2900 (same offer). Live compare wrote size <strong>34568.88</strong> on both directions of that lock. Eight seconds later REST still had an offer at 0.29, size 31956.78 (some taken). Kalshi Yes 6063 is the live-compare Kalshi size on Virtanen Yes, also contracts.</p>

<h2>What 0.33 on recheck was</h2>
<p>Same Poly GET, same field: <code>offers[0].px.value = 0.33</code>, <code>qty = 37676.90</code>. Not 1 − Yes bid (that bid was 0.32, which would have printed 0.68). Not a mid. Not a stale catalog list. The 0.29 level was gone from the offer book.</p>
{books}

<h2>How size became “unknown”</h2>
<p>The deny string names prices (<code>limit=0.68 other=0.33</code>) and then drops the live Poly spec. <code>record_send_skip</code> logged the Kalshi first-look spec only (<code>ask_size=6063</code> plus Kalshi volume / open interest). Opportunities.html kept the websocket sizes 6063 / 34568.88 next to the recheck prices. That is why 34,568.88 at 0.29 looks like it turned into a blank size at 0.33. The book still had size. The log did not. Fix: over-cap skip reason now includes <code>limit_size</code> / <code>other_size</code> from the REST books, and the skip row can keep those specs. No POST change.</p>

<h2>Counts: over cap after book recheck</h2>
<p>Every one of these skips had a first look that cleared the send gate (after-fee at or under 0.99, unrounded). Recheck then printed gross ≥ 1 or net &gt; 0.99. Click column headers to sort.</p>
{counts}
<h3>Today’s tennis Kalshi + Polymarket US skips</h3>
<p>Gross move = (recheck Yes ask + No ask) − (first-look Yes + No), in cents. Virtanen was +1¢ Kalshi Yes and +4¢ Poly No = +5¢ gross, then a 2¢ Poly fee on 0.33.</p>
{today}

<h2>Individual REST GET per side per venue?</h2>
{design}
<p>HOLD. The 4¢ Poly walk happened while we were still on a 50-second-old websocket No, waiting for the next Kalshi tick to claim again. Recheck did its job: it refused a 1.03 net. Faster parallel GETs (already shipped) save about a second of venue pacing, not 44 seconds of book move. Catalog walker is unchanged here: it still does not invent a new POST; the sibling’s parallel verify + handoff is left in place.</p>

<h2>Freeze</h2>
{freeze}
<p class="note">Tape: <a href="opportunities.html">opportunities.html</a> · <a href="orders.html">orders.html</a>. Catalog verify note (sibling, not reverted): <a href="lock_catalog_verify_row_20261026.html">lock_catalog_verify_row_20261026.html</a>.</p>
<p class="tiny">Updated {esc(opportunity_considerations._now())}. {esc(FILE_URL)}</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Virtanen over-cap recheck — 26 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
h3 {{ font-size: 0.95rem; margin: 1rem 0 0.35rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
code {{ font-size: 0.9em; }}
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
