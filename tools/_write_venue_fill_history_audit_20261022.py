"""Venue fill-history audit for Paul. Read-only. Does not place, cancel, or sell."""
from __future__ import annotations

import html as html_lib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "venue_fill_history_audit_20261022.html"
EXTRACT = RAW / "_venue_fill_audit_extract_20261022.json"
POS = RAW / "_venue_positions_pull_20261022.json"
PULL = RAW / "_venue_fill_history_pull_20261022.json"

ASKED = (
    "can't you get a history of trades from each venue automatically, examine what is "
    "different from what we thought, figure out WHY, then tell HIM the plan: A) how did "
    "it happen? what are you going to do to fix it? what are you going to do to prevent "
    "it happening again?"
)
PLAIN = (
    "A prediction market is a ticket that costs between 0 and $1 and pays $1 if that named "
    "result happens. Kalshi, Gemini, Polymarket US, and Novig are the four shops. Paul sent "
    "the official docs; this job fetched those pages, used only paths named there, and pulled "
    "18–22 Oct 2026 ET fills. We should have looked the URLs up ourselves. Immediate-or-cancel "
    "(IOC) means fill now or cancel. A fill on this page is quantity at least 1. HTTP 201 with "
    "fill quantity 0 is an empty cancel, not a fill. Kalshi No stores the venue Yes-wire and "
    "the house cash (1 minus Yes-wire / venue no_price); that is one No ticket, not a second "
    "Yes. Polymarket US is api.polymarket.us (same signed GET host as the live client). Global "
    "CLOB and the institutional report host are different products and were not called. This "
    "page does not place a good-til-canceled (GTC) order, does not sell, and does not start a "
    "second Strategy B."
)


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, kind: str = "text") -> str:
    extra = ' class="num"' if kind == "num" else ""
    return f"<td{extra}>{esc('' if value is None else value)}</td>"


def table(headers: list[tuple[str, str]], rows: list[list], total: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(td(cell, headers[i][1] if i < len(headers) else "text") for i, cell in enumerate(row))
        body.append(f"<tr>{cells}</tr>")
    if total is not None:
        cells = "".join(td(cell, headers[i][1] if i < len(headers) else "text") for i, cell in enumerate(total))
        body.append(f'<tr class="total-row">{cells}</tr>')
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def http_list(pages) -> str:
    if not pages:
        return ""
    return ", ".join(str(p.get("http")) for p in pages if isinstance(p, dict))


def main() -> None:
    extract = load_json(EXTRACT)
    pos = load_json(POS)
    pull = load_json(PULL)
    stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    venues = pull.get("venues") or {}
    kalshi_p = venues.get("kalshi") or {}
    gemini_p = venues.get("gemini") or {}
    poly_p = venues.get("polymarket") or {}
    novig_p = venues.get("novig") or {}
    named = ((pull.get("diff") or {}).get("named") or {})
    fills = extract.get("fills") or []
    gemini_fills = [r for r in (extract.get("gemini_io") or []) if r.get("qty_ge_1")]
    poly_rows = ((pos.get("poly") or {}).get("rows") or [])
    kalshi_n = (pos.get("kalshi") or {}).get("n")
    kalshi_http = (pos.get("kalshi") or {}).get("http")
    poly_http = (pos.get("poly") or {}).get("http")
    poly_n = (pos.get("poly") or {}).get("n")
    empty_201 = extract.get("empty_201") or 0
    empty_by = extract.get("empty_201_by_venue") or {}
    io_by = extract.get("io_fills_by_venue") or {}
    tape_not_io = extract.get("tape_not_io") or []
    io_not_tape = extract.get("io_not_tape") or []

    helper_rows = [
        [
            "Kalshi",
            "GET",
            "/trade-api/v2/portfolio/fills",
            "https://api.elections.kalshi.com (existing signed helper; docs also list https://external-api.kalshi.com/trade-api/v2)",
            "https://docs.kalshi.com/api-reference/portfolio/get-fills",
            "Yes",
            http_list(kalshi_p.get("http_pages")),
            f"{kalshi_p.get('n')} rows, {kalshi_p.get('n_house')} with qty >= 1",
        ],
        [
            "Kalshi",
            "GET",
            "/trade-api/v2/portfolio/orders",
            "https://api.elections.kalshi.com",
            "https://docs.kalshi.com/api-reference/orders/get-orders",
            "No",
            "",
            "Documented order list. Fills endpoint already returned the fill tape, so this was not called.",
        ],
        [
            "Gemini predictions",
            "POST",
            "/v1/prediction-markets/orders/history",
            "https://api.gemini.com",
            "https://developer.gemini.com/rest-api/prediction-markets/order-management/get-order-history",
            "Yes",
            http_list(gemini_p.get("http_pages")),
            f"{gemini_p.get('n')} filled orders, {gemini_p.get('n_house')} with qty >= 1",
        ],
        [
            "Polymarket US",
            "GET",
            "/v1/portfolio/activities",
            "https://api.polymarket.us (same signed GET host as polymarket_us_live.py)",
            "https://docs.polymarket.us/api-reference/portfolio/get-activities",
            "Yes",
            http_list(poly_p.get("http_pages")),
            f"{poly_p.get('n')} TRADE activities in window, {poly_p.get('n_house')} with qty >= 1. types=ACTIVITY_TYPE_TRADE",
        ],
        [
            "Polymarket institutional Report",
            "POST",
            "/v1/report/trades/search",
            "https://api.prod.polymarketexchange.com (Bearer JWT)",
            "https://docs.polymarket.us/api-reference/report/search-trades",
            "No",
            "",
            "Different host and auth than our US live client. Not called.",
        ],
        [
            "Polymarket global CLOB",
            "GET",
            "/data/orders (example on docs.polymarket.com)",
            "https://clob.polymarket.com",
            "https://docs.polymarket.com/getting-started/api",
            "No",
            "",
            "Different product than Polymarket US. Not called.",
        ],
        [
            "Novig",
            "GET",
            "/v3/portfolio/fills",
            "https://api.novig.com (production; paper sample host in the same doc is api.paper.novig.com)",
            "https://docs.novig.com/api-reference/execution/list-fills",
            "Yes",
            http_list(novig_p.get("http_pages")),
            f"{novig_p.get('n')} fills. Empty matches Paul.",
        ],
    ]

    gemini_hist = {str(r.get("ticker") or ""): r for r in (gemini_p.get("all_rows") or gemini_p.get("fills") or [])}
    gemini_rows = [
        [
            "TB vs CLE moneyline TB",
            "GEMI-MLB-2610180000-TB-CLE-M-TB",
            "0.97 Yes, resolved Yes $1",
            f"history GET: qty {gemini_hist.get('GEMI-MLB-2610180000-TB-CLE-M-TB', {}).get('qty')} @ {gemini_hist.get('GEMI-MLB-2610180000-TB-CLE-M-TB', {}).get('price')} {gemini_hist.get('GEMI-MLB-2610180000-TB-CLE-M-TB', {}).get('time_et')} resolution {gemini_hist.get('GEMI-MLB-2610180000-TB-CLE-M-TB', {}).get('resolution')}",
            "order_io 2026-10-18 19:46 ET HTTP 201 qty 1, request 0.97. No orders.jsonl filled event.",
            "history and order_io agree. Tape logging gap on orders.jsonl filled.",
        ],
        [
            "CAR vs CGY moneyline CGY",
            "GEMI-NHL-2610190000-CAR-CGY-M-CGY",
            "0.99 Yes, resolved Yes $1",
            f"history GET: qty {gemini_hist.get('GEMI-NHL-2610190000-CAR-CGY-M-CGY', {}).get('qty')} @ {gemini_hist.get('GEMI-NHL-2610190000-CAR-CGY-M-CGY', {}).get('price')} {gemini_hist.get('GEMI-NHL-2610190000-CAR-CGY-M-CGY', {}).get('time_et')} resolution {gemini_hist.get('GEMI-NHL-2610190000-CAR-CGY-M-CGY', {}).get('resolution')}",
            "order_io HTTP 201 qty 1; orders.jsonl filled 0.99",
            "aligned with Paul, history, order_io, and tape",
        ],
        [
            "MTN vs FIU total over 48",
            "GEMI-NCAAF-2610202300-MTN-FIU-T-O48",
            "0.44 Yes, resolved Yes $1",
            f"history GET: qty {gemini_hist.get('GEMI-NCAAF-2610202300-MTN-FIU-T-O48', {}).get('qty')} @ {gemini_hist.get('GEMI-NCAAF-2610202300-MTN-FIU-T-O48', {}).get('price')} limit {gemini_hist.get('GEMI-NCAAF-2610202300-MTN-FIU-T-O48', {}).get('limit')} resolution {gemini_hist.get('GEMI-NCAAF-2610202300-MTN-FIU-T-O48', {}).get('resolution')}",
            "order_io HTTP 201 qty 1, request limit 0.46 (limit, not a second ticket); orders.jsonl filled 0.44",
            "aligned. Fill 0.44 vs limit 0.46 is one Yes ticket.",
        ],
    ]

    poly_pos_rows = [
        [
            r.get("title"),
            r.get("slug"),
            r.get("outcome"),
            r.get("net"),
            r.get("qty_bought"),
            r.get("qty_sold"),
            r.get("avg_px"),
            r.get("cost"),
            r.get("cash_value"),
            r.get("expired"),
        ]
        for r in poly_rows
    ]

    mismatch_rows = [
        [
            "opportunities said both-filled; no venue fill",
            "NMSU vs SHSU spread SHSU 9.5",
            "Kalshi / Gemini",
            "2026-10-21 22:42 ET",
            "considerations.json had multiple sent rows at the same second including “Both legs filled” at No prices 0.400 / 0.50 / 0.53. order_io: 0 Kalshi and 0 Gemini posts. Kalshi positions then and now: 0 SHSU 9.5 rows. Dedicated page shsu95_false_both_filled_20261021.html.",
            "HTTP 201 fill_count 0 treated as fill; Opportunities quote-patch multiple sent rows one second",
        ],
        [
            "opportunities said one-leg; no venue fill",
            "NMSU vs SHSU spread SHSU 9.5",
            "Kalshi / Gemini",
            "2026-10-21 22:58:48 ET",
            "opportunities: “Sent. One leg filled and flatten missed. gemini flatten HTTP 201 flatten miss.” order_io: no Kalshi and no Gemini post at that second. Paul flat. Dedicated page shsu95_225848_false_one_leg_20261021.html.",
            "HTTP 201 fill_count 0 treated as fill",
        ],
        [
            "price/side differ (Yes-wire vs UI No cash)",
            "Ribecai vs Houkes",
            "Kalshi",
            "2026-10-22 07:52:55 ET",
            "order_io: one fill, ask/No, HTTP 201 fill_count 1.00, average_fill_price 0.4700 (Yes-wire). House No cash = 1 − 0.47 = 0.53. orders.jsonl filled and one_leg both store 0.4700. Flatten Yes: fill_count 0. Paul: 1× No at 0.55, lost. Kalshi GET positions this pull: 0 RIBHOU rows. The 0.47 is not a second Yes ticket.",
            "Kalshi No logged as Yes-wire price (1-p) vs UI No cash",
        ],
        [
            "price remainder after 1-p (does not fit a second class)",
            "Ribecai vs Houkes",
            "Kalshi",
            "2026-10-22 07:52:55 ET",
            "Kalshi GET /portfolio/fills: one No fill, count 1.00, yes_price_dollars 0.4700, no_price_dollars 0.5300. House cash 0.53. Paul UI 0.55. History is venue truth for the fill; 0.55 is not a second ticket.",
            "Kalshi No: store venue Yes-wire 0.47 and house/venue No cash 0.53. Not a second Yes.",
        ],
        [
            "partial Poly qty < 1 vs house 1-contract fill; Paul dollars match",
            "Aurora Urso vs Aneta Poborilova",
            "Polymarket US",
            "2026-10-22 04:01 ET",
            "order_io: Yes Urso qty 0.10 avg 0.78 (0.10×0.78 = $0.078 ≈ Paul’s $0.08); Yes Poborilova BUY_SHORT qty 1 avg 0.77 cash 0.23 fee 0.01 (house fill); Yes Urso qty 0.15 avg 0.79 (0.15×0.79 = $0.1185 ≈ Paul’s $0.12). GET positions this pull: still held, net −0.75, bought 0.25, sold 1.00, avgPx 0.24, outcome Poborilova. House rule does not count the 0.10 / 0.15 as 1-contract fills.",
            "Partial Poly qty < 1 not counted as house 1-contract fill",
        ],
        [
            "tape fill not on venue book; Paul says void",
            "Danilova-Liu vs Beck-Sibai",
            "Polymarket US",
            "2026-10-21 23:29–23:30 ET",
            "order_io qty >= 1 three times on aec-itfwo-olgdanyuhliu-avabecjizsib-2026-10-22 (Yes Danilova-Liu 0.44; two Beck-Sibai shorts 0.43/0.57). GET positions: 0 rows for that slug. Paul: void on Poly. Strategy B still says absorbed after cross.",
            "does not fit a named class — Paul’s void is venue truth; ask before inventing a void mechanism",
        ],
        [
            "tape fill not on venue book; B still says holdings stay",
            "Vivian Wolff vs Stefani Webb",
            "Polymarket US",
            "2026-10-21 19:12:37 ET",
            "order_io qty 1 Webb short cash 0.15 and qty 1 Wolff long 0.86. GET positions: not in the 2 current rows. Paul: not on the apps. Strategy B stage postponed, note “Holdings stay.”",
            "Claim then restart, no skip, ghost open slots",
        ],
        [
            "tape fills; venue book empty; B still waiting_fav_dip (counts as currently_open)",
            "Machac vs Khachanov",
            "Kalshi",
            "2026-10-22 06:59–07:27 ET",
            "order_io five Kalshi qty 1.00 fills (KHA Yes 0.86, KHA No flatten 0.15 cash, MAC Yes 0.16, KHA Yes 0.85, MAC Yes 0.50). GET positions: 0 MACKHA rows. Paul: not on the apps. Strategy B currently_open includes waiting_fav_dip “cross filled at 0.5; waiting fav Yes at/below 0.25”.",
            "Claim then restart / ghost open slots; Strategy B extra/leftover vs lock-bot",
        ],
        [
            "partial Poly + B holdings stay vs Paul settled",
            "Aaron Funk vs Sergey Petrov",
            "Polymarket US",
            "2026-10-22 02:59–03:00 ET",
            "order_io three posts: Petrov 0.09; Yes Funk qty 1 at 0.40; Petrov 0.92. Poly GET /v1/portfolio/activities: six TRADE prints on aec-itfme-aarfun-serpet-2026-10-22 — 0.92@0.43, 0.90@0.40, 0.10@0.40, and three 0.03@0.39 (0.09). The fourth ticket is the 0.10 split of the order_io qty-1 Funk Yes. Paul four tickets = 0.92, 0.90, 0.10, 0.09. None of those prints is qty >= 1, so house fill count stays 0 from history (order_io still counted the combined qty 1).",
            "Poly history splits one HTTP 201 qty 1 into 0.90+0.10. Fourth ticket is that 0.10 print.",
        ],
        [
            "venue fill not on tape (orders.jsonl filled event)",
            "TB vs CLE Gemini Yes TB 0.97",
            "Gemini",
            "2026-10-18 19:46 ET",
            "Paul paste and order_io qty 1 filled at request 0.97. orders.jsonl has 0 Gemini filled events for this symbol (only CAR-CGY and MTN-FIU Gemini filled events exist).",
            "does not fit a named class beyond a logging gap — ask before inventing why the filled event was skipped",
        ],
        [
            "venue open book has it; orders.jsonl has no filled event",
            "David Tixhon vs Carles Cordoba",
            "Polymarket US",
            "2026-10-22 03:34 ET",
            "GET positions this pull: held, outcome Cordoba, net −0.90, bought 0.10, sold 1.00, avgPx 0.89. order_io: qty 0.10 long + qty 1 short. Not in orders.jsonl filled keys. Strategy B postponed and the venue still lists it, so this one is a true open, not a ghost.",
            "Partial Poly qty < 1 (the 0.10); Strategy B extra/leftover vs lock-bot (filled event missing)",
        ],
        [
            "tape filled event; no matching order_io qty>=1 in window",
            "19 Kalshi NFL tickers (e.g. CARPHI total 41 filled 0.36; ARI/LAR game and spreads)",
            "Kalshi",
            "2026-10-18 window",
            "orders.jsonl event=filled for 19 Kalshi NFL instruments with 0 matching order_io rows. Kalshi GET /portfolio/fills this job returned those tickers (e.g. KXNFLGAME-26OCT18ARILAR-ARI/LAR, spreads, CARPHI-41). History confirms they filled. Send-time order_io for this window never stored the POSTs.",
            "venue history confirms tape; order_io gap for those NFL sends",
        ],
    ]

    plan_blocks = [
        (
            "Kalshi No logged as Yes-wire price (1-p) vs UI No cash",
            "Ribecai vs Houkes on 22 Oct 2026 07:52:55 ET: we sent a Kalshi No as an ask (Yes-wire). The venue returned HTTP 201 fill_count 1.00 and average_fill_price 0.4700. That 0.47 is the Yes-wire / limit, not a Yes ticket. House No cash is 1 − 0.47 = 0.53. orders.jsonl stored 0.4700 on both filled and one_leg. The Yes flatten was fill_count 0. Paul sees one No at 0.55, now lost. Kalshi GET positions this pull has 0 RIBHOU rows, so the open book cannot settle 0.53 vs 0.55.",
            "On the scoreboard, show one No ticket. Display venue No cash 0.53 (no_price_dollars, also 1 minus Yes-wire 0.47) next to the Yes-wire. Label 0.47 “Yes-wire / limit,” never a second Yes. Still-open = Kalshi positions list only (this ticker is not on it). Do not sell. History GET is venue truth for the fill; do not store 0.55 as a second ticket.",
            "Logging: never write a Yes-wire as a second Yes ticket. Persist GET /portfolio/fills after each send (now that the path is documented). Do not wire GTC.",
        ),
        (
            "HTTP 201 fill_count 0 treated as fill (false both-legs / one-leg)",
            "SHSU 9.5 at 22:42 ET: opportunities wrote several sent rows including “Both legs filled” while order_io had zero Kalshi and zero Gemini posts and Kalshi positions were 0. SHSU 9.5 at 22:58:48 ET: opportunities wrote one-leg plus “gemini flatten HTTP 201 flatten miss” with no Kalshi or Gemini order post. Window-wide, order_io has 1012 HTTP 200/201 posts with qty < 1 (Gemini 926, Polymarket 60, Kalshi 26). orders.jsonl both_unfilled is 1007, so most empty 201s are now logged as unfilled. The SHSU rows were the ones that leaked into sent / both-filled / one-leg.",
            "Void those SHSU sent / both-filled / one-leg rows on opportunities. A fill on the scoreboard is qty >= 1 only. HTTP 201 fill_count 0 stays unfilled. Do not count them as house fills. Do not sell.",
            "Logging already patched in live_lock_orders.filled_contracts / leg_filled_at_least_one (qty >= 1 wins; fill_count 0 is 0). Keep tests test_kalshi_201_fill_count_zero_is_not_a_fill and test_send_pair_does_not_log_both_filled_on_empty_201. Add a venue-return column on every sent row. Do not wire GTC.",
        ),
        (
            "Claim then restart, no skip, ghost open slots",
            "Strategy B currently_open is 2 (Urso one_leg_miss, which Polymarket still lists, and Machac waiting_fav_dip, which Kalshi positions do not list). The watch file still says “Holdings stay” for Wolff (Paul: not on the apps; Poly positions: absent), Funk (Paul: settled +0.01; Poly positions: absent), and other postponed/absorbed matches. After a claim plus a process restart, those slots were not skipped, so the diary still talks as if the tickets are open.",
            "Still-open on the scoreboard = current venue book only (Kalshi GET positions + Polymarket GET positions + Paul’s Gemini/Novig paste). Drop Wolff / Machac / Funk from still-open. Leave Urso and Tixhon, which this pull still lists on Polymarket. Do not sell.",
            "On restart, skip bet_keys that are already claimed unless the venue positions list still holds them. Logging: write venue_held=yes/no from the positions GET next to each B stage. Optional later: persist venue fill history each send. Do not wire GTC.",
        ),
        (
            "Opportunities quote-patch multiple sent rows one second",
            "SHSU 9.5 at 22:42:05 ET: same timestamp, three Gemini No prices (0.400, 0.50, 0.53), multiple sent rows including “Both legs filled” and “Neither leg filled.” That is websocket / book-recheck / consider patches, not three locks. Fingerprint included Yes/No prices, so each patch became a new row. The current considerations.json 500-row window has rotated those rows out; the dedicated SHSU page still has them.",
            "Keep one sent row per bet per timestamp second. Mark the extra 22:42 patches as quote patches, not fills. Do not sell.",
            "opportunity_considerations.record already refuses a second sent row for the same bet at the same second (test_record_sent_same_second_does_not_stack_quote_patches). Keep that guard. Venue-return column so a patch cannot look like a fill. Do not wire GTC.",
        ),
        (
            "Catalog scan logged as denied send",
            "Paul’s original opportunities ask quotes the backwards sentence: “After-fee cost 0.93 is at or under the 0.98 send line. This catalog pass does not send orders.” The first sentence is the send condition; the decision is denied. The catalog scan never sends. The current 500-row window has 0 remaining rows matching that old pattern (the page now rewrites catalog eligible rows to a denied-because-catalog reason).",
            "Leave catalog rows as denied. Do not treat “at or under the send line” as a fill. No tape tickets to void for this class in the current window.",
            "Keep catalog_eligible_reason / _CATALOG_OLD_REASON rewrite. Logging: decision=denied and a catalog tag, never sent. Do not wire GTC.",
        ),
        (
            "Strategy B extra/leftover vs lock-bot",
            "Lock-bot orders.jsonl filled events this window: 55. order_io qty >= 1 fills: 92 (Kalshi 23, Polymarket 66, Gemini 3). 23 instruments are in order_io qty >= 1 but not in orders.jsonl filled, mostly Strategy B tennis (Machac, Funk, Wolff, Danilova, Urso, Tixhon, Broady, …). B extras, flattens, and partials are stored on order_io and strategy_b_watch, not as lock-bot filled events. Machac’s five Kalshi fills are B extras while the lock-bot scoreboard never listed them as filled.",
            "Show B fills from order_io qty >= 1 on the same scoreboard as lock-bot fills, labeled intent=Strategy B. Still-open remains venue book only. Do not merge B leftovers into lock-bot one-leg. Do not sell.",
            "Logging: one ledger row per venue return with source=lock|B, qty, and venue-return. Do not skip writing a filled event when B is the sender. Do not wire GTC.",
        ),
        (
            "Partial Poly qty < 1 not counted as house 1-contract fill",
            "Urso: qty 0.10 and 0.15 Yes are under 1; Paul sees those as $0.08 and $0.12 paid, which matches qty × avg. Funk: qty 0.09 and 0.92 Petrov shorts are under 1; Yes Funk qty 1 is the house fill. Tixhon: qty 0.10 long plus qty 1 short; Polymarket still nets them (bought 0.10, sold 1.00). House rule is qty >= 1. The venue still lists the partials when they are open.",
            "Walk-up tables already show qty < 1. Keep them off the house 1-contract fill count. On still-open, show the venue net (Urso −0.75, Tixhon −0.90) so Paul sees the dollars. Do not round 0.92 up to 1. Do not sell.",
            "Logging: store qty as returned. Flag house_fill=(qty>=1) separately from venue_open=(positions net != 0). Do not wire GTC.",
        ),
        (
            "rewrite_send_line_copy inverted 0.98399 vs 0.984",
            "Paul’s original skip: “After-fee cost 0.98399 is above the 0.984 send line but still at or under 0.99.” 0.98399 is less than 0.984, so “above” was false. rewrite_send_line_copy now refuses to rewrite an “above {line}” sentence when the named cost is at or under NET_MAX (0.984). The current 500-row considerations window has 0 remaining inverted 0.98399 rows.",
            "No current tape fill to void. Keep showing the true after-fee cost unrounded. Do not treat that skip as a send.",
            "Keep rewrite_send_line_copy and test_live_lock_orders coverage for 0.98399. Do not wire GTC.",
        ),
    ]

    fill_headers = [
        ("Time ET", "date"),
        ("Venue", "text"),
        ("HTTP", "num"),
        ("Instrument", "text"),
        ("Book / intent", "text"),
        ("Qty", "num"),
        ("Yes-wire / avg", "num"),
        ("No cash / Poly cash", "num"),
        ("Poly fee", "num"),
        ("Outcome", "text"),
        ("Order id", "text"),
        ("Note", "text"),
    ]
    fill_rows = []
    for row in fills:
        fill_rows.append([
            row.get("ts"),
            row.get("venue"),
            row.get("http"),
            row.get("instrument"),
            row.get("book_side") or row.get("req_side"),
            row.get("qty"),
            row.get("yes_wire") or row.get("poly_avg") or row.get("gemini_price"),
            row.get("no_cash") or row.get("poly_cash"),
            row.get("poly_fee"),
            row.get("poly_outcome"),
            row.get("order_id"),
            row.get("note"),
        ])

    nfl_rows = [[v, inst] for v, inst in tape_not_io]
    b_gap_rows = [[v, inst] for v, inst in io_not_tape]

    questions = [
        "No remaining history-URL blocker. All four venues name a fills/history path; this job called each one that matches our live host.",
        "TB vs CLE Gemini 0.97: history GET and order_io agree it filled. orders.jsonl still has no filled event. Logging gap; not a missing ticket.",
        "Danilova: Paul said Poly voided. History still lists three TRADE prints (qty 1 at 0.43 / 0.43 / 0.44). Void is a later state, not a missing fill.",
    ]

    helper_html = table(
        [
            ("Venue", "text"),
            ("Method", "text"),
            ("Path", "text"),
            ("Host", "text"),
            ("Doc URL", "text"),
            ("Called this job?", "text"),
            ("HTTP", "text"),
            ("Result", "text"),
        ],
        helper_rows,
    )
    kalshi_hist_rows = [
        [
            r.get("time_et"),
            r.get("ticker"),
            r.get("side"),
            r.get("qty"),
            r.get("yes_wire"),
            r.get("no_price"),
            r.get("house_cash"),
            r.get("house_fill"),
            r.get("order_id"),
        ]
        for r in (kalshi_p.get("all_rows") or kalshi_p.get("fills") or [])
    ]
    gemini_hist_rows = [
        [
            r.get("time_et"),
            r.get("ticker"),
            r.get("side"),
            r.get("outcome"),
            r.get("qty"),
            r.get("price"),
            r.get("limit"),
            r.get("resolution"),
            r.get("house_fill"),
        ]
        for r in (gemini_p.get("all_rows") or gemini_p.get("fills") or [])
    ]
    poly_hist_rows = [
        [
            r.get("time_et"),
            r.get("ticker"),
            r.get("qty"),
            r.get("price"),
            r.get("cost"),
            r.get("house_fill"),
            r.get("state"),
            r.get("trade_id"),
        ]
        for r in (poly_p.get("all_rows") or poly_p.get("fills") or [])
    ]
    novig_hist_rows = [
        [
            r.get("time_et"),
            r.get("ticker"),
            r.get("qty"),
            r.get("price"),
            r.get("cost"),
            r.get("house_fill"),
            r.get("order_id"),
        ]
        for r in (novig_p.get("all_rows") or novig_p.get("fills") or [])
    ]
    funk_hist = ((named.get("funk") or {}).get("history_all") or (named.get("funk") or {}).get("history") or [])
    funk_rows = [
        [r.get("time_et"), r.get("ticker"), r.get("qty"), r.get("price"), r.get("house_fill")]
        for r in funk_hist
    ]
    rib_hist = ((named.get("ribecai") or {}).get("history_all") or (named.get("ribecai") or {}).get("history") or [])
    rib_rows = [
        [r.get("time_et"), r.get("ticker"), r.get("side"), r.get("qty"), r.get("yes_wire"), r.get("no_price"), r.get("house_cash")]
        for r in rib_hist
    ]
    hist_not_io = (pull.get("diff") or {}).get("hist_not_io") or []
    io_not_hist = (pull.get("diff") or {}).get("io_not_hist") or []
    hist_not_io_html = table(
        [("Venue", "text"), ("Ticker on history qty>=1, not on order_io qty>=1", "text")],
        [[a, b] for a, b in hist_not_io],
        total=["pairs", str(len(hist_not_io))],
    )
    io_not_hist_html = table(
        [("Venue", "text"), ("Ticker on order_io qty>=1, not on history qty>=1", "text")],
        [[a, b] for a, b in io_not_hist],
        total=["pairs", str(len(io_not_hist))],
    )
    kalshi_hist_html = table(
        [
            ("Time ET", "date"),
            ("Ticker", "text"),
            ("Side", "text"),
            ("Qty", "num"),
            ("Yes-wire", "num"),
            ("No price", "num"),
            ("House cash", "num"),
            ("House fill qty>=1", "text"),
            ("Order id", "text"),
        ],
        kalshi_hist_rows,
        total=["Kalshi fills", str(len(kalshi_hist_rows)), "", "", "", "", "", "", ""],
    )
    gemini_hist_html = table(
        [
            ("Time ET", "date"),
            ("Symbol", "text"),
            ("Side", "text"),
            ("Outcome", "text"),
            ("Qty", "num"),
            ("Avg fill", "num"),
            ("Limit", "num"),
            ("Resolution", "text"),
            ("House fill qty>=1", "text"),
        ],
        gemini_hist_rows,
        total=["Gemini filled orders", str(len(gemini_hist_rows)), "", "", "", "", "", "", ""],
    )
    poly_hist_html = table(
        [
            ("Time ET", "date"),
            ("Market slug", "text"),
            ("Qty", "num"),
            ("Price", "num"),
            ("Cost", "num"),
            ("House fill qty>=1", "text"),
            ("State", "text"),
            ("Trade id", "text"),
        ],
        poly_hist_rows,
        total=["Poly TRADE activities", str(len(poly_hist_rows)), "", "", "", "", "", ""],
    )
    novig_hist_html = table(
        [
            ("Time ET", "date"),
            ("Market id", "text"),
            ("Qty", "num"),
            ("Price", "num"),
            ("Cost", "num"),
            ("House fill qty>=1", "text"),
            ("Order id", "text"),
        ],
        novig_hist_rows,
        total=["Novig fills", str(len(novig_hist_rows)), "", "", "", "", ""],
    )
    funk_html = table(
        [("Time ET", "date"), ("Slug", "text"), ("Qty", "num"), ("Price", "num"), ("House fill qty>=1", "text")],
        funk_rows,
        total=["Funk Poly prints", str(len(funk_rows)), "", "", ""],
    )
    rib_html = table(
        [
            ("Time ET", "date"),
            ("Ticker", "text"),
            ("Side", "text"),
            ("Qty", "num"),
            ("Yes-wire", "num"),
            ("No price", "num"),
            ("House cash", "num"),
        ],
        rib_rows,
    )
    gemini_html = table(
        [
            ("Game", "text"),
            ("Instrument", "text"),
            ("Paul paste (venue history)", "text"),
            ("Send-time order_io / tape", "text"),
            ("Diff", "text"),
            ("Class", "text"),
        ],
        gemini_rows,
    )
    poly_html = table(
        [
            ("Title", "text"),
            ("Slug", "text"),
            ("Outcome", "text"),
            ("Net", "num"),
            ("Qty bought", "num"),
            ("Qty sold", "num"),
            ("Avg px", "num"),
            ("Cost", "num"),
            ("Mark", "num"),
            ("Expired", "text"),
        ],
        poly_pos_rows,
    )
    mismatch_html = table(
        [
            ("Kind", "text"),
            ("Game", "text"),
            ("Venue", "text"),
            ("When ET", "date"),
            ("Evidence (no guesses)", "text"),
            ("Root-cause class", "text"),
        ],
        mismatch_rows,
        total=["Mismatch rows", str(len(mismatch_rows)), "", "", "", ""],
    )
    plan_html = []
    for i, (title, how, fix, prevent) in enumerate(plan_blocks, 1):
        plan_html.append(
            f"<h3>{i}. {esc(title)}</h3>"
            f"<p><strong>A) How it happened.</strong> {esc(how)}</p>"
            f"<p><strong>B) Fix the data/page.</strong> {esc(fix)}</p>"
            f"<p><strong>C) Prevent.</strong> {esc(prevent)}</p>"
        )
    fills_html = table(fill_headers, fill_rows, total=["order_io qty>=1 in window", str(len(fill_rows)), "", "", "", "", "", "", "", "", "", ""])
    nfl_html = table([("Venue", "text"), ("Instrument on orders.jsonl filled, not on order_io qty>=1", "text")], nfl_rows)
    b_gap_html = table([("Venue", "text"), ("Instrument on order_io qty>=1, not on orders.jsonl filled", "text")], b_gap_rows)

    q_html = "<ol>" + "".join(f"<li>{esc(q)}</li>" for q in questions) + "</ol>"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Venue fill history audit — 22 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
h3 {{ font-size: 1rem; margin: 1rem 0 0.3rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
ul, ol {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Venue fill history vs what we thought — 18–22 Oct 2026 ET</h1>
<p class="note">America/New_York. Written {esc(stamp)}. Research live. Not gold. Not DailyRun. This page does not place, cancel, flatten, sell, or start a second Strategy B. Click column headers to sort. Immediate-or-cancel (IOC) is fill now or cancel. HTTP 201 with fill quantity 0 is not a fill.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout warn">
<h2>What auto-history did this job</h2>
<ul>
<li><strong>We looked the URLs up.</strong> You sent the docs. This job fetched them and called only paths named there. Sorry for asking first.</li>
<li><strong>Kalshi</strong> GET /trade-api/v2/portfolio/fills HTTP {esc(http_list(kalshi_p.get('http_pages')))}: {esc(kalshi_p.get('n'))} fills, {esc(kalshi_p.get('n_house'))} with qty &gt;= 1. Open positions GET is a different call (HTTP {esc(kalshi_http)}, {esc(kalshi_n)} market rows).</li>
<li><strong>Polymarket US</strong> GET /v1/portfolio/activities?types=ACTIVITY_TYPE_TRADE HTTP {esc(http_list(poly_p.get('http_pages')))}: {esc(poly_p.get('n'))} trades in the window, {esc(poly_p.get('n_house'))} with qty &gt;= 1. Host api.polymarket.us. Did not call clob.polymarket.com or api.prod.polymarketexchange.com.</li>
<li><strong>Gemini</strong> POST /v1/prediction-markets/orders/history status=filled HTTP {esc(http_list(gemini_p.get('http_pages')))}: {esc(gemini_p.get('n'))} filled orders, all qty &gt;= 1. Matches your three resolved Yes $1 tickets.</li>
<li><strong>Novig</strong> GET /v3/portfolio/fills HTTP {esc(http_list(novig_p.get('http_pages')))}: {esc(novig_p.get('n'))} fills. Empty, as you said. order_io also has 0 Novig posts.</li>
<li><strong>Send-time order_io</strong> is still the POST return, not history. Window order_io qty &gt;= 1: {esc(extract.get('io_fills_qty_ge_1'))} (Kalshi {esc(io_by.get('kalshi'))}, Polymarket {esc(io_by.get('polymarket'))}, Gemini {esc(io_by.get('gemini'))}). HTTP 200/201 with qty &lt; 1: {esc(empty_201)} (not fills).</li>
<li><strong>What we thought:</strong> orders.jsonl filled {esc(extract.get('orders_filled_n'))}, one_leg {esc(extract.get('orders_one_leg_n'))}, both_unfilled {esc((extract.get('orders_jsonl_events') or {}).get('both_unfilled'))}.</li>
</ul>
</div>

<div class="callout ok">
<h2>Mismatch counts</h2>
<ul>
<li><strong>Named mismatch rows in the table below:</strong> {esc(len(mismatch_rows))}.</li>
<li><strong>History qty&gt;=1 not on order_io qty&gt;=1:</strong> {esc(len(hist_not_io))} tickers (mostly Kalshi NFL that tape already had as filled).</li>
<li><strong>order_io qty&gt;=1 not on history qty&gt;=1:</strong> {esc(len(io_not_hist))} tickers (Poly splits: Funk/Urso/Tixhon and two others exist on history as qty &lt; 1 prints).</li>
<li><strong>Gemini history GET vs your paste:</strong> 3 of 3. Novig empty: match.</li>
<li><strong>False both-filled / one-leg with no venue fill:</strong> 2 SHSU 9.5 timestamps (22:42 and 22:58).</li>
</ul>
</div>

<h2>Documented history endpoints</h2>
<p class="note">Fetched from the docs you sent. No invented paths. Click column headers to sort.</p>
{helper_html}

<h2>Ribecai (Kalshi No) — venue history</h2>
<p class="note">One No fill. Yes-wire 0.47 and No price / house cash 0.53. Not a second Yes ticket. Your UI 0.55 is not a second ticket either.</p>
{rib_html}

<h2>Funk (Poly four tickets)</h2>
<p class="note">order_io had three posts. History GET split the qty-1 Funk Yes into 0.90 + 0.10 at 0.40, plus 0.92 at 0.43 and 0.09 (three 0.03 prints) at 0.39. That is four tickets. House fill remains qty &gt;= 1, so none of these prints count as a house 1-contract fill.</p>
{funk_html}

<h2>Gemini history GET (not the paste)</h2>
<p class="note">POST /v1/prediction-markets/orders/history, status=filled, 18–22 Oct 2026 ET. Your paste: MTN/FIU 0.44, CAR/CGY 0.99, TB/CLE 0.97, all resolved Yes $1. Click column headers to sort.</p>
{gemini_html}
{gemini_hist_html}

<h2>Kalshi GET /portfolio/fills</h2>
<p class="note">Qty from count_fp. House fill is qty &gt;= 1. No cash is venue no_price_dollars. Click column headers to sort.</p>
{kalshi_hist_html}

<h2>Polymarket US GET /v1/portfolio/activities (TRADE)</h2>
<p class="note">Same host as the live client. qtyDecimal shown as returned. House fill is qty &gt;= 1. Click column headers to sort.</p>
{poly_hist_html}

<h2>Novig GET /v3/portfolio/fills</h2>
<p class="note">Empty page. Matches you. Click column headers to sort.</p>
{novig_hist_html}

<h2>Diff: history qty&gt;=1 vs order_io qty&gt;=1</h2>
<p class="note">No guesses. A ticker can sit on history as qty &lt; 1 prints and still be missing from the qty&gt;=1 house set.</p>
{hist_not_io_html}
{io_not_hist_html}

<h2>Open books this pull (not fill history)</h2>
<p class="note">Kalshi GET /trade-api/v2/portfolio/positions HTTP {esc(kalshi_http)}, {esc(kalshi_n)} rows. Polymarket US GET /v1/portfolio/positions HTTP {esc(poly_http)}, {esc(poly_n)} rows, eof {(pos.get('poly') or {}).get('eof')}. Pulled {esc(pos.get('pulled_at'))}. Amounts only. No secrets.</p>
{poly_html}

<h2>Mismatch table</h2>
<p class="note">Truth order: venue fill history GET → open positions → your Gemini/Novig notes. Tape is what we thought. Click column headers to sort.</p>
{mismatch_html}

<h2>The plan (A / B / C)</h2>
<p class="note">No GTC. No sell. No live trading change in this pass. Logging-only items below are the plan, not a wire.</p>
{''.join(plan_html)}

<h2>Leftovers (not URL questions)</h2>
{q_html}

<h2>Send-time venue returns with qty &gt;= 1 (order_io, not a history GET)</h2>
<p class="note">Window 18 Oct 2026 00:00 ET through 22 Oct 2026 24:00 ET. Qty from filled_contracts (fill_count / cumQuantity). Kalshi No cash = 1 minus Yes-wire when request side is ask/sell. HTTP 201 qty 0 is excluded here and counted in the empty-201 total {esc(empty_201)}. Click column headers to sort.</p>
{fills_html}

<h2>orders.jsonl filled, no matching order_io qty &gt;= 1</h2>
<p class="note">Kalshi fills GET this job confirmed these NFL tickers filled. The gap is order_io, not the venue.</p>
{nfl_html}

<h2>order_io qty &gt;= 1, no matching orders.jsonl filled event</h2>
<p class="note">Mostly Strategy B tennis. Lock-bot filled events did not list these instruments.</p>
{b_gap_html}

<p class="note">Sibling job owns ledger vs open positions on orders_performance.html. This page owns fill-history APIs and the diff. Rerun: <code>python tools/_pull_venue_fill_history_20261022.py</code> then <code>python tools/_write_venue_fill_history_audit_20261022.py</code>. No secrets. No tickets sold.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}")


if __name__ == "__main__":
    main()
