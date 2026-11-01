"""One-shot performance page for the live prediction-market lock bot + Strategy B.

Reads the local tape (orders.jsonl, order_io.jsonl, strategy_b_watch.json).
Does not place, cancel, or sell. Does not print secrets. Does not start Strategy B.
Does not restart pollers. Not gold. Not DailyRun.
"""
from __future__ import annotations

import csv
import html as html_lib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import live_lock_orders  # noqa: E402
import report_page_extras  # noqa: E402
from compare_format import ann_ror_from_closed, format_money  # noqa: E402
from odds_cross_winrate_20261020 import SETTLE_CACHE, game_norm  # noqa: E402
import order_types  # noqa: E402
from order_ledger import (  # noqa: E402
    ORDERS,
    _io_instrument,
    _load_jsonl,
    _order_id_of,
    polymarket_fill,
)
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "orders_performance.html"
STAMP_DIR = STAMP / "orders_performance_20261022"
B_WATCH = RAW / "strategy_b_watch.json"
ONE_LEG = RAW / "one_leg_watch.json"
CONSIDER = RAW / "considerations.json"
STOPPED = RAW / "orders_stopped.json"
LEFTOVER = RAW / "leftover_watch_stats.jsonl"
VENUE_FILL_PULL = RAW / "_venue_fill_history_pull_20261022.json"
SETTLE_LIVE = RAW / "orders_performance_settlements.json"
NFL_SETTLE = RAW / "nfl_t0_spread_settlements_20261025.json"
SETTLED_PNL = RAW / "settled_pnl.json"
UNKNOWN_ASK = "unknown — ask Paul"
ONE = Decimal("1")
CENT = Decimal("0.01")
FOUR = Decimal("0.0001")

INTENT_FULL_LOCK = "intentional full-system lock"
INTENT_INCOMPLETE_LOCK = "intentional incomplete lock"
INTENT_B = "intentional Strategy B"
INTENT_TENNIS = "tennis_crossover"
INTENT_CFB = "cfb_favorite"
INTENT_SPREAD = "spread_t0"
INTENT_DOG = "tennis_t0_dog"
INTENT_SPREAD_F = "tennis_t0_spread"
INTENT_TOTAL_G = "soccer_t0_total"
INTENT_LEFTOVER = "not intentional leftover"
INTENT_LOCK_MISS = "intentional lock, both unfilled"
INTENT_LOCK = "lock"

B_STEPS = {"b-t0", "b-cross", "b-leftover-yes", "b-fav"}
C_STEPS = {"c-t0"}
D_STEPS = {"d-t0"}
E_STEPS = {"e-t0"}
F_STEPS = {"f-t0"}
G_STEPS = {"g-t0"}
FALSE_SHSU_TIMES = ("2026-10-21T22:42:05", "2026-10-21T22:58:48")
IS_CUT = "2024-01-01"
MIN_DAYS_FOR_ANN = 1.0
B_ALIASES = {"b", "strategy_b", "strategy-b", "tennis_crossover", "tennis-crossover"}

SYSTEM_SPECS = (
    ("A", "lock", "Lock gap", "live_lock_orders"),
    ("B", "tennis_crossover", "Tennis crossover", "live_strategy_b (was Strategy B)"),
    ("C", "cfb_favorite", "College football favorite", "live_cfb_favorite"),
    ("D", "spread_t0", "T0 spreads", "live_spread_t0"),
    ("E", "tennis_t0_dog", "Tennis T0 dog", "live_tennis_t0_dog"),
    ("F", "tennis_t0_spread", "Tennis spread", "live_tennis_t0_spread"),
    ("G", "soccer_t0_total", "Soccer total", "live_soccer_t0_total"),
)
SYSTEM_BY_LETTER = {row[0]: row for row in SYSTEM_SPECS}

# Sourced freeze / code / bug-fix stamps. Do not invent dates.
# HTML Written lines, systems.json updated_at, and the live tape. Git on these
# files only has 2026-10-18 17:51 (the dump). Later edits are uncommitted.
CHANGELOG_STAMPS = (
    {
        "when": "2026-10-23T08:29:17-04:00",
        "what": "B Novig enabled: VENUE_ORDER includes Novig; 1-contract IOC + GET /v3/portfolio/fills confirm",
        "systems": ("B",),
        "source": "strategy_b_novig_20261023.html Written 2026-10-23T08:29:17-04:00",
    },
    {
        "when": "2026-10-23T09:18:12-04:00",
        "what": "B wrong-player 50-cross fix (Trungelliti): T0 dog from Yes ask, from-below 50-cross, rewind false favorite-cross",
        "systems": ("B",),
        "source": "trungelliti_dodig_20261023.html Status Checked 2026-10-23 09:18:12 ET",
    },
    {
        "when": "2026-10-23T13:07:00-04:00",
        "what": "Skip-absorbed-B lock skip documented live (test_lock_bot_skip_absorbed_b); page says already in live_lock_orders",
        "systems": ("A",),
        "source": "moutet_paul_t0_20261023.html Written 2026-10-23 13:07 ET",
    },
    {
        "when": "2026-10-24T13:16:00-04:00",
        "what": "C_LO 0.95 floor removed from live T0 send + all-in stack while fees < $1; post-order venue confirm qty ≥ 1",
        "systems": ("B",),
        "source": "strategy_b_t0_under_one_20261024.html Written 2026-10-24 13:16 ET",
    },
    {
        "when": "2026-10-24T15:02:00-04:00",
        "what": "Systems A–D CLI / C and D live start; skip lock also covers an open C or D ticket on the same event",
        "systems": ("A", "B", "C", "D"),
        "source": "systems_abcd_cli_20261024.html Written 2026-10-24 15:02 ET; live_cfb_favorite.py / live_spread_t0.py mtime 14:51 ET",
    },
    {
        "when": "2026-10-29T14:42:00-04:00",
        "what": "Kitchen re-GET settle on postponed; Poly qty > 0 is a ticket; 0.3 leftover cannot flatten as house 1 (Moreno/Herrera)",
        "systems": ("B",),
        "source": "moreno_herrera_poly_autopsy_20261029.html",
    },
)

ASKED = (
    "Paul: kitchen rows for Chirag Duhan vs Aryan Lakshmanan look different from his Polymarket orders page. "
    "Call Poly for completed orders and reconcile. Also: aren't you supposed to do this at the end of each match? "
    "Should we start a separate process that resolves/settles open matches not yet reconciled? "
    "How did you reconcile this match and how does Poly have something different? "
    "Prior: "
    "Paul: game HAS ended and Polymarket HAS settled. We bought 4 different bets, 3 should have won, "
    "kitchen only settled $0.30. Moreno vs Herrera (screenshot jollycobra4517). Kitchen rows marked "
    "postponed: flatten Yes Moreno 0.86 fill 1; initial low Yes Herrera 0.16 fill 1; initial Hi Yes "
    "Moreno 0.85 fill 0.3 HTTP 200 confirm 0 missed send. Guess: many marked postponed have actually "
    "settled — check them ALL. Same class as Pohle/Kostina invert. Do not leftover-GTC on A. Do not "
    "retune C/D/E or B 1.05/0.25. Do not bump stake. Do not DailyRun. Do not start a second B. "
    "Prior: "
    "Paul: “you have the wrong winner here again. can you go back and make sure all of the matches "
    "have the correct winner? Now we need to go back and regenerate all the reports again” "
    "Prior: "
    "Paul: orders_performance.html Performance by system is off — way more open at risk than we should. "
    "In the bottom trade table, add what league the sport was in (lots of tennis leagues; he suspects some are very low volume). "
    "N filled vs N settled is WAY off if settled means the game is over and bets have been paid. MOST filled orders have been settled. "
    "Page shows only 42 of 132 games settled. Define settled honestly: venue-paid / game over / expired/final/void with fill-history qty truth. "
    "Empty Poly positions GET must not drop a confirmed fill while market OPEN; settled/expired/final/void never count as open. "
    "Open at risk = unique games with venue-confirmed qty still unsettled (same overlay as job_status Positions). "
    "Find why N settled is 42/132 and backfill from venue APIs / Kalshi fills GET / Poly activities+positions+market status / Gemini. "
    "If a match is postponed (Llanes, Del Pino) it is open or void — label it, don’t call it settled. "
    "Prior: "
    "Paul: “this should be updated after every closed trade.” Also: performance by system on this page. For each system A–E: from inception "
    "(first confirmed fill / first time that system could trade) and since the last freeze / "
    "code change / bug fix, including a table of those events with the P&L data after each "
    "(not just a date list). Systems: A Lock gap (live_lock_orders); B Tennis crossover "
    "(live_strategy_b, was Strategy B); C College football favorite (live_cfb_favorite, T0 "
    "fav Yes in (0.50, 0.90), best venue, CFB moneyline); D T0 spreads (live_spread_t0, one "
    "spread per game, T0 fav in (0.50, 0.90)). Call out Novig fills. Show open exposure by "
    "system, not only settled. Then the prior asks: "
    "the performance page should be updated after each completed game, and for open games "
    "once an order is filled. Venue confirm (quantity from the Kalshi / Gemini / Polymarket / Novig "
    "fill APIs) is the truth, not the order tape. Do not rebuild on denies, skips, empty Kalshi "
    "HTTP 201s, or catalog scans. Rebuild must not block leftover watch (one-second tick) or "
    "immediate-or-cancel (IOC) send; background debounce is fine. ntfy the Drive HTML rewrite "
    "but do not spam the phone. Then: he would like to reconcile the table “Removed from still-open "
    "(closed, flattened, void, or not on a venue book)” if he knew who the players are and who the "
    "bet was for / against. "
    "Add Players/game, Bet for (the side we bought: player + Yes/No), and Bet against (the hedge "
    "if it was a lock, or unpaired leftover / extra Yes if Strategy B extra). Truth = venues, not "
    "tape guesses. Use Kalshi/Poly/Gemini/Novig fill history and position books already pulled in "
    "this stamp. If a row cannot be identified, say unknown and ask — do not invent names. "
    "Prior venue facts still apply: (1) Ribecai: 1 contract bought. 0.55 No Ribecai vs Houkes. "
    "$1 payout. lost. (2) Urso 0.08/0.12 dollars paid on the 0.10 and 0.15 tickets: yes; leftover "
    "still-open last pull if still on Poly must stay out of Removed. (3) Danilova tape void: yes "
    "(he has no Poly record). (4) Novig empty. Gemini paste: Middle Tennessee vs FIU Total Points, "
    "Resolved Yes more than 48.5, $1.00 USD; Buy Yes more than 48.5 $0.44 USD, 1 "
    "GEMI-NCAAF-2610202300-MTN-FIU-T-O48. Carolina vs Calgary, Resolved Yes Calgary $1.00; "
    "Buy Yes Calgary $0.99, 1 GEMI-NHL-2610190000-CAR-CGY-M-CGY. Tampa Bay vs Cleveland Game 5, "
    "Resolved Yes Tampa Bay $1.00; Buy Yes Tampa Bay $0.97, 1 GEMI-MLB-2610180000-TB-CLE-. "
    "(5) Wolff vs Webb / Machac vs Khachanov still on apps: no. (6) Funk vs Petrov Poly history: "
    "petrov 0.54 to win 0.92; funk 0.42 to win $1; petrov 0.02 to win 0.03; petrov 0.04 to win "
    "0.06; settled for 0.01 win. Tixhon/Cordoba: Poly postponed leftover last pull. Taverna vs "
    "Bueno postponed Kalshi — settlement unknown. Do not place GTC, sell, commit, print secrets, "
    "start a second B, change NET_MAX / deadline / max-open, invent API, or guess."
)
PLAIN = (
    "Aryan Lakshmanan beat Chirag Duhan. Kitchen called a 0.02 extra a missed send because a full house bet is 1; "
    "Polymarket’s orders page still lists that 0.02. The zero-fill extra is not on Poly, and that miss is correct. "
    "The start pair is the same two tickets Poly shows (Yes Duhan 1 lost, Yes Lakshmanan 1 won). "
    "A one-process checker now re-pulls venue fills on open / postponed / missed-send rows after a match ends. "
    "Prior: "
    "Alejandro Moreno beat Thomas Cardona Herrera (UTR PTT Knoxville Men 05, 3-6 6-4 7-6). "
    "Polymarket Yes=Moreno settled at $1. Kitchen kept the tickets postponed because the watch "
    "said “closed without settlement” and never re-GETed, and it treated the 0.3 Moreno fill as a "
    "missed send (confirm 0) because a house fill is 1 contract. Ledger qty now matches the venue "
    "(0.3 is a real ticket). Postponed is only when the market is still open and the start is still "
    "in the future, or the venue officially postponed. Closed games get a settlement GET. "
    "Prior: "
    "We showed the wrong player as the winner on some Polymarket tennis games, so P&L was backwards. "
    "Victoria Pohle beat Arina Kostina (ITF W15 Essen, 1-6 6-1 6-2); kitchen had paid Kostina. "
    "We checked every settled game against the platform (venue fill + venue settlementPx) and rebuilt the pages. "
    "Settled on this page means the venue already paid, voided, expired, or marked the market final — "
    "the game is over and the ticket is not still a live holding. Quantity truth is fill-history "
    "(Kalshi fills GET, Polymarket activities / this-order quantity, Gemini history), not an empty "
    "positions list. An empty Polymarket positions GET does not drop a confirmed fill while that "
    "market is still OPEN. Settled / expired / final / void never count as open. Open at risk is the "
    "same unique-game overlay as job_status Positions: venue-confirmed quantity still unsettled. "
    "A postponed match (Llanes, Del Pino) is labeled postponed — open if the book still holds it, "
    "or void if the venue cancelled it — never called settled. The old 42-of-132 settled count was "
    "wrong because the research settlement cache stops at Oct 20/21 and C/D/E fills with an empty "
    "GET were treated as still open. "
    "This page rewrites itself in the background after each closed trade — a venue settlement, "
    "a flatten close, or a void/final/expired market on a ticket we already bought — and also "
    "when a venue confirms a real fill on a still-open game (quantity greater than zero; a house "
    "fill is at least 1 contract; a partial Polymarket ticket below 1 still counts if it is a real "
    "venue ticket). An empty Polymarket positions list does not count as a close while that market "
    "is still open. Five systems settling the same second share one rewrite. A deny, a skip, an empty "
    "Kalshi immediate-or-cancel (HTTP 201 with fill_count 0), or a catalog scan does not rewrite it. "
    "This page is a scoreboard of the live prediction-market experiment. A prediction market is a "
    "venue (Kalshi, Gemini, Polymarket, Novig) where a ticket costs between 0 and $1 and pays $1 "
    "if that named result happens. Four live systems: A Lock gap buys Yes on one venue and No on "
    "the other when the pair is cheap enough. B Tennis crossover (was Strategy B) buys Yes on both "
    "tennis players at the first trusted start. C College football favorite buys the kickoff favorite "
    "on the who-wins market when that Yes is between 50 and 90 cents, cheapest venue. D T0 spreads "
    "buys one qualifying point-spread favorite in that same 50–90 cent band. The Removed-from-still-open "
    "table now names both players (or both teams) and spells out Bet for / Bet against so Paul can match "
    "the row on the venue apps: Bet for is the "
    "side we actually bought; Bet against is the hedge if both legs filled, or “unpaired leftover / "
    "extra Yes” if we only got one side. Names come from venue fill history, the live position "
    "book, or a Paul-confirmed paste — not from guessing a ticker. If we cannot name the side, the "
    "cell says unknown — ask Paul. Truth here is what the venues currently hold or already settled, "
    "plus the six history facts Paul confirmed. The tape is a diary. When tape and venue disagree, "
    "the venue wins and the row is flagged. Still open means the ticket is on a live venue book "
    "right now (fresh Kalshi GET and Polymarket US GET this job). Gemini has no "
    "positions helper in the modules we already use; Paul's paste is the Gemini book, and those "
    "three tickets are resolved, not still open. Realized dollars are only from a venue settlement "
    "or Paul's confirmed history. Everything else is unknown — ask. Immediate-or-cancel (IOC) means "
    "fill now or cancel: Kalshi HTTP 201 with fill_count 0 is an empty cancel, not a fill. A house "
    "fill is order_io quantity of at least 1, or a live venue position. Partial Polymarket sizes "
    "below 1 are listed when the venue still nets them, but they are not house fills. "
    "Fill prices are the venue wire. After-fee (all-in) is wire plus the documented taker fee "
    "(Kalshi 0.07 × p × (1 − p) or POST average_fee_paid; Polymarket theta × p × (1 − p); "
    "Gemini ceil-cent; Novig c × p × (1 − p) or GET /v3/portfolio/fills fee). "
    "If we only have a wire, that cell says fee unknown, not 0."
)
HOLD_OPEN = "venue-confirmed open"
HOLD_SETTLED = "venue-settled / Paul history"
HOLD_FLATTEN = "closed flatten (order_io Yes+No, ticker gone)"
HOLD_VOID = "void (tape only, not a venue holding)"
HOLD_POSTPONED = "postponed (not settled; open or void)"
HOLD_UNKNOWN = "tape fill, venue empty, P&L unknown"
HOLD_NEVER = "never held"
HOLD_PRICE = "matched qty; tape vs venue price differs"
FINAL_RESULTS = {"yes", "no", "void", "n/a"}
FINAL_STATUS = {
    "settled", "resolved", "expired", "final", "finalized", "determined",
    "inactive", "void", "voided",
}
KALSHI_FINAL_STATUS = FINAL_STATUS | {"closed"}
# Catalog series / slug prefixes already used in-repo. Do not invent a league.
LEAGUE_FROM_TOKEN = (
    ("KXATPCHALLENGERMATCH", "ATP Challenger"),
    ("KXWTACHALLENGERMATCH", "WTA Challenger"),
    ("KXATPMATCH", "ATP"),
    ("KXWTAMATCH", "WTA"),
    ("KXITF", "ITF"),
    ("KXNCAAF", "CFB"),
    ("KXNFL", "NFL"),
    ("KXNHL", "NHL"),
    ("KXMLB", "MLB"),
    ("KXWNBA", "WNBA"),
    ("KXNBA", "NBA"),
    ("KXUCL", "UCL"),
    ("KXEPL", "EPL"),
    ("KXLIGAMX", "Liga MX"),
    ("KXMLS", "MLS"),
    ("KXNCAAMB", "NCAAMB"),
    ("AEC-NFL-", "NFL"),
    ("AEC-ATPCHALLENGER", "ATP Challenger"),
    ("AEC-WTACHALLENGER", "WTA Challenger"),
    ("AEC-ATP-", "ATP"),
    ("AEC-WTA-", "WTA"),
    ("AEC-ITFME-", "ITF"),
    ("AEC-ITFWO-", "ITF"),
    ("AEC-ITF-", "ITF"),
    ("GEMI-NCAAF", "CFB"),
    ("GEMI-NFL", "NFL"),
    ("GEMI-NHL", "NHL"),
    ("GEMI-MLB", "MLB"),
    ("GEMI-NBA", "NBA"),
    ("GEMI-WNBA", "WNBA"),
)

GEMINI_PASTE = [
    {
        "instrument": "GEMI-NCAAF-2610202300-MTN-FIU-T-O48",
        "game": "Middle Tennessee vs FIU Total Points",
        "resolved": "Yes more than 48.5",
        "payout": Decimal("1.00"),
        "buy": "Yes more than 48.5",
        "buy_price": Decimal("0.44"),
        "qty": Decimal("1"),
        "pnl": Decimal("0.56"),
        "arithmetic": "$1.00 Resolved Yes minus $0.44 Buy Yes = +$0.56",
        "needles": ("gemi-ncaaf-2610202300-mtn-fiu-t-o48", "middle tennessee vs fiu"),
    },
    {
        "instrument": "GEMI-NHL-2610190000-CAR-CGY-M-CGY",
        "game": "Carolina vs Calgary",
        "resolved": "Yes Calgary",
        "payout": Decimal("1.00"),
        "buy": "Yes Calgary",
        "buy_price": Decimal("0.99"),
        "qty": Decimal("1"),
        "pnl": Decimal("0.01"),
        "arithmetic": "$1.00 Resolved Yes minus $0.99 Buy Yes = +$0.01",
        "needles": ("gemi-nhl-2610190000-car-cgy-m-cgy", "carolina vs calgary"),
    },
    {
        "instrument": "GEMI-MLB-2610180000-TB-CLE-M-TB",
        "game": "Tampa Bay vs Cleveland Game 5",
        "resolved": "Yes Tampa Bay",
        "payout": Decimal("1.00"),
        "buy": "Yes Tampa Bay",
        "buy_price": Decimal("0.97"),
        "qty": Decimal("1"),
        "pnl": Decimal("0.03"),
        "arithmetic": "$1.00 Resolved Yes minus $0.97 Buy Yes = +$0.03",
        "needles": ("gemi-mlb-2610180000-tb-cle-m-tb", "gemi-mlb-2610180000-tb-cle-", "tampa bay vs cleveland"),
    },
]
FUNK_PAUL_TICKETS = [
    {"name": "petrov", "paid": "0.54", "to_win": "0.92"},
    {"name": "funk", "paid": "0.42", "to_win": "1.00"},
    {"name": "petrov", "paid": "0.02", "to_win": "0.03"},
    {"name": "petrov", "paid": "0.04", "to_win": "0.06"},
]
LEFTOVER_YES = "leftover"
LEFTOVER_NO = "no leftover"


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, kind: str = "text") -> str:
    text = "" if value is None else str(value)
    extra = ' class="num"' if kind == "num" else ""
    return f"<td{extra}>{esc(text)}</td>"


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
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def money(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    sign = "" if number >= 0 else "-"
    return f"{sign}${abs(number).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def money4(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    return format(number.quantize(FOUR, rounding=ROUND_HALF_UP), "f")


def fee_cell_text(leg: dict) -> str:
    """Fee on a filled leg. Missing → fee unknown, not 0."""
    if not qty_is_fill(leg.get("qty")):
        return ""
    if leg.get("fee") in (None, ""):
        return "fee unknown"
    return money4(leg.get("fee"))


def after_fee_text(leg: dict) -> str:
    """All-in wire + fee. Wire alone is not after-fee."""
    if not qty_is_fill(leg.get("qty")):
        return ""
    cash = ddec(leg.get("cash"))
    fee = ddec(leg.get("fee")) if leg.get("fee") not in (None, "") else None
    if cash is None:
        return ""
    if fee is None:
        return "fee unknown"
    return money4(cash + fee)


def money4_dollar(value) -> str:
    """After-fee / fill-cost dollars at >=4 decimals."""
    text = money4(value)
    if not text:
        return ""
    try:
        number = Decimal(text)
    except Exception:
        return text
    sign = "" if number >= 0 else "-"
    return f"{sign}${abs(number)}"


def qty_is_fill(qty) -> bool:
    """Any venue-confirmed size is a ticket. House 1 is qty_is_house_fill."""
    try:
        return Decimal(str(qty or 0)) > 0
    except Exception:
        return False


def qty_is_house_fill(qty) -> bool:
    """Full 1-contract house size. A Polymarket 0.3 leftover is not this."""
    try:
        return Decimal(str(qty or 0)) >= 1
    except Exception:
        return False


def flatten_marks_house_one(filled_qty, flatten_qty=None) -> bool:
    """True when a sub-1 venue fill would be flattened or booked as house 1."""
    try:
        filled = Decimal(str(filled_qty or 0))
    except Exception:
        return False
    try:
        flat = Decimal("1") if flatten_qty is None else Decimal(str(flatten_qty or 0))
    except Exception:
        flat = Decimal("1")
    return Decimal("0") < filled < 1 and flat >= 1


def is_empty_http_fill(http_status, qty) -> bool:
    try:
        status = int(http_status)
    except (TypeError, ValueError):
        return False
    return status in {200, 201} and not qty_is_fill(qty)


def is_strategy_b_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or row.get("source") or "").strip().lower().replace(" ", "_")
    if system in B_ALIASES:
        return True
    return bool(row.get("_strategy_b")) or key.startswith("tennis-b") or step.startswith("b-") or step in B_STEPS


def is_cfb_favorite_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or "")
    return system == "cfb_favorite" or key.startswith("cfb-favorite") or step in C_STEPS or step.startswith("c-")


def is_spread_t0_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or "")
    return system == "spread_t0" or key.startswith("spread-t0") or step in D_STEPS or step.startswith("d-")


def is_tennis_t0_dog_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or "")
    return system == "tennis_t0_dog" or key.startswith("tennis-t0-dog") or step in E_STEPS or step.startswith("e-")


def is_tennis_t0_spread_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or "")
    return system == "tennis_t0_spread" or key.startswith("tennis-t0-spread") or step in F_STEPS or step.startswith("f-")


def is_soccer_t0_total_row(row: dict) -> bool:
    key = str(row.get("bet_key") or "")
    step = str(row.get("step") or "")
    system = str(row.get("system") or "")
    return system == "soccer_t0_total" or key.startswith("soccer-t0-total") or step in G_STEPS or step.startswith("g-")


def order_type_of(leg: dict, cluster: dict) -> str:
    """A–E send role. One label per order."""
    return order_types.from_leg(leg, cluster)


def source_label(row: dict) -> str:
    if is_cfb_favorite_row(row):
        return "cfb_favorite"
    if is_spread_t0_row(row):
        return "spread_t0"
    if is_tennis_t0_dog_row(row):
        return "tennis_t0_dog"
    if is_tennis_t0_spread_row(row):
        return "tennis_t0_spread"
    if is_soccer_t0_total_row(row):
        return "soccer_t0_total"
    if is_strategy_b_row(row):
        return "tennis_crossover"
    return "lock"


def classify_intent(
    *,
    is_b: bool,
    posted: bool,
    n_fill_legs: int,
    complementary: bool,
    b_t0_both: bool = False,
    leftover_stack: bool = False,
) -> str:
    if leftover_stack:
        return INTENT_LEFTOVER
    if is_b:
        if b_t0_both or (n_fill_legs >= 2 and complementary):
            return INTENT_B
        if posted and n_fill_legs >= 1:
            return INTENT_LEFTOVER
        if not posted:
            return INTENT_LEFTOVER
        return INTENT_B
    if not posted:
        return INTENT_LEFTOVER
    if n_fill_legs >= 2 and complementary:
        return INTENT_FULL_LOCK
    if n_fill_legs >= 1:
        return INTENT_INCOMPLETE_LOCK
    return INTENT_LOCK_MISS


def leftover_status(cluster: dict) -> str:
    """leftover = we hold one side of a lock/B pair and never got the hedge.

    no leftover = both legs of that intended pair filled, or we flattened, or we never held
    (claim/skip only). Flatten-filled is no leftover even if the original cluster looked one-leg.
    """
    if cluster.get("void") or cluster.get("paul_settled") or cluster.get("gemini_settled"):
        return LEFTOVER_NO
    if cluster.get("flatten_filled"):
        return LEFTOVER_NO
    n_fill = int(cluster.get("n_fill_legs") or 0)
    if n_fill <= 0:
        return LEFTOVER_NO
    if cluster.get("complementary") and n_fill >= 2:
        return LEFTOVER_NO
    if cluster.get("b_t0_both"):
        return LEFTOVER_NO
    kind = str(cluster.get("kind") or "")
    intent = str(cluster.get("intent") or "")
    if kind in {"cfb_favorite", "spread_t0", "tennis_t0_dog", "tennis_t0_spread", "soccer_t0_total"} or intent in {INTENT_CFB, INTENT_SPREAD, INTENT_DOG, INTENT_SPREAD_F, INTENT_TOTAL_G}:
        return LEFTOVER_NO
    return LEFTOVER_YES


def system_of(cluster: dict) -> str:
    """A lock (incl. leftover/flatten), B tennis crossover, C CFB favorite, D T0 spreads.

    Lock leftover and flatten stay on A (lock-bot), not B. Older Strategy B / strategy_b
    labels map to B Tennis crossover.
    """
    kind = str(cluster.get("kind") or "")
    intent = str(cluster.get("intent") or "")
    system = str(cluster.get("system") or cluster.get("source") or "").strip().lower().replace(" ", "_")
    if kind == "cfb_favorite" or intent == INTENT_CFB or system in {"c", "cfb_favorite", "cfb-favorite"}:
        return "C"
    if kind == "spread_t0" or intent == INTENT_SPREAD or system in {"d", "spread_t0", "spread-t0"}:
        return "D"
    if kind == "tennis_t0_dog" or intent == INTENT_DOG or system in {"e", "tennis_t0_dog", "tennis-t0-dog"}:
        return "E"
    if kind == "tennis_t0_spread" or intent == INTENT_SPREAD_F or system in {"f", "tennis_t0_spread", "tennis-t0-spread"}:
        return "F"
    if kind == "soccer_t0_total" or intent == INTENT_TOTAL_G or system in {"g", "soccer_t0_total", "soccer-t0-total"}:
        return "G"
    if (
        cluster.get("is_b")
        or kind == "b"
        or intent in {INTENT_B, INTENT_TENNIS}
        or system in B_ALIASES
        or is_strategy_b_row(cluster)
    ):
        return "B"
    return "A"


def system_role(cluster: dict) -> str:
    letter = cluster.get("system_letter") or system_of(cluster)
    intent = str(cluster.get("intent") or "")
    leftover = str(cluster.get("leftover_flag") or leftover_status(cluster))
    if letter == "A":
        if intent == INTENT_FULL_LOCK or cluster.get("flatten_filled"):
            if cluster.get("flatten_filled") and leftover == LEFTOVER_NO:
                return "true lock / flatten"
            return "true lock"
        if intent == INTENT_INCOMPLETE_LOCK or leftover == LEFTOVER_YES:
            return "leftover lock"
        if intent == INTENT_LOCK_MISS:
            return "lock miss (unfilled)"
        return "lock"
    if letter == "B":
        if cluster.get("leftover_stack") or intent == INTENT_LEFTOVER:
            return "leftover extra (B)"
        if cluster.get("b_t0_both"):
            return "tennis crossover T0"
        return "tennis crossover"
    if letter == "C":
        return "CFB favorite Yes"
    if letter == "D":
        return "T0 spread Yes"
    if letter == "E":
        return "tennis T0 dog Yes"
    return letter


def assign_system(cluster: dict) -> dict:
    letter = system_of(cluster)
    spec = SYSTEM_BY_LETTER[letter]
    if letter == "B" and cluster.get("intent") == INTENT_B:
        cluster["intent"] = INTENT_TENNIS
    cluster["system_letter"] = letter
    cluster["system_id"] = spec[1]
    cluster["system_name"] = spec[2]
    cluster["system_code"] = spec[3]
    cluster["system_role"] = system_role(cluster)
    return cluster


def cluster_when(cluster: dict) -> datetime | None:
    times = []
    for leg in cluster.get("fill_legs") or []:
        stamp = parse_dt(leg.get("sent_at"))
        if stamp:
            times.append(stamp)
    if times:
        return min(times)
    return cluster.get("start") if isinstance(cluster.get("start"), datetime) else parse_dt(cluster.get("start"))


def game_sides(game: str) -> list[str]:
    """Both names/teams from a matchup title. Does not invent a second name."""
    text = str(game or "").strip()
    if not text:
        return []
    parts = re.split(r"\s+vs\.?\s+|\s+@\s+|\s+v\.?\s+", text, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return [text]
    left, right = parts[0].strip(), parts[1].strip()
    right = re.sub(r"\s+Round of \d+\s*$", "", right, flags=re.I).strip()
    right = re.sub(r"\s+Total Points\s*$", "", right, flags=re.I).strip()
    right = re.sub(r"\s*:?\s*Game \d+\s*$", "", right, flags=re.I).strip()
    return [bit for bit in (left, right) if bit]


def players_game_label(game: str, sport: str = "") -> str:
    sides = game_sides(game)
    if len(sides) >= 2:
        core = f"{sides[0]} vs {sides[1]}"
    elif sides:
        core = sides[0]
    else:
        core = UNKNOWN_ASK
    sport_s = str(sport or "").strip()
    return f"{core} ({sport_s})" if sport_s and core != UNKNOWN_ASK else core


def join_unique(bits: list[str], fallback: str = UNKNOWN_ASK) -> str:
    seen: list[str] = []
    for bit in bits:
        text = str(bit or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "; ".join(seen) if seen else fallback


def match_code_to_name(code: str, names: list[str]) -> str:
    """Map a ticker suffix (RIB, MAC, MIN) onto a name already in the game title."""
    token = game_norm(code).replace(" ", "")
    if not token or not names:
        return ""
    scored: list[tuple[int, str]] = []
    for name in names:
        compact = game_norm(name).replace(" ", "")
        last = last_name(name)
        words = [w for w in game_norm(name).split() if w]
        if not compact:
            continue
        if compact == token or last == token:
            scored.append((100, name))
            continue
        if compact.startswith(token) or last.startswith(token):
            scored.append((80 + min(len(token), 9), name))
            continue
        if len(token) >= 3 and (token.startswith(last[:3]) or last.startswith(token[:3])):
            scored.append((60, name))
            continue
        for word in words:
            if len(token) >= 3 and (word.startswith(token) or token.startswith(word[:3])):
                scored.append((50, name))
                break
    if not scored:
        return ""
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return scored[0][1]


def kalshi_ticker_who(ticker: str, names: list[str]) -> str:
    try:
        import kalshi_ticker_decode as ktd

        if ktd.is_sports_ticker(ticker):
            decoded = ktd.decode_kalshi_ticker(ticker)
            if decoded.kind == "total":
                return f"Over {decoded.line_raw}".strip() if decoded.line_raw else "Over"
            if decoded.kind == "spread":
                who = decoded.yes_name or match_code_to_name(decoded.yes_code, names) or decoded.yes_code
                line = decoded.line or decoded.line_raw
                return f"{who} {line}".strip() if who else (f"spread {line}".strip() if line else "")
            if decoded.kind == "moneyline":
                return (
                    match_code_to_name(decoded.yes_code, names)
                    or decoded.yes_name
                    or decoded.yes_code
                )
    except Exception:
        pass
    parts = [p for p in str(ticker or "").split("-") if p]
    if not parts:
        return ""
    token = parts[-1]
    upper = str(ticker or "").upper()
    letters = "".join(ch for ch in token if ch.isalpha())
    digits = "".join(ch for ch in token if ch.isdigit())
    if "TOTAL" in upper and digits:
        return f"total {digits}"
    if "SPREAD" in upper:
        who = match_code_to_name(letters, names) if letters else ""
        if who and digits:
            return f"{who} spread {token}"
        if who:
            return f"{who} spread"
        return f"spread {token}" if token else ""
    if letters and not digits:
        return match_code_to_name(letters, names)
    if letters:
        who = match_code_to_name(letters, names)
        return who or ""
    return ""


def _overlay_bet_for(item: dict, leg: dict, inst: str) -> str:
    """Kitchen bet-for for a Positions overlay row. Never print ‘Yes no’."""
    try:
        import kalshi_ticker_decode as ktd

        raw = str(item.get("bets") or leg.get("side_label") or "")
        pay = str(leg.get("pay") or item.get("pay") or "")
        if not pay:
            pay = ktd.pay_from_garbled_bet(raw)
        if ktd.is_sports_ticker(inst):
            decoded = ktd.decode_with_cached_title(inst, pay=pay, fetch=False)
            if decoded.kind:
                return ktd.kitchen_phrase(decoded, pay or "yes")
        if ktd.is_yes_no_token(raw.split()[0] if raw.split() else "") and len(raw.split()) >= 2 and ktd.is_yes_no_token(raw.split()[1]):
            return ktd.kitchen_phrase(ktd.decode_kalshi_ticker(inst, pay=pay), pay or "yes") if inst else raw
    except Exception:
        pass
    return str(item.get("bets") or item.get("side_label") or UNKNOWN_ASK)


def load_venue_fill_index(path: Path | None = None) -> dict[tuple[str, str], list[dict]]:
    """Stamp fill-history pull already on disk. Does not call venues."""
    data = load_json(path or VENUE_FILL_PULL) or {}
    index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    venues = data.get("venues") if isinstance(data, dict) else {}
    if not isinstance(venues, dict):
        return index
    for venue_name, block in venues.items():
        if not isinstance(block, dict):
            continue
        rows = list(block.get("fills") or []) + list(block.get("all_rows") or [])
        seen_ids: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            venue = str(row.get("venue") or venue_name or "").lower()
            ticker = str(row.get("ticker") or "")
            if not venue or not ticker:
                continue
            rid = str(row.get("fill_id") or row.get("trade_id") or row.get("order_id") or "")
            key = f"{venue}|{ticker}|{rid}|{row.get('time_et')}|{row.get('qty')}|{row.get('side')}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            index[(venue, ticker.lower())].append(row)
    return index


def venue_fills_for_leg(leg: dict, fills: dict[tuple[str, str], list[dict]]) -> list[dict]:
    venue = str(leg.get("venue") or "").lower()
    inst = str(leg.get("instrument") or "")
    if not venue or not inst:
        return []
    return list(fills.get((venue, inst.lower()), []))


def gemini_buy_label(instrument: str, game: str) -> tuple[str, str]:
    """Yes + named result from Paul's Gemini paste / venue history ticker. No invented teams."""
    inst = str(instrument or "").upper()
    for row in GEMINI_PASTE:
        target = str(row["instrument"]).upper()
        if target in inst or inst in target:
            buy = str(row["buy"] or "")
            lowered = buy.lower()
            book = "yes" if lowered.startswith("yes") else "no" if lowered.startswith("no") else "yes"
            who = buy[4:].strip() if book == "yes" and len(buy) > 4 else buy
            return book, who or UNKNOWN_ASK
    names = game_sides(game)
    if "-T-O" in inst:
        match = re.search(r"T-O(\d+)", inst)
        line = match.group(1) if match else ""
        who = f"more than {line}.5" if line == "48" else (f"more than {line}" if line else UNKNOWN_ASK)
        return "yes", who
    if "-M-" in inst:
        code = inst.rsplit("-M-", 1)[-1]
        who = match_code_to_name(code, names)
        return "yes", who or UNKNOWN_ASK
    return "yes", UNKNOWN_ASK


def leg_book_side(leg: dict, vfills: list[dict]) -> str:
    book = str(leg.get("side") or "").lower()
    if book in {"yes", "no"}:
        return book
    intent = str(leg.get("io_intent") or "").upper()
    if "SHORT" in intent:
        return "no"
    if "LONG" in intent:
        return "yes"
    for row in vfills:
        side = str(row.get("side") or row.get("outcome") or "").lower()
        if side in {"yes", "no"}:
            return side
        if side == "buy" and str(row.get("outcome") or "").lower() in {"yes", "no"}:
            return str(row.get("outcome")).lower()
        if side in {"ask", "sell"}:
            return "no"
        if side in {"bid"}:
            return "yes"
    return ""


def leg_who(leg: dict, names: list[str], vfills: list[dict], game: str) -> str:
    venue = str(leg.get("venue") or "").lower()
    inst = str(leg.get("instrument") or "")
    if venue == "gemini":
        _book, who = gemini_buy_label(inst, game)
        if who and who != UNKNOWN_ASK:
            return who
    outcome = str(leg.get("outcome_name") or "").strip()
    if outcome:
        return outcome
    player = str(leg.get("player") or "").strip()
    if player and player.lower() not in {"yes", "no", "over", "under"}:
        if names and match_code_to_name(player, names):
            return match_code_to_name(player, names)
        if names and any(same_player(player, name) for name in names):
            for name in names:
                if same_player(player, name):
                    return name
        if " vs " not in player.lower() and " vs." not in player.lower():
            return player
    if venue == "kalshi":
        who = kalshi_ticker_who(inst, names)
        if who:
            return who
    for row in vfills:
        event = str(row.get("event") or row.get("title") or "").strip()
        if event and venue == "gemini":
            _book, who = gemini_buy_label(inst, event)
            if who and who != UNKNOWN_ASK:
                return who
    return ""


def _real_player_name(text: str) -> str:
    name = str(text or "").strip()
    if not name:
        return ""
    low = name.lower()
    if low in {"yes", "no", "over", "under"} or low.startswith("unknown"):
        return ""
    return name


def _t0_yes_pair(cluster: dict | None) -> tuple[str, str]:
    slots = ((cluster or {}).get("watch") or {}).get("t0_yes") if isinstance(cluster, dict) else None
    if not isinstance(slots, dict):
        return "", ""
    a = _real_player_name(((slots.get("a") or {}) if isinstance(slots.get("a"), dict) else {}).get("player"))
    b = _real_player_name(((slots.get("b") or {}) if isinstance(slots.get("b"), dict) else {}).get("player"))
    return a, b


def _cluster_name_legs(cluster: dict | None) -> list[dict]:
    if not isinstance(cluster, dict):
        return []
    return list(cluster.get("fill_legs") or []) or list(cluster.get("legs") or [])


def _poly_is_short(leg: dict) -> bool:
    intent = str(leg.get("io_intent") or "").upper()
    if "SHORT" in intent:
        return True
    if "LONG" in intent:
        return False
    return str(leg.get("side") or "").lower() == "no"


def _other_game_name(player: str, names: list[str]) -> str:
    names = [str(n).strip() for n in (names or []) if str(n).strip()]
    if len(names) < 2:
        return ""
    if not player:
        return names[1]
    others = [n for n in names if not same_player(player, n)]
    return others[0] if others else ""


def _long_outcome_name(leg: dict, cluster: dict | None, names: list[str]) -> str:
    """Named Yes / long player on this Polymarket slug. Not this SHORT's metadata."""
    a, _b = _t0_yes_pair(cluster)
    if a:
        return a
    inst = str(leg.get("instrument") or "")
    for other in _cluster_name_legs(cluster):
        if other is leg:
            continue
        if inst and str(other.get("instrument") or "") != inst:
            continue
        o_intent = str(other.get("io_intent") or "").upper()
        o_side = str(other.get("side") or "").lower()
        if "SHORT" in o_intent or o_side == "no":
            continue
        who = _real_player_name(other.get("outcome_name") or other.get("player"))
        if who:
            return who
    if not _poly_is_short(leg):
        who = _real_player_name(leg.get("outcome_name") or leg.get("player"))
        if who:
            return who
    if names:
        return names[0]
    return _real_player_name((cluster or {}).get("side") if isinstance(cluster, dict) else "")


def _named_poly_outcome(leg: dict) -> str:
    """Who this Poly seat names. LONG prefers outcome_name; SHORT prefers player."""
    if _poly_is_short(leg):
        return _real_player_name(leg.get("player") or leg.get("outcome_name"))
    return _real_player_name(leg.get("outcome_name") or leg.get("player"))


def _same_named_yes_no(leg: dict, cluster: dict | None) -> bool:
    """True No: Yes and No on one named outcome (lock), not two-player T0."""
    this = _named_poly_outcome(leg)
    inst = str(leg.get("instrument") or "")
    this_short = _poly_is_short(leg)
    this_yes = (not this_short) and str(leg.get("side") or "").lower() == "yes"
    for other in _cluster_name_legs(cluster):
        if other is leg:
            continue
        if inst and str(other.get("instrument") or "") != inst:
            continue
        other_who = _named_poly_outcome(other)
        if not this or not other_who or not same_player(this, other_who):
            continue
        o_short = _poly_is_short(other)
        o_yes = (not o_short) and str(other.get("side") or "").lower() == "yes"
        if (this_short and o_yes) or (this_yes and o_short):
            return True
    return False


def _poly_short_is_yes_opponent(leg: dict, cluster: dict | None, names: list[str]) -> bool:
    """Polymarket BUY_SHORT on a two-player moneyline pays when the opponent wins."""
    if not isinstance(cluster, dict):
        cluster = {}
    market = str(cluster.get("market") or cluster.get("market_type") or (cluster.get("claim") or {}).get("market_type") or "").lower()
    if any(bit in market for bit in ("spread", "total")):
        return False
    a, b = _t0_yes_pair(cluster)
    if a and b and not same_player(a, b):
        return True
    if cluster.get("b_t0_both") or cluster.get("is_b"):
        return True
    kind = str(cluster.get("kind") or "")
    if kind in {"b", "tennis_crossover", "tennis", "tennis_t0_dog"}:
        return True
    letter = str(cluster.get("system_letter") or "")
    if letter in {"B", "E"}:
        return True
    if str(cluster.get("sport") or "").lower() == "tennis":
        return True
    this = _real_player_name(leg.get("player") or leg.get("outcome_name"))
    inst = str(leg.get("instrument") or "")
    for other in _cluster_name_legs(cluster):
        if other is leg:
            continue
        if inst and str(other.get("instrument") or "") != inst:
            continue
        other_who = _real_player_name(other.get("player") or other.get("outcome_name"))
        if this and other_who and not same_player(this, other_who):
            return True
    return False


def _short_pay_player(leg: dict, cluster: dict | None, names: list[str]) -> str:
    """Player this Polymarket BUY_SHORT pays $1 with (short-named / opponent)."""
    a, b = _t0_yes_pair(cluster)
    player = _real_player_name(leg.get("player"))
    outcome = _real_player_name(leg.get("outcome_name"))
    long_name = _long_outcome_name(leg, cluster, names)
    if player and long_name and not same_player(player, long_name):
        return player
    if player and b and same_player(player, b):
        return b if len(b) >= len(player) else player
    if b and (not player or (a and same_player(player, a))):
        return b
    if player and long_name and same_player(player, long_name):
        return _other_game_name(player, names) or b or player
    if outcome and long_name and not same_player(outcome, long_name):
        return outcome
    if player:
        return player
    if b:
        return b
    other = _other_game_name(long_name or outcome, names)
    if other:
        return other
    if len(names) >= 2:
        return names[1]
    return player or outcome or ""


def kitchen_side_label(leg: dict, cluster: dict | None = None, *, names: list[str] | None = None, game: str = "") -> str:
    """Kitchen Yes/No for a filled/sent ticket.

    If this seat pays $1 when player P wins → ``Yes P``. Polymarket BUY_SHORT on
    a two-player moneyline is Yes on the short-named player (opponent of the
    long outcome), not No that player. BUY_LONG stays Yes {outcome/long player}.
    A true No (Yes+No same named outcome, or Kalshi No) stays No {that name}.
    Does not change send side (BUY_LONG / BUY_SHORT).
    """
    venue = str(leg.get("venue") or "").lower()
    game = game or str((cluster or {}).get("game") or "")
    names = list(names) if names is not None else game_sides(game)
    player = _real_player_name(leg.get("player"))
    outcome = _real_player_name(leg.get("outcome_name"))
    book = str(leg.get("side") or "").lower()
    a, _b = _t0_yes_pair(cluster)
    who = player or outcome
    if venue == "kalshi":
        phrase = ""
        try:
            import kalshi_ticker_decode as ktd

            inst = str(leg.get("instrument") or "")
            if ktd.is_sports_ticker(inst):
                decoded = ktd.decode_kalshi_ticker(inst, title=str(leg.get("title") or ""), pay=book)
                phrase = ktd.kitchen_phrase(decoded, book if book in {"yes", "no"} else "yes")
        except Exception:
            phrase = ""
        if not phrase:
            if not who:
                who = kalshi_ticker_who(str(leg.get("instrument") or ""), names) or _real_player_name((cluster or {}).get("side") if isinstance(cluster, dict) else "")
            yn = book.capitalize() if book in {"yes", "no"} else ""
            if yn and who:
                phrase = f"{yn} {who}"
            else:
                phrase = yn or who or UNKNOWN_ASK
        try:
            import kalshi_ticker_decode as ktd

            gloss = ktd.sold_yes_buy_no_gloss(book)
        except Exception:
            gloss = "Sold Yes = buy No" if book == "no" else ""
        if gloss and gloss.lower() not in phrase.lower():
            return f"{phrase} ({gloss})"
        return phrase
    if venue != "polymarket":
        yn = book.capitalize() if book in {"yes", "no"} else ""
        who = who or _real_player_name((cluster or {}).get("side") if isinstance(cluster, dict) else "")
        if yn and who:
            return f"{yn} {who}"
        return yn or who or UNKNOWN_ASK
    is_short = _poly_is_short(leg)
    if not is_short:
        who = outcome or player or a or _real_player_name((cluster or {}).get("side") if isinstance(cluster, dict) else "") or (names[0] if names else "")
        return f"Yes {who}" if who else "Yes"
    if str(leg.get("step") or "") == "e-t0":
        who = player or _short_pay_player(leg, cluster, names)
        return f"Yes {who}" if who else "Yes"
    if _same_named_yes_no(leg, cluster):
        who = player or outcome or _long_outcome_name(leg, cluster, names) or (names[0] if names else "")
        return f"No {who}" if who else "No"
    if _poly_short_is_yes_opponent(leg, cluster, names):
        who = _short_pay_player(leg, cluster, names)
        return f"Yes {who}" if who else "Yes"
    who = player or outcome or _long_outcome_name(leg, cluster, names) or _real_player_name((cluster or {}).get("side") if isinstance(cluster, dict) else "") or (names[0] if names else "")
    return f"No {who}" if who else "No"


def stamp_kitchen_side_labels(cluster: dict) -> dict:
    """Set display ``side_label`` on each enrich leg. Leaves venue ``side`` alone."""
    for leg in list(cluster.get("legs") or []) + list(cluster.get("fill_legs") or []):
        if not isinstance(leg, dict):
            continue
        leg["side_label"] = kitchen_side_label(leg, cluster)
    return cluster


def format_leg_bet(leg: dict, names: list[str], fills_index: dict, game: str, cluster: dict | None = None) -> dict:
    vfills = venue_fills_for_leg(leg, fills_index)
    book = leg_book_side(leg, vfills)
    who = leg_who(leg, names, vfills, game)
    venue = str(leg.get("venue") or "").lower() or UNKNOWN_ASK
    qty = None
    price = None
    when = ""
    if vfills:
        house = [row for row in vfills if row.get("house_fill")] or vfills
        qtys = [ddec(row.get("qty")) for row in house if ddec(row.get("qty")) is not None]
        if qtys:
            qty = sum(qtys, Decimal("0"))
        for row in house:
            if venue == "kalshi":
                price = ddec(row.get("house_cash")) or ddec(row.get("no_price" if book == "no" else "yes_wire"))
            else:
                price = ddec(row.get("price")) or ddec(row.get("cost"))
            when = str(row.get("time_et") or "")
            if price is not None:
                break
    if qty is None:
        qty = ddec(leg.get("qty"))
    if price is None:
        price = ddec(leg.get("cash"))
    if not when:
        when = fmt_et(leg.get("sent_at"))
    phrase = kitchen_side_label(leg, cluster, names=names, game=game)
    who_txt = who or UNKNOWN_ASK
    if phrase.startswith("Yes ") or phrase.startswith("No "):
        who_txt = phrase.split(" ", 1)[1] or who_txt
    return {
        "phrase": phrase,
        "book": book,
        "who": who_txt,
        "venue": venue,
        "qty": qty,
        "price": price,
        "when": when,
        "step": str(leg.get("step") or ""),
        "named": bool(who_txt) and who_txt != UNKNOWN_ASK and (phrase.startswith("Yes ") or phrase.startswith("No ")),
    }


def cluster_bet_view(cluster: dict, fills_index: dict | None = None) -> dict:
    """Players / Bet for / Bet against from venue fills + order_io legs. No invented names."""
    fills_index = fills_index or {}
    game = str(cluster.get("game") or "")
    sport = str(cluster.get("sport") or "")
    names = game_sides(game)
    if not names:
        insts = " ".join(
            str(leg.get("instrument") or "")
            for leg in (cluster.get("fill_legs") or cluster.get("legs") or [])
        ).upper()
        if "MTUFIU" in insts or "MTN-FIU" in insts:
            game = game or "Middle Tennessee vs FIU"
            sport = sport or "college football"
            names = game_sides(game)
    if not names:
        outcomes: list[str] = []
        for leg in cluster.get("fill_legs") or []:
            outcome = str(leg.get("outcome_name") or "").strip()
            if outcome and outcome not in outcomes:
                outcomes.append(outcome)
        if len(outcomes) >= 2:
            game = f"{outcomes[0]} vs {outcomes[1]}"
            names = outcomes[:2]
            sport = sport or "tennis"
        elif len(outcomes) == 1:
            game = outcomes[0]
            names = outcomes[:1]
            sport = sport or "tennis"
    players = players_game_label(game, sport)
    fill_legs = [leg for leg in (cluster.get("fill_legs") or []) if qty_is_fill(leg.get("qty"))]
    if not fill_legs:
        fill_legs = list(cluster.get("fill_legs") or [])
    formatted = [format_leg_bet(leg, names, fills_index, game, cluster) for leg in fill_legs]
    gem = gemini_paste_for(cluster)
    if gem is not None:
        buy = str(gem["buy"])
        players = players_game_label(str(gem.get("game") or game), sport)
        bet_for = buy
        bet_against = "no hedge (one-leg Gemini Yes; resolved)"
        return {
            "players": players,
            "bet_for": bet_for,
            "bet_against": bet_against,
            "venue": "gemini",
            "qty": money4(gem.get("qty")),
            "prices": money4(gem.get("buy_price")),
            "times": "",
            "named": True,
            "legs": formatted,
        }
    if blob_has(cluster_blob(cluster), "ribecai", "houkes", "ribhou") and cluster.get("paul_settled"):
        return {
            "players": players_game_label(game or "Ribecai vs Houkes", sport or "tennis"),
            "bet_for": "No Ribecai (Kalshi, 1 contract)",
            "bet_against": "unpaired leftover (no hedge; lost)",
            "venue": "kalshi",
            "qty": "1",
            "prices": "0.55",
            "times": join_unique([row["when"] for row in formatted if row.get("when")], ""),
            "named": True,
            "legs": formatted,
        }
    if blob_has(cluster_blob(cluster), "aaron funk", "sergey petrov", "aarfun", "serpet") and cluster.get("paul_settled"):
        return {
            "players": players_game_label(game or "Aaron Funk vs Sergey Petrov", sport or "tennis"),
            "bet_for": "Yes Funk (Poly)",
            "bet_against": "No Petrov (Poly shorts; lock hedge). Settled +$0.01",
            "venue": "polymarket",
            "qty": join_unique([money4(row.get("qty")) for row in formatted if row.get("qty") is not None], ""),
            "prices": join_unique([money4(row.get("price")) for row in formatted if row.get("price") is not None], ""),
            "times": join_unique([row["when"] for row in formatted if row.get("when")], ""),
            "named": True,
            "legs": formatted,
        }
    if cluster.get("void") and blob_has(cluster_blob(cluster), "danilova", "beck", "sibai"):
        for_bits = [row["phrase"] for row in formatted]
        return {
            "players": players_game_label(game or "Danilova-Liu vs Beck-Sibai", sport or "tennis"),
            "bet_for": join_unique(for_bits) if for_bits else "void — tape only, not a venue holding",
            "bet_against": "void — not a venue holding (Paul: no Poly record)",
            "venue": join_unique([row["venue"] for row in formatted], "polymarket"),
            "qty": join_unique([money4(row.get("qty")) for row in formatted if row.get("qty") is not None], ""),
            "prices": join_unique([money4(row.get("price")) for row in formatted if row.get("price") is not None], ""),
            "times": join_unique([row["when"] for row in formatted if row.get("when")], ""),
            "named": bool(names) and len(names) >= 2,
            "legs": formatted,
        }
    venues = join_unique([row["venue"] for row in formatted], "")
    qtys = join_unique([money4(row.get("qty")) for row in formatted if row.get("qty") is not None], "")
    prices = join_unique([money4(row.get("price")) for row in formatted if row.get("price") is not None], "")
    times = join_unique([row["when"] for row in formatted if row.get("when")], "")
    phrases = [row["phrase"] for row in formatted]
    named = bool(names) and len(names) >= 2 and all(row.get("named") for row in formatted) if formatted else bool(names)
    if not formatted:
        return {
            "players": players,
            "bet_for": UNKNOWN_ASK,
            "bet_against": UNKNOWN_ASK,
            "venue": "",
            "qty": "",
            "prices": "",
            "times": "",
            "named": False,
            "legs": [],
        }
    extra = bool(cluster.get("leftover_stack") or cluster.get("intent") == INTENT_LEFTOVER)
    leftover = leftover_status(cluster) == LEFTOVER_YES
    if extra or (leftover and len(formatted) == 1):
        against = "unpaired leftover / extra Yes" if cluster.get("is_b") or extra else "unpaired leftover (no hedge filled)"
        return {
            "players": players,
            "bet_for": join_unique(phrases),
            "bet_against": against,
            "venue": venues,
            "qty": qtys,
            "prices": prices,
            "times": times,
            "named": named,
            "legs": formatted,
        }
    if cluster.get("flatten_filled"):
        orig = [row for row in formatted if str(row.get("step") or "") not in {"flatten", "extra-flatten"}]
        flat = [row for row in formatted if str(row.get("step") or "") in {"flatten", "extra-flatten"}]
        if orig and flat:
            bet_for = join_unique([row["phrase"] for row in orig])
            bet_against = join_unique([row["phrase"] for row in flat]) + " (flatten/lock closed)"
        elif len(phrases) >= 2:
            bet_for, bet_against = phrases[0], join_unique(phrases[1:]) + " (flatten/lock closed)"
        else:
            bet_for = join_unique(phrases)
            bet_against = "flatten opposite on same ticker (closed)"
        return {
            "players": players,
            "bet_for": bet_for,
            "bet_against": bet_against,
            "venue": venues,
            "qty": qtys,
            "prices": prices,
            "times": times,
            "named": named,
            "legs": formatted,
        }
    if cluster.get("b_t0_both") or (cluster.get("is_b") and cluster.get("complementary") and len(formatted) >= 2):
        return {
            "players": players,
            "bet_for": phrases[0],
            "bet_against": join_unique(phrases[1:]) + " (Strategy B dual-Yes pair, not a lock hedge)",
            "venue": venues,
            "qty": qtys,
            "prices": prices,
            "times": times,
            "named": named,
            "legs": formatted,
        }
    if cluster.get("complementary") and len(phrases) >= 2:
        return {
            "players": players,
            "bet_for": phrases[0],
            "bet_against": join_unique(phrases[1:]) + " (lock hedge)",
            "venue": venues,
            "qty": qtys,
            "prices": prices,
            "times": times,
            "named": named,
            "legs": formatted,
        }
    if len(phrases) == 1:
        return {
            "players": players,
            "bet_for": phrases[0],
            "bet_against": "unpaired leftover (no hedge filled)",
            "venue": venues,
            "qty": qtys,
            "prices": prices,
            "times": times,
            "named": named,
            "legs": formatted,
        }
    return {
        "players": players,
        "bet_for": join_unique(phrases),
        "bet_against": UNKNOWN_ASK,
        "venue": venues,
        "qty": qtys,
        "prices": prices,
        "times": times,
        "named": named,
        "legs": formatted,
    }


def cluster_blob(cluster: dict) -> str:
    bits = [str(cluster.get("game") or ""), str(cluster.get("key") or "")]
    for leg in list(cluster.get("fill_legs") or []) + list(cluster.get("legs") or []):
        bits.extend(
            [
                str(leg.get("instrument") or ""),
                str(leg.get("player") or ""),
                str(leg.get("venue") or ""),
            ]
        )
    return game_norm(" ".join(bits))


def blob_has(blob: str, *needles: str) -> bool:
    hay = game_norm(blob)
    return any(game_norm(n) in hay for n in needles if n)


def gemini_paste_for(cluster: dict) -> dict | None:
    insts = [
        str(leg.get("instrument") or "").upper()
        for leg in (cluster.get("fill_legs") or cluster.get("legs") or [])
        if str(leg.get("venue") or "").lower() == "gemini"
    ]
    for row in GEMINI_PASTE:
        target = str(row["instrument"]).upper()
        if any(target in inst or inst in target for inst in insts if inst):
            return row
    return None


def attach_orphan_gemini(clusters: list[dict], io_list: list[dict]) -> None:
    """order_io Gemini qty>=1 on Paul's three instruments, even if orders.jsonl has no claim cluster."""
    seen: set[str] = set()
    for cluster in clusters:
        for leg in list(cluster.get("fill_legs") or []) + list(cluster.get("legs") or []):
            inst = str(leg.get("instrument") or "").upper()
            if inst:
                seen.add(inst)
    for row in GEMINI_PASTE:
        target = str(row["instrument"]).upper()
        if any(target in inst or inst in target for inst in seen):
            continue
        fills = []
        for item in io_list:
            if str(item.get("kind") or "") not in {"order", ""}:
                continue
            if str(item.get("venue") or "").lower() != "gemini":
                continue
            inst = str(_io_instrument(item) or "").upper()
            if target not in inst and inst not in target:
                continue
            payload = item.get("response")
            qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
            if not qty_is_fill(qty):
                continue
            fills.append(item)
        if not fills:
            continue
        first = fills[0]
        sport = "college football" if "NCAAF" in target else "pro hockey" if "NHL" in target else "pro baseball"
        clusters.append({
            "game": row["game"],
            "sport": sport,
            "market": "moneyline" if "M-" in target else "total",
            "side": row["buy"],
            "number": "",
            "is_b": False,
            "posted": True,
            "legs": [{
                "venue": "gemini",
                "instrument": row["instrument"],
                "side": "yes",
                "player": "",
                "cash": row["buy_price"],
                "fee": Decimal("0"),
                "qty": Decimal("1"),
                "http": first.get("http_status") or first.get("status"),
                "http_line": f"gemini HTTP {first.get('http_status') or first.get('status')} fill 1",
            }],
            "fill_legs": [{
                "venue": "gemini",
                "instrument": row["instrument"],
                "side": "yes",
                "player": row["buy"],
                "cash": row["buy_price"],
                "fee": Decimal("0"),
                "qty": Decimal("1"),
            }],
            "n_fill_legs": 1,
            "n_fill_qty": 1,
            "complementary": False,
            "intent": INTENT_INCOMPLETE_LOCK,
            "result": "one-leg leftover",
            "start": parse_dt(first.get("timestamp")),
            "n_attempts": len(fills),
            "notes": [
                "orphan order_io Gemini fill qty>=1; no matching orders.jsonl claim cluster. "
                "Matched to Paul Gemini paste."
            ],
            "key": row["instrument"],
        })


def hold_class_of(cluster: dict) -> str:
    if cluster.get("void"):
        return HOLD_VOID
    if cluster.get("price_mismatch"):
        return HOLD_PRICE
    if cluster.get("postponed") and not cluster.get("venue_paid"):
        return HOLD_POSTPONED
    if cluster.get("paul_settled") or cluster.get("gemini_settled") or cluster.get("venue_paid"):
        return HOLD_SETTLED
    if cluster.get("venue_live"):
        return HOLD_OPEN
    if cluster.get("flatten_filled"):
        return HOLD_FLATTEN
    if not cluster.get("n_fill_legs"):
        return HOLD_NEVER
    if cluster.get("settled_legs") or cluster.get("market_final"):
        return HOLD_SETTLED
    if cluster.get("status_unknown"):
        return HOLD_UNKNOWN
    return HOLD_UNKNOWN


def apply_paul_history(clusters: list[dict], io_list: list[dict]) -> None:
    """Overlay venue/Paul history. Does not invent P&L for unnamed games."""
    funk_io = io_walk_rows(io_list, ("aarfun", "serpet", "funk", "petrov"))
    for cluster in clusters:
        blob = cluster_blob(cluster)
        notes = list(cluster.get("notes") or [])
        gem = gemini_paste_for(cluster)
        if blob_has(blob, "ribecai", "houkes", "ribhou", "micrib"):
            held = any(
                qty_is_fill(leg.get("qty")) and "ribhou" in str(leg.get("instrument") or "").lower()
                for leg in (cluster.get("fill_legs") or cluster.get("legs") or [])
            )
            if not held:
                notes.append(
                    "Same match as the one No Ribecai contract. This cluster did not hold it "
                    "(IOC miss / no qty>=1). Realized is only on the fill cluster, once."
                )
                cluster["notes"] = notes
                cluster["hold_class"] = hold_class_of(cluster)
                continue
            cluster["paul_settled"] = True
            cluster["void"] = False
            cluster["venue_live"] = False
            cluster["status_unknown"] = False
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
            cluster["realized"] = Decimal("-0.55")
            cluster["settled_legs"] = 1
            cluster["wins"] = 0
            cluster["losses"] = 1
            cluster["leftover_flag"] = LEFTOVER_NO
            cluster["price_mismatch"] = True
            cluster["result"] = "venue settled: 1 No Ribecai at 0.55, $1 payout, lost"
            notes.append(
                "Paul/Kalshi history: 1 contract, No Ribecai vs Houkes at 0.55, $1 payout, lost "
                "(realized -$0.55). Tape 0.47 Yes-wire / 0.53 cash is a logging difference, not a "
                "second contract. Fresh Kalshi GET has 0 RIBHOU rows."
            )
        elif blob_has(blob, "aaron funk", "sergey petrov", "aarfun", "serpet") and not cluster.get("n_fill_legs") and not any(
            "aarfun" in str(leg.get("instrument") or "").lower() or "serpet" in str(leg.get("instrument") or "").lower()
            for leg in (cluster.get("fill_legs") or cluster.get("legs") or [])
        ):
            cluster["notes"] = notes
            cluster["hold_class"] = hold_class_of(cluster)
            continue
        elif blob_has(blob, "danilova", "sibai", "olgdanyuhliu", "avabecjizsib"):
            cluster["void"] = True
            cluster["paul_settled"] = False
            cluster["venue_live"] = False
            cluster["status_unknown"] = False
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
            cluster["realized"] = Decimal("0")
            cluster["settled_legs"] = 0
            cluster["wins"] = 0
            cluster["losses"] = 0
            cluster["leftover_flag"] = LEFTOVER_NO
            cluster["result"] = "void (not a venue holding)"
            notes.append(
                "Paul: no Polymarket record. Tape qty>=1 fills marked void / not a venue holding. "
                "No invented P&L."
            )
        elif blob_has(blob, "aaron funk", "sergey petrov", "aarfun", "serpet"):
            cluster["paul_settled"] = True
            cluster["venue_live"] = False
            cluster["status_unknown"] = False
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
            cluster["realized"] = Decimal("0.01")
            cluster["settled_legs"] = 1
            cluster["wins"] = 1
            cluster["losses"] = 0
            cluster["leftover_flag"] = LEFTOVER_NO
            cluster["result"] = "venue/Paul history: settled for +$0.01 win"
            named = (
                "Paul tickets: petrov 0.54 to win 0.92; funk 0.42 to win $1; petrov 0.02 to win "
                "0.03; petrov 0.04 to win 0.06. order_io: Yes Funk qty 1 cash 0.40 fee 0.02 "
                "(= $0.42, matches funk 0.42 to win $1); Petrov BUY_SHORT qty 0.92 cash 0.57 "
                "(~ $0.52–0.54 paid, matches 0.54 to win 0.92); Petrov BUY_SHORT qty 0.09 cash "
                "0.61 (0.03×0.61≈0.02 and 0.06×0.61≈0.04 — the two small tickets as one 0.09 fill). "
                "No extra house fill. No missing house fill. Realized +$0.01 per Paul, not recomputed."
            )
            notes.append(named)
            cluster["funk_io_n"] = len(funk_io)
        elif gem is not None:
            gemini_legs = [
                leg for leg in (cluster.get("fill_legs") or [])
                if str(leg.get("venue") or "").lower() == "gemini"
                and (
                    str(gem["instrument"]).upper() in str(leg.get("instrument") or "").upper()
                    or str(leg.get("instrument") or "").upper() in str(gem["instrument"]).upper()
                )
            ]
            kalshi_legs = [
                leg for leg in (cluster.get("fill_legs") or [])
                if str(leg.get("venue") or "").lower() == "kalshi"
            ]
            cluster["gemini_settled"] = True
            cluster["venue_live"] = False
            cluster["status_unknown"] = False
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
            cluster["realized"] = gem["pnl"]
            cluster["settled_legs"] = 1
            cluster["wins"] = 1
            cluster["losses"] = 0
            cluster["leftover_flag"] = LEFTOVER_NO
            cluster["result"] = f"Gemini paste settled: {gem['arithmetic']}"
            notes.append(
                f"Paul Gemini book: {gem['instrument']} qty {gem['qty']} {gem['buy']} at "
                f"{gem['buy_price']}; resolved {gem['resolved']} ${gem['payout']}. "
                f"{gem['arithmetic']}. order_io has a matching Gemini fill qty>=1 on that "
                "instrument. Gemini $1 is counted once. Kalshi No on a different line/time is "
                "not folded into this $1."
            )
            if kalshi_legs:
                notes.append(
                    "This cluster also has a Kalshi fill on a related ticker. That Kalshi fill is "
                    "kept on the ledger; its P&L is not taken from the Gemini $1. If it is not a "
                    "closed Yes+No flatten, Kalshi P&L stays unknown — ask."
                )
                if not cluster.get("flatten_filled"):
                    cluster["kalshi_related_unknown"] = True
            _ = gemini_legs
        elif blob_has(blob, "urso", "poborilova", "ursaur", "pobane"):
            notes.append(
                "Paul: 0.08 and 0.12 are dollars paid on the 0.10 and 0.15 Yes Urso tickets "
                "(0.10×0.78≈0.08, 0.15×0.79≈0.12). Yes Poborilova qty 1 is the house fill. "
                "Fresh Poly GET still lists this slug (still open). P&L unknown until it settles."
            )
        elif blob_has(blob, "wolff", "webb", "vivwol", "steweb"):
            cluster["venue_live"] = False
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
            cluster["status_unknown"] = True
            cluster["skip_ticker_pnl"] = True
            cluster["realized"] = Decimal("0")
            cluster["leftover_flag"] = LEFTOVER_NO
            notes.append(
                "Paul: not still on the apps. Poly GET has 0 rows. Tape had qty>=1 fills. "
                "Removed from still-open. Settlement P&L unknown — ask."
            )
        elif blob_has(blob, "machac", "khachanov", "mackha"):
            cluster["venue_live"] = False
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
            cluster["status_unknown"] = True
            cluster["skip_ticker_pnl"] = True
            cluster["realized"] = Decimal("0")
            cluster["wins"] = 0
            cluster["losses"] = 0
            notes.append(
                "Paul: not still on the apps. Kalshi GET has 0 MACKHA rows. Removed from still-open. "
                "Several Kalshi fills on MAC and KHA (not a clean one-ticker flatten). "
                "P&L unknown — ask, do not invent from the fill stack."
            )
        cluster["notes"] = notes
        cluster["hold_class"] = hold_class_of(cluster)


def restrict_realized(clusters: list[dict], settlements: list[dict]) -> None:
    """Realized $ only from venue settlement, Paul history, or a closed Yes+No flatten."""
    for cluster in clusters:
        if cluster.get("void"):
            cluster["realized"] = Decimal("0")
            cluster["hold_class"] = HOLD_VOID
            continue
        if cluster.get("paul_settled") or cluster.get("gemini_settled") or cluster.get("flatten_filled"):
            cluster["hold_class"] = hold_class_of(cluster)
            continue
        if cluster.get("postponed") and not cluster.get("venue_paid"):
            cluster["realized"] = Decimal("0")
            cluster["hold_class"] = HOLD_POSTPONED
            continue
        if cluster.get("venue_live"):
            cluster["realized"] = Decimal("0")
            cluster["hold_class"] = HOLD_OPEN
            continue
        fill_legs = cluster.get("fill_legs") or []
        if not fill_legs:
            cluster["realized"] = Decimal("0")
            cluster["hold_class"] = HOLD_NEVER
            continue
        tickers = {str(leg.get("instrument") or "").lower() for leg in fill_legs if str(leg.get("instrument") or "").strip()}
        sides = {str(leg.get("side") or "").lower() for leg in fill_legs}
        same_ticker_lock = (
            len(tickers) == 1 and "yes" in sides and "no" in sides and len(fill_legs) >= 2
        )
        # B T0 on Polymarket is Yes + No on one slug (both players' Yes). That
        # lock's dollars are knowable, but the game is not settled until the
        # market is final. Do not stamp "settled" while it is still live.
        b_t0_open = bool(cluster.get("b_t0_both")) and not cluster.get("market_final") and not cluster.get("flatten_filled")
        if same_ticker_lock and not b_t0_open:
            pnl = lock_realized(fill_legs)
            cluster["realized"] = pnl
            cluster["status_unknown"] = False
            cluster["wins"] = 1 if pnl >= 0 else 0
            cluster["losses"] = 0 if pnl >= 0 else 1
            cluster["settled_legs"] = len(fill_legs)
            cluster["venue_paid"] = True
            cluster["market_final"] = True
            cluster["hold_class"] = HOLD_SETTLED
            cluster["notes"] = list(cluster.get("notes") or []) + [
                "realized from closed Yes+No on the same ticker (lock, no winner needed)"
            ]
            continue
        if same_ticker_lock and b_t0_open:
            cluster["realized"] = Decimal("0")
            cluster["status_unknown"] = False
            cluster["venue_paid"] = False
            cluster["market_final"] = False
            cluster["settled_legs"] = 0
            cluster["hold_class"] = HOLD_OPEN
            cluster["notes"] = list(cluster.get("notes") or []) + [
                "B T0 Yes+No on one Polymarket slug is still live — not settled"
            ]
            continue
        known = True
        pnl = Decimal("0")
        wins = 0
        losses = 0
        winner = str(cluster.get("winner") or "")
        for leg in fill_legs:
            result = ticker_result(settlements, str(leg.get("instrument") or ""))
            if result in {"void", "n/a"}:
                continue
            status, leg_pnl = ticket_settled_pnl(leg, settlements, winner)
            if status == "void":
                continue
            if status not in {"win", "lose"} or leg_pnl is None:
                known = False
                break
            pnl += leg_pnl
            if status == "win":
                wins += 1
            elif status == "lose":
                losses += 1
        if known:
            cluster["realized"] = pnl
            cluster["status_unknown"] = False
            cluster["wins"] = wins
            cluster["losses"] = losses
            cluster["settled_legs"] = len(fill_legs)
            cluster["venue_paid"] = True
            cluster["market_final"] = True
            cluster["hold_class"] = HOLD_SETTLED
            cluster["notes"] = list(cluster.get("notes") or []) + [
                "realized from venue ticker settlement (not a name-guess)"
            ]
        elif cluster.get("market_final") or cluster.get("venue_paid"):
            if not cluster.get("venue_paid"):
                cluster["realized"] = Decimal("0")
                cluster["status_unknown"] = True
            cluster["hold_class"] = HOLD_SETTLED
        else:
            cluster["realized"] = Decimal("0")
            cluster["status_unknown"] = True
            cluster["wins"] = 0
            cluster["losses"] = 0
            cluster["hold_class"] = HOLD_UNKNOWN


def _stamp_flatten_tickets(cluster: dict) -> bool:
    """Venue flatten round-trip: net P&L on the close, $0 on the origin. Not two directional settles."""
    filled = []
    seen: set[int] = set()
    for bucket in ("fill_legs", "legs"):
        for leg in cluster.get(bucket) or []:
            if not isinstance(leg, dict) or id(leg) in seen:
                continue
            if not qty_is_fill(leg.get("qty")) or is_empty_http_fill(leg.get("http"), leg.get("qty")):
                continue
            seen.add(id(leg))
            filled.append(leg)
    if len(filled) < 2:
        return False
    try:
        import settled_pnl_store
    except Exception:
        settled_pnl_store = None
    net = None
    close = None
    for leg in filled:
        if settled_pnl_store is not None:
            row = settled_pnl_store.row_for(leg) or {}
            if row.get("flatten_pair") and row.get("flatten_net") not in (None, ""):
                net = ddec(row.get("flatten_net"))
            if row.get("flatten_close"):
                close = leg
        if str(leg.get("step") or "").lower() in {"flatten", "extra-flatten"}:
            close = close or leg
    if net is None and cluster.get("flatten_filled"):
        net = ddec(cluster.get("realized"))
        if net is None:
            net = lock_realized(filled)
    if net is None:
        return False
    if close is None:
        close = filled[-1]
    for leg in filled:
        is_close = leg is close or str(leg.get("order_id") or "") == str(close.get("order_id") or "")
        pnl = net if is_close else Decimal("0")
        if settled_pnl_store is not None:
            status, stored = settled_pnl_store.apply_to_leg(leg)
            if status == "flatten" and stored is not None:
                pnl = stored
        leg["ticket_status"] = "flatten"
        leg["ticket_pnl"] = str(pnl)
        leg["settle_result"] = "flatten"
    cluster["realized"] = net
    cluster["flatten_filled"] = True
    return True


def stamp_ticket_pnl(clusters: list[dict], settlements: list[dict]) -> None:
    """One venue fill → one win or one loss. Flatten round-trip books venue net, not two directional settles."""
    for cluster in clusters or []:
        winner = str(cluster.get("winner") or "")
        voided = bool(cluster.get("void"))
        postponed = bool(cluster.get("postponed") and not cluster.get("venue_paid"))
        if not voided and not postponed and _stamp_flatten_tickets(cluster):
            continue
        seen: set[int] = set()
        for bucket in ("fill_legs", "legs"):
            for leg in cluster.get(bucket) or []:
                if not isinstance(leg, dict):
                    continue
                marker = id(leg)
                if marker in seen:
                    continue
                seen.add(marker)
                if not qty_is_fill(leg.get("qty")):
                    continue
                if is_empty_http_fill(leg.get("http"), leg.get("qty")):
                    continue
                if voided:
                    leg["ticket_status"] = "void"
                    leg["ticket_pnl"] = "0"
                    leg["settle_result"] = "void"
                    continue
                if postponed:
                    continue
                status, pnl = ticket_settled_pnl(leg, settlements, winner)
                if status in {"win", "lose", "void", "flatten"}:
                    leg["ticket_status"] = status
                    if pnl is not None:
                        leg["ticket_pnl"] = str(pnl)


def persist_settled_pnl(clusters: list[dict], settlements: list[dict], *, source: str = "tape_rebuild") -> None:
    """Write priced fills to local/settled_pnl.json. Postponed is not stored as settled."""
    try:
        import settled_pnl_store
    except Exception:
        return
    blob = settled_pnl_store.load()
    for cluster in clusters or []:
        if cluster.get("postponed") and not cluster.get("venue_paid") and not cluster.get("void"):
            continue
        game = str(cluster.get("game") or "")
        if cluster.get("flatten_filled"):
            pair = []
            seen_flat: set[int] = set()
            for bucket in ("fill_legs", "legs"):
                for leg in cluster.get(bucket) or []:
                    if not isinstance(leg, dict) or id(leg) in seen_flat:
                        continue
                    seen_flat.add(id(leg))
                    if not qty_is_fill(leg.get("qty")):
                        continue
                    pair.append(leg)
            if len(pair) >= 2:
                already = False
                for leg in pair:
                    row = blob.get(str(leg.get("order_id") or ""))
                    if isinstance(row, dict) and row.get("flatten_pair"):
                        already = True
                        break
                if not already:
                    settled_pnl_store.upsert_flatten_pair(
                        pair,
                        source=source,
                        store=blob,
                        game=game,
                    )
                continue
        seen: set[int] = set()
        for bucket in ("fill_legs", "legs"):
            for leg in cluster.get(bucket) or []:
                if not isinstance(leg, dict) or id(leg) in seen:
                    continue
                seen.add(id(leg))
                if not qty_is_fill(leg.get("qty")):
                    continue
                result = str(leg.get("settle_result") or ticker_result(settlements, str(leg.get("instrument") or "")) or "")
                if not leg.get("settlementPx"):
                    for row in settlements or []:
                        if str(row.get("ticker") or "").strip().lower() == str(leg.get("instrument") or "").strip().lower():
                            if row.get("settlementPx") not in (None, ""):
                                leg["settlementPx"] = row.get("settlementPx")
                            break
                if result not in FINAL_RESULTS:
                    status = str(leg.get("ticket_status") or "")
                    side = str(leg.get("side") or "").lower()
                    poly = str(leg.get("venue") or "").lower() in {"polymarket", "poly"}
                    px_ok = _poly_px_result(leg) in FINAL_RESULTS
                    if status == "void":
                        result = "void"
                    elif poly and not px_ok:
                        result = ""
                    elif status == "win" and side in {"yes", "no"}:
                        result = side
                    elif status == "lose" and side in {"yes", "no"}:
                        result = "no" if side == "yes" else "yes"
                if result not in FINAL_RESULTS:
                    continue
                settled_pnl_store.upsert_leg(
                    leg,
                    result=result,
                    source=source,
                    store=blob,
                    game=game,
                )
                inst = str(leg.get("instrument") or "")
                venue = str(leg.get("venue") or "").lower()
                px = leg.get("settlementPx")
                market_result = ticker_result(settlements, inst) or result
                if inst and venue and (px not in (None, "") or market_result in FINAL_RESULTS):
                    tkey = f"ticker|{venue}|{inst.lower()}"
                    prev = blob.get(tkey) if isinstance(blob.get(tkey), dict) else {}
                    blob[tkey] = {
                        **prev,
                        "order_id": tkey,
                        "venue": venue,
                        "instrument": inst,
                        "result": market_result,
                        "settlementPx": px if px not in (None, "") else prev.get("settlementPx"),
                        "status": "void" if market_result in {"void", "n/a"} else "settled",
                        "game": game or prev.get("game") or "",
                        "source": source,
                    }
    settled_pnl_store.save(blob)
    print(f"settled_pnl.json n={len(blob)} {SETTLED_PNL}", flush=True)


def match_bucket(cluster: dict) -> str:
    hold = cluster.get("hold_class") or hold_class_of(cluster)
    if hold == HOLD_VOID:
        return "void"
    if hold in {HOLD_OPEN, HOLD_SETTLED, HOLD_FLATTEN, HOLD_PRICE, HOLD_POSTPONED}:
        return "matched"
    if hold == HOLD_NEVER:
        return "never held"
    return "mismatched"


def is_false_sent_no_http(*, n_order_io: int, opportunities_said_sent: bool) -> bool:
    return bool(opportunities_said_sent) and int(n_order_io or 0) == 0


def is_shsu95_false_log(game: str, number: str, when: str) -> bool:
    blob = f"{game} {number} {when}".lower()
    if "sam houston" not in blob and "shsu" not in blob:
        return False
    if "9.5" not in str(number) and "9.5" not in blob:
        return False
    return any(stamp in str(when) for stamp in FALSE_SHSU_TIMES)


def result_label(
    *,
    posted: bool,
    n_fill_legs: int,
    flattened: bool,
    complementary: bool,
    flatten_filled: bool = False,
) -> str:
    if not posted:
        return "never posted (claim+skip)"
    if flattened and n_fill_legs >= 1:
        return "flatten filled" if flatten_filled else "flatten miss"
    if n_fill_legs >= 2 and complementary:
        return "both filled lock"
    if n_fill_legs == 1:
        return "one-leg leftover"
    if n_fill_legs >= 2:
        return "both filled (same-side / not a lock)"
    return "both unfilled"


def parse_dt(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def fmt_et(value) -> str:
    stamp = parse_dt(value) if not isinstance(value, datetime) else value
    if stamp is None:
        return ""
    return stamp.strftime("%Y-%m-%d %H:%M:%S ET")


def ddec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").split()[0])
    except Exception:
        return None


def last_name(text: str) -> str:
    toks = [t for t in game_norm(text).split() if t]
    return toks[-1] if toks else game_norm(text)


def same_player(a: str, b: str) -> bool:
    x, y = last_name(a), last_name(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if len(x) >= 3 and (y.startswith(x) or x.startswith(y)):
        return True
    if len(y) >= 3 and (x.startswith(y) or y.startswith(x)):
        return True
    return False


def parse_key(bet_key: str) -> dict:
    parts = str(bet_key or "").split("\t")
    while len(parts) < 8:
        parts.append("")
    return {
        "sport": parts[0],
        "game_code": parts[1],
        "date": parts[2],
        "market_type": parts[3],
        "side_key": parts[4],
        "number": parts[5],
        "venue_a": parts[6],
        "venue_b": parts[7],
    }


def sport_of(row: dict, key: str = "") -> str:
    sport = str(row.get("sport") or "")
    if sport:
        return sport
    info = parse_key(key or str(row.get("bet_key") or ""))
    sport = str(info.get("sport") or "")
    if sport.startswith("tennis"):
        return "tennis"
    return sport or "unknown"


def league_from_instrument(instrument: str) -> str:
    """League from a catalog ticker / slug prefix. Empty if the prefix is unknown."""
    text = str(instrument or "").strip().upper()
    if not text:
        return ""
    for token, league in LEAGUE_FROM_TOKEN:
        if token in text:
            return league
    return ""


def league_of(cluster: dict) -> str:
    """ATP / WTA / Challenger / ITF / CFB / NFL from catalog tickers or watch. Do not invent."""
    if str(cluster.get("league") or "").strip():
        named = str(cluster.get("league")).strip()
        if named.lower() not in {"unknown", "unknown — ask paul", UNKNOWN_ASK}:
            return named
    watch = cluster.get("watch") or {}
    for key in ("league", "series", "tour"):
        raw = str(watch.get(key) or "").strip()
        if raw:
            mapped = league_from_instrument(raw) or (
                raw if raw.upper() in {row[1].upper() for row in LEAGUE_FROM_TOKEN} else ""
            )
            if mapped:
                return mapped
            if raw.upper() in {"ATP", "WTA", "ITF", "NFL", "NHL", "MLB", "NBA", "CFB", "NCAAF"}:
                return "CFB" if raw.upper() in {"CFB", "NCAAF"} else raw.upper()
            if "CHALLENGER" in raw.upper() and "WTA" in raw.upper():
                return "WTA Challenger"
            if "CHALLENGER" in raw.upper():
                return "ATP Challenger"
    for leg in list(cluster.get("fill_legs") or []) + list(cluster.get("legs") or []):
        found = league_from_instrument(str(leg.get("instrument") or ""))
        if found:
            return found
    blob = " ".join(
        [
            str(cluster.get("key") or ""),
            str((cluster.get("claim") or {}).get("bet_key") or ""),
            str(cluster.get("game") or ""),
        ]
    )
    found = league_from_instrument(blob)
    if found:
        return found
    sport = str(cluster.get("sport") or "").lower()
    if sport in {"college football", "ncaaf", "cfb"}:
        return "CFB"
    if sport in {"pro football", "nfl"}:
        return "NFL"
    if sport in {"pro hockey", "nhl"}:
        return "NHL"
    if sport in {"pro baseball", "mlb"}:
        return "MLB"
    return "unknown"


def leg_fill_qty(io_row: dict | None) -> Decimal:
    if not io_row:
        return Decimal("0")
    payload = io_row.get("response")
    return live_lock_orders.filled_contracts(payload)


def public_http_line(sent: dict, io_row: dict | None) -> str:
    venue = str(sent.get("venue") or (io_row or {}).get("venue") or "venue")
    status = sent.get("http_status")
    if status in (None, "") and io_row:
        status = io_row.get("http_status") or io_row.get("status")
    payload = (io_row or {}).get("response")
    qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
    note = live_lock_orders.public_venue_note(payload, str(sent.get("note") or ""))
    flatten = str(sent.get("step") or "") in {"flatten", "extra-flatten"}
    head = f"{'flatten ' if flatten else ''}{venue} HTTP {status} fill {qty}"
    line = f"{head} {note}".strip() if note else head
    return live_lock_orders._scrub_public_text(line)


def fill_cash_fee(sent: dict, io_row: dict | None) -> tuple[Decimal | None, Decimal, Decimal]:
    payload = (io_row or {}).get("response") if io_row else None
    qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
    if not qty_is_fill(qty):
        return None, Decimal("0"), qty
    req = (io_row or {}).get("request") if isinstance((io_row or {}).get("request"), dict) else {}
    quote = sent.get("quote_price") or (io_row or {}).get("quote_price") if io_row else sent.get("quote_price")
    if isinstance((io_row or {}).get("quote"), dict) and not quote:
        quote = (io_row or {}).get("quote", {}).get("quote_price")
    spec = {
        "venue": str(sent.get("venue") or ""),
        "outcome": str(sent.get("side") or ""),
        "pay": quote or sent.get("house_cash") or sent.get("limit_price"),
        "quote_price": quote,
        "intent": "",
        "fee_coefficient": sent.get("fee_coefficient"),
        "limit": sent.get("limit_price"),
        "limit_price": sent.get("limit_price"),
        "body": req,
    }
    if req:
        spec["intent"] = str(req.get("intent") or "")
        if not spec["fee_coefficient"]:
            spec["fee_coefficient"] = req.get("feeRateBps") or req.get("fee_coefficient")
    cash = live_lock_orders._actual_fill_cash(spec, payload)
    if cash is None:
        cash = ddec(sent.get("house_cash") or sent.get("limit_price"))
    poly = {}
    if str(sent.get("venue") or "") == "polymarket" and payload is not None:
        poly = polymarket_fill(
            payload,
            quote=quote,
            pay=quote or sent.get("house_cash"),
            api_limit=sent.get("limit_price") or (req.get("price") if req else None),
        )
        poly_cash = ddec(poly.get("cash"))
        if poly_cash is not None:
            cash = poly_cash
    if sent.get("after_fee") not in (None, "") and ddec(sent.get("wire")) is not None:
        stored = ddec(sent.get("house_cash") or sent.get("wire"))
        if poly.get("cash"):
            cash = ddec(poly.get("cash")) or stored or cash
        else:
            cash = stored or cash
        fee = ddec(sent.get("fee"))
        if fee is None and cash is not None:
            after = ddec(sent.get("after_fee"))
            fee = after - cash if after is not None else None
        poly_fee = ddec(poly.get("fee"))
        if poly_fee is not None:
            fee = poly_fee
        return cash, fee, qty
    fee = live_lock_orders.leg_fee(spec, cash or Decimal("0"), payload)
    poly_fee = ddec(poly.get("fee"))
    if poly_fee is not None:
        fee = poly_fee
    if cash is None and poly.get("cash"):
        cash = ddec(poly.get("cash"))
    return cash, fee, qty


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def io_indexes(io_list: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    by_id: dict[str, dict] = {}
    orders = []
    for row in io_list:
        if str(row.get("kind") or "") != "order":
            continue
        orders.append(row)
        oid = _order_id_of(row.get("response"))
        if oid:
            by_id[oid] = row
    return by_id, orders


def match_io(sent: dict, context: dict, by_id: dict[str, dict], io_list: list[dict], used: set[str]) -> dict | None:
    oid = str(sent.get("order_id") or "")
    if oid and oid in by_id:
        used.add(oid)
        return by_id[oid]
    venue = str(sent.get("venue") or "")
    instrument = str(sent.get("instrument") or "")
    when = parse_dt(sent.get("sent_at") or context.get("compared_at") or "")
    best = None
    best_delta = None
    for row in io_list:
        if str(row.get("venue") or "") != venue:
            continue
        if _io_instrument(row) != instrument:
            continue
        found_id = _order_id_of(row.get("response"))
        if found_id and found_id in used:
            continue
        other = parse_dt(row.get("timestamp") or "")
        if when is None or other is None:
            continue
        delta = abs((when - other).total_seconds())
        if delta > 30:
            continue
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best = row
    if best:
        found_id = _order_id_of(best.get("response"))
        if found_id:
            used.add(found_id)
        return best
    return None


def tennis_pay_key(side: str, player: str, instrument: str) -> str:
    book = str(side or "").lower()
    name = last_name(player)
    inst = str(instrument or "").lower()
    if not name and inst.startswith("aec-"):
        return f"{book}:{inst}"
    if book == "yes":
        return f"win:{name}"
    if book == "no":
        return f"lose:{name}"
    return f"{book}:{name}"


def opposite_pay(a: str, b: str) -> bool:
    if not a or not b or a == b:
        return False
    if a.startswith("win:") and b.startswith("lose:"):
        return same_player(a[4:], b[5:])
    if a.startswith("lose:") and b.startswith("win:"):
        return same_player(a[5:], b[4:])
    if a.startswith("win:") and b.startswith("win:"):
        return bool(a[4:] and b[4:]) and not same_player(a[4:], b[4:])
    if a.startswith("lose:") and b.startswith("lose:"):
        return bool(a[5:] and b[5:]) and not same_player(a[5:], b[5:])
    if a.endswith(":yes") and b.endswith(":no") and a.rsplit(":", 1)[0] == b.rsplit(":", 1)[0]:
        return True
    if a.endswith(":no") and b.endswith(":yes") and a.rsplit(":", 1)[0] == b.rsplit(":", 1)[0]:
        return True
    # Same Polymarket slug Yes + No is always a lock.
    if a[a.find(":") + 1:] == b[b.find(":") + 1:] and a.split(":")[0] != b.split(":")[0]:
        if "aec-" in a:
            return True
    return False


def complementary_legs(legs: list[dict]) -> bool:
    filled = [leg for leg in legs if qty_is_fill(leg.get("qty"))]
    if len(filled) < 2:
        return False
    keys = [
        tennis_pay_key(str(leg.get("side") or ""), str(leg.get("player") or ""), str(leg.get("instrument") or ""))
        for leg in filled
    ]
    for i, left in enumerate(keys):
        for right in keys[i + 1:]:
            if opposite_pay(left, right):
                return True
    inst = {str(leg.get("instrument") or "") for leg in filled}
    books = {str(leg.get("side") or "").lower() for leg in filled}
    if len(inst) == 1 and "yes" in books and "no" in books:
        return True
    return False


def cluster_lock_attempts(orders: list[dict]) -> list[dict]:
    clusters: list[dict] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current:
            clusters.append(current)
        current = None

    for row in orders:
        if is_strategy_b_row(row) or is_cfb_favorite_row(row) or is_spread_t0_row(row) or is_tennis_t0_dog_row(row) or is_tennis_t0_spread_row(row) or is_soccer_t0_total_row(row):
            continue
        event = str(row.get("event") or "")
        if event == "claim":
            flush()
            current = {"claim": row, "events": [], "kind": "lock"}
            continue
        if current is None:
            continue
        row_key = str(row.get("bet_key") or "")
        claim_key = str((current.get("claim") or {}).get("bet_key") or "")
        if row_key and claim_key and row_key != claim_key:
            continue
        if event in {"sent", "filled", "one_leg", "both_unfilled", "flatten_filled", "flatten_miss", "skip", "orders_off"}:
            current["events"].append(row)
    flush()
    return clusters


def b_match_id(bet_key: str) -> str:
    parts = str(bet_key or "").split("\t")
    if parts and str(parts[0]).startswith("tennis-b") and len(parts) >= 2:
        return parts[1].strip()
    if parts and str(parts[0]).startswith("tennis_"):
        return parts[0].strip()
    return str(bet_key or "").strip()


def cluster_b_attempts(orders: list[dict], watch: dict | None) -> list[dict]:
    by_key: dict[str, dict] = {}
    for row in orders:
        if not is_strategy_b_row(row):
            continue
        raw_key = str(row.get("bet_key") or "")
        key = b_match_id(raw_key)
        slot = by_key.setdefault(
            key,
            {
                "claim": {
                    "bet_key": raw_key,
                    "sport": "tennis",
                    "game": row.get("game") or "",
                    "market_type": "moneyline",
                },
                "events": [],
                "kind": "b",
            },
        )
        if row.get("game"):
            slot["claim"]["game"] = row.get("game")
        slot["events"].append(row)
        if row.get("event") == "sent" and not slot["claim"].get("compared_at"):
            slot["claim"]["compared_at"] = row.get("sent_at")
    matches = (watch or {}).get("matches") if isinstance(watch, dict) else []
    for match in matches or []:
        mid = str(match.get("key") or "")
        slot = by_key.get(mid)
        if slot is None:
            for k, item in by_key.items():
                if mid and (mid == k or mid in k or k in mid):
                    slot = item
                    break
        if slot is None:
            slot = {
                "claim": {
                    "bet_key": "tennis-b\t" + mid,
                    "sport": "tennis",
                    "game": match.get("game") or "",
                    "market_type": "moneyline",
                    "compared_at": match.get("opened_at") or match.get("t0_when"),
                },
                "events": [],
                "kind": "b",
            }
            by_key[mid or str(len(by_key))] = slot
        slot["watch"] = match
        if match.get("game"):
            slot["claim"]["game"] = match.get("game")
        t0 = match.get("t0_yes") or {}
        slot["claim"]["side"] = " / ".join(
            str((t0.get(letter) or {}).get("player") or "") for letter in ("a", "b") if (t0.get(letter) or {}).get("player")
        )
    return list(by_key.values())


def cluster_directional_attempts(orders: list[dict], watch: dict | None, *, kind: str, prefix: str) -> list[dict]:
    """One cluster per C or D game. A filled Yes is the intended trade, not leftover."""
    by_key: dict[str, dict] = {}
    check = {
        "cfb_favorite": is_cfb_favorite_row,
        "spread_t0": is_spread_t0_row,
        "tennis_t0_dog": is_tennis_t0_dog_row,
        "tennis_t0_spread": is_tennis_t0_spread_row,
        "soccer_t0_total": is_soccer_t0_total_row,
    }.get(kind) or is_spread_t0_row
    for row in orders:
        if not check(row):
            continue
        raw_key = str(row.get("bet_key") or "")
        parts = raw_key.split("\t")
        key = parts[1].strip() if len(parts) >= 2 else raw_key
        slot = by_key.setdefault(
            key,
            {
                "claim": {
                    "bet_key": raw_key,
                    "sport": row.get("sport") or ("college football" if kind == "cfb_favorite" else "tennis" if kind in {"tennis_t0_dog", "tennis_t0_spread"} else "soccer" if kind == "soccer_t0_total" else ""),
                    "game": row.get("game") or "",
                    "market_type": "moneyline" if kind in {"cfb_favorite", "tennis_t0_dog"} else "total" if kind == "soccer_t0_total" else "spread",
                    "side": row.get("side_label") or "",
                },
                "events": [],
                "kind": kind,
            },
        )
        if row.get("game"):
            slot["claim"]["game"] = row.get("game")
        slot["events"].append(row)
        if row.get("event") == "sent" and not slot["claim"].get("compared_at"):
            slot["claim"]["compared_at"] = row.get("sent_at")
    matches = (watch or {}).get("matches") if isinstance(watch, dict) else []
    for match in matches or []:
        mid = str(match.get("key") or "")
        slot = by_key.get(mid)
        if slot is None:
            for k, item in by_key.items():
                if mid and (mid == k or mid in k or k in mid):
                    slot = item
                    break
        if slot is None and mid:
            slot = {
                "claim": {
                    "bet_key": prefix + "\t" + mid,
                    "sport": match.get("sport") or "",
                    "game": match.get("game") or "",
                    "market_type": match.get("kind") or ("moneyline" if kind in {"cfb_favorite", "tennis_t0_dog"} else "spread"),
                    "side": match.get("dog") or match.get("fav") or "",
                    "compared_at": match.get("opened_at") or match.get("t0_when"),
                },
                "events": [],
                "kind": kind,
            }
            by_key[mid] = slot
        if slot is None:
            continue
        slot["watch"] = match
        if match.get("game"):
            slot["claim"]["game"] = match.get("game")
        if match.get("fav"):
            slot["claim"]["side"] = match.get("fav")
    return list(by_key.values())


def first_time(cluster: dict) -> datetime | None:
    claim = cluster.get("claim") or {}
    stamps = [
        claim.get("compared_at"),
        claim.get("opened_at"),
    ]
    for ev in cluster.get("events") or []:
        stamps.extend([ev.get("sent_at"), ev.get("at"), ev.get("compared_at"), ev.get("timestamp")])
    best = None
    for raw in stamps:
        stamp = parse_dt(raw)
        if stamp and (best is None or stamp < best):
            best = stamp
    return best


def _settle_sig(row: dict) -> tuple:
    return (
        str(row.get("ticker") or "").lower(),
        str(row.get("result") or "").lower(),
        str(row.get("status") or row.get("state") or "").lower(),
        str(row.get("source") or ""),
    )


def _settle_trust(row: dict | None) -> int:
    """live_market_get + settlementPx beats close_hook / SHORT-resolution guesses."""
    if not isinstance(row, dict):
        return 0
    source = str(row.get("source") or "")
    px = _poly_px_result(row)
    if source == "live_market_get" and px in FINAL_RESULTS:
        return 5
    if source == "live_market_get":
        return 4
    if px in FINAL_RESULTS and not source.startswith("close_hook") and "position_resolution" not in source:
        return 3
    if px in FINAL_RESULTS:
        return 2
    if "position_resolution" in source:
        return 0
    venue = str(row.get("venue") or "").lower()
    if venue in {"polymarket", "poly"}:
        return 0
    if str(row.get("result") or "").lower() in FINAL_RESULTS:
        return 1
    return 0


def merge_settlement_rows(rows: list[dict], incoming: list[dict]) -> list[dict]:
    """Keep the richest result per ticker. Venue GET settlementPx beats stored guesses."""
    by_ticker: dict[str, dict] = {}
    extras: list[dict] = []
    seen_extra: set[tuple] = set()
    for row in list(rows) + list(incoming):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            sig = _settle_sig(row)
            if sig in seen_extra:
                continue
            seen_extra.add(sig)
            extras.append(row)
            continue
        key = ticker.lower()
        prev = by_ticker.get(key)
        if prev is None:
            by_ticker[key] = dict(row)
            continue
        prev_res = str(prev.get("result") or "").lower()
        new_res = str(row.get("result") or "").lower()
        if prev_res not in FINAL_RESULTS and new_res in FINAL_RESULTS:
            merged = dict(prev)
            merged.update(row)
            by_ticker[key] = merged
        elif new_res in FINAL_RESULTS and prev_res in FINAL_RESULTS:
            take_new = _settle_trust(row) >= _settle_trust(prev)
            winner = row if take_new else prev
            other = prev if take_new else row
            merged = dict(other)
            merged.update({k: v for k, v in winner.items() if v not in (None, "")})
            px = _poly_px_result(winner) or _poly_px_result(other)
            merged["result"] = px if px in FINAL_RESULTS else str(winner.get("result") or other.get("result") or "").lower()
            if take_new:
                merged["source"] = winner.get("source") or merged.get("source")
            by_ticker[key] = merged
        else:
            for field, value in row.items():
                if value not in (None, "") and not prev.get(field):
                    prev[field] = value
    return extras + list(by_ticker.values())


def _contract_settlement(contract: dict, *, venue: str, game: str, sport: str, source: str) -> dict | None:
    if not isinstance(contract, dict):
        return None
    ticker = str(contract.get("ticker") or contract.get("instrumentSymbol") or contract.get("slug") or "")
    if not ticker:
        return None
    result = str(contract.get("result") or contract.get("resolutionSide") or "").lower()
    status = str(contract.get("status") or contract.get("state") or contract.get("marketStatus") or "").lower()
    px = contract.get("settlementPx") or contract.get("settlementPrice") or contract.get("settlement_px")
    px_result = _poly_px_result({"settlementPx": px})
    if px_result in FINAL_RESULTS:
        result = px_result
    elif result not in FINAL_RESULTS and px not in (None, ""):
        try:
            number = Decimal(str(px if not isinstance(px, dict) else px.get("value")))
            if number >= 1:
                result = "yes"
            elif number <= 0:
                result = "no"
        except Exception:
            pass
    if result not in FINAL_RESULTS and status not in KALSHI_FINAL_STATUS and status not in FINAL_STATUS:
        if not contract.get("expired") and not contract.get("void"):
            return None
    return {
        "source": source,
        "venue": venue,
        "sport": sport,
        "game": game or str(contract.get("title") or contract.get("event_title") or ""),
        "market_type": str(contract.get("market_type") or ""),
        "side": contract.get("yes_sub_title") or contract.get("label") or contract.get("title") or "",
        "result": result,
        "status": status,
        "ticker": ticker,
        "expired": bool(contract.get("expired")),
        "void": bool(contract.get("void")) or result in {"void", "n/a"},
        "settlementPx": px,
        "occurrence": contract.get("occurrence_datetime") or contract.get("resolvedAt") or "",
    }


def load_disk_venue_settlements() -> list[dict]:
    """Local venue dumps already on disk (not the Oct 20 research cache)."""
    rows: list[dict] = []
    for path in RAW.glob("*kalshi.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        game = str(payload.get("game") or payload.get("title") or "")
        sport = str(payload.get("sport") or "college football")
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            title = str(event.get("title") or event.get("sub_title") or game)
            for contract in event.get("contracts") or []:
                row = _contract_settlement(
                    contract, venue="Kalshi", game=title, sport=sport, source=path.name
                )
                if row:
                    rows.append(row)
    for path in RAW.glob("*gemini.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        game = str(payload.get("game") or payload.get("title") or "")
        sport = str(payload.get("sport") or "")
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            title = str(event.get("title") or game)
            contracts = event.get("contracts") or []
            inner = event.get("event") if isinstance(event.get("event"), dict) else {}
            if not contracts and inner:
                contracts = inner.get("contracts") or []
                title = title or str(inner.get("title") or "")
            for contract in contracts:
                row = _contract_settlement(
                    contract, venue="Gemini", game=title, sport=sport, source=path.name
                )
                if row:
                    rows.append(row)
    for extra in (SETTLE_LIVE, NFL_SETTLE):
        if not extra.is_file():
            continue
        try:
            raw = json.loads(extra.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict):
            raw = raw.get("rows") or raw.get("settlements") or []
        if isinstance(raw, list):
            rows.extend(row for row in raw if isinstance(row, dict))
    try:
        import settled_pnl_store

        rows.extend(settled_pnl_store.settlement_rows())
    except Exception:
        pass
    return rows


def load_watch_settlements() -> list[dict]:
    """C/D/E close-hook notes already have result=yes/no on the ticker. B postponed is not settled."""
    rows: list[dict] = []
    files = {
        "cfb_favorite": RAW / "cfb_favorite_watch.json",
        "spread_t0": RAW / "spread_t0_watch.json",
        "tennis_t0_dog": RAW / "tennis_t0_dog_watch.json",
        "tennis_t0_spread": RAW / "tennis_t0_spread_watch.json",
        "soccer_t0_total": RAW / "soccer_t0_total_watch.json",
        "tennis_crossover": RAW / "strategy_b_watch.json",
    }
    for kind, path in files.items():
        payload = load_json(path) or {}
        for match in payload.get("matches") or []:
            if not isinstance(match, dict):
                continue
            stage = str(match.get("stage") or "").lower()
            game = str(match.get("game") or "")
            postponed = stage == "postponed" or bool(match.get("postponed_reason"))
            note = str(match.get("note") or "")
            inst = str(match.get("instrument") or "")
            venue = str(match.get("venue") or "kalshi")
            found = re.search(r"result\s*=\s*(yes|no|void)", note, re.I)
            ticker_hit = re.search(r"(KX[A-Z0-9-]+)", note)
            ticker = ticker_hit.group(1) if ticker_hit else inst
            if postponed:
                reason = str(match.get("postponed_reason") or "").lower()
                if "closed without settlement" in reason:
                    # Not a kitchen postpone. Rebuild re-GETs the market.
                    continue
                rows.append({
                    "source": "watch_postponed",
                    "venue": venue,
                    "game": game,
                    "ticker": ticker or inst,
                    "status": "postponed",
                    "postponed": True,
                    "result": "",
                })
                continue
            if stage != "settled" and not found:
                continue
            result = found.group(1).lower() if found else ""
            rows.append({
                "source": f"watch_{kind}",
                "venue": venue,
                "sport": str(match.get("sport") or ""),
                "game": game,
                "ticker": ticker,
                "result": result,
                "status": "settled" if stage == "settled" or result in FINAL_RESULTS else stage,
            })
    return rows


def load_settlements() -> list[dict]:
    rows: list[dict] = []
    if SETTLE_CACHE.is_file():
        try:
            raw = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                rows.extend(row for row in raw if isinstance(row, dict))
        except json.JSONDecodeError:
            pass
    cfb = RAW / "cfb_game_results.jsonl"
    if cfb.is_file():
        for row in _load_jsonl(cfb):
            row.setdefault("sport", "college football")
            rows.append(row)
    rows = merge_settlement_rows(rows, load_disk_venue_settlements())
    rows = merge_settlement_rows(rows, load_watch_settlements())
    return rows


def market_still_open(row: dict | None) -> bool:
    """True when the venue book is still trading. Closed / expired / settled is not open."""
    if not isinstance(row, dict) or not row:
        return False
    if _poly_px_result(row) in FINAL_RESULTS:
        return False
    result = str(row.get("result") or "").lower()
    if result in FINAL_RESULTS:
        return False
    if row.get("expired") in (True, "true", "TRUE") or row.get("void") or row.get("closed") in (True, "true", "TRUE"):
        return False
    status = str(row.get("status") or row.get("state") or "").lower().replace("-", "_").replace(" ", "_")
    if not status:
        return False
    if "open" in status.split("_") or status in {"active", "trading"}:
        return True
    return False


def official_postponed_market(row: dict | None) -> bool:
    """Venue said delayed / postponed / suspended. Closed-without-settlement is not this."""
    if not isinstance(row, dict) or not row:
        return False
    blob = " ".join(
        str(row.get(key) or "")
        for key in ("status", "state", "period", "postponed_reason", "source")
    ).lower()
    if "closed without settlement" in blob:
        return False
    if any(token in blob for token in ("postpon", "delayed", "suspended")):
        return True
    return bool(row.get("postponed")) and market_still_open(row)


def kitchen_is_postponed(cluster: dict, market_rows: list) -> bool:
    """Postponed only if the venue is still open AND (start is in the future OR official postpone).

    Watch stage postponed / closed-without-settlement does not stick after the game is complete.
    Binary settlementPx always wins.
    """
    rows = [row for row in (market_rows or []) if isinstance(row, dict)]
    if any(_poly_px_result(row) in FINAL_RESULTS for row in rows):
        return False
    if any(str(row.get("result") or "").lower() in FINAL_RESULTS for row in rows):
        return False
    if any(settlement_is_final(row, venue=str(row.get("venue") or "")) for row in rows):
        return False
    still_open = any(market_still_open(row) for row in rows)
    if not still_open:
        return False
    if any(official_postponed_market(row) for row in rows):
        return True
    watch = cluster.get("watch") or {}
    reason = str(watch.get("postponed_reason") or "").lower()
    if "closed without settlement" in reason:
        return False
    start = cluster.get("start") or watch.get("t0_when") or watch.get("listed_start") or watch.get("occurrence")
    stamp = start if isinstance(start, datetime) else parse_dt(start)
    if stamp is None:
        return False
    now = datetime.now(ET)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp > now


def scan_postponed_but_settled(clusters: list[dict], settlements: list[dict]) -> list[dict]:
    """Kitchen postponed (watch/notes) where the venue already has a binary settle."""
    index = market_index_of(settlements)
    hits = []
    for cluster in clusters or []:
        watch = cluster.get("watch") or {}
        notes = " ".join(str(note) for note in (cluster.get("notes") or []))
        labeled = (
            str(watch.get("stage") or "") == "postponed"
            or bool(watch.get("postponed_reason"))
            or "postponed" in notes.lower()
            or bool(cluster.get("postponed"))
        )
        if not labeled:
            continue
        rows = [_leg_market_row(leg, settlements, index) for leg in (cluster.get("fill_legs") or cluster.get("legs") or [])]
        paid = any(
            _poly_px_result(row) in FINAL_RESULTS or str((row or {}).get("result") or "").lower() in FINAL_RESULTS
            for row in rows
            if row
        )
        if paid and not kitchen_is_postponed(cluster, rows):
            hits.append({
                "game": cluster.get("game"),
                "reason": watch.get("postponed_reason") or "watch postponed",
                "result": next(
                    (
                        str(row.get("result") or "")
                        for row in rows
                        if row and str(row.get("result") or "").lower() in FINAL_RESULTS
                    ),
                    "",
                ),
            })
    return hits


def settlement_is_final(row: dict | None, *, venue: str = "") -> bool:
    if not isinstance(row, dict) or not row:
        return False
    if official_postponed_market(row) and market_still_open(row) and str(row.get("result") or "").lower() not in {"void", "n/a"}:
        return False
    if row.get("postponed") and market_still_open(row) and str(row.get("result") or "").lower() not in {"void", "n/a"}:
        return False
    shop = str(venue or row.get("venue") or "").lower()
    result = str(row.get("result") or "").lower()
    if result in FINAL_RESULTS:
        return True
    status_raw = str(row.get("status") or row.get("state") or "").lower().replace("-", "_").replace(" ", "_")
    if "open" in status_raw.split("_") and result not in FINAL_RESULTS:
        return False
    if row.get("void") or row.get("expired") in (True, "true", "TRUE"):
        return True
    status = str(row.get("status") or row.get("state") or "").lower().replace("-", "_").replace(" ", "_")
    words = KALSHI_FINAL_STATUS if shop == "kalshi" else FINAL_STATUS
    return status in words


def market_index_of(settlements: list[dict]) -> dict:
    index: dict = {}
    for row in settlements:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        venue = str(row.get("venue") or "").lower()
        index[ticker.lower()] = row
        if venue:
            index[(venue, ticker.lower())] = row
    return index


def save_live_settlements(rows: list[dict]) -> None:
    skip_sources = {"kalshi_api", "gemini_api", "polymarket", SETTLE_CACHE.name, ""}
    live = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("source") or "") not in skip_sources
        and "odds_cross" not in str(row.get("source") or "")
    ]
    payload = {
        "written_at": datetime.now(ET).isoformat(timespec="seconds"),
        "n": len(live),
        "rows": live,
    }
    try:
        SETTLE_LIVE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def filled_instruments(clusters: list[dict]) -> list[tuple[str, str, str]]:
    found = []
    seen = set()
    for cluster in clusters:
        game = str(cluster.get("game") or "")
        for bucket in ("fill_legs", "legs"):
            for leg in cluster.get(bucket) or []:
                if not qty_is_fill(leg.get("qty")) and bucket != "fill_legs":
                    continue
                venue = str(leg.get("venue") or "").lower()
                inst = str(leg.get("instrument") or "").strip()
                if not venue or not inst:
                    continue
                key = (venue, inst.lower())
                if key in seen:
                    continue
                seen.add(key)
                found.append((venue, inst, game))
    return found


def _poly_px_result(info: dict) -> str:
    px = info.get("settlementPx") or info.get("settlementPrice") or info.get("settlement_px")
    if px in (None, ""):
        return ""
    if isinstance(px, dict):
        px = px.get("value")
    try:
        number = Decimal(str(px))
    except Exception:
        return ""
    if number >= 1:
        return "yes"
    if number <= 0:
        return "no"
    return ""


def fetch_one_market_settlement(venue: str, ident: str, game: str = "") -> dict | None:
    """Public market status. No secrets. Empty on failure. Does not trade."""
    venue = str(venue or "").lower()
    ident = str(ident or "").strip()
    if not ident:
        return None
    try:
        import open_count_sync
    except Exception:
        return None
    info = {}
    if venue == "kalshi":
        info = open_count_sync._fetch_kalshi_market(ident) or {}
    elif venue == "polymarket":
        info = open_count_sync._fetch_poly_market(ident) or {}
    else:
        return None
    if not info:
        return None
    try:
        import settled_pnl_store

        result = settled_pnl_store.result_from_market(info)
    except Exception:
        result = str(info.get("result") or "").lower()
    if result not in FINAL_RESULTS:
        result = _poly_px_result(info)
    if result not in FINAL_RESULTS and venue != "polymarket":
        result = str(info.get("result") or "").lower()
    row = {
        "source": "live_market_get",
        "venue": "Kalshi" if venue == "kalshi" else "Polymarket",
        "game": game,
        "ticker": ident,
        "result": result,
        "status": str(info.get("status") or info.get("state") or ""),
        "expired": bool(info.get("expired")),
        "void": bool(info.get("void")) or result in {"void", "n/a"},
        "settlementPx": info.get("settlementPx") or info.get("settlementPrice"),
        "postponed": False,
    }
    state = str(row["status"] or "").lower()
    if "postpon" in state or state in {"delayed", "suspended"}:
        row["postponed"] = True
        if result not in {"void", "n/a"}:
            row["result"] = ""
    if not settlement_is_final(row, venue=venue) and not row["postponed"]:
        return row if result or row["status"] else None
    return row


def backfill_venue_settlements(
    clusters: list[dict],
    settlements: list[dict],
    *,
    fetch: bool = True,
) -> list[dict]:
    """Fill missing ticker results from public Kalshi/Poly market GET. Does not sell."""
    index = market_index_of(settlements)
    extra: list[dict] = []
    missing = []
    for venue, ident, game in filled_instruments(clusters):
        row = index.get((venue, ident.lower())) or index.get(ident.lower())
        result = str((row or {}).get("result") or "").lower()
        if venue == "polymarket":
            # Always re-GET Poly, including rows previously labeled postponed.
            # Stored close_hook / tape_rebuild settlementPx can be a SHORT-resolution
            # guess (Pohle stored 0, venue 1.0000). Watch "closed without settlement"
            # is not a settle (Moreno/Herrera).
            missing.append((venue, ident, game))
            continue
        if row and row.get("postponed"):
            # Re-GET postponed Kalshi/Gemini too. Closed games often have a px now.
            missing.append((venue, ident, game))
            continue
        if row and result in FINAL_RESULTS:
            continue
        if venue not in {"kalshi", "polymarket"}:
            continue
        missing.append((venue, ident, game))
    if fetch and missing:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"backfill market GET n={len(missing)}", flush=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {
                pool.submit(fetch_one_market_settlement, venue, ident, game): (venue, ident)
                for venue, ident, game in missing
            }
            done = 0
            for fut in as_completed(futs):
                done += 1
                try:
                    row = fut.result()
                except Exception:
                    row = None
                if row:
                    extra.append(row)
                if done % 25 == 0:
                    print(f"  market GET {done}/{len(missing)} hits {len(extra)}", flush=True)
        n_res = sum(1 for row in extra if str(row.get("result") or "").lower() in FINAL_RESULTS)
        print(f"backfill hits {len(extra)}/{len(missing)} with result {n_res}", flush=True)
    merged = merge_settlement_rows(settlements, extra)
    still = []
    index = market_index_of(merged)
    for venue, ident, game in filled_instruments(clusters):
        row = index.get((venue, ident.lower())) or index.get(ident.lower())
        result = str((row or {}).get("result") or "").lower()
        if result in FINAL_RESULTS or (row or {}).get("postponed"):
            continue
        if venue in {"kalshi", "polymarket"}:
            still.append((venue, ident, game))
    if fetch and still:
        print(f"backfill sequential retry n={len(still)}", flush=True)
        retry = []
        for venue, ident, game in still:
            try:
                row = fetch_one_market_settlement(venue, ident, game)
            except Exception:
                row = None
            if row:
                retry.append(row)
        n_res = sum(1 for row in retry if str(row.get("result") or "").lower() in FINAL_RESULTS)
        print(f"backfill retry hits {len(retry)}/{len(still)} with result {n_res}", flush=True)
        merged = merge_settlement_rows(merged, retry)
    save_live_settlements(merged)
    return merged


def ticker_result(settlements: list[dict], ticker: str) -> str:
    ticker_l = str(ticker or "").strip().lower()
    if not ticker_l:
        return ""
    best_row = None
    best_trust = -1
    for row in settlements:
        if str(row.get("ticker") or "").strip().lower() != ticker_l:
            continue
        trust = _settle_trust(row)
        if trust > best_trust:
            best_row = row
            best_trust = trust
        elif trust == best_trust and str(row.get("source") or "") == "live_market_get":
            best_row = row
    if not best_row:
        return ""
    px = _poly_px_result(best_row)
    if px in FINAL_RESULTS:
        return px
    venue = str(best_row.get("venue") or "").lower()
    source = str(best_row.get("source") or "").lower()
    if venue in {"polymarket", "poly"} or "position_resolution" in source:
        return ""
    result = str(best_row.get("result") or "").lower()
    if result in FINAL_RESULTS:
        return result
    return ""


def game_winner(settlements: list[dict], game: str) -> str:
    g = game_norm(game)
    if not g:
        return ""
    votes: dict[str, int] = defaultdict(int)
    for row in settlements:
        rg = game_norm(str(row.get("game") or row.get("game_n") or ""))
        if not rg or (rg != g and g not in rg and rg not in g):
            continue
        if str(row.get("market_type") or "").lower() not in {"moneyline", "winner", "match", "game", ""}:
            continue
        side = last_name(str(row.get("side") or row.get("side_n") or ""))
        result = str(row.get("result") or "").lower()
        if side and result in {"yes", "win", "won"}:
            votes[side] += 1
        if side and result in {"no", "lose", "lost"}:
            votes["!" + side] += 1
    if not votes:
        return ""
    yes = [(name, n) for name, n in votes.items() if not name.startswith("!")]
    if yes:
        yes.sort(key=lambda item: -item[1])
        return yes[0][0]
    return ""


def ticket_settled_pnl(leg: dict, settlements: list[dict], winner: str) -> tuple[str, Decimal | None]:
    """Return (status, realized dollars) for one filled leg. status: win/lose/open/void/flatten."""
    ticker = str(leg.get("instrument") or "")
    venue_result = ticker_result(settlements, ticker)
    oid = str(leg.get("order_id") or "").strip()
    venue_name = str(leg.get("venue") or "").lower()
    try:
        import settled_pnl_store

        stored_row = settled_pnl_store.row_for(leg) or {}
        stored_status, stored_pnl = settled_pnl_store.apply_to_leg(leg)
        if stored_row.get("flatten_pair") or stored_status == "flatten":
            return "flatten", stored_pnl if stored_pnl is not None else Decimal("0")
    except Exception:
        pass
    if oid and venue_result not in FINAL_RESULTS:
        skip_stored = False
        if venue_name in {"polymarket", "poly"}:
            stored_px = ""
            try:
                import settled_pnl_store

                stored_row = settled_pnl_store.row_for(leg) or {}
                stored_px = _poly_px_result(stored_row) or _poly_px_result(leg)
            except Exception:
                stored_px = _poly_px_result(leg)
            if stored_px not in FINAL_RESULTS:
                skip_stored = True
        if not skip_stored:
            try:
                import settled_pnl_store

                stored_status, stored_pnl = settled_pnl_store.apply_to_leg(leg)
                if stored_status in {"win", "lose", "void", "flatten"} and (stored_pnl is not None or stored_status == "void"):
                    if stored_status != "void":
                        row = settled_pnl_store.row_for(leg) or {}
                        if row.get("result"):
                            leg["settle_result"] = row.get("result")
                    else:
                        leg["settle_result"] = "void"
                    return stored_status, stored_pnl if stored_status != "void" else Decimal("0")
            except Exception:
                pass
    qty = Decimal(str(leg.get("qty") or 0))
    cash = Decimal(str(leg.get("cash") or 0))
    venue = str(leg.get("venue") or "").lower()
    fee = ddec(leg.get("fee")) if leg.get("fee") not in (None, "") else None
    if fee is None:
        try:
            import settled_pnl_store

            fee = settled_pnl_store.documented_fee(leg)
            if fee is None:
                fee = settled_pnl_store.enrich_poly_leg_fee(leg)
        except Exception:
            fee = None
    book = str(leg.get("side") or "").lower()
    result = venue_result or ticker_result(settlements, ticker)
    if result in FINAL_RESULTS:
        leg["settle_result"] = result
    for row in settlements or []:
        if str(row.get("ticker") or "").strip().lower() != ticker.strip().lower():
            continue
        if row.get("settlementPx") not in (None, "") and not leg.get("settlementPx"):
            leg["settlementPx"] = row.get("settlementPx")
        break
    if result in {"void", "n/a"}:
        return "void", Decimal("0")
    if fee is None and venue == "novig":
        return "open", None
    if fee is None and result in {"yes", "no"}:
        return "open", None
    if fee is None:
        fee = Decimal("0")
    cost = (cash * qty) + fee
    if result in {"yes", "no"}:
        won = (book == "yes" and result == "yes") or (book == "no" and result == "no")
        pnl = (qty - cost) if won else (Decimal("0") - cost)
        return ("win" if won else "lose"), pnl
    player = last_name(str(leg.get("player") or ""))
    if winner and player:
        won = same_player(player, winner) if book == "yes" else not same_player(player, winner)
        # Polymarket short / No on a moneyline slug is the other player.
        pnl = (qty - cost) if won else (Decimal("0") - cost)
        inferred = book if won else ("no" if book == "yes" else "yes")
        if inferred in {"yes", "no"}:
            leg["settle_result"] = inferred
        return ("win" if won else "lose"), pnl
    return "open", None


def lock_realized(legs: list[dict]) -> Decimal:
    qty = min((Decimal(str(leg.get("qty") or 0)) for leg in legs if qty_is_fill(leg.get("qty"))), default=Decimal("0"))
    cost = sum((Decimal(str(leg.get("cash") or 0)) * Decimal(str(leg.get("qty") or 0))) + Decimal(str(leg.get("fee") or 0)) for leg in legs)
    if qty <= 0:
        return Decimal("0") - cost
    return qty - cost


def load_considerations() -> list[dict]:
    raw = load_json(CONSIDER)
    if isinstance(raw, dict):
        rows = raw.get("rows") or []
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    return []


KNOWN_FALSE_SENT = [
    {
        "at": "2026-10-21T22:42:05-04:00",
        "game": "New Mexico State vs Sam Houston",
        "market_type": "spread",
        "side": "Sam Houston 9.5",
        "number": "9.5",
        "decision": "sent",
        "reason": "Opportunities diary said both legs filled / one-leg. No order_io HTTP. Not a trade.",
    },
    {
        "at": "2026-10-21T22:58:48-04:00",
        "game": "New Mexico State vs Sam Houston",
        "market_type": "spread",
        "side": "Sam Houston 9.5",
        "number": "9.5",
        "decision": "sent",
        "reason": "Opportunities diary said one leg filled and flatten missed. No order_io HTTP. Not a trade.",
    },
]


def false_sent_rows(considerations: list[dict], io_list: list[dict]) -> list[dict]:
    found = list(KNOWN_FALSE_SENT)
    for row in considerations:
        decision = str(row.get("decision") or "").lower()
        reason = str(row.get("reason") or "").lower()
        said_sent = "sent" in decision or "both legs filled" in reason or "one leg filled" in reason
        if not said_sent:
            continue
        when = str(row.get("at") or "")
        game = str(row.get("game") or "")
        number = str(row.get("number") or "")
        if not is_shsu95_false_log(game, number, when):
            continue
        if any(item.get("at") == when for item in found):
            continue
        found.append(row)
    return found


def same_slug_cloned_prices(clusters: list[dict]) -> list[dict]:
    """Two T0 fills on one slug with the same cash — the Varaksina clone bug."""
    hits = []
    for cluster in clusters or []:
        fills = [leg for leg in (cluster.get("fill_legs") or []) if qty_is_fill(leg.get("qty"))]
        by_inst: dict[str, list[dict]] = {}
        for leg in fills:
            inst = str(leg.get("instrument") or "").strip().lower()
            if inst:
                by_inst.setdefault(inst, []).append(leg)
        for inst, legs in by_inst.items():
            if len(legs) < 2:
                continue
            sides = {str(leg.get("side") or "").lower() for leg in legs}
            if "yes" not in sides or "no" not in sides:
                continue
            cashes = [money4(leg.get("cash")) for leg in legs]
            # Same named player on Yes+No is a real lock. The clone bug copies
            # one fill's cash onto the other ticket (not a 50/50 coin-flip).
            same_cash = len(set(c for c in cashes if c)) == 1 and cashes[0] not in {"", "0.5000"}
            if same_cash:
                hits.append({
                    "game": cluster.get("game"),
                    "instrument": inst,
                    "cash": cashes,
                    "players": [str(leg.get("player") or "") for leg in legs],
                    "sides": [str(leg.get("side") or "") for leg in legs],
                    "order_ids": [str(leg.get("order_id") or "") for leg in legs],
                })
    return hits


def apply_overlay_live_flags(clusters: list[dict], open_rows: list[dict]) -> None:
    """Keep live B T0 open when the Polymarket GET is empty. Do not stamp settled."""
    open_keys = {
        (str(r.get("venue") or "").lower(), str(r.get("instrument") or "").lower())
        for r in open_rows or []
    }
    open_games = {game_norm(str(r.get("game") or "")) for r in open_rows or []}
    for cluster in clusters or []:
        inst_hit = any(
            (str(leg.get("venue") or "").lower(), str(leg.get("instrument") or "").lower()) in open_keys
            for leg in (cluster.get("fill_legs") or [])
        )
        game_hit = game_norm(str(cluster.get("game") or "")) in open_games
        on_overlay = inst_hit or game_hit
        b_t0_live = (
            bool(cluster.get("b_t0_both"))
            and not cluster.get("market_final")
            and not cluster.get("flatten_filled")
            and not cluster.get("void")
        )
        if cluster_is_settled(cluster) or (cluster.get("postponed") and not on_overlay and not b_t0_live):
            cluster["venue_live"] = False
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
            continue
        if on_overlay or b_t0_live:
            if Decimal(str(cluster.get("open_cost") or 0)) <= 0:
                cost = Decimal("0")
                for leg in cluster.get("fill_legs") or []:
                    cost += (Decimal(str(leg.get("cash") or 0)) * Decimal(str(leg.get("qty") or 0))) + Decimal(str(leg.get("fee") or 0))
                cluster["open_cost"] = cost
                cluster["open_legs"] = len(cluster.get("fill_legs") or [])
            cluster["venue_live"] = True
        else:
            cluster["venue_live"] = False
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
        cluster["hold_class"] = hold_class_of(cluster)


def t0_node_for_sent(watch: dict, sent: dict) -> dict:
    """Pick the T0 Yes node for this send.

    Polymarket T0 both-Yes uses one slug for both players (BUY_LONG Yes and
    BUY_SHORT No). Matching on instrument alone copies the last node's
    player and fill_px onto both tickets.
    """
    slots = watch.get("t0_yes") if isinstance(watch, dict) else None
    if not isinstance(slots, dict):
        return {}
    inst = str(sent.get("instrument") or "").strip().lower()
    player = last_name(str(sent.get("side_label") or sent.get("player") or ""))
    book = str(sent.get("side") or "").lower()
    nodes = [slots.get(letter) or {} for letter in ("a", "b")]
    nodes = [node for node in nodes if isinstance(node, dict) and node]

    def score(node: dict) -> int:
        n_inst = str(node.get("instrument") or "").strip().lower()
        n_player = last_name(str(node.get("player") or ""))
        n_side = str(node.get("side") or node.get("pay") or "").lower()
        points = 0
        if inst and n_inst == inst:
            points += 1
        if player and n_player and same_player(player, n_player):
            points += 4
        if book and n_side and book == n_side:
            points += 2
        return points

    if not nodes:
        return {}
    ranked = sorted(nodes, key=score, reverse=True)
    best = ranked[0]
    inst_hits = [node for node in nodes if str(node.get("instrument") or "").strip().lower() == inst]
    if len(inst_hits) > 1 and score(best) < 2:
        return {}
    if score(best) <= 0:
        return inst_hits[0] if len(inst_hits) == 1 else {}
    return best


def enrich_cluster(cluster: dict, by_id: dict, io_list: list[dict]) -> dict:
    claim = cluster.get("claim") or {}
    events = cluster.get("events") or []
    key = str(claim.get("bet_key") or "")
    info = parse_key(key)
    is_b = cluster.get("kind") == "b" or key.startswith("tennis-b")
    is_cfb = cluster.get("kind") == "cfb_favorite" or key.startswith("cfb-favorite")
    is_spread = cluster.get("kind") == "spread_t0" or key.startswith("spread-t0")
    is_dog = cluster.get("kind") == "tennis_t0_dog" or key.startswith("tennis-t0-dog")
    is_f_spread = cluster.get("kind") == "tennis_t0_spread" or key.startswith("tennis-t0-spread")
    is_g_total = cluster.get("kind") == "soccer_t0_total" or key.startswith("soccer-t0-total")
    sends = [row for row in events if row.get("event") == "sent"]
    skips = [row for row in events if row.get("event") == "skip"]
    flats = [row for row in events if row.get("event") in {"flatten_filled", "flatten_miss"}]
    used: set[str] = set()
    legs = []
    watch = cluster.get("watch") or {}
    t0_players = {}
    for letter in ("a", "b"):
        node = ((watch.get("t0_yes") or {}).get(letter) or {})
        inst = str(node.get("instrument") or "")
        player_name = str(node.get("player") or "")
        if inst and player_name:
            t0_players[(inst, last_name(player_name))] = player_name
        elif inst and inst not in t0_players:
            t0_players[inst] = player_name
    for sent in sends:
        io_row = match_io(sent, claim, by_id, io_list, used)
        cash, fee, qty = fill_cash_fee(sent, io_row)
        http_line = public_http_line(sent, io_row)
        player = str(sent.get("side_label") or sent.get("player") or "")
        if not player:
            player = t0_players.get(
                (str(sent.get("instrument") or ""), last_name(player)),
                "",
            ) or t0_players.get(str(sent.get("instrument") or ""), "")
        if not player:
            player = str(claim.get("side") or info.get("side_key") or "")
        step = str(sent.get("step") or "")
        node = t0_node_for_sent(watch, sent)
        watch_px = ddec(node.get("fill_px")) if node else None
        if node.get("player") and not player:
            player = str(node.get("player") or player)
        # T0 fill_px is only the trusted-start ticket. A later Yes on the same
        # ticker (b-cross / b-fav / leftover) is a different venue fill.
        # Do not copy a sibling's fill_px onto this send when venue cash exists.
        if watch_px is not None and qty_is_fill(qty) and step in {"b-t0", "t0"} and cash is None:
            cash = watch_px
        outcome_name = ""
        io_intent = ""
        book = str(sent.get("side") or "")
        if io_row and str(sent.get("venue") or "").lower() == "polymarket":
            payload = io_row.get("response") if isinstance(io_row.get("response"), dict) else {}
            poly = polymarket_fill(
                payload,
                quote=sent.get("quote_price") or (io_row or {}).get("quote_price"),
                pay=sent.get("quote_price") or sent.get("house_cash"),
                api_limit=sent.get("limit_price"),
            )
            outcome_name = str(poly.get("outcome_name") or "")
            io_intent = str(poly.get("intent") or "")
            if poly.get("side"):
                book = str(poly.get("side"))
            if outcome_name and (not player or player.lower() in {"yes", "no"}):
                player = outcome_name
        elif io_row and str(sent.get("venue") or "").lower() == "kalshi":
            req = io_row.get("request") if isinstance(io_row.get("request"), dict) else {}
            req_side = str(req.get("side") or req.get("action") or "").lower()
            if req_side in {"ask", "sell", "no"}:
                book = "no"
            elif req_side in {"bid", "buy", "yes"}:
                book = "yes"
        legs.append({
            "venue": str(sent.get("venue") or ""),
            "instrument": str(sent.get("instrument") or ""),
            "side": book,
            "player": player,
            "outcome_name": outcome_name,
            "io_intent": io_intent,
            "limit": sent.get("limit_price"),
            "cash": cash,
            "house_cash": cash,
            "fee": fee,
            "qty": qty,
            "http": sent.get("http_status"),
            "http_line": http_line,
            "step": str(sent.get("step") or ""),
            "order_id": str(sent.get("order_id") or ""),
            "sent_at": sent.get("sent_at"),
            "note": str(sent.get("note") or ""),
            "quote_source": sent.get("quote_source") or "",
            "quote_price": sent.get("quote_price") or "",
            "quote_size": sent.get("quote_size") or sent.get("ask_size") or "",
            "ask_size": sent.get("ask_size") or sent.get("quote_size") or "",
            "trigger": " ".join(
                part for part in (
                    str(sent.get("trigger_venue") or claim.get("trigger_venue") or ""),
                    str(sent.get("trigger_side") or claim.get("trigger_side") or ""),
                    str(sent.get("trigger_price") or claim.get("trigger_price") or ""),
                ) if part
            ),
            "posted": True,
            "has_io": io_row is not None,
        })
    n_posted = sum(1 for leg in legs if leg.get("has_io") or str(leg.get("http") or "") not in {"", "0", "pending"})
    # A send with no order_io and no real HTTP is not a post.
    posted = n_posted > 0 or any(leg.get("has_io") for leg in legs)
    fill_legs = [leg for leg in legs if qty_is_fill(leg.get("qty"))]
    n_fill_legs = len(fill_legs)
    complementary = complementary_legs(fill_legs)
    flatten_events = [row for row in events if row.get("event") in {"flatten_filled", "flatten_miss"}]
    flatten_filled = any(row.get("event") == "flatten_filled" for row in flatten_events)
    flattened = bool(flatten_events) or any(str(leg.get("step") or "") in {"flatten", "extra-flatten"} for leg in legs)
    t0_fills = [leg for leg in fill_legs if str(leg.get("step") or "") in {"b-t0", "t0", ""}]
    if is_b:
        t0_fills = [leg for leg in fill_legs if str(leg.get("step") or "") in {"b-t0", "t0"}]
    b_t0_both = is_b and len(t0_fills) >= 2
    leftover_stack = False
    if is_b:
        steps = {str(leg.get("step") or "") for leg in legs}
        watch = cluster.get("watch") or {}
        if "b-leftover-yes" in steps and not b_t0_both:
            leftover_stack = True
        if str(watch.get("stage") or "") in {"one_leg_miss"}:
            leftover_stack = True
        extra_after_miss = any(str(leg.get("step") or "") in {"b-leftover-yes"} for leg in fill_legs)
        if extra_after_miss and not b_t0_both:
            leftover_stack = True
        # Shigeta extra: T0 both then extra cross on dog after T0 — user called extra not intentional.
        if b_t0_both and any(str(leg.get("step") or "") == "b-cross" for leg in fill_legs):
            # keep T0 as B; mark extra legs leftover by splitting later
            pass
        if not b_t0_both and n_fill_legs == 1:
            leftover_stack = True  # Takagi unpaired T0 dog
    intent = classify_intent(
        is_b=is_b,
        posted=posted,
        n_fill_legs=n_fill_legs,
        complementary=complementary,
        b_t0_both=b_t0_both,
        leftover_stack=leftover_stack and not b_t0_both,
    )
    if is_cfb:
        intent = INTENT_CFB if n_fill_legs >= 1 else INTENT_CFB
        leftover_stack = False
    elif is_spread:
        intent = INTENT_SPREAD if n_fill_legs >= 1 else INTENT_SPREAD
        leftover_stack = False
    elif is_dog:
        intent = INTENT_DOG
        leftover_stack = False
    elif is_f_spread:
        intent = INTENT_SPREAD_F
        leftover_stack = False
    elif is_g_total:
        intent = INTENT_TOTAL_G
        leftover_stack = False
    elif is_b:
        intent = INTENT_TENNIS if intent == INTENT_B else intent
    result = result_label(
        posted=posted,
        n_fill_legs=n_fill_legs,
        flattened=flattened,
        complementary=complementary,
        flatten_filled=flatten_filled,
    )
    if not posted and skips:
        result = "never posted (claim+skip)"
    game = str(claim.get("game") or "")
    sport = sport_of(claim, key)
    market = str(claim.get("market_type") or info.get("market_type") or "")
    side = str(claim.get("side") or info.get("side_key") or "")
    number = str(claim.get("number") or info.get("number") or "")
    start = first_time(cluster)
    n_claims = 1 if claim.get("event") == "claim" or claim.get("bet_key") else 1
    n_attempts = max(1, len(sends) or len(skips) or n_claims)
    if not posted:
        n_attempts = max(len(skips), 1) if (skips or claim) else 1
        # count the claim itself as an attempt
        n_attempts = (1 if claim else 0) + len(skips) + len(sends)
        if n_attempts <= 0:
            n_attempts = 1
    else:
        n_attempts = max(len(sends), 1)
    notes = []
    if claim.get("trigger_venue"):
        notes.append(
            f"trigger {claim.get('trigger_venue')} {claim.get('trigger_side')} "
            f"{claim.get('trigger_price')} vs recheck"
        )
    if any(leg.get("quote_source") for leg in legs):
        notes.append("quote " + ", ".join(sorted({str(leg.get('quote_source')) for leg in legs if leg.get("quote_source")})))
    watch = cluster.get("watch") or {}
    if watch.get("stage"):
        notes.append(f"B stage {watch.get('stage')}")
    if watch.get("postponed_reason"):
        notes.append(f"postponed {watch.get('postponed_reason')}")
    if watch.get("note"):
        notes.append(str(watch.get("note"))[:160])
    if any(row.get("event") == "orders_off" for row in events):
        notes.append("latch orders_off")
    cluster.update({
        "game": game,
        "sport": sport,
        "market": market,
        "side": side,
        "number": number,
        "is_b": is_b,
        "posted": posted,
        "legs": legs,
        "fill_legs": fill_legs,
        "n_fill_legs": n_fill_legs,
        "complementary": complementary,
        "intent": intent,
        "result": result,
        "start": start,
        "n_attempts": n_attempts,
        "n_sends": len(sends),
        "n_skips": len(skips),
        "flattened": flattened,
        "flatten_filled": flatten_filled,
        "b_t0_both": b_t0_both,
        "leftover_stack": leftover_stack,
        "notes": notes,
        "key": key,
    })
    stamp_kitchen_side_labels(cluster)
    return cluster


def ghost_clusters(lock_clusters: list[dict]) -> list[dict]:
    """Group never-posted lock claims by game/market/line so attempt counts stay honest."""
    groups: dict[tuple, dict] = {}
    for cluster in lock_clusters:
        if cluster.get("posted") or cluster.get("n_fill_legs"):
            continue
        if cluster.get("is_b"):
            continue
        key = (
            cluster.get("sport") or "",
            cluster.get("game") or "",
            cluster.get("market") or "",
            cluster.get("side") or "",
            str(cluster.get("number") or ""),
        )
        slot = groups.get(key)
        if slot is None:
            slot = dict(cluster)
            slot["n_attempts"] = 0
            slot["ghost_n"] = 0
            slot["intent"] = INTENT_LEFTOVER
            slot["result"] = "never posted (claim+skip)"
            slot["notes"] = list(cluster.get("notes") or [])
            slot["notes"].append("ghost claim: no order_io HTTP")
            groups[key] = slot
        slot["ghost_n"] += 1
        slot["n_attempts"] += int(cluster.get("n_attempts") or 1)
        start = cluster.get("start")
        if start and (slot.get("start") is None or start < slot["start"]):
            slot["start"] = start
    return list(groups.values())


def split_b_extras(cluster: dict) -> list[dict]:
    """T0 both-Yes stays intentional B; leftover extras after a miss / Shigeta extra are leftover rows.

    T0 and extra must not share `legs`. Dashboard walks `legs`; leaving the
    later Yes on the T0 cluster prints the same venue fill twice.
    """
    if not cluster.get("is_b"):
        return [cluster]
    fill_legs = cluster.get("fill_legs") or []
    all_legs = list(cluster.get("legs") or [])
    extra_steps = {"b-leftover-yes", "b-cross", "b-fav"}
    t0 = [leg for leg in fill_legs if str(leg.get("step") or "") == "b-t0"]
    extras = [leg for leg in fill_legs if str(leg.get("step") or "") in extra_steps]
    t0_all = [leg for leg in all_legs if str(leg.get("step") or "") == "b-t0"]
    extra_all = [leg for leg in all_legs if str(leg.get("step") or "") in extra_steps]
    rest = [leg for leg in all_legs if str(leg.get("step") or "") not in extra_steps]
    rows = []
    base = dict(cluster)
    if len(t0) >= 2:
        base["fill_legs"] = t0
        base["legs"] = rest or t0_all or t0
        base["n_fill_legs"] = len(t0)
        base["complementary"] = True
        base["intent"] = INTENT_TENNIS
        base["result"] = "both filled lock" if complementary_legs(t0) else "intentional B T0"
        base["b_t0_both"] = True
        rows.append(base)
    elif fill_legs:
        rows.append(cluster)
        return rows
    else:
        rows.append(cluster)
        return rows
    leftover_extras = [leg for leg in extras if str(leg.get("step") or "") == "b-leftover-yes"]
    leftover_all = [leg for leg in extra_all if str(leg.get("step") or "") == "b-leftover-yes"]
    # Shigeta-style extra: extra dog after T0 both already filled
    playbook = [leg for leg in extras if str(leg.get("step") or "") in {"b-cross", "b-fav"}]
    playbook_all = [leg for leg in extra_all if str(leg.get("step") or "") in {"b-cross", "b-fav"}]
    watch = cluster.get("watch") or {}
    extra_stuck = bool(watch.get("extra_stuck"))
    if leftover_extras or extra_stuck:
        extra_row = dict(cluster)
        extra_row["fill_legs"] = leftover_extras or playbook
        extra_row["n_fill_legs"] = len(extra_row["fill_legs"])
        extra_row["intent"] = INTENT_LEFTOVER
        extra_row["result"] = "not intentional leftover"
        extra_row["leftover_stack"] = True
        extra_row["complementary"] = False
        extra_row["notes"] = list(cluster.get("notes") or []) + ["extra after miss / unpaired leftover"]
        extra_row["legs"] = leftover_all or playbook_all or extra_row["fill_legs"]
        rows.append(extra_row)
    elif playbook:
        extra_row = dict(cluster)
        extra_row["fill_legs"] = playbook
        extra_row["n_fill_legs"] = len(playbook)
        extra_row["intent"] = INTENT_TENNIS
        extra_row["result"] = "intentional B extra/cross/fav"
        extra_row["notes"] = list(cluster.get("notes") or []) + ["B playbook extra/cross/fav"]
        extra_row["legs"] = playbook_all or playbook
        rows.append(extra_row)
    return rows


def _leg_market_row(leg: dict, settlements: list[dict], market_index: dict | None) -> dict | None:
    ticker = str(leg.get("instrument") or "").strip()
    venue = str(leg.get("venue") or "").lower()
    if not ticker:
        return None
    index = market_index or {}
    row = index.get((venue, ticker.lower())) or index.get(ticker.lower())
    if row:
        return row
    for item in settlements:
        if str(item.get("ticker") or "").lower() == ticker.lower():
            return item
    return None


def score_cluster(
    cluster: dict,
    settlements: list[dict],
    venue_index: dict | None = None,
    market_index: dict | None = None,
) -> dict:
    fill_legs = cluster.get("fill_legs") or []
    winner = game_winner(settlements, str(cluster.get("game") or ""))
    realized = Decimal("0")
    open_mark = Decimal("0")
    open_cost = Decimal("0")
    fees = sum((Decimal(str(leg.get("fee") or 0)) for leg in fill_legs), Decimal("0"))
    n_fills = sum((Decimal(str(leg.get("qty") or 0)) for leg in fill_legs if qty_is_fill(leg.get("qty"))), Decimal("0"))
    settled_legs = 0
    open_legs = 0
    wins = 0
    losses = 0
    complementary = bool(cluster.get("complementary"))
    watch = cluster.get("watch") or {}
    market_index = market_index or {}
    market_rows = [_leg_market_row(leg, settlements, market_index) for leg in fill_legs]
    postponed = kitchen_is_postponed(cluster, market_rows)
    market_final = any(settlement_is_final(row, venue=str((fill_legs[i].get("venue") if i < len(fill_legs) else "") or "")) for i, row in enumerate(market_rows))
    venue_paid = any(
        str((row or {}).get("result") or "").lower() in {"yes", "no", "void", "n/a"}
        or _poly_px_result(row or {}) in FINAL_RESULTS
        for row in market_rows
    )
    voided = any(str((row or {}).get("result") or "").lower() in {"void", "n/a"} or (row or {}).get("void") for row in market_rows)
    held_legs = [leg for leg in fill_legs if venue_holds_leg(leg, venue_index or {})]
    # Empty Poly GET must not drop a confirmed fill while the market is still OPEN.
    # Settled / expired / final / void never count as open.
    if postponed and not voided and not venue_paid:
        venue_live = bool(held_legs)
        market_final = False
        venue_paid = False
    elif market_final or venue_paid or voided:
        venue_live = False
        held_legs = []
    else:
        venue_live = bool(held_legs)
    # Empty Poly GET must not drop a B T0 both-Yes while the market is OPEN.
    # Flattened Yes+No is not open — no TRADE/position remains on the book.
    if cluster.get("flatten_filled"):
        venue_live = False
        held_legs = []
    elif cluster.get("b_t0_both") and not market_final and not voided and not postponed:
        venue_live = True
        if not held_legs:
            held_legs = list(fill_legs)
    unknown = False
    if venue_live:
        cost = sum(
            (Decimal(str(leg.get("cash") or 0)) * Decimal(str(leg.get("qty") or 0))) + Decimal(str(leg.get("fee") or 0))
            for leg in held_legs
        )
        open_cost += cost
        open_legs = len(held_legs)
        if complementary and len(fill_legs) >= 2:
            open_mark += lock_realized(fill_legs)
    elif postponed and not voided:
        unknown = True
        cluster["result"] = cluster.get("result") or "postponed (not settled)"
    elif (
        complementary
        and len(fill_legs) >= 2
        and cluster.get("flatten_filled")
        and all(qty_is_house_fill(leg.get("qty")) for leg in fill_legs)
    ):
        pnl = lock_realized(fill_legs)
        realized += pnl
        settled_legs = len(fill_legs)
        venue_paid = True
        market_final = True
        if pnl >= 0:
            wins += 1
        else:
            losses += 1
    elif (
        complementary
        and len(fill_legs) >= 2
        and not postponed
        and all(qty_is_house_fill(leg.get("qty")) for leg in fill_legs)
    ):
        if winner or venue_paid or market_final:
            if winner or venue_paid:
                pnl = lock_realized(fill_legs)
                realized += pnl
                settled_legs = len(fill_legs)
                venue_paid = True
                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1
            else:
                settled_legs = len(fill_legs)
                market_final = True
                unknown = True
        else:
            unknown = True
    else:
        for i, leg in enumerate(fill_legs):
            status, pnl = ticket_settled_pnl(leg, settlements, winner)
            row = market_rows[i] if i < len(market_rows) else None
            if status == "open" and settlement_is_final(row, venue=str(leg.get("venue") or "")):
                result = str((row or {}).get("result") or "").lower()
                if result in {"void", "n/a"} or (row or {}).get("void"):
                    status, pnl = "void", Decimal("0")
                elif result in {"yes", "no"}:
                    status, pnl = ticket_settled_pnl(leg, settlements, winner)
            if status == "open":
                if postponed:
                    unknown = True
                elif settlement_is_final(row, venue=str(leg.get("venue") or "")):
                    settled_legs += 1
                    market_final = True
                    unknown = True
                else:
                    unknown = True
            elif pnl is not None:
                realized += pnl
                settled_legs += 1
                venue_paid = True
                if status == "win":
                    wins += 1
                else:
                    losses += 1
            elif status == "void":
                settled_legs += 1
                voided = True
    cluster["realized"] = realized
    cluster["open_mark"] = open_mark
    cluster["open_cost"] = open_cost
    cluster["fees"] = fees
    cluster["n_fill_qty"] = n_fills
    cluster["settled_legs"] = settled_legs
    cluster["open_legs"] = open_legs
    cluster["wins"] = wins
    cluster["losses"] = losses
    cluster["winner"] = winner
    cluster["postponed"] = postponed
    cluster["venue_live"] = venue_live
    cluster["market_final"] = bool(market_final or venue_paid or voided) and not (postponed and not voided and not venue_paid)
    cluster["venue_paid"] = bool(venue_paid)
    cluster["status_unknown"] = unknown and not venue_live
    cluster["league"] = league_of(cluster)
    cluster["leftover_flag"] = leftover_status(cluster)
    if voided and postponed:
        cluster["void"] = True
        cluster["result"] = "void (postponed / cancelled)"
    return cluster


def fetch_kalshi_amounts(*, force: bool = True) -> dict:
    """Existing GET /trade-api/v2/portfolio/positions helper. Amounts only. Fail-soft.

    Force a fresh pull unless a cache from the last 15 minutes exists and force is false.
    """
    try:
        import cheaper_same_bet

        cached = load_json(cheaper_same_bet.POSITIONS)
        pulled = parse_dt((cached or {}).get("pulled_at") or "")
        now = datetime.now(ET)
        fresh = pulled is not None and abs((now - pulled).total_seconds()) < 15 * 60
        payload = cached if (fresh and not force and isinstance(cached, dict)) else cheaper_same_bet.fetch_positions()
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "rows": []}
    body = (payload or {}).get("body") or {}
    rows = []
    by_ticker: dict[str, dict] = {}
    for item in body.get("market_positions") or []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "")
        row = {
            "ticker": ticker,
            "position": item.get("position_fp"),
            "exposure": item.get("market_exposure_dollars"),
            "fees": item.get("fees_paid_dollars"),
            "realized": item.get("realized_pnl_dollars"),
            "last_updated_ts": item.get("last_updated_ts"),
        }
        rows.append(row)
        if ticker:
            by_ticker[ticker] = row
    return {
        "ok": True,
        "http": payload.get("http_status"),
        "pulled_at": payload.get("pulled_at"),
        "rows": rows,
        "n": len(rows),
        "by_ticker": by_ticker,
    }


def fetch_polymarket_positions() -> dict:
    """GET /v1/portfolio/positions through existing polymarket_us_live.signed_json.

    Path already used in-repo (19 Oct 2026 dump). Amounts only. No secrets.
    """
    try:
        import polymarket_us_live

        status, text = polymarket_us_live.signed_json("GET", "/v1/portfolio/positions")
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "http": 0, "rows": [], "by_slug": {}}
    try:
        body = json.loads(text) if text else {}
    except json.JSONDecodeError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    pulled_at = datetime.now(ET).isoformat()
    positions = body.get("positions") if isinstance(body.get("positions"), dict) else {}
    rows = []
    by_slug: dict[str, dict] = {}
    for slug, item in positions.items():
        if not isinstance(item, dict):
            continue
        meta = item.get("marketMetadata") if isinstance(item.get("marketMetadata"), dict) else {}
        avg = item.get("avgPx") if isinstance(item.get("avgPx"), dict) else {}
        cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
        cash = item.get("cashValue") if isinstance(item.get("cashValue"), dict) else {}
        fees = item.get("fees") if isinstance(item.get("fees"), dict) else {}
        row = {
            "slug": slug,
            "title": meta.get("title") or "",
            "outcome": meta.get("outcome") or "",
            "net": item.get("netPositionDecimal") or item.get("netPosition") or "",
            "qty_bought": item.get("qtyBoughtDecimal") or item.get("qtyBought") or "",
            "qty_sold": item.get("qtySoldDecimal") or item.get("qtySold") or "",
            "avg_px": avg.get("value") if isinstance(avg, dict) else "",
            "cost": cost.get("value") if isinstance(cost, dict) else "",
            "cash_value": cash.get("value") if isinstance(cash, dict) else "",
            "fees": fees.get("value") if isinstance(fees, dict) else "",
            "expired": item.get("expired"),
        }
        rows.append(row)
        by_slug[str(slug)] = row
    payload = {
        "http_status": status,
        "pulled_at": pulled_at,
        "eof": body.get("eof"),
        "n": len(rows),
    }
    try:
        (RAW / "polymarket_positions_pull.json").write_text(
            json.dumps({"http_status": status, "pulled_at": pulled_at, "body": {
                "eof": body.get("eof"),
                "nextCursor": body.get("nextCursor") or "",
                "n": len(rows),
                "slugs": list(by_slug),
            }}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return {
        "ok": status == 200,
        "http": status,
        "pulled_at": pulled_at,
        "eof": body.get("eof"),
        "rows": rows,
        "n": len(rows),
        "by_slug": by_slug,
        **payload,
    }


def venue_index_of(kalshi_pos: dict, poly_pos: dict) -> dict:
    return {
        "kalshi": kalshi_pos.get("by_ticker") or {},
        "polymarket": poly_pos.get("by_slug") or {},
        "gemini": None,
        "novig": None,
        "kalshi_ok": bool(kalshi_pos.get("ok")),
        "poly_ok": bool(poly_pos.get("ok")),
    }


def venue_holds_leg(leg: dict, venue_index: dict) -> bool:
    venue = str(leg.get("venue") or "").lower()
    instrument = str(leg.get("instrument") or "")
    if not instrument:
        return False
    if venue == "kalshi":
        row = (venue_index.get("kalshi") or {}).get(instrument)
        if not row:
            return False
        try:
            return Decimal(str(row.get("position") or 0)) != 0
        except Exception:
            return bool(row.get("position"))
    if venue == "polymarket":
        row = (venue_index.get("polymarket") or {}).get(instrument)
        if not row:
            return False
        try:
            return Decimal(str(row.get("net") or 0)) != 0
        except Exception:
            return bool(row.get("net"))
    return False


def kalshi_io_fill_legs(io_list: list[dict]) -> dict[str, list[dict]]:
    """Kalshi order_io fills with qty >= 1, keyed by ticker. Uses request side/intent only."""
    found: dict[str, list[dict]] = defaultdict(list)
    for row in io_list:
        if str(row.get("kind") or "") != "order":
            continue
        if str(row.get("venue") or "").lower() != "kalshi":
            continue
        payload = row.get("response")
        qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
        if not qty_is_fill(qty):
            continue
        ticker = _io_instrument(row)
        if not ticker:
            continue
        req = row.get("request") if isinstance(row.get("request"), dict) else {}
        req_side = str(req.get("side") or req.get("action") or "").lower()
        book = "no" if req_side in {"ask", "sell", "no"} else "yes" if req_side in {"bid", "buy", "yes"} else ""
        if not book:
            continue
        inner = payload.get("order") if isinstance(payload, dict) and isinstance(payload.get("order"), dict) else payload
        avg = ddec(inner.get("average_fill_price")) if isinstance(inner, dict) else None
        if book == "no" and avg is not None:
            cash = ONE - avg
        else:
            cash = avg or Decimal("0")
        found[ticker].append({
            "venue": "kalshi",
            "instrument": ticker,
            "side": book,
            "qty": qty,
            "cash": cash,
            "fee": Decimal("0"),
        })
    return found


def net_closed_same_ticker(clusters: list[dict], venue_index: dict, io_list: list[dict] | None = None) -> None:
    """If Kalshi Yes+No on the same ticker both filled and the ticker is gone from positions, that is a closed flatten/lock."""
    by_ticker: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for cluster in clusters:
        for leg in cluster.get("fill_legs") or []:
            if str(leg.get("venue") or "").lower() != "kalshi":
                continue
            ticker = str(leg.get("instrument") or "")
            if ticker:
                by_ticker[ticker].append((cluster, leg))
    io_fills = kalshi_io_fill_legs(io_list or [])
    kalshi = venue_index.get("kalshi") or {}
    tickers = set(by_ticker) | set(io_fills)
    for ticker in tickers:
        if ticker in kalshi:
            continue
        pairs = by_ticker.get(ticker) or []
        io_legs = io_fills.get(ticker) or []
        sides = {str(leg.get("side") or "").lower() for _c, leg in pairs}
        sides |= {str(leg.get("side") or "").lower() for leg in io_legs}
        if "yes" not in sides or "no" not in sides:
            continue
        all_legs = io_legs or [leg for _c, leg in pairs]
        pnl = lock_realized(all_legs)
        first = True
        seen: set[int] = set()
        targets = [c for c, _leg in pairs]
        if not targets:
            continue
        for cluster in targets:
            cid = id(cluster)
            if cid in seen:
                continue
            seen.add(cid)
            other = [
                leg for leg in (cluster.get("fill_legs") or [])
                if str(leg.get("venue") or "").lower() == "kalshi"
                and str(leg.get("instrument") or "") != ticker
            ]
            if other:
                cluster["notes"] = list(cluster.get("notes") or []) + [
                    f"Kalshi ticker {ticker} Yes+No both filled on order_io and is gone from positions; this cluster also has other tickers so it is not labeled a full flatten"
                ]
                continue
            cluster["complementary"] = True
            cluster["flatten_filled"] = True
            cluster["result"] = "flatten filled"
            cluster["leftover_flag"] = LEFTOVER_NO
            cluster["open_legs"] = 0
            cluster["open_cost"] = Decimal("0")
            cluster["open_mark"] = Decimal("0")
            cluster["status_unknown"] = False
            cluster["venue_live"] = False
            cluster["realized"] = pnl if first else Decimal("0")
            cluster["settled_legs"] = len(all_legs) if first else 0
            cluster["notes"] = list(cluster.get("notes") or []) + [
                f"Kalshi ticker {ticker} Yes+No both filled on order_io and the position list is now empty; counted as closed flatten/lock, not still-open"
            ]
            first = False


def venue_stats(clusters: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = defaultdict(lambda: {
        "fills": Decimal("0"),
        "fees": Decimal("0"),
        "realized": Decimal("0"),
        "open_cost": Decimal("0"),
        "n_sends": 0,
        "n_empty_201": 0,
    })
    for cluster in clusters:
        share = Decimal("0")
        n_fill = len(cluster.get("fill_legs") or []) or 1
        realized_each = Decimal(str(cluster.get("realized") or 0)) / n_fill
        for leg in cluster.get("legs") or []:
            venue = str(leg.get("venue") or "unknown")
            found[venue]["n_sends"] += 1
            if is_empty_http_fill(leg.get("http"), leg.get("qty")):
                found[venue]["n_empty_201"] += 1
            if qty_is_fill(leg.get("qty")):
                found[venue]["fills"] += Decimal(str(leg.get("qty") or 0))
                found[venue]["fees"] += Decimal(str(leg.get("fee") or 0))
                found[venue]["realized"] += realized_each
                if cluster.get("open_legs"):
                    found[venue]["open_cost"] += (
                        Decimal(str(leg.get("cash") or 0)) * Decimal(str(leg.get("qty") or 0))
                    ) + Decimal(str(leg.get("fee") or 0))
    return found


def intent_stats(clusters: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = defaultdict(lambda: {
        "n": 0,
        "realized": Decimal("0"),
        "open_mark": Decimal("0"),
        "open_cost": Decimal("0"),
        "fills": 0,
        "locks": 0,
        "leftovers": 0,
        "b_t0": 0,
    })
    for cluster in clusters:
        intent = str(cluster.get("intent") or INTENT_LEFTOVER)
        slot = found[intent]
        slot["n"] += 1
        slot["realized"] += Decimal(str(cluster.get("realized") or 0))
        slot["open_mark"] += Decimal(str(cluster.get("open_mark") or 0))
        slot["open_cost"] += Decimal(str(cluster.get("open_cost") or 0))
        slot["fills"] += Decimal(str(cluster.get("n_fill_qty") or 0))
        if intent == INTENT_FULL_LOCK:
            slot["locks"] += 1
        if intent == INTENT_INCOMPLETE_LOCK:
            slot["leftovers"] += 1
        if intent in {INTENT_B, INTENT_TENNIS} and cluster.get("b_t0_both"):
            slot["b_t0"] += 1
        if intent == INTENT_LEFTOVER and cluster.get("n_fill_legs"):
            slot["leftovers"] += 1
    return found


def sport_stats(clusters: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = defaultdict(lambda: {
        "n": 0,
        "realized": Decimal("0"),
        "open_mark": Decimal("0"),
        "open_cost": Decimal("0"),
        "fills": 0,
        "full_locks": 0,
        "incomplete": 0,
        "b": 0,
        "leftover": 0,
        "ghosts": 0,
    })
    for cluster in clusters:
        sport = str(cluster.get("sport") or "unknown")
        slot = found[sport]
        slot["n"] += 1
        slot["realized"] += Decimal(str(cluster.get("realized") or 0))
        slot["open_mark"] += Decimal(str(cluster.get("open_mark") or 0))
        slot["open_cost"] += Decimal(str(cluster.get("open_cost") or 0))
        slot["fills"] += Decimal(str(cluster.get("n_fill_qty") or 0))
        intent = cluster.get("intent")
        if intent == INTENT_FULL_LOCK:
            slot["full_locks"] += 1
        elif intent == INTENT_INCOMPLETE_LOCK:
            slot["incomplete"] += 1
        elif intent in {INTENT_B, INTENT_TENNIS}:
            slot["b"] += 1
        elif cluster.get("result") == "never posted (claim+skip)":
            slot["ghosts"] += 1
            slot["leftover"] += 1
        else:
            slot["leftover"] += 1
    return found


def still_open_from_venue(
    kalshi_pos: dict,
    poly_pos: dict,
    clusters: list[dict],
    market_index: dict | None = None,
) -> list[dict]:
    """Still-open = currently on a venue position list and the market is not final."""
    rows = []
    cluster_by_inst: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for cluster in clusters:
        for leg in (cluster.get("fill_legs") or cluster.get("legs") or []):
            venue = str(leg.get("venue") or "").lower()
            inst = str(leg.get("instrument") or "")
            if venue and inst:
                cluster_by_inst[(venue, inst)].append(cluster)
    for row in kalshi_pos.get("rows") or []:
        ticker = str(row.get("ticker") or "")
        try:
            pos = Decimal(str(row.get("position") or 0))
        except Exception:
            pos = Decimal("0")
        if not ticker or pos == 0:
            continue
        info = (market_index or {}).get(("kalshi", ticker.lower())) or (market_index or {}).get(ticker.lower())
        if settlement_is_final(info, venue="kalshi"):
            continue
        related = cluster_by_inst.get(("kalshi", ticker), [])
        postponed = any(c.get("postponed") for c in related)
        game = next((c.get("game") for c in related if c.get("game")), "") or ticker
        leftover = leftover_status(related[0]) if related else LEFTOVER_YES
        if abs(pos) > 1:
            leftover = LEFTOVER_YES
        sport = next((c.get("sport") for c in related if c.get("sport")), "")
        sys_letter = next((c.get("system_letter") or system_of(c) for c in related), "")
        try:
            import job_status_positions as jsp

            inferred = jsp.sport_from_ticker(ticker)
            if inferred == "pro football":
                sport = "pro football"
                if jsp.is_nfl_moneyline(ticker) and sys_letter in {"", "B", "unknown"}:
                    sys_letter = "A"
            elif inferred:
                sport = sport or inferred
        except Exception:
            pass
        if not sys_letter:
            sys_letter = "A"
        names = game_sides(game)
        who = kalshi_ticker_who(ticker, names) or UNKNOWN_ASK
        book = "yes" if pos > 0 else "no"
        try:
            import kalshi_ticker_decode as ktd

            if ktd.is_sports_ticker(ticker):
                decoded = ktd.decode_with_cached_title(ticker, pay=book, fetch=False)
                if decoded.kind:
                    game = decoded.game or game
                    sport = sport or decoded.sport
                    who = ktd.bet_for_who(decoded, book) or who
                    bet_for = ktd.kitchen_phrase(decoded, book)
                else:
                    bet_for = f"{book.capitalize()} {who} (Kalshi leftover)"
            else:
                bet_for = f"{book.capitalize()} {who} (Kalshi leftover)"
        except Exception:
            bet_for = f"{book.capitalize()} {who} (Kalshi leftover)"
        if not str(bet_for or "").strip():
            bet_for = f"{book.capitalize()} {who} (Kalshi leftover)"
        if not sport:
            sport = "tennis"
        who_pays = ""
        try:
            import kalshi_ticker_decode as ktd

            if ktd.is_sports_ticker(ticker):
                decoded = ktd.decode_with_cached_title(ticker, pay=book, fetch=False)
                if decoded.kind:
                    who_pays = ktd.pays_if_label(decoded, book)
        except Exception:
            who_pays = ""
        rows.append({
            "game": game,
            "sport": sport,
            "league": league_from_instrument(ticker) if ticker else "",
            "system": sys_letter,
            "open_type": order_types.open_now_type(sys_letter),
            "players": players_game_label(game, sport),
            "bet_for": bet_for,
            "who_pays": who_pays,
            "bet_against": "unpaired leftover (still on Kalshi book)",
            "venue": "kalshi",
            "instrument": ticker,
            "confirmed": f"Yes {pos}" if pos > 0 else f"No {abs(pos)}",
            "position": str(pos),
            "exposure": row.get("exposure"),
            "postponed": "yes" if postponed else "no",
            "leftover": leftover,
            "source": "Kalshi GET /trade-api/v2/portfolio/positions",
            "tape": "; ".join(
                f"{c.get('intent')} / {c.get('result')}" for c in related[:3]
            ) or "no matching tape cluster",
        })
    for row in poly_pos.get("rows") or []:
        slug = str(row.get("slug") or "")
        try:
            net = Decimal(str(row.get("net") or 0))
        except Exception:
            net = Decimal("0")
        if not slug or net == 0:
            continue
        info = (market_index or {}).get(("polymarket", slug.lower())) or (market_index or {}).get(slug.lower())
        if settlement_is_final(info, venue="polymarket"):
            continue
        related = cluster_by_inst.get(("polymarket", slug), [])
        postponed = any(c.get("postponed") for c in related)
        game = row.get("title") or next((c.get("game") for c in related if c.get("game")), slug)
        leftover = leftover_status(related[0]) if related else LEFTOVER_YES
        sport = next((c.get("sport") for c in related if c.get("sport")), "")
        sys_letter = next((c.get("system_letter") or system_of(c) for c in related), "")
        outcome = str(row.get("outcome") or "").strip()
        who = ""
        try:
            import job_status_positions as jsp

            inferred = jsp.sport_from_ticker(slug)
            if inferred == "pro football":
                sport = "pro football"
                if jsp.is_nfl_moneyline(slug) and sys_letter in {"", "B", "unknown"}:
                    sys_letter = "A"
            elif inferred:
                sport = sport or inferred
            who = jsp._nfl_full_name(outcome) if outcome else ""
            poly_game = jsp._poly_nfl_game(slug)
            if poly_game:
                game = poly_game
                sport = "pro football"
                if jsp.is_nfl_moneyline(slug) and sys_letter in {"", "B", "unknown"}:
                    sys_letter = "A"
        except Exception:
            who = outcome
        if not sport:
            sport = "tennis"
        if not sys_letter:
            sys_letter = "B"
        if who and net < 0:
            bet_for = f"No {who}"
            who_pays = ""
        elif who and net > 0:
            bet_for = f"Yes {who}"
            who_pays = f"{who} win"
        elif outcome and net < 0:
            bet_for = f"No {outcome} (Poly short leftover)"
            who_pays = ""
        elif outcome and net > 0:
            bet_for = f"Yes {outcome} (Poly leftover)"
            who_pays = f"{outcome} win"
        else:
            bet_for = UNKNOWN_ASK
            who_pays = ""
        rows.append({
            "game": game,
            "sport": sport,
            "league": league_from_instrument(slug) if slug else "",
            "system": sys_letter,
            "open_type": order_types.open_now_type(sys_letter),
            "players": players_game_label(game, sport),
            "bet_for": bet_for,
            "who_pays": who_pays,
            "bet_against": "unpaired leftover / extra Yes" if leftover == LEFTOVER_YES else "unpaired leftover (still on Poly book)",
            "venue": "polymarket",
            "instrument": slug,
            "confirmed": (
                f"outcome {row.get('outcome')} net {row.get('net')} "
                f"bought {row.get('qty_bought')} sold {row.get('qty_sold')} "
                f"avgPx {row.get('avg_px')} cost {row.get('cost')} mark {row.get('cash_value')}"
            ),
            "position": str(net),
            "exposure": row.get("cost"),
            "postponed": "yes" if postponed else "no",
            "leftover": leftover,
            "source": "Polymarket US GET /v1/portfolio/positions",
            "tape": "; ".join(
                f"{c.get('intent')} / {c.get('result')}" for c in related[:3]
            ) or "no matching tape cluster",
        })
    try:
        import job_status_positions as jsp

        jsp.pair_nfl_lock_tickets(rows)
        for row in rows:
            if str(row.get("sport") or "") == "pro football":
                row["players"] = players_game_label(str(row.get("game") or ""), "pro football")
                row["league"] = row.get("league") or league_from_instrument(str(row.get("instrument") or ""))
            letter = str(row.get("system") or row.get("letter") or "")
            row["open_type"] = order_types.open_now_type(letter)
    except Exception:
        pass
    rows.sort(key=lambda item: str(item.get("game") or ""))
    return rows


def open_risk_rows(open_rows: list[dict]) -> list[list]:
    out = []
    for row in open_rows:
        letter = row.get("system") or ""
        spec = SYSTEM_BY_LETTER.get(letter)
        sys_label = f"{letter} {spec[2]}" if spec else (letter or "unknown")
        out.append([
            sys_label,
            row.get("players") or players_game_label(str(row.get("game") or ""), str(row.get("sport") or "")),
            row.get("sport"),
            row.get("bet_for") or UNKNOWN_ASK,
            row.get("bet_against") or "unpaired leftover (still on venue book)",
            row.get("venue"),
            row.get("leftover"),
            row.get("postponed"),
            row.get("confirmed"),
            row.get("source"),
            row.get("tape"),
        ])
    return out


def removed_closed_rows(
    clusters: list[dict],
    open_rows: list[dict],
    fills_index: dict | None = None,
) -> list[list]:
    """One row per filled cluster that is gone from live Kalshi/Poly books."""
    open_games = {game_norm(str(r.get("game") or "")) for r in open_rows}
    open_inst = {(str(r.get("venue") or "").lower(), str(r.get("instrument") or "")) for r in open_rows}
    fills_index = fills_index or {}
    out = []
    for cluster in clusters:
        if not cluster.get("n_fill_legs"):
            continue
        game = str(cluster.get("game") or "")
        key = game_norm(game)
        if key and key in open_games:
            continue
        held = False
        for leg in cluster.get("fill_legs") or []:
            if (str(leg.get("venue") or "").lower(), str(leg.get("instrument") or "")) in open_inst:
                held = True
                break
        if held:
            continue
        if cluster.get("venue_live"):
            continue
        why = []
        if cluster.get("void"):
            why.append("void (tape only, not a venue holding)")
        if cluster.get("flatten_filled"):
            why.append("flatten/lock closed; ticker gone from venue positions")
        if cluster.get("status_unknown"):
            why.append("status unknown — ask Paul")
        if cluster.get("postponed"):
            why.append("B/tape said postponed but venue position list has no row")
        if cluster.get("paul_settled") or cluster.get("gemini_settled"):
            why.append("settled / not on a live venue book")
        if not why:
            why.append("not on Kalshi or Polymarket US position lists")
        view = cluster_bet_view(cluster, fills_index)
        pnl = money(cluster.get("realized")) if not cluster.get("status_unknown") else "status unknown — ask Paul"
        if cluster.get("void"):
            pnl = "void — not a holding"
        out.append([
            view.get("players") or players_game_label(game, str(cluster.get("sport") or "")),
            cluster.get("sport"),
            view.get("bet_for") or UNKNOWN_ASK,
            view.get("bet_against") or UNKNOWN_ASK,
            view.get("venue") or "",
            view.get("qty") or "",
            view.get("prices") or "",
            view.get("times") or "",
            leftover_status(cluster),
            cluster.get("result"),
            pnl,
            "; ".join(why),
        ])
    out.sort(key=lambda row: str(row[0] or ""))
    return out


def ledger_row(cluster: dict) -> list:
    fill_legs = cluster.get("fill_legs") or cluster.get("legs") or []
    venues = " / ".join(str(leg.get("venue") or "") for leg in (cluster.get("legs") or fill_legs)[:6])
    sides = " / ".join(str(leg.get("side") or "") for leg in (cluster.get("legs") or fill_legs)[:6])
    limits = " / ".join(money4(leg.get("limit") or leg.get("cash")) for leg in (cluster.get("legs") or fill_legs)[:6])
    qtys = " / ".join(money4(leg.get("qty")) for leg in fill_legs[:6]) if fill_legs else "0"
    prices = " / ".join(money4(leg.get("cash")) for leg in fill_legs[:6])
    fees = " / ".join(fee_cell_text(leg) for leg in fill_legs[:6])
    afters = " / ".join(after_fee_text(leg) for leg in fill_legs[:6])
    http = " | ".join(str(leg.get("http_line") or "") for leg in (cluster.get("legs") or [])[:6])
    full = "yes" if cluster.get("intent") == INTENT_FULL_LOCK or (cluster.get("b_t0_both") and cluster.get("complementary")) else "no"
    leftover_intent = (
        "leftover extra (B)" if cluster.get("is_b") or cluster.get("system_letter") == "B"
        else "leftover lock (A)"
    )
    intent_short = {
        INTENT_FULL_LOCK: "yes lock",
        INTENT_INCOMPLETE_LOCK: "yes lock incomplete",
        INTENT_B: "yes tennis crossover",
        INTENT_TENNIS: "yes tennis crossover",
        INTENT_CFB: "yes C cfb favorite",
        INTENT_SPREAD: "yes D T0 spread",
        INTENT_DOG: "yes E tennis T0 dog",
        INTENT_LEFTOVER: leftover_intent,
        INTENT_LOCK_MISS: "yes lock miss",
    }.get(cluster.get("intent"), cluster.get("intent"))
    leftover_txt = cluster.get("leftover_flag") or leftover_status(cluster)
    pnl = cluster.get("realized")
    if cluster.get("void"):
        pnl_txt = "void — not a holding"
    elif cluster.get("postponed") and not cluster.get("venue_paid"):
        pnl_txt = "postponed — not settled"
    elif cluster.get("open_legs") and not cluster_is_settled(cluster):
        pnl_txt = f"open {money4_dollar(cluster.get('open_cost'))} at risk"
    elif cluster.get("status_unknown"):
        pnl_txt = "unknown — ask"
    else:
        pnl_txt = money(pnl)
        if cluster.get("wins") or cluster.get("losses"):
            pnl_txt += f" ({'win' if (cluster.get('wins') or 0) >= (cluster.get('losses') or 0) else 'loss'})"
    notes = "; ".join(cluster.get("notes") or [])
    if cluster.get("winner"):
        notes = (notes + f"; winner {cluster.get('winner')}").strip("; ")
    if cluster.get("postponed"):
        notes = (notes + "; postponed (not settled)").strip("; ")
    return [
        f"{cluster.get('system_letter') or system_of(cluster)} {cluster.get('system_name') or ''}".strip(),
        cluster.get("system_role") or system_role(cluster),
        order_types.cluster_types(cluster) or "—",
        cluster.get("game") or "",
        cluster.get("sport") or "",
        cluster.get("league") or league_of(cluster),
        cluster.get("market") or "",
        cluster.get("side") or "",
        cluster.get("number") or "",
        intent_short,
        leftover_txt,
        cluster.get("hold_class") or hold_class_of(cluster),
        full,
        fmt_et(cluster.get("start")),
        cluster.get("n_attempts") or 0,
        venues,
        sides,
        limits,
        qtys,
        prices,
        fees,
        afters,
        http,
        cluster.get("result") or "",
        pnl_txt,
        notes[:500],
    ]


def write_support(stamp_dir: Path, clusters: list[dict], summary: dict) -> None:
    stamp_dir.mkdir(parents=True, exist_ok=True)
    (stamp_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    slim = []
    for cluster in clusters:
        slim.append({
            "game": cluster.get("game"),
            "sport": cluster.get("sport"),
            "league": cluster.get("league") or league_of(cluster),
            "market": cluster.get("market"),
            "side": cluster.get("side"),
            "number": cluster.get("number"),
            "intent": cluster.get("intent"),
            "system_letter": cluster.get("system_letter") or system_of(cluster),
            "system_role": cluster.get("system_role") or system_role(cluster),
            "result": cluster.get("result"),
            "start": fmt_et(cluster.get("start")),
            "n_attempts": cluster.get("n_attempts"),
            "realized": str(cluster.get("realized")),
            "open_cost": str(cluster.get("open_cost")),
            "n_fill_legs": cluster.get("n_fill_legs"),
            "posted": cluster.get("posted"),
            "is_b": cluster.get("is_b"),
        })
    (stamp_dir / "clusters.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    headers = [
        "system", "role", "game", "sport", "league", "market", "side", "line", "intentional", "leftover",
        "venue_class", "full_system", "first_attempt_et", "attempts", "venues", "sides", "limits",
        "fill_qty", "fill_prices", "fees", "after_fee", "http", "result", "pnl", "notes",
    ]
    with (stamp_dir / "ledger.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for cluster in clusters:
            writer.writerow(ledger_row(cluster))


def build_summary(clusters: list[dict], false_sent: list[dict], latch_n: int, kalshi_pos: dict, poly_pos: dict | None = None, open_n: int = 0) -> dict:
    realized = sum((Decimal(str(c.get("realized") or 0)) for c in clusters), Decimal("0"))
    open_mark = sum((Decimal(str(c.get("open_mark") or 0)) for c in clusters), Decimal("0"))
    open_cost = sum((Decimal(str(c.get("open_cost") or 0)) for c in clusters), Decimal("0"))
    n_fills = sum((Decimal(str(c.get("n_fill_qty") or 0)) for c in clusters), Decimal("0"))
    n_true = sum(1 for c in clusters if c.get("intent") == INTENT_FULL_LOCK)
    n_incomplete = sum(1 for c in clusters if c.get("intent") == INTENT_INCOMPLETE_LOCK)
    n_b_t0 = sum(1 for c in clusters if c.get("is_b") and c.get("b_t0_both"))
    n_leftover = sum(1 for c in clusters if c.get("intent") == INTENT_LEFTOVER and c.get("n_fill_legs"))
    return {
        "generated_at": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET"),
        "realized": str(realized),
        "open_mark": str(open_mark),
        "open_cost": str(open_cost),
        "n_fills": n_fills,
        "n_true_locks": n_true,
        "n_incomplete": n_incomplete,
        "n_one_leg_leftovers": n_leftover,
        "n_b_t0s": n_b_t0,
        "false_sent": len(false_sent),
        "latch_events": latch_n,
        "net_max": str(live_lock_orders.NET_MAX),
        "kalshi_positions_n": kalshi_pos.get("n"),
        "kalshi_positions_http": kalshi_pos.get("http"),
        "kalshi_positions_at": kalshi_pos.get("pulled_at"),
        "poly_positions_n": (poly_pos or {}).get("n"),
        "poly_positions_http": (poly_pos or {}).get("http"),
        "poly_positions_at": (poly_pos or {}).get("pulled_at"),
        "still_open_confirmed_n": open_n,
        "n_matched": sum(1 for c in clusters if match_bucket(c) == "matched" and c.get("n_fill_legs")),
        "n_mismatched": sum(1 for c in clusters if match_bucket(c) == "mismatched" and c.get("n_fill_legs")),
        "n_void": sum(1 for c in clusters if match_bucket(c) == "void"),
        "n_unknown": sum(1 for c in clusters if (c.get("hold_class") or hold_class_of(c)) == HOLD_UNKNOWN and c.get("n_fill_legs")),
        "n_never_held_fills": sum(1 for c in clusters if match_bucket(c) == "never held"),
        "novig": "see Novig fills table (qty>=1 on tape)",
        "gemini_book": "Paul paste, 3 resolved tickets",
        "ann_ror": None,
        "ann_ror_note": (
            "Annualized rate of return is not computed from this tape. "
            "The house helper compare_format.ann_ror_from_closed is not in this workspace, "
            "and these are 1-contract prediction tickets held hours (not BRT-slot stock trades), "
            "so applying ((1 + total PnL / (slot cash × N)) ** (365 / avg days held) − 1) × 100 "
            "would require inventing a slot-cash mapping we do not have."
        ),
    }


def io_walk_rows(io_list: list[dict], needles: tuple[str, ...]) -> list[dict]:
    out = []
    for row in io_list:
        if str(row.get("kind") or "") != "order":
            continue
        blob = json.dumps(row.get("request") or {}, default=str) + json.dumps(row.get("response") or {}, default=str)
        blob += str(row.get("venue") or "") + str(_io_instrument(row) or "")
        if not any(n in blob.lower() for n in needles):
            continue
        payload = row.get("response")
        qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
        poly = polymarket_fill(payload) if str(row.get("venue") or "") == "polymarket" and isinstance(payload, dict) else {}
        inner = payload.get("order") if isinstance(payload, dict) and isinstance(payload.get("order"), dict) else (payload if isinstance(payload, dict) else {})
        req = row.get("request") if isinstance(row.get("request"), dict) else {}
        out.append({
            "ts": fmt_et(row.get("timestamp")),
            "venue": row.get("venue"),
            "http": row.get("http_status") or row.get("status"),
            "instrument": _io_instrument(row),
            "order_id": _order_id_of(payload),
            "qty": str(qty),
            "qty_ge_1": qty_is_fill(qty),
            "fill_count": inner.get("fill_count") if isinstance(inner, dict) else None,
            "average_fill_price": inner.get("average_fill_price") if isinstance(inner, dict) else None,
            "req_side": str(req.get("side") or req.get("action") or req.get("intent") or ""),
            "poly_side": poly.get("side") or "",
            "poly_avg": poly.get("avg") or "",
            "poly_cash": poly.get("cash") or "",
            "poly_fee": poly.get("fee") or "",
            "poly_outcome": poly.get("outcome_name") or "",
            "note": live_lock_orders._scrub_public_text(
                live_lock_orders.public_venue_note(payload, "")
            ) if payload is not None else "",
        })
    return out


def mismatch_rows(clusters: list[dict], open_rows: list[dict], kalshi_pos: dict, poly_pos: dict, io_list: list[dict]) -> list[list]:
    """Every tape-vs-venue disagreement on filled clusters, plus named logging diffs."""
    rows = []
    seen: set[str] = set()
    open_inst = {(str(r.get("venue") or "").lower(), str(r.get("instrument") or "")) for r in open_rows}
    kalshi_tickers = set((kalshi_pos.get("by_ticker") or {}))
    poly_slugs = set((poly_pos.get("by_slug") or {}))
    gemini_inst = {str(g["instrument"]).upper() for g in GEMINI_PASTE}

    def add(game, tape, venue, page, flag):
        key = game_norm(f"{game}|{tape}|{venue}|{flag}")
        if key in seen:
            return
        seen.add(key)
        rows.append([game, tape[:280], venue[:280], page[:200], flag])

    add(
        "Ribecai vs Houkes",
        "order_io Kalshi No RIBHOU fill_count 1.00 average_fill_price 0.47 Yes-wire (house No cash 0.53); leftover_watch 0.53; Yes flatten fill_count 0",
        "Paul/Kalshi history: 1 contract, No Ribecai at 0.55, $1 payout, lost. GET positions: 0 RIBHOU rows",
        "one contract, lost -$0.55. 0.47/0.53 is a logging difference, not a second ticket",
        "mismatch (tape price vs venue 0.55)",
    )
    add(
        "Danilova - Liu vs. Beck - Sibai",
        "order_io has Polymarket qty>=1 fills on aec-itfwo-olgdanyuhliu-avabecjizsib-2026-10-22",
        "Paul: no Poly record. Poly GET: 0 rows",
        "void — not a venue holding",
        "void",
    )
    add(
        "Aaron Funk vs. Sergey Petrov",
        "order_io: Yes Funk qty 1 cash 0.40 fee 0.02; Petrov short 0.09; Petrov short 0.92 (two shorts below house fill 1)",
        "Paul Poly history: four tickets (0.54/0.92, 0.42/$1, 0.02/0.03, 0.04/0.06), settled +$0.01. GET: 0 rows",
        "realized +$0.01. 0.09 short nets the two small Petrov tickets. No extra/missing house fill",
        "aligned (history); ticket split vs one 0.09 fill",
    )
    for gem in GEMINI_PASTE:
        add(
            gem["game"],
            f"order_io Gemini fill qty>=1 on {gem['instrument']}",
            f"Paul Gemini book: {gem['buy']} at {gem['buy_price']}, resolved {gem['resolved']} ${gem['payout']}. Novig empty. Not still-open",
            gem["arithmetic"],
            "aligned (Gemini paste = book)",
        )

    for cluster in clusters:
        if not cluster.get("n_fill_legs") and not cluster.get("void"):
            continue
        game = str(cluster.get("game") or "")
        hold = cluster.get("hold_class") or hold_class_of(cluster)
        tape = (
            f"{cluster.get('result')} leftover={leftover_status(cluster)} "
            f"fill_legs={cluster.get('n_fill_legs')} open_legs={cluster.get('open_legs')}"
        )
        venue_bits = []
        held_any = False
        for leg in cluster.get("fill_legs") or []:
            venue = str(leg.get("venue") or "").lower()
            inst = str(leg.get("instrument") or "")
            if venue == "kalshi":
                on = inst in kalshi_tickers
                venue_bits.append(f"Kalshi {inst} {'held' if on else 'not on GET'}")
                held_any = held_any or on
            elif venue == "polymarket":
                on = inst in poly_slugs
                venue_bits.append(f"Poly {inst} {'held' if on else 'not on GET'}")
                held_any = held_any or on
            elif venue == "gemini":
                on = inst.upper() in gemini_inst or any(inst.upper() in g for g in gemini_inst)
                venue_bits.append(f"Gemini {inst} {'in Paul paste (resolved)' if on else 'not in Paul paste'}")
            elif venue == "novig":
                venue_bits.append(
                    f"Novig {inst or 'fill'} qty {money4(leg.get('qty'))} "
                    f"@ {money4(leg.get('cash') or leg.get('limit'))} (no positions helper)"
                )
                if qty_is_fill(leg.get("qty")):
                    held_any = True
        venue_txt = "; ".join(venue_bits) or "no venue instrument"
        page = hold
        flag = None
        if hold == HOLD_VOID:
            flag = "void"
        elif hold == HOLD_PRICE:
            flag = "mismatch (tape price vs venue)"
        elif hold == HOLD_OPEN:
            flag = "aligned (still on venue book)"
        elif hold in {HOLD_SETTLED, HOLD_FLATTEN}:
            flag = "aligned (settled / flatten)"
        elif hold == HOLD_UNKNOWN:
            flag = "mismatch (tape fill, venue empty, no settlement)"
        elif cluster.get("n_fill_legs") and not held_any and not cluster.get("flatten_filled"):
            flag = "mismatch (tape fill, venue empty)"
        if flag and not str(flag).startswith("aligned"):
            add(game, tape, venue_txt, page, flag)
        elif hold == HOLD_PRICE:
            add(game, tape, venue_txt, page, flag)

    for row in open_rows:
        inst = str(row.get("instrument") or "")
        venue = str(row.get("venue") or "").lower()
        related = [
            c for c in clusters
            if any(
                str(leg.get("venue") or "").lower() == venue and str(leg.get("instrument") or "") == inst
                for leg in (c.get("fill_legs") or c.get("legs") or [])
            )
        ]
        if not related:
            add(
                str(row.get("game") or inst),
                "no matching tape cluster with this instrument",
                f"{venue} GET holds {inst}",
                "still open from venue book",
                "mismatch (venue holding not on tape)",
            )
    _ = io_list, open_inst
    rows.sort(key=lambda item: (str(item[4] or ""), str(item[0] or "")))
    return rows


def questions_for_paul(open_rows: list[dict], kalshi_pos: dict, poly_pos: dict, io_list: list[dict], clusters: list[dict] | None = None) -> list[str]:
    """Only remaining gaps. Do not re-ask the six answers Paul already gave."""
    qs = []
    kalshi_n = kalshi_pos.get("n")
    qs.append(
        "Kalshi GET /trade-api/v2/portfolio/positions (existing helper, count_filter=position) is HTTP "
        f"{kalshi_pos.get('http')} with {kalshi_n} market rows at {kalshi_pos.get('pulled_at')}. The 12:04 ET "
        "pull this morning had 2 rows (Rodriguez Taverna Yes 0.35 and Bueno Yes 0.66). This pull is empty. "
        "order_io still has those two Kalshi fills. Did Taverna/Bueno settle on Kalshi, and what was the "
        "payout? If the Kalshi UI still shows them, the GET list is missing a book we cannot invent."
    )
    qs.append(
        "Kalshi leftover Nos on Middle Tennessee vs FIU totals: order_io fill_count 1.00 ask on "
        "KXNCAAFTOTAL-26OCT20MTUFIU-49 (average_fill_price 0.67 Yes-wire) at 19:32 ET, and ask on "
        "KXNCAAFTOTAL-26OCT20MTUFIU-48 (0.72 Yes-wire) at 21:40 ET. Those are different lines/times from "
        "the Gemini Over 48.5 ticket that resolved Yes. GET has 0 Kalshi rows. What did Kalshi history "
        "pay on 48 and 49? We did not fold them into the Gemini $1.00."
    )
    unknown_games = []
    for cluster in clusters or []:
        if not cluster.get("n_fill_legs"):
            continue
        if cluster.get("void") or cluster.get("paul_settled") or cluster.get("gemini_settled"):
            continue
        if cluster.get("flatten_filled") or cluster.get("venue_live"):
            continue
        if cluster.get("status_unknown") or (cluster.get("hold_class") or hold_class_of(cluster)) == HOLD_UNKNOWN:
            game = str(cluster.get("game") or "").strip()
            if game and game not in unknown_games:
                unknown_games.append(game)
    if unknown_games:
        shown = unknown_games[:40]
        extra = "" if len(unknown_games) <= 40 else f" (+{len(unknown_games) - 40} more on the unknown table)"
        qs.append(
            "These tape fills are gone from Kalshi GET and Polymarket US GET, are not in your six answers, "
            "and are not a closed Yes+No flatten on order_io. Settlement P&L is unknown — paste payout / "
            "winner, or say they never held: " + "; ".join(shown) + extra + "."
        )
    qs.append(
        "Urso and Tixhon are still on the fresh Polymarket US GET (expired false). No question on whether "
        "they are open. If either has actually settled on the app since this pull, paste the payout."
    )
    _ = open_rows, poly_pos, io_list
    return qs


def spot_check_html(io_list: list[dict], kalshi_pos: dict, poly_pos: dict) -> str:
    def block(title: str, rows: list[dict], extra: str) -> str:
        body_rows = []
        for r in rows:
            body_rows.append([
                r.get("ts"), r.get("venue"), r.get("http"), r.get("instrument"),
                r.get("req_side") or r.get("poly_side"), r.get("qty"),
                "yes" if r.get("qty_ge_1") else "no",
                r.get("average_fill_price") or r.get("poly_avg"),
                r.get("poly_cash"), r.get("poly_fee"), r.get("poly_outcome"),
                r.get("fill_count"), r.get("order_id"), r.get("note"),
            ])
        headers = [
            ("Time ET", "date"), ("Venue", "text"), ("HTTP", "num"), ("Instrument", "text"),
            ("Side/intent", "text"), ("Qty", "num"), ("House fill qty>=1?", "text"),
            ("Avg / Yes-wire", "num"), ("Poly cash", "num"), ("Fee", "num"),
            ("Outcome", "text"), ("fill_count", "text"), ("Order id", "text"), ("Note", "text"),
        ]
        return (
            f"<h3>{esc(title)}</h3><p class=\"note\">{esc(extra)}</p>"
            + table(headers, body_rows)
        )
    parts = []
    rib = io_walk_rows(io_list, ("ribhou", "micrib", "ribecai", "houkes"))
    parts.append(block(
        "Ribecai vs Houkes — venue truth",
        rib,
        "Venue/Paul: 1 contract, No Ribecai vs Houkes at 0.55, $1 payout, lost (realized -$0.55). "
        "order_io: one Kalshi fill_count 1.00 ask on RIBHOU, average_fill_price 0.47 Yes-wire "
        "(house No cash 0.53). Yes flatten fill_count 0. Tape 0.47/0.53 is a logging difference, "
        "not a second contract. Kalshi GET: 0 RIBHOU rows.",
    ))
    urso = io_walk_rows(io_list, ("ursaur", "pobane", "urso", "poborilova"))
    poly_u = (poly_pos.get("by_slug") or {}).get("aec-utr-ursaur-pobane-2026-10-20") or {}
    parts.append(block(
        "Aurora Urso vs Aneta Poborilova — still on Poly GET",
        urso,
        "Paul: 0.08 and 0.12 are dollars paid on the 0.10 and 0.15 Yes Urso tickets. "
        "order_io: Yes Urso qty 0.10 avg 0.78 (0.10×0.78=0.078≈0.08); Yes Urso qty 0.15 avg 0.79 "
        "(0.15×0.79=0.1185≈0.12); Yes Poborilova BUY_SHORT qty 1 avg 0.77 cash 0.23 fee 0.01. "
        "Fresh Poly GET: "
        f"outcome {poly_u.get('outcome')} net {poly_u.get('net')} bought {poly_u.get('qty_bought')} "
        f"sold {poly_u.get('qty_sold')} avgPx {poly_u.get('avg_px')} cost {poly_u.get('cost')} "
        f"mark {poly_u.get('cash_value')} expired={poly_u.get('expired')}. Still open. P&L unknown.",
    ))
    dan = io_walk_rows(io_list, ("olgdanyuhliu", "avabecjizsib", "danilova", "sibai"))
    parts.append(block(
        "Danilova-Liu vs Beck-Sibai — void",
        dan,
        "Paul: no Polymarket record. Mark tape fills void / not a venue holding. Poly GET: 0 rows. "
        "No invented P&L.",
    ))
    funk = io_walk_rows(io_list, ("aarfun", "serpet", "funk", "petrov"))
    parts.append(block(
        "Aaron Funk vs Sergey Petrov — Paul history +$0.01",
        funk,
        "Paul tickets: petrov 0.54 to win 0.92; funk 0.42 to win $1; petrov 0.02 to win 0.03; "
        "petrov 0.04 to win 0.06; settled for 0.01 win. order_io: Funk qty 1 cash 0.40 fee 0.02 "
        "(=0.42, matches); Petrov short 0.92 cash 0.57 (~0.54 paid, matches 0.54 to win 0.92); "
        "Petrov short 0.09 cash 0.61 (0.03+0.06=0.09 — the two small tickets as one fill). "
        "No extra house fill. No missing house fill. Realized +$0.01. Poly GET: 0 rows.",
    ))
    gem = io_walk_rows(io_list, (
        "gemi-ncaaf-2610202300-mtn-fiu-t-o48",
        "gemi-nhl-2610190000-car-cgy-m-cgy",
        "gemi-mlb-2610180000-tb-cle-m-tb",
    ))
    parts.append(block(
        "Gemini paste (the Gemini book) vs order_io",
        gem,
        "Paul: Novig empty. Gemini three, all resolved Yes $1.00. order_io qty>=1 matches all three "
        "instruments (TB avgExecutionPrice 0.97, CGY 0.99, MTN-FIU 0.44). Arithmetic: $1.00 minus "
        "Buy Yes = +$0.03 / +$0.01 / +$0.56. Gemini $1 counted once. Kalshi No 48/49 on MTN-FIU are "
        "separate leftover fills, not this $1. Not still-open (resolved).",
    ))
    tix = io_walk_rows(io_list, ("davtix", "carcor", "tixhon", "cordoba"))
    poly_t = (poly_pos.get("by_slug") or {}).get("aec-itfme-davtix-carcor-2026-10-21") or {}
    parts.append(block(
        "David Tixhon vs Carles Cordoba — still on Poly GET",
        tix,
        "Fresh Poly GET: "
        f"outcome {poly_t.get('outcome')} net {poly_t.get('net')} bought {poly_t.get('qty_bought')} "
        f"sold {poly_t.get('qty_sold')} avgPx {poly_t.get('avg_px')} cost {poly_t.get('cost')} "
        f"mark {poly_t.get('cash_value')} expired={poly_t.get('expired')}. "
        "order_io: Yes Tixhon qty 0.10 at 0.13 (below house fill 1); BUY_SHORT Cordoba qty 1 avg 0.12 "
        "cash 0.88. Still open. P&L unknown.",
    ))
    tav = io_walk_rows(io_list, ("rodbue", "taverna", "kxatpchallengermatch-26oct21rodbue"))
    parts.append(block(
        "Rodriguez Taverna vs Bueno — Kalshi GET now empty",
        tav,
        "order_io: Kalshi Yes Taverna 0.35 and Yes Bueno 0.66 (qty 1 each). 12:04 ET GET had both. "
        "This pull: 0 Kalshi rows. Paul did not settle this one. P&L unknown — ask.",
    ))
    cui = io_walk_rows(io_list, ("cuiyib", "jiecui", "yibwu"))
    parts.append(block(
        "Cui vs Wu — closed flatten",
        cui,
        "Kalshi GET: 0 CUIYIB rows. order_io: No Cui fill_count 1.00 average_fill_price 0.49, then "
        "Yes flatten fill_count 1.00 average_fill_price 0.43. Yes+No on the same ticker, gone from "
        "positions: no leftover. Realized from those two fills (not invented).",
    ))
    wolff = io_walk_rows(io_list, ("vivwol", "steweb", "wolff", "webb"))
    parts.append(block(
        "Vivian Wolff vs Stefani Webb — not on apps",
        wolff,
        "Paul: not still on the apps. Poly GET: 0 rows. Tape had qty>=1. Removed from still-open. "
        "Settlement P&L unknown — ask.",
    ))
    mac = io_walk_rows(io_list, ("mackha", "machac", "khachanov"))
    parts.append(block(
        "Machac vs Khachanov — not on apps",
        mac,
        "Paul: not still on the apps. Kalshi GET: 0 MACKHA rows. Several Kalshi fills on MAC and KHA. "
        "Removed from still-open. P&L only if a same-ticker Yes+No flatten is complete; otherwise unknown.",
    ))
    _ = kalshi_pos
    return "\n".join(parts)


def cluster_is_settled(cluster: dict) -> bool:
    """Venue-paid / final / expired / void / flatten. Postponed is not settled."""
    if cluster.get("void"):
        return True
    if cluster.get("postponed") and not cluster.get("venue_paid") and not cluster.get("void"):
        return False
    # B T0 Yes+No on one Polymarket slug is a lock, not a settled match.
    if (
        cluster.get("b_t0_both")
        and not cluster.get("market_final")
        and not cluster.get("flatten_filled")
        and not cluster.get("void")
    ):
        return False
    if cluster.get("flatten_filled") or cluster.get("paul_settled") or cluster.get("gemini_settled"):
        return True
    if cluster.get("venue_paid") or cluster.get("market_final"):
        return True
    return int(cluster.get("settled_legs") or 0) > 0


def filled_trade_clusters(clusters: list[dict]) -> list[dict]:
    return [c for c in clusters if int(c.get("n_fill_legs") or 0) >= 1 and not c.get("void")]


def in_window(cluster: dict, start: datetime | None, end: datetime | None) -> bool:
    when = cluster_when(cluster)
    if when is None:
        return start is None
    if start is not None and when < start:
        return False
    if end is not None and when >= end:
        return False
    return True


def ann_ror_cells(metrics: dict) -> tuple[str, str, str, str]:
    """Full / IS / OOS Ann ROR. Same-day contracts omit the house formula."""
    note = (
        "Annualized rate of return is omitted: these are same-day 1-contract prediction tickets "
        "(held hours, not BRT-slot stocks). compare_format.ann_ror_from_closed needs avg days held "
        f">= {MIN_DAYS_FOR_ANN:g} and a slot-cash mapping we will not invent. IS cut is entry_date "
        f"< {IS_CUT}; this tape is all 2026 so IS N=0 / n/a. OOS is the whole window."
    )
    avg_days = metrics.get("avg_days")
    omit = avg_days is None or float(avg_days) < MIN_DAYS_FOR_ANN
    if omit:
        reason = note
        if avg_days is not None:
            reason = (
                f"Ann ROR omitted — avg days held {float(avg_days):.4f} "
                f"(same-day contracts; house compare_format.ann_ror_from_closed would explode "
                f"on a near-zero hold). IS n/a (all 2026). OOS = this window."
            )
        return "omitted (same-day)", "n/a — no IS (tape is 2026)", "omitted (same-day)", reason
    try:
        ann = ann_ror_from_closed(
            total_pnl=float(metrics["realized"]),
            n_trades=int(metrics["n_settled"] or metrics["n"]),
            avg_days_held=float(avg_days),
            brt_cash=float(metrics.get("slot_cash") or 1),
        )
    except (OverflowError, ValueError, ZeroDivisionError):
        ann = None
    if ann is None:
        return "n/a", "n/a — no IS (tape is 2026)", "n/a", note
    txt = f"{ann:.2f}%"
    return txt, "n/a — no IS (tape is 2026)", txt, (
        "House compare_format.ann_ror_from_closed. Slot cash = median fill cost with fees. "
        f"IS cut {IS_CUT}; this tape is 2026 so IS is empty."
    )


def window_metrics(clusters: list[dict], *, start: datetime | None = None, end: datetime | None = None) -> dict:
    picked = [c for c in filled_trade_clusters(clusters) if in_window(c, start, end)]
    realized = sum((Decimal(str(c.get("realized") or 0)) for c in picked), Decimal("0"))
    fees = sum((Decimal(str(c.get("fees") or 0)) for c in picked), Decimal("0"))
    open_cost = sum((Decimal(str(c.get("open_cost") or 0)) for c in picked), Decimal("0"))
    wins = sum(int(c.get("wins") or 0) for c in picked)
    losses = sum(int(c.get("losses") or 0) for c in picked)
    decided = wins + losses
    settled = [c for c in picked if cluster_is_settled(c)]
    settled_pnl = [Decimal(str(c.get("realized") or 0)) for c in settled]
    mean = (sum(settled_pnl, Decimal("0")) / Decimal(len(settled_pnl))) if settled_pnl else None
    win_pnls = [p for p in settled_pnl if p > 0]
    loss_pnls = [p for p in settled_pnl if p < 0]
    pf = None
    if loss_pnls:
        pf = (sum(win_pnls, Decimal("0")) / abs(sum(loss_pnls, Decimal("0")))) if sum(loss_pnls, Decimal("0")) != 0 else None
    elif win_pnls:
        pf = Decimal("inf")
    wr = (Decimal(wins) / Decimal(decided) * Decimal(100)) if decided else None
    true_locks = sum(1 for c in picked if (c.get("system_letter") or system_of(c)) == "A" and c.get("intent") == INTENT_FULL_LOCK)
    leftovers = sum(1 for c in picked if str(c.get("leftover_flag") or leftover_status(c)) == LEFTOVER_YES)
    costs = []
    for c in picked:
        for leg in c.get("fill_legs") or []:
            try:
                cash = Decimal(str(leg.get("cash") or 0)) * Decimal(str(leg.get("qty") or 0))
                fee = Decimal(str(leg.get("fee") or 0))
                costs.append(cash + fee)
            except Exception:
                continue
    slot_cash = (sum(costs) / Decimal(len(costs))) if costs else Decimal("1")
    # Same-day: we do not have a reliable hold-day series on this tape.
    avg_days = Decimal("0")
    return {
        "n": len(picked),
        "n_settled": len(settled),
        "realized": realized,
        "fees": fees,
        "open_cost": open_cost,
        "wins": wins,
        "losses": losses,
        "wr": wr,
        "mean": mean,
        "pf": pf,
        "true_locks": true_locks,
        "leftovers": leftovers,
        "avg_days": avg_days,
        "slot_cash": slot_cash,
        "clusters": picked,
    }


def fmt_pct(value) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"
    except Exception:
        return str(value)


def fmt_pf(value) -> str:
    if value is None:
        return "n/a"
    if value == Decimal("inf"):
        return "inf (no losses)"
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def metrics_row(label: str, window_label: str, from_et: str, metrics: dict) -> list:
    ann_full, ann_is, ann_oos, _note = ann_ror_cells(metrics)
    return [
        label,
        window_label,
        from_et,
        metrics["n"],
        metrics["n_settled"],
        metrics["wins"],
        metrics["losses"],
        fmt_pct(metrics["wr"]),
        format_money(metrics["realized"]),
        format_money(metrics["mean"]) if metrics["mean"] is not None else "n/a",
        money4_dollar(metrics["open_cost"]),
        money4_dollar(metrics["fees"]),
        metrics["true_locks"],
        metrics["leftovers"],
        fmt_pf(metrics["pf"]),
        ann_full,
        ann_is,
        ann_oos,
    ]


def find_novig_fills(clusters: list[dict]) -> list[dict]:
    found = []
    for cluster in clusters:
        for leg in cluster.get("fill_legs") or cluster.get("legs") or []:
            if str(leg.get("venue") or "").lower() != "novig":
                continue
            if not qty_is_fill(leg.get("qty")):
                continue
            found.append({
                "when": parse_dt(leg.get("sent_at")) or cluster_when(cluster),
                "game": cluster.get("game") or "",
                "side": leg.get("player") or cluster.get("side") or "",
                "book": leg.get("side") or "yes",
                "price": leg.get("cash") or leg.get("limit"),
                "qty": leg.get("qty"),
                "system": cluster.get("system_letter") or system_of(cluster),
                "system_name": cluster.get("system_name") or "",
                "step": leg.get("step") or "",
            })
    found.sort(key=lambda row: row.get("when") or datetime.max.replace(tzinfo=ET))
    return found


def systems_snapshot() -> dict:
    try:
        import prediction_systems as ps

        cfg = ps.load_config()
        blob = load_json(ps.CONFIG_PATH) or {}
        return {
            "updated_at": parse_dt(blob.get("updated_at")),
            "rows": {sid: node.as_dict() for sid, node in cfg.items()},
        }
    except Exception:
        return {"updated_at": None, "rows": {}}


def changelog_events(clusters: list[dict], novig_fills: list[dict]) -> list[dict]:
    events = []
    for row in CHANGELOG_STAMPS:
        when = parse_dt(row["when"])
        if when is None:
            continue
        events.append({**row, "when": when})
    if novig_fills:
        first = novig_fills[0]
        events.append({
            "when": first["when"],
            "what": (
                f"First Novig fill: {first.get('game')} "
                f"{str(first.get('book') or 'Yes').capitalize()} {first.get('side')} "
                f"at {money4(first.get('price'))}, qty {money4(first.get('qty'))}, "
                f"system {first.get('system')} {first.get('system_name')}".strip()
            ),
            "systems": (first.get("system") or "C",),
            "source": "order_io.jsonl qty>=1 FILLED + orders.jsonl sent",
        })
    snap = systems_snapshot()
    updated = snap.get("updated_at")
    rows = snap.get("rows") or {}
    if updated and rows:
        bits = []
        for sid, letter in (("lock", "A"), ("tennis_crossover", "B"), ("cfb_favorite", "C"), ("spread_t0", "D")):
            node = rows.get(sid) or {}
            bits.append(f"{letter} max_open={node.get('max_open')} on={node.get('on')}")
        events.append({
            "when": updated,
            "what": "systems.json MAX_OPEN / on / stake snapshot: " + "; ".join(bits),
            "systems": ("A", "B", "C", "D"),
            "source": f"systems.json updated_at {fmt_et(updated)}",
        })
    events.sort(key=lambda row: row["when"] or datetime.max.replace(tzinfo=ET))
    # D=0.25 was live from B's first send and never moved (HTML stamps say unchanged).
    first_b = None
    for cluster in filled_trade_clusters(clusters):
        if (cluster.get("system_letter") or system_of(cluster)) != "B":
            continue
        when = cluster_when(cluster)
        if when and (first_b is None or when < first_b):
            first_b = when
    if first_b is not None:
        events.append({
            "when": first_b,
            "what": "D=0.25 extra-pair lock live on Tennis crossover (unchanged freeze; not a later retune)",
            "systems": ("B",),
            "source": "live_strategy_b.py D=0.25; first B fill on tape; later HTML stamps say D stays 0.25",
        })
    events.sort(key=lambda row: row["when"] or datetime.max.replace(tzinfo=ET))
    return events


def last_change_for(letter: str, events: list[dict]) -> dict | None:
    """Latest sourced freeze/code/bugfix for this system.

    The live systems.json snapshot is listed in the changelog (MAX_OPEN / on / stake)
    but is not used as the 'since last freeze' cut — it is a config write, often after
    the last fill, and would zero the window.
    """
    hits = [
        e for e in events
        if letter in (e.get("systems") or ())
        and "systems.json MAX_OPEN" not in str(e.get("what") or "")
    ]
    return hits[-1] if hits else None


def extra_open_from_unsettled(clusters: list[dict], open_rows: list[dict]) -> list[dict]:
    """Novig fills, plus live B T0, when the market is not final. C/D empty GET is not automatically open."""
    seen = {(str(r.get("venue") or "").lower(), str(r.get("instrument") or "").lower()) for r in open_rows}
    extra = []
    for cluster in filled_trade_clusters(clusters):
        b_t0_live = (
            bool(cluster.get("b_t0_both"))
            and not cluster.get("market_final")
            and not cluster.get("flatten_filled")
            and not cluster.get("void")
        )
        if cluster.get("flatten_filled") or cluster.get("void"):
            continue
        if cluster.get("venue_live") and not b_t0_live:
            continue
        if cluster_is_settled(cluster):
            continue
        if cluster.get("postponed") and not cluster.get("venue_live"):
            continue
        letter = cluster.get("system_letter") or system_of(cluster)
        for leg in cluster.get("fill_legs") or []:
            venue = str(leg.get("venue") or "").lower()
            inst = str(leg.get("instrument") or "")
            key = (venue, inst.lower())
            if key in seen:
                continue
            if venue != "novig" and not (b_t0_live and venue == "polymarket"):
                continue
            try:
                cost = (Decimal(str(leg.get("cash") or 0)) * Decimal(str(leg.get("qty") or 0))) + Decimal(str(leg.get("fee") or 0))
            except Exception:
                cost = Decimal("0")
            extra.append({
                "game": cluster.get("game") or "",
                "sport": cluster.get("sport") or "",
                "league": cluster.get("league") or league_of(cluster),
                "system": letter,
                "players": players_game_label(str(cluster.get("game") or ""), str(cluster.get("sport") or "")),
                "bet_for": kitchen_side_label(leg, cluster),
                "bet_against": "directional Yes (C/D)" if letter in {"C", "D"} else "unpaired / not on GET",
                "venue": venue,
                "instrument": inst,
                "confirmed": f"qty {money4(leg.get('qty'))} @ {money4(leg.get('cash') or leg.get('limit'))} cost {money4_dollar(cost)}",
                "position": str(leg.get("qty") or ""),
                "exposure": str(cost),
                "postponed": "yes" if cluster.get("postponed") else "no",
                "leftover": cluster.get("leftover_flag") or leftover_status(cluster),
                "source": (
                    "B T0 Yes+No on one Polymarket slug; market not final — unique-game overlay"
                    if b_t0_live and venue == "polymarket"
                    else "Novig fill qty>=1; no positions helper; market not final — unique-game overlay"
                ),
                "tape": f"{cluster.get('intent')} / {cluster.get('result')}",
            })
            seen.add(key)
    return extra


def overlay_open_rows(
    kalshi_pos: dict,
    poly_pos: dict,
    clusters: list[dict],
    market_index: dict | None = None,
) -> list[dict]:
    """Unique-game open overlay matching job_status Positions."""
    rows = still_open_from_venue(kalshi_pos, poly_pos, clusters, market_index)
    try:
        import job_status_positions
        import open_count_sync

        snap = open_count_sync._read_cache() or {}
        if not snap.get("kalshi_by_ticker") and not snap.get("poly_by_slug"):
            snap = {
                **open_count_sync.empty_snapshot(),
                "kalshi_ok": bool(kalshi_pos.get("ok")),
                "poly_ok": bool(poly_pos.get("ok")),
                "kalshi": [
                    {"venue": "kalshi", "ticker": r.get("ticker"), "qty": r.get("position"), "title": r.get("ticker")}
                    for r in (kalshi_pos.get("rows") or [])
                ],
                "kalshi_by_ticker": {
                    t: {"ticker": t, "qty": r.get("position")}
                    for t, r in (kalshi_pos.get("by_ticker") or {}).items()
                },
                "poly": [
                    {"venue": "polymarket", "ticker": r.get("slug"), "qty": r.get("net"), "title": r.get("title")}
                    for r in (poly_pos.get("rows") or [])
                ],
                "poly_by_slug": {
                    s: {"ticker": s, "qty": r.get("net")}
                    for s, r in (poly_pos.get("by_slug") or {}).items()
                },
            }
        watches = {sid: open_count_sync.load_watch(sid) for sid in open_count_sync.WATCH}
        tape = open_count_sync.load_tape_index()
        bundle = job_status_positions.build_rows(
            snap, fetch_quotes=False, fetch_titles=True, watches=watches, tape=tape,
        )
        seen = {(str(r.get("venue") or "").lower(), str(r.get("instrument") or "").lower()) for r in rows}
        by_key = {key: row for key, row in ((
            (str(r.get("venue") or "").lower(), str(r.get("instrument") or "").lower()), r
        ) for r in rows)}
        for item in bundle.get("rows") or []:
            letter = str(item.get("letter") or "")
            game = str(item.get("game") or item.get("name") or "")
            sport = str(item.get("sport") or "")
            for leg in item.get("legs") or [item]:
                venue = str(leg.get("venue") or "").lower()
                inst = str(leg.get("ticker") or item.get("ticker") or "")
                key = (venue, inst.lower())
                if not venue or not inst:
                    continue
                if key in by_key:
                    existing = by_key[key]
                    if letter == "A" or sport == "pro football":
                        if letter:
                            existing["system"] = letter
                            existing["open_type"] = item.get("open_type") or order_types.open_now_type(letter)
                        if sport:
                            existing["sport"] = sport
                            existing["players"] = players_game_label(
                                str(existing.get("game") or game), sport
                            )
                        if game and (
                            "tennis" in str(existing.get("players") or "").lower()
                            or not existing.get("game")
                        ):
                            existing["game"] = game
                            existing["players"] = players_game_label(game, existing.get("sport") or sport)
                    continue
                info = (market_index or {}).get(key) or (market_index or {}).get(inst.lower())
                if settlement_is_final(info, venue=venue):
                    continue
                cost = leg.get("cost") or item.get("cost") or 0
                rows.append({
                    "game": game,
                    "sport": sport,
                    "league": league_from_instrument(inst),
                    "system": letter,
                    "open_type": item.get("open_type") or order_types.open_now_type(letter),
                    "players": players_game_label(game, sport),
                    "bet_for": _overlay_bet_for(item, leg, inst),
                    "who_pays": item.get("who_pays") or "",
                    "bet_against": "Positions overlay",
                    "venue": venue,
                    "instrument": inst,
                    "confirmed": item.get("qty_text") or str(leg.get("qty") or ""),
                    "position": str(leg.get("qty") or item.get("qty_text") or ""),
                    "exposure": str(cost),
                    "postponed": "no",
                    "leftover": "",
                    "source": "job_status Positions overlay",
                    "tape": "",
                })
                seen.add(key)
                by_key[key] = rows[-1]
    except Exception as exc:
        print(f"positions overlay {type(exc).__name__}", flush=True)
    rows.extend(extra_open_from_unsettled(clusters, rows))
    return rows


def by_system_html(clusters: list[dict], open_rows: list[dict]) -> str:
    filled = filled_trade_clusters(clusters)
    novig_fills = find_novig_fills(clusters)
    events = changelog_events(clusters, novig_fills)
    by_letter: dict[str, list[dict]] = {letter: [] for letter, *_ in SYSTEM_SPECS}
    for cluster in filled:
        letter = cluster.get("system_letter") or system_of(cluster)
        by_letter.setdefault(letter, []).append(cluster)

    window_headers = [
        ("System", "text"),
        ("Window", "text"),
        ("From ET", "date"),
        ("N filled", "num"),
        ("N settled", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win %", "num"),
        ("Net P&L with fees $", "num"),
        ("Mean $", "num"),
        ("Open at risk $", "num"),
        ("Fees $", "num"),
        ("True locks", "num"),
        ("Leftover", "num"),
        ("Profit factor", "num"),
        ("Ann ROR full", "text"),
        ("Ann ROR IS", "text"),
        ("Ann ROR OOS", "text"),
    ]
    window_rows = []
    inception_times: dict[str, datetime | None] = {}
    last_events: dict[str, dict | None] = {}
    for letter, _sid, name, code in SYSTEM_SPECS:
        group = by_letter.get(letter) or []
        first = None
        for cluster in group:
            when = cluster_when(cluster)
            if when and (first is None or when < first):
                first = when
        if first is None and letter in {"C", "D"}:
            first = parse_dt("2026-10-24T15:02:00-04:00")
        inception_times[letter] = first
        last = last_change_for(letter, events)
        last_events[letter] = last
        label = f"{letter} {name}"
        inc = window_metrics(group)
        window_rows.append(metrics_row(
            label,
            "inception → now",
            fmt_et(first) if first else "no fill yet (could-trade stamp below)",
            inc,
        ))
        since_start = last["when"] if last else first
        since = window_metrics(group, start=since_start)
        last_label = (last["what"][:72] + "…") if last and len(last["what"]) > 72 else (last["what"] if last else "no sourced freeze")
        window_rows.append(metrics_row(
            label,
            f"since last freeze ({last_label})" if last else "since last freeze (none sourced)",
            fmt_et(since_start) if since_start else "",
            since,
        ))
    window_rows.append(metrics_row("Combined A–D", "inception → now", "first fill on tape", window_metrics(filled)))
    last_any = None
    for event in events:
        if "systems.json MAX_OPEN" in str(event.get("what") or ""):
            continue
        last_any = event
    window_rows.append(metrics_row(
        "Combined A–D",
        "since last freeze (any system)",
        fmt_et(last_any["when"]) if last_any else "",
        window_metrics(filled, start=last_any["when"] if last_any else None),
    ))

    change_headers = [
        ("When ET", "date"),
        ("What changed", "text"),
        ("Systems", "text"),
        ("Source", "text"),
        ("N from here → now", "num"),
        ("Net P&L with fees $ → now", "num"),
        ("Win % → now", "num"),
        ("Mean $ → now", "num"),
        ("Until next: N", "num"),
        ("Until next: P&L with fees $", "num"),
        ("Until next: WR", "num"),
        ("Until next: mean $", "num"),
    ]
    change_rows = []
    for i, event in enumerate(events):
        nxt = events[i + 1]["when"] if i + 1 < len(events) else None
        letters = tuple(event.get("systems") or ())
        scope = [c for c in filled if (c.get("system_letter") or system_of(c)) in letters] if letters else filled
        forward = window_metrics(scope, start=event["when"])
        interval = window_metrics(scope, start=event["when"], end=nxt)
        change_rows.append([
            fmt_et(event["when"]),
            event["what"],
            ", ".join(letters),
            event.get("source") or "",
            forward["n"],
            format_money(forward["realized"]),
            fmt_pct(forward["wr"]),
            format_money(forward["mean"]) if forward["mean"] is not None else "n/a",
            interval["n"],
            format_money(interval["realized"]),
            fmt_pct(interval["wr"]),
            format_money(interval["mean"]) if interval["mean"] is not None else "n/a",
        ])

    open_by = {letter: Decimal("0") for letter, *_ in SYSTEM_SPECS}
    for row in open_rows:
        letter = str(row.get("system") or "")
        if letter not in open_by:
            continue
        try:
            open_by[letter] += Decimal(str(row.get("exposure") or 0))
        except Exception:
            pass
    open_games_n = {letter: 0 for letter, *_ in SYSTEM_SPECS}
    seen_games = {letter: set() for letter, *_ in SYSTEM_SPECS}
    for row in open_rows:
        letter = str(row.get("system") or "")
        if letter not in seen_games:
            continue
        key = game_norm(str(row.get("game") or row.get("instrument") or ""))
        if key and key in seen_games[letter]:
            continue
        if key:
            seen_games[letter].add(key)
        open_games_n[letter] += 1
    open_headers = [
        ("System", "text"),
        ("Open games (Positions overlay)", "num"),
        ("Exposure / cost $", "num"),
    ]
    open_sys_rows = [
        [f"{letter} {name}", open_games_n[letter], money4_dollar(open_by[letter])]
        for letter, _sid, name, _code in SYSTEM_SPECS
    ]
    open_total = [
        "Combined",
        sum(open_games_n.values()),
        money4_dollar(sum(open_by.values(), Decimal("0"))),
    ]

    novig_rows = []
    for i, row in enumerate(novig_fills):
        novig_rows.append([
            "first" if i == 0 else str(i + 1),
            fmt_et(row.get("when")),
            row.get("game"),
            f"{str(row.get('book') or 'Yes').capitalize()} {row.get('side')}",
            money4(row.get("price")),
            money4(row.get("qty")),
            f"{row.get('system')} {row.get('system_name')}".strip(),
            row.get("step"),
        ])
    if not novig_rows:
        novig_rows.append(["none", "", "No Novig fill with qty >= 1 on this tape", "", "", "", "", ""])

    unattributed = [
        "Git on live_*.py / write_orders_performance.py / prediction_job_control.py is only the 2026-10-18 17:51 dump. Later freezes are from HTML Written lines, file mtimes, systems.json updated_at, and the tape — not git hashes.",
        "D=0.25 never moved after B went live (stamps say unchanged). Listed as a freeze, not a retune.",
        "Skip-absorbed-B: moutet page at 13:07 ET 23 Oct says it was already in live_lock_orders. Add-date before that stamp is not sourced.",
        "MAX_OPEN_B was 2 on strategy_b_novig_20261023.html (08:29 ET 23 Oct) and is 4 in live_strategy_b.py / systems.json now. The 2→4 edit is not in git; nearest sourced times are the 23 Oct HTML freeze and the 24 Oct 18:02 systems.json write.",
        "C_LO is still the 0.95 constant in live_strategy_b.py; live send ignores that floor (in_c_band uses C_HI only). Wired stamp is 24 Oct 13:16 ET.",
        "Venue post-order confirm for lock-bot Novig fills existed before B Novig (08:29 ET 23 Oct page). B stacked-T0 confirm qty ≥ 1 is in the 24 Oct 13:16 stamp.",
    ]
    first_novig = novig_fills[0] if novig_fills else None
    congrats = ""
    if first_novig:
        congrats = (
            f" First Novig purchase on the tape: {first_novig.get('game')}, "
            f"{str(first_novig.get('book') or 'Yes').capitalize()} {first_novig.get('side')} "
            f"at {money4(first_novig.get('price'))}, system {first_novig.get('system')} "
            f"{first_novig.get('system_name')} at {fmt_et(first_novig.get('when'))}. Congratulations."
        )
    _ann = ann_ror_cells(window_metrics(filled))[3]
    return f"""
<h2>Performance by system</h2>
<p class="note">Kitchen book. Primary P&amp;L is <strong>with fees</strong>.
Each system has two windows: inception (first confirmed fill, or C/D could-trade at the 15:02 ET 24 Oct CLI stamp)
and since the last sourced freeze / code change / bug fix that affected that system.
{_ann} Click column headers to sort.</p>
<p class="note"><strong>Settled</strong> means the venue already paid, voided, expired, or marked the market final
(fill-history quantity is the ticket truth). An empty Polymarket positions GET does not drop a confirmed fill
while the market is still OPEN. Settled / expired / final / void never count as open.
<strong>Open at risk</strong> is unique games with venue-confirmed quantity still unsettled — the same overlay
as job_status Positions. A postponed match is labeled postponed (open if still on the book, void if cancelled),
never settled. After-fee dollars use at least four decimals.</p>
<p class="note">{esc(congrats.strip() or "No Novig fill with quantity at least 1 is on this tape yet.")}</p>
{table(window_headers, window_rows)}

<h2>Freeze / code / bug-fix changelog (P&amp;L after each)</h2>
<p class="note">Timestamp Eastern Time. N / net P&amp;L with fees / win rate / mean $ from that timestamp forward
on the affected system(s), and the same figures until the next listed change. Dates are HTML Written lines,
systems.json updated_at, or the live tape. Git does not date the later edits.</p>
{table(change_headers, change_rows)}
<ul>
{''.join(f'<li>{esc(item)}</li>' for item in unattributed)}
</ul>

<h2>Open exposure by system</h2>
<p class="note">Same unique-game overlay as job_status Positions: Kalshi qty ≥ 1, Polymarket qty &gt; 0,
plus a confirmed Poly fill when the positions GET is empty <em>and</em> the market is still OPEN.
Settled / expired / final / void never count. Click headers to sort.</p>
{table(open_headers, open_sys_rows, total=open_total)}

<h2>Novig fills</h2>
<p class="note">House fill = order_io / venue qty ≥ 1. First row is the first Novig purchase on this tape.</p>
{table(
    [("Rank", "text"), ("When ET", "date"), ("Game", "text"), ("Side", "text"),
     ("Price $", "num"), ("Qty", "num"), ("System", "text"), ("Step", "text")],
    novig_rows,
)}
"""


def write_html(
    clusters: list[dict],
    ghosts: list[dict],
    summary: dict,
    false_sent: list[dict],
    kalshi_pos: dict,
    latch_n: int,
    poly_pos: dict | None = None,
    open_rows: list[dict] | None = None,
    io_list: list[dict] | None = None,
    fills_index: dict | None = None,
) -> str:
    sports = sport_stats(clusters + ghosts)
    intents = intent_stats(clusters)
    venues = venue_stats(clusters)
    by_system = by_system_html(clusters, open_rows or [])
    novig_fills = find_novig_fills(clusters)
    first_novig = novig_fills[0] if novig_fills else None
    plain_txt = PLAIN
    if first_novig:
        plain_txt += (
            f" First Novig purchase on this tape: {first_novig.get('game')}, "
            f"{str(first_novig.get('book') or 'Yes').capitalize()} {first_novig.get('side')} "
            f"at {money4(first_novig.get('price'))}, system {first_novig.get('system')} "
            f"{first_novig.get('system_name')} at {fmt_et(first_novig.get('when'))}. Congratulations."
        )
    else:
        plain_txt += " No Novig fill with quantity at least 1 is on this tape yet — we are not guessing."
    posted = [
        c for c in clusters
        if (c.get("n_fill_legs") or 0) >= 1 or str(c.get("result") or "").startswith("flatten")
    ]
    posted.sort(key=lambda c: (str(c.get("game") or ""), c.get("start") or datetime.max.replace(tzinfo=ET)))
    empty_posted = [
        c for c in clusters
        if c.get("posted") and not c.get("n_fill_legs") and c.get("intent") == INTENT_LOCK_MISS
    ]
    empty_groups: dict[tuple, dict] = {}
    for cluster in empty_posted:
        key = (
            cluster.get("sport") or "",
            cluster.get("game") or "",
            cluster.get("market") or "",
            cluster.get("side") or "",
            str(cluster.get("number") or ""),
        )
        slot = empty_groups.get(key)
        if slot is None:
            slot = dict(cluster)
            slot["n_attempts"] = 0
            empty_groups[key] = slot
        slot["n_attempts"] += int(cluster.get("n_attempts") or 1)
        start = cluster.get("start")
        if start and (slot.get("start") is None or start < slot["start"]):
            slot["start"] = start
    empty_rows = sorted(empty_groups.values(), key=lambda c: str(c.get("game") or ""))
    ghosts.sort(key=lambda c: (str(c.get("game") or ""), -(c.get("n_attempts") or 0)))

    sport_rows = []
    for sport, slot in sorted(sports.items()):
        sport_rows.append([
            sport,
            money(slot["realized"]),
            money(slot["open_cost"]),
            slot["fills"],
            slot["full_locks"],
            slot["incomplete"],
            slot["b"],
            slot["leftover"],
            slot["ghosts"],
        ])
    intent_rows = []
    order = [
        INTENT_FULL_LOCK, INTENT_INCOMPLETE_LOCK, INTENT_TENNIS, INTENT_B,
        INTENT_CFB, INTENT_SPREAD, INTENT_DOG, INTENT_LEFTOVER, INTENT_LOCK_MISS,
    ]
    for name in order:
        slot = intents.get(name) or {"n": 0, "realized": Decimal("0"), "open_cost": Decimal("0"), "fills": 0}
        intent_rows.append([name, slot["n"], money(slot["realized"]), money(slot["open_cost"]), slot["fills"]])
    venue_rows = []
    for venue, slot in sorted(venues.items()):
        venue_rows.append([
            venue,
            money4(slot["fills"]),
            money(slot["fees"]),
            money(slot["realized"]),
            money(slot["open_cost"]),
            slot["n_sends"],
            slot["n_empty_201"],
        ])
    grand_rows = [[
        "all tape",
        money(summary["realized"]),
        money(summary["open_cost"]),
        summary["n_fills"],
        summary.get("n_matched"),
        summary.get("n_mismatched"),
        summary.get("n_void"),
        summary.get("n_unknown"),
        summary["n_true_locks"],
        summary["n_one_leg_leftovers"],
        summary["n_b_t0s"],
        summary["false_sent"],
        latch_n,
    ]]
    match_rows = [
        ["fully matched (venue book, Paul history, or closed flatten)", summary.get("n_matched")],
        ["mismatched (tape vs venue, including tape fill / venue empty)", summary.get("n_mismatched")],
        ["void (tape only, not a venue holding)", summary.get("n_void")],
        ["tape fill, venue empty, P&L unknown — ask", summary.get("n_unknown")],
        ["still open (fresh venue GET only)", summary.get("still_open_confirmed_n")],
    ]
    gemini_rows = [
        [
            g["game"],
            g["instrument"],
            g["buy"],
            money4(g["buy_price"]),
            g["resolved"],
            money(g["payout"]),
            g["arithmetic"],
            "resolved — not still-open",
        ]
        for g in GEMINI_PASTE
    ]
    ledger_headers = [
        ("System", "text"),
        ("Role", "text"),
        ("Order type", "text"),
        ("Game", "text"),
        ("Sport", "text"),
        ("League", "text"),
        ("Market", "text"),
        ("Side", "text"),
        ("Line", "num"),
        ("Intentional?", "text"),
        ("Leftover?", "text"),
        ("Venue class", "text"),
        ("Full system both legs?", "text"),
        ("First attempt ET", "date"),
        ("Attempts", "num"),
        ("Venues", "text"),
        ("Sides", "text"),
        ("Limits", "text"),
        ("Fill qty", "text"),
        ("Fill prices (wire)", "text"),
        ("Fees", "text"),
        ("After-fee (all-in)", "text"),
        ("Venue HTTP", "text"),
        ("Result", "text"),
        ("P&L / open", "text"),
        ("Notes", "text"),
    ]
    ghost_headers = [
        ("Game", "text"),
        ("Sport", "text"),
        ("Market", "text"),
        ("Side", "text"),
        ("Line", "num"),
        ("First claim ET", "date"),
        ("Attempts (claims/skips, never posted)", "num"),
        ("Result", "text"),
        ("Notes", "text"),
    ]
    ghost_rows = [
        [
            g.get("game"),
            g.get("sport"),
            g.get("market"),
            g.get("side"),
            g.get("number"),
            fmt_et(g.get("start")),
            g.get("n_attempts"),
            g.get("result"),
            "; ".join(g.get("notes") or [])[:240],
        ]
        for g in ghosts
    ]
    poly_pos = poly_pos or {}
    open_rows = open_rows or []
    io_list = io_list or []
    open_headers = [
        ("System", "text"),
        ("Players / game", "text"),
        ("Sport", "text"),
        ("Bet for", "text"),
        ("Bet against", "text"),
        ("Venue", "text"),
        ("Leftover?", "text"),
        ("Postponed", "text"),
        ("Venue-confirmed holding", "text"),
        ("Source", "text"),
        ("Tape cluster", "text"),
    ]
    removed_headers = [
        ("Players / game", "text"),
        ("Sport", "text"),
        ("Bet for", "text"),
        ("Bet against", "text"),
        ("Venue", "text"),
        ("Qty", "text"),
        ("Prices", "text"),
        ("Times ET", "text"),
        ("Leftover?", "text"),
        ("Tape result", "text"),
        ("P&L", "text"),
        ("Why removed from still-open", "text"),
    ]
    mismatch_headers = [
        ("Game", "text"),
        ("Tape said", "text"),
        ("Venue says", "text"),
        ("This page", "text"),
        ("Flag", "text"),
    ]
    kalshi_rows = [
        [r.get("ticker"), r.get("position"), r.get("exposure"), r.get("fees"), r.get("realized")]
        for r in (kalshi_pos.get("rows") or [])
    ]
    poly_rows = [
        [r.get("title"), r.get("slug"), r.get("outcome"), r.get("net"), r.get("qty_bought"),
         r.get("qty_sold"), r.get("avg_px"), r.get("cost"), r.get("cash_value"), r.get("fees"), r.get("expired")]
        for r in (poly_pos.get("rows") or [])
    ]
    q_list = questions_for_paul(open_rows, kalshi_pos, poly_pos, io_list, clusters)
    q_html = "<ul>" + "".join(f"<li>{esc(q)}</li>" for q in q_list) + "</ul>"
    mismatch = mismatch_rows(clusters, open_rows, kalshi_pos, poly_pos, io_list)
    removed = removed_closed_rows(clusters, open_rows, fills_index or {})
    spot_html = spot_check_html(io_list, kalshi_pos, poly_pos)
    false_rows = [
        [
            r.get("at"),
            r.get("game"),
            r.get("market_type"),
            r.get("side"),
            r.get("number"),
            r.get("decision"),
            str(r.get("reason") or "")[:160],
        ]
        for r in false_sent
    ]
    net_max = str(live_lock_orders.NET_MAX)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live prediction-market orders performance</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 16px; color: #0f172a; background: #fff; }}
h1, h2 {{ color: #1e293b; }}
.ask, .plain, .def, .q {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 16px; margin: 12px 0; }}
.q {{ border-color: #c4b5fd; background: #f5f3ff; }}
.note {{ color: #475569; font-size: 14px; }}
.updated {{ font-size: 1.1rem; margin: 0.25rem 0 1rem; }}
code {{ font-size: 13px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Live prediction-market orders performance</h1>
<p class="updated"><strong>Updated {esc(summary['generated_at'])}</strong> (Eastern Time)</p>
<p class="note">Tape through the local lock-bot + Tennis crossover / C / D / E files on this PC. Does not place or sell tickets. Click column headers to sort. {report_page_extras.SWIPE_NOTE_HTML.replace('<p class="swipe-note">', '').replace('</p>', '')}</p>
<p class="note">True both-sides locks only (Yes on one venue + No on the other, not leftover/flatten): <a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a>.</p>

<div class="ask">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="plain">
<h2>In plain English</h2>
<p>{esc(plain_txt)}</p>
</div>
{by_system}
<div class="def">
<h2>What leftover and no leftover mean</h2>
<ul>
<li><strong>Leftover:</strong> we hold one side of a lock or Tennis crossover pair and never got the hedge. Cash is at risk on that one side. Lock leftover/flatten stays on <strong>A</strong> (lock-bot). Extra Yes after a B miss stays on <strong>B</strong>.</li>
<li><strong>No leftover:</strong> both legs of that intended pair filled, or we flattened the holding, or we never held (claim/skip only, or IOC with fill quantity 0). This is not a mystery label — it means the pair is complete, gone, or was never on the book. C and D are one-way Yes, so leftover does not apply.</li>
</ul>
<p>The leftover nickel on a completed lock is locked profit, not leftover risk. Dual-Yes is Tennis crossover's pair, not a lock-bot Yes+No lock.</p>
</div>
<div class="def">
<h2>What “intentional” means on this page</h2>
<ul>
<li><strong>Intentional lock (full system):</strong> the lock-bot meant Yes on one venue + No on the other for the same settlement, posted both legs, and <strong>both filled quantity at least 1</strong>. That is a true lock.</li>
<li><strong>Intentional lock, incomplete:</strong> the lock-bot posted aiming at a lock but only one leg filled. Still an intentional order, not a full system. That is leftover until flattened or the venue book is empty.</li>
<li><strong>Intentional Tennis crossover (was Strategy B):</strong> T0 both-Yes (and later extra/cross/favorite per the B playbook).</li>
<li><strong>C College football favorite / D T0 spreads:</strong> one directional Yes at T0. Not a lock leftover.</li>
<li><strong>Leftover-watch on an E/C/D ticket:</strong> lock-bot A hedge after a one-leg miss, not an E Tennis T0 dog. Kitchen Type is leftover / hedge (A leftover). Polymarket tennis BUY_SHORT that pays if that player wins is Yes that player, same as B T0 Poly.</li>
<li><strong>Leftover (not the intended pair):</strong> extra Yes stacked on the same player, extra after a miss, or an unpaired T0 dog — still system B if it came from Tennis crossover, system A if it came from the lock bot.</li>
</ul>
<p><strong>Fill rule:</strong> a fill is <code>order_io</code> <code>filled_contracts &gt;= 1</code>, or a venue position. HTTP 201 with <code>fill_count 0</code> is an empty cancel, not a fill. Opportunities “sent” / “both legs filled” without order_io qty &gt;= 1 are not trades. orders.jsonl <code>filled</code> with no matching order_io qty is not a fill.</p>
<p><strong>Still open rule:</strong> unique games with venue-confirmed quantity still unsettled — the same overlay as job_status Positions. An empty Polymarket positions GET does not drop a confirmed fill while the market is still OPEN. Settled / expired / final / void never count as open. A postponed match is labeled postponed (open if still on the book, void if the venue cancelled it), never settled. Gemini paste tickets are resolved. Closed / void / flattened games leave Still open even if the diary still says leftover.</p>
</div>
<div class="q">
<h2>Questions for Paul</h2>
<p class="note">No guesses. The six answers he already gave are recorded as venue truth and are not re-asked. These are the remaining gaps.</p>
{q_html}
</div>

<h2>Ledger vs venue (filled clusters)</h2>
<p class="note">Matched = venue book, Paul confirmed history, or a closed Yes+No flatten on order_io. Mismatched = tape said one thing and the venue book / settlement says another, including tape fills that are gone from every live book with no settlement. Void = Danilova tape fills Paul said never existed on Poly. Click headers to sort.</p>
{table(
    [("Bucket", "text"), ("N clusters", "num")],
    match_rows,
)}

<h2>Grand totals</h2>
<p class="note">Cash P&amp;L is settled only (venue settlement or Paul history, or a closed flatten). Open cash at risk is still-open tickets and is not mixed into realized. Unknown P&amp;L is not invented and is not in realized. House dollars.</p>
{table(
    [("Slice", "text"), ("Realized $", "num"), ("Open cash at risk $", "num"), ("N fills (qty>=1)", "num"),
     ("Matched", "num"), ("Mismatched", "num"), ("Void", "num"), ("Unknown P&L", "num"),
     ("True locks", "num"), ("One-leg leftovers", "num"), ("B T0s", "num"), ("False sent", "num"), ("Latch events", "num")],
    grand_rows,
)}

<h2>By sport</h2>
{table(
    [("Sport", "text"), ("Realized $", "num"), ("Open cash at risk $", "num"), ("N fills", "num"),
     ("Full-system locks", "num"), ("Incomplete locks", "num"), ("Tennis crossover", "num"),
     ("Not intentional leftover", "num"), ("Ghost never-posted clusters", "num")],
    sport_rows,
)}

<h2>By intent</h2>
{table(
    [("Intent", "text"), ("N clusters", "num"), ("Realized $", "num"), ("Open cash at risk $", "num"), ("N fills", "num")],
    intent_rows,
)}

<h2>By venue</h2>
<p class="note">Filled contracts and fees from the saved order response. Realized dollars are the cluster P&amp;L shared across filled legs of that cluster (not a second formula). Empty 200/201 is fill quantity 0.</p>
{table(
    [("Venue", "text"), ("Filled contracts", "num"), ("Fees $", "num"), ("Realized $ (share)", "num"),
     ("Open cost $", "num"), ("Sends", "num"), ("Empty 200/201", "num")],
    venue_rows,
)}

<h2>Still open (fresh venue book only)</h2>
<p class="note">Kalshi GET this job: {esc(kalshi_pos.get('n'))} rows at {esc(kalshi_pos.get('pulled_at'))} (HTTP {esc(kalshi_pos.get('http'))}). Polymarket US GET: {esc(poly_pos.get('n'))} rows at {esc(poly_pos.get('pulled_at'))} (HTTP {esc(poly_pos.get('http'))}, eof {esc(poly_pos.get('eof'))}). Unsettled Novig fills are listed by system even without a Novig positions helper. Gemini paste is resolved, not open. Bet for is the side we bought. Click headers to sort.</p>
{table(open_headers, open_risk_rows(open_rows))}

<h2>Gemini book (Paul paste — resolved, not still-open)</h2>
<p class="note">No Gemini positions helper in the modules we already use. Paul pasted these three. order_io has a qty&gt;=1 fill on each instrument. Arithmetic is Resolved Yes $1.00 minus Buy Yes cost. Gemini $1 is counted once; a Kalshi No on a different line is not folded into that $1.</p>
{table(
    [("Game", "text"), ("Instrument", "text"), ("Buy", "text"), ("Buy $", "num"),
     ("Resolved", "text"), ("Payout $", "num"), ("Arithmetic", "text"), ("Open?", "text")],
    gemini_rows,
)}

<h2>Removed from still-open (closed, flattened, void, or not on a venue book)</h2>
<p class="note">These had tape fills or a prior still-open row. They are not on the current Kalshi or Polymarket US position lists. One row per filled cluster so Gemini Over 48.5 and a Kalshi leftover No on the same game stay separate. <strong>Players / game</strong> is both names (sport in parentheses). <strong>Bet for</strong> is the side we bought (player or team + Yes/No) from venue fill history or the order response. <strong>Bet against</strong> is the hedge if both legs filled, or “unpaired leftover / extra Yes” if Strategy B extra / one-leg. Names are not invented: unknown cells say ask Paul. Qty / prices / times prefer the stamp’s Kalshi/Gemini/Poly fill-history pull, then order_io. P&amp;L is shown only from venue settlement, Paul history, or a closed Yes+No flatten on order_io. Otherwise: unknown — ask. Click headers to sort.</p>
{table(removed_headers, removed)}

<h2>Mismatch (tape said X, venue says Y)</h2>
<p class="note">Every filled cluster with a tape-vs-venue disagreement, plus the named logging diffs Paul already answered. Aligned Gemini/Funk history rows are listed so the walk is complete; sort Flag to group mismatches. Click headers to sort.</p>
{table(mismatch_headers, mismatch)}

<h2>Spot-check walk-throughs (times ET)</h2>
<p class="note">Every row is an order_io HTTP post. House fill means qty &gt;= 1. Partial Polymarket sizes are listed because the venue still nets them.</p>
{spot_html}

<h2>Helpful extras</h2>
<ul>
<li><strong>Send cap path:</strong> after-fee send line moved 0.95 → 0.97 → 0.98 → 0.984. Live <code>NET_MAX</code> now is {esc(net_max)}.</li>
<li><strong>False sent (not trades):</strong> {esc(summary['false_sent'])} Sam Houston 9.5 diary rows at 22:42 / 22:58 with no <code>order_io</code> HTTP. Do not count as P&amp;L.</li>
<li><strong>Latch:</strong> {esc(latch_n)} <code>orders_off</code> events on the tape. Strategy B is independent of that latch.</li>
<li><strong>Annualized rate of return (Ann ROR):</strong> {esc(summary['ann_ror_note'])}</li>
<li><strong>Kalshi open positions</strong> (existing GET <code>/trade-api/v2/portfolio/positions</code>, amounts only): HTTP {esc(kalshi_pos.get('http'))}, pulled {esc(kalshi_pos.get('pulled_at'))}, {esc(kalshi_pos.get('n'))} market rows.</li>
<li><strong>Polymarket US open positions</strong> (existing <code>signed_json</code> GET <code>/v1/portfolio/positions</code>): HTTP {esc(poly_pos.get('http'))}, pulled {esc(poly_pos.get('pulled_at'))}, {esc(poly_pos.get('n'))} market rows, eof {esc(poly_pos.get('eof'))}.</li>
<li><strong>Novig:</strong> see the Novig fills table. No positions helper; fills are order_io qty ≥ 1.</li>
<li><strong>Gemini:</strong> no positions-list helper. Paul's paste is the book: three resolved Yes $1.00 tickets matched to order_io fills. Arithmetic $1.00 − Buy Yes. Not still-open.</li>
<li>Did not place GTC, sell, flatten, or start a second Strategy B.</li>
</ul>

<h2>Kalshi positions (amounts only)</h2>
{table(
    [("Ticker", "text"), ("Position", "num"), ("Exposure $", "num"), ("Fees paid $", "num"), ("Realized $", "num")],
    kalshi_rows,
)}

<h2>Polymarket US positions (amounts only)</h2>
{table(
    [("Title", "text"), ("Slug", "text"), ("Outcome", "text"), ("Net", "num"), ("Qty bought", "num"),
     ("Qty sold", "num"), ("Avg px", "num"), ("Cost $", "num"), ("Mark $", "num"), ("Fees $", "num"), ("Expired", "text")],
    poly_rows,
)}

<h2>False sent diary rows (not trades)</h2>
{table(
    [("When", "date"), ("Game", "text"), ("Market", "text"), ("Side", "text"), ("Line", "num"), ("Decision", "text"), ("Reason", "text")],
    false_rows,
)}

<h2>Game-by-game ledger</h2>
<p class="note">One row per trade/attempt cluster. Game is the sticky first column. League is from the catalog ticker or slug (ATP / WTA / Challenger / ITF / CFB / NFL) — not invented. Full system means both legs filled quantity at least 1 on a complementary pair. New Mexico State vs Sam Houston ghost claims are in the next table so attempt counts stay honest. Click headers to sort. Swipe sideways to see more columns.</p>
{table(ledger_headers, [ledger_row(c) for c in posted])}

<h2>Posted but both unfilled (IOC empty)</h2>
<p class="note">These claims did post at least one immediate-or-cancel (IOC) order, but fill quantity was 0 (Kalshi HTTP 201 fill_count 0, Gemini cancelled / no part filled). Grouped by game and line so attempt counts stay honest. Not trades and not P&amp;L.</p>
{table(ghost_headers, [
    [g.get("game"), g.get("sport"), g.get("market"), g.get("side"), g.get("number"), fmt_et(g.get("start")), g.get("n_attempts"), g.get("result"), "posted IOC, fill 0"]
    for g in empty_rows
])}

<h2>Never posted (ghost claims / claim+skip)</h2>
<p class="note">These claims never produced an <code>order_io</code> post. NMSU vs Sam Houston 22:42 and 22:58 SHSU 9.5 false diary rows are also not trades. Attempt count is claims plus skips in that market/line cluster.</p>
{table(ghost_headers, ghost_rows)}

<p class="note">Data: <code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw/orders.jsonl</code>, <code>order_io.jsonl</code>, <code>strategy_b_watch.json</code>, <code>cfb_favorite_watch.json</code>, <code>spread_t0_watch.json</code>, <code>one_leg_watch.json</code>, settlements cache. Opportunities/considerations used only as a false-sent cross-check. Live jobs rewrite this page after a confirmed fill or a closed trade (settle / flatten / void / final, debounced), including C/D/E. Manual rerun: <code>python tools/write_orders_performance.py</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    return report_page_extras.inject_report_page_extras(page)


def main() -> int:
    print("loading tape", flush=True)
    orders = _load_jsonl(ORDERS)
    io_all = _load_jsonl(RAW / "order_io.jsonl")
    by_id, io_list = io_indexes(io_all)
    watch = load_json(B_WATCH) or {}
    considerations = load_considerations()
    settlements = load_settlements()
    latch_n = sum(1 for row in orders if row.get("event") == "orders_off")
    false_sent = false_sent_rows(considerations, io_list)
    print(f"orders {len(orders)} io {len(io_list)} settlements {len(settlements)}", flush=True)

    lock_raw = cluster_lock_attempts(orders)
    b_raw = cluster_b_attempts(orders, watch)
    cfb_watch = load_json(RAW / "cfb_favorite_watch.json") or {}
    spread_watch = load_json(RAW / "spread_t0_watch.json") or {}
    cfb_raw = cluster_directional_attempts(orders, cfb_watch, kind="cfb_favorite", prefix="cfb-favorite")
    spread_raw = cluster_directional_attempts(orders, spread_watch, kind="spread_t0", prefix="spread-t0")
    dog_watch = load_json(RAW / "tennis_t0_dog_watch.json") or {}
    dog_raw = cluster_directional_attempts(orders, dog_watch, kind="tennis_t0_dog", prefix="tennis-t0-dog")
    f_watch = load_json(RAW / "tennis_t0_spread_watch.json") or {}
    f_raw = cluster_directional_attempts(orders, f_watch, kind="tennis_t0_spread", prefix="tennis-t0-spread")
    g_watch = load_json(RAW / "soccer_t0_total_watch.json") or {}
    g_raw = cluster_directional_attempts(orders, g_watch, kind="soccer_t0_total", prefix="soccer-t0-total")
    print(
        f"lock clusters {len(lock_raw)} B clusters {len(b_raw)} "
        f"C clusters {len(cfb_raw)} D clusters {len(spread_raw)} E clusters {len(dog_raw)} "
        f"F clusters {len(f_raw)} G clusters {len(g_raw)}",
        flush=True,
    )

    print("fetching Kalshi + Polymarket US positions (existing helpers, amounts only)", flush=True)
    kalshi_pos = fetch_kalshi_amounts(force=True)
    poly_pos = fetch_polymarket_positions()
    venue_index = venue_index_of(kalshi_pos, poly_pos)
    print(
        f"kalshi http {kalshi_pos.get('http')} n={kalshi_pos.get('n')} "
        f"poly http {poly_pos.get('http')} n={poly_pos.get('n')}",
        flush=True,
    )

    lock_enriched = [enrich_cluster(c, by_id, io_list) for c in lock_raw]
    b_enriched = []
    for cluster in b_raw:
        enrich_cluster(cluster, by_id, io_list)
        b_enriched.extend(split_b_extras(cluster))
    cd_enriched = [enrich_cluster(c, by_id, io_list) for c in cfb_raw + spread_raw + dog_raw + f_raw + g_raw]
    ghosts = ghost_clusters(lock_enriched)
    posted_lock = [c for c in lock_enriched if c.get("posted") or c.get("n_fill_legs")]
    pending = posted_lock + b_enriched + cd_enriched
    settlements = backfill_venue_settlements(pending, settlements, fetch=True)
    market_index = market_index_of(settlements)
    print(f"settlements after backfill {len(settlements)}", flush=True)
    scored = [score_cluster(c, settlements, venue_index, market_index) for c in pending]
    flipped = scan_postponed_but_settled(scored, settlements)
    if flipped:
        print(f"postponed-but-settled flipped n={len(flipped)}", flush=True)
        for hit in flipped[:20]:
            print(f"  settled {hit.get('game')} was {hit.get('reason')} now {hit.get('result')}", flush=True)
    net_closed_same_ticker(scored, venue_index, io_list)
    attach_orphan_gemini(scored, io_list)
    apply_paul_history(scored, io_list)
    try:
        import settled_pnl_store

        n_fee = settled_pnl_store.enrich_fill_fees(scored)
        if n_fee:
            print(f"enriched poly fees n={n_fee}", flush=True)
    except Exception:
        pass
    restrict_realized(scored, settlements)
    stamp_ticket_pnl(scored, settlements)
    persist_settled_pnl(scored, settlements, source="tape_rebuild")
    for cluster in scored:
        cluster["league"] = league_of(cluster)
        cluster["leftover_flag"] = leftover_status(cluster)
        cluster["hold_class"] = hold_class_of(cluster)
        assign_system(cluster)
    for cluster in ghosts:
        cluster["league"] = league_of(cluster)
        assign_system(cluster)
    open_rows = overlay_open_rows(kalshi_pos, poly_pos, scored, market_index)
    apply_overlay_live_flags(scored, open_rows)
    clones = same_slug_cloned_prices(scored)
    if clones:
        print(f"same-slug cloned prices n={len(clones)} {clones[:8]}", flush=True)
    fills_index = load_venue_fill_index()
    print(f"venue fill-history keys {len(fills_index)} from {VENUE_FILL_PULL.name}", flush=True)
    summary = build_summary(scored, false_sent, latch_n, kalshi_pos, poly_pos, len(open_rows))
    write_support(STAMP_DIR, scored + ghosts, summary)
    html = write_html(
        scored, ghosts, summary, false_sent, kalshi_pos, latch_n,
        poly_pos=poly_pos, open_rows=open_rows, io_list=io_list,
        fills_index=fills_index,
    )
    PAGE.write_text(html, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    try:
        import write_dashboard

        write_dashboard.write_from_performance(scored, open_rows, summary=summary)
    except Exception as exc:
        import traceback

        print(f"dashboard {type(exc).__name__}", flush=True)
        traceback.print_exc()
    filled_n = len(filled_trade_clusters(scored))
    settled_n = sum(1 for c in filled_trade_clusters(scored) if cluster_is_settled(c))
    print(
        "totals realized", summary["realized"],
        "open", summary["open_cost"],
        "n_filled", filled_n,
        "n_settled", settled_n,
        "open_overlay", len(open_rows),
        "true_locks", summary["n_true_locks"],
        "leftover", summary["n_one_leg_leftovers"],
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
