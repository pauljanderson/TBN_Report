"""One same-side midpoint limit. Does not flip ORDERS_ENABLED and does not touch the supervisor.

Buys one contract when a same-outcome ask is at least 10 cents under the next venue
and the buy book shows size of at least 1. Immediate-or-cancel at the midpoint,
rounded down. One accepted attempt, then stop.
"""
from __future__ import annotations

import html
import json
import sys
import time
import traceback
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
sys.path.insert(0, str(STAMP))

import cheaper_same_bet  # noqa: E402
import overnight_scan as scan  # noqa: E402
import polymarket_us_live  # noqa: E402
import price_memory  # noqa: E402
import report_page_extras  # noqa: E402
import venue_pace  # noqa: E402

ET = ZoneInfo("America/New_York")
JOBS = RAW / "live_jobs"
PAGE = STAMP / "cheaper_mid_test.html"
STATE_PATH = RAW / "cheaper_mid_state.json"
WATCH_LOG = RAW / "cheaper_mid_watch.log"
DEADLINE = datetime(2026, 10, 19, 8, 0, tzinfo=ET)
CENT = Decimal("0.01")
SIZE = Decimal("1")
CLOSED = {"closed", "settled", "determined", "finalized", "inactive"}

ASKED = (
    "let's try a test on cheaper same bet. let's continue to monitor this and when we find a cheaper bet "
    "that is in the 10 cents or more bucket, let's put in a limit order at the midway point between the "
    "platform we are buying it on, and the next highest platform. we only do this once, until we get it to "
    "work and see if it moves up in price"
)


def log(text: str) -> None:
    line = datetime.now(ET).isoformat(timespec="seconds") + " " + text
    print(line, flush=True)
    RAW.mkdir(parents=True, exist_ok=True)
    with WATCH_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_state() -> dict:
    if not STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def jobs() -> list[dict]:
    found = []
    if not JOBS.is_dir():
        return found
    for path in JOBS.glob("*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


_TICKER_CACHE: dict[str, tuple[list[str], list[str]]] | None = None


def saved_tickers(game: str) -> tuple[list[str], list[str]]:
    """Event tickers from the catalog's saved book files. Prices in those files are not used."""
    global _TICKER_CACHE
    want = (game or "").strip().lower()
    if not want:
        return [], []
    if _TICKER_CACHE is None:
        found: dict[str, tuple[list[str], list[str]]] = {}
        for path in list(RAW.glob("*_kalshi.json")) + list(RAW.glob("*_gemini.json")):
            try:
                head = path.read_text(encoding="utf-8")[:600]
            except OSError:
                continue
            marker = '"game": "'
            if marker not in head:
                continue
            title = head.split(marker, 1)[1].split('"', 1)[0].strip().lower()
            if not title:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            kalshi, gemini = found.get(title, ([], []))
            kalshi, gemini = list(kalshi), list(gemini)
            for event in payload.get("events") or []:
                if not isinstance(event, dict):
                    continue
                ticker = str(event.get("event_ticker") or event.get("ticker") or "")
                if not ticker:
                    continue
                if path.name.endswith("_kalshi.json"):
                    kalshi.append(ticker)
                else:
                    gemini.append(ticker)
            found[title] = (list(dict.fromkeys(kalshi)), list(dict.fromkeys(gemini)))
        _TICKER_CACHE = found
    return _TICKER_CACHE.get(want, ([], []))


def job_for(sport: str, game: str, listed: list[dict]) -> dict | None:
    want_s = (sport or "").strip().lower()
    want_g = (game or "").strip().lower()
    for job in listed:
        title = str(job.get("title") or "").strip().lower()
        js = str(job.get("sport") or "").strip().lower()
        if title == want_g and js == want_s:
            return job
    return None


def as_size(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def money(value) -> str:
    if value is None:
        return ""
    return format(Decimal(str(value)).quantize(Decimal("0.0001")), "f")


def fresh_legs(sport: str, game: str, kalshi_events, gemini_events, poly_contracts) -> list[dict]:
    """Sized asks only. Gemini No is omitted when the stamp marks it as not a real offer."""
    nick = cheaper_same_bet.nickname_maps()
    mapping = nick.get((sport, game), {})
    legs = []

    def add(kind, side_raw, number, venue, pay, price, size, instrument, intent, event_ticker):
        if price is None or size is None or size < SIZE:
            return
        if price <= 0 or price >= 1:
            return
        if not instrument:
            return
        kind = str(kind or "")
        if kind not in ("moneyline", "spread", "total"):
            return
        side = price_memory.norm_side(str(side_raw or ""), kind)
        if kind in ("moneyline", "spread"):
            side = mapping.get(side, side)
        outcome = cheaper_same_bet._outcome(kind, side, pay)
        if outcome is None:
            return
        label, pay_used = outcome
        legs.append({
            "sport": sport,
            "game": game,
            "market_type": kind,
            "side": label,
            "number": price_memory.norm_number(number) if kind != "moneyline" else "",
            "pay": pay_used,
            "venue": venue,
            "price": price,
            "size": size,
            "instrument": instrument,
            "intent": intent or "",
            "event_ticker": event_ticker or "",
        })

    for source, events, venue in (("kalshi", kalshi_events or [], "Kalshi"), ("gemini", gemini_events or [], "Gemini")):
        for event in events or []:
            if not isinstance(event, dict):
                continue
            event_ticker = str(event.get("ticker") or event.get("event_ticker") or "")
            kind_hint = scan.market_type_from_ticker(event_ticker)
            for raw in event.get("contracts") or []:
                if not isinstance(raw, dict):
                    continue
                view = scan.contract_view(raw, kind_hint, source)
                if not view:
                    continue
                if str(view.get("status") or "").lower() in CLOSED:
                    continue
                yes_size = as_size(view.get("yes_size"))
                no_size = as_size(view.get("no_size"))
                add(view.get("kind"), view.get("side"), view.get("number"), venue, "yes", view.get("yes"), yes_size, str(view.get("ident") or ""), "", event_ticker)
                if source == "gemini" and view.get("no_reject"):
                    continue
                add(view.get("kind"), view.get("side"), view.get("number"), venue, "no", view.get("no"), no_size, str(view.get("ident") or ""), "", event_ticker)
    for contract in poly_contracts or []:
        if not isinstance(contract, dict):
            continue
        for view in polymarket_us_live.contract_views(contract):
            yes_size = as_size(view.get("yes_size"))
            no_size = as_size(view.get("no_size"))
            add(
                view.get("kind"), view.get("side"), view.get("number"), "Polymarket", "yes",
                view.get("yes"), yes_size, str(view.get("ident") or ""), str(view.get("poly_yes_intent") or ""), "",
            )
            add(
                view.get("kind"), view.get("side"), view.get("number"), "Polymarket", "no",
                view.get("no"), no_size, str(view.get("ident") or ""), str(view.get("poly_no_intent") or ""), "",
            )
    return legs


def gaps_from_legs(legs: list[dict]) -> list[dict]:
    grouped: dict[tuple, list] = {}
    for leg in legs:
        key = (leg["market_type"], leg["side"], leg["number"], leg["pay"])
        grouped.setdefault(key, []).append(leg)
    found = []
    for key, group in grouped.items():
        by_venue = {}
        for leg in group:
            prev = by_venue.get(leg["venue"])
            if prev is None or leg["price"] < prev["price"]:
                by_venue[leg["venue"]] = leg
        if len(by_venue) < 2:
            continue
        priced = []
        for leg in by_venue.values():
            rounded = leg["price"].quantize(CENT, rounding=ROUND_HALF_UP)
            priced.append((rounded, leg))
        priced.sort(key=lambda item: (item[0], item[1]["venue"]))
        gap = priced[1][0] - priced[0][0]
        gap_cents = int(gap / CENT)
        if gap_cents < 10:
            continue
        cheap, nxt = priced[0][1], priced[1][1]
        mid = (cheap["price"] + nxt["price"]) / 2
        found.append({
            "market_type": key[0],
            "side": key[1],
            "number": key[2],
            "pay": key[3],
            "cheap": cheap,
            "next": nxt,
            "gap_cents": gap_cents,
            "mid": mid,
        })
    found.sort(key=lambda item: -item["gap_cents"])
    return found


def page_games(rows: list[dict]) -> list[tuple[str, str, bool]]:
    """Unique games with a 10-cent page gap, freshest first. The flag is true when Polymarket is one of the two prices."""
    ordered = []
    seen = set()
    ranked = [row for row in rows if row.get("gap_cents", 0) >= 10]
    ranked.sort(key=lambda row: str(row.get("seen") or ""), reverse=True)
    for row in ranked:
        key = (row.get("sport") or "", row.get("game") or "")
        if key in seen or not key[1]:
            continue
        seen.add(key)
        uses_poly = row.get("cheapest") == "Polymarket" or row.get("next") == "Polymarket"
        ordered.append((key[0], key[1], uses_poly))
    return ordered


def load_books(job: dict, want_poly: bool):
    game = job.get("game") if isinstance(job.get("game"), dict) else {}
    k_tickers, g_tickers = scan.tickers_of(game)
    gemini_events = [scan.fetch_gemini_event(ticker) for ticker in g_tickers]
    kalshi_events = [scan.fetch_kalshi_event(ticker) for ticker in k_tickers]
    poly = []
    if want_poly:
        import live_game_pollers
        poly = live_game_pollers._polymarket_contracts(game, scan, kalshi_events, gemini_events)
    return game, kalshi_events, gemini_events, poly


def reload_leg(leg: dict, game: dict) -> dict | None:
    """One more read of the buy instrument. None when the ask or the size is gone."""
    venue = leg["venue"]
    instrument = leg["instrument"]
    pay = leg["pay"]
    if venue == "Kalshi":
        event = scan.fetch_kalshi_event(leg["event_ticker"]) if leg.get("event_ticker") else None
        events = [event] if event else []
        source = "kalshi"
    elif venue == "Gemini":
        event = scan.fetch_gemini_event(leg["event_ticker"]) if leg.get("event_ticker") else None
        events = [event] if event else []
        source = "gemini"
    elif venue == "Polymarket":
        import live_game_pollers
        contracts = live_game_pollers._polymarket_contracts(game, scan, [], [])
        legs = fresh_legs(leg["sport"], leg["game"], [], [], contracts)
        for item in legs:
            if item["venue"] == "Polymarket" and item["instrument"] == instrument and item["pay"] == pay:
                return item
        return None
    else:
        return None
    legs = fresh_legs(leg["sport"], leg["game"], events if source == "kalshi" else [], events if source == "gemini" else [], [])
    for item in legs:
        if item["venue"] == venue and item["instrument"] == instrument and item["pay"] == pay and item["market_type"] == leg["market_type"]:
            if item["number"] == leg["number"] and item["side"] == leg["side"]:
                return item
    return None


def send_ioc(built: dict) -> tuple[int, str]:
    """Venue order call. Does not read or write ORDERS_ENABLED."""
    import gemini_private
    import kalshi_private
    import live_lock_orders

    recorded: dict = {}
    venue = built["venue"]
    body = built["body"]
    if venue == "kalshi":
        status, text = kalshi_private.signed_call("POST", "/trade-api/v2/portfolio/events/orders", body)
        request = body
    elif venue == "gemini":
        status, text = gemini_private.private_call("/v1/prediction-markets/order", body, "POST", record=recorded)
        request = recorded.get("request") or body
    elif venue == "polymarket":
        status, text = polymarket_us_live.signed_json("POST", "/v1/orders", body)
        request = body
    else:
        return 0, "unknown venue"
    live_lock_orders.record_order_io(venue, "order", request, status, text if isinstance(text, str) else json.dumps(text))
    if not isinstance(text, str):
        text = json.dumps(text)
    return status, text


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, num: bool = False) -> str:
    text = "" if value is None else str(value)
    if num:
        return f'<td style="text-align:right">{esc(text)}</td>'
    return f"<td>{esc(text)}</td>"


def write_page(state: dict) -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    rows = list(state.get("samples") or [])
    attempt = state.get("attempt") or {}
    body = []
    order_row = {
        "when": attempt.get("sent_at") or state.get("updated") or "",
        "game": attempt.get("game") or "",
        "market": attempt.get("market_type") or "",
        "side": attempt.get("buy_label") or "",
        "number": attempt.get("number") or "",
        "buy_venue": attempt.get("buy_venue") or "",
        "next_venue": attempt.get("next_venue") or "",
        "buy_price": attempt.get("buy_price") or "",
        "next_price": attempt.get("next_price") or "",
        "gap": attempt.get("gap_cents") if attempt else "",
        "mid": attempt.get("midpoint") or "",
        "limit": attempt.get("limit") or "",
        "result": attempt.get("result") or state.get("status") or "",
        "order_id": attempt.get("order_id") or "",
        "fill_price": attempt.get("fill_price") or "",
        "later_buy": "",
        "later_next": "",
    }
    if attempt:
        body.append(order_row)
    for sample in rows:
        body.append({
            "when": sample.get("at") or "",
            "game": attempt.get("game") or "",
            "market": attempt.get("market_type") or "",
            "side": attempt.get("buy_label") or "",
            "number": attempt.get("number") or "",
            "buy_venue": attempt.get("buy_venue") or "",
            "next_venue": attempt.get("next_venue") or "",
            "buy_price": attempt.get("buy_price") or "",
            "next_price": attempt.get("next_price") or "",
            "gap": attempt.get("gap_cents") if attempt else "",
            "mid": attempt.get("midpoint") or "",
            "limit": attempt.get("limit") or "",
            "result": "later quote",
            "order_id": attempt.get("order_id") or "",
            "fill_price": attempt.get("fill_price") or "",
            "later_buy": sample.get("buy") or "",
            "later_next": sample.get("next") or "",
        })
    if not body:
        body.append({
            "when": now,
            "game": "",
            "market": "",
            "side": "",
            "number": "",
            "buy_venue": "",
            "next_venue": "",
            "buy_price": "",
            "next_price": "",
            "gap": "",
            "mid": "",
            "limit": "",
            "result": state.get("status") or "watching",
            "order_id": "",
            "fill_price": "",
            "later_buy": "",
            "later_next": "",
        })
    html_rows = []
    for row in body:
        html_rows.append(
            "<tr>"
            + td(row["when"])
            + td(row["game"])
            + td(row["market"])
            + td(row["side"])
            + td(row["number"])
            + td(row["buy_venue"])
            + td(row["next_venue"])
            + td(row["buy_price"], True)
            + td(row["next_price"], True)
            + td(row["gap"], True)
            + td(row["mid"], True)
            + td(row["limit"], True)
            + td(row["result"])
            + td(row["order_id"])
            + td(row["fill_price"], True)
            + td(row["later_buy"], True)
            + td(row["later_next"], True)
            + "</tr>"
        )
    note = state.get("note") or ""
    moved = state.get("moved") or ""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cheaper midpoint test</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.6rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.2rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>One midpoint limit on a cheaper same bet</h1>
<p class="note">Written {esc(now)}. One contract, one attempt. Same outcome on two venues. This is not a Yes-plus-No lock.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2>
<p>We watched the same bet on more than one site: same game, same kind of bet, same side, same number. When one site's price to buy that side was at least 10 cents cheaper than the next site, and that cheaper site actually had at least one contract for sale, we sent one buy for a single contract. The limit was halfway between those two prices, rounded so we would not pay more than that halfway point. The order was immediate-or-cancel, so it could take the cheaper price and would not sit on the book. We do this once. If it filled, we kept writing down both sites' prices to see if the cheap site moved up toward the other one.</p>
<p class="note">A Gemini No price that is only one dollar minus the Yes bid, with no size, is not used. Quotes on the monitor page still have to be within 15 minutes of each other, and the newest within 3 hours. The live book is read again before the order.</p>
</div>
<p>{esc(note)}</p>
<p>{esc(moved)}</p>
<p class="note">Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{th("When", "date")}{th("Game", "text")}{th("Market", "text")}{th("Side", "text")}{th("Number", "num")}{th("Buy venue", "text")}{th("Next venue", "text")}{th("Buy price", "num")}{th("Next price", "num")}{th("Gap cents", "num")}{th("Midpoint", "num")}{th("Limit", "num")}{th("Order result", "text")}{th("Order id", "text")}{th("Fill price", "num")}{th("Later buy ask", "num")}{th("Later next ask", "num")}
</tr></thead>
<tbody>
{"".join(html_rows)}
</tbody>
</table>
</div>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(page, encoding="utf-8")


def buy_label(market_type: str, side: str, pay: str) -> str:
    if market_type == "total" and pay == "no":
        return "Under"
    if market_type == "total":
        return "Over"
    return side


def attempt_order(choice: dict, game: dict) -> dict:
    import live_lock_orders

    cheap = choice["cheap"]
    nxt = choice["next"]
    again = reload_leg(cheap, game)
    if again is None:
        log(f"gone before send {cheap['game']} {cheap['market_type']} {cheap['side']} {cheap['number']} no sized ask")
        return {"sent": False, "reason": "sized ask gone before send"}
    mid = (again["price"] + nxt["price"]) / 2
    limit = live_lock_orders.snap_pay(cheap["venue"].lower(), mid)
    if limit is None:
        return {"sent": False, "reason": "midpoint not sendable"}
    if again["price"] > mid or again["price"] > limit:
        log(
            f"do not chase {cheap['game']} ask {money(again['price'])} mid {money(mid)} limit {money(limit)}"
        )
        return {"sent": False, "reason": "ask above midpoint"}
    spec = {
        "venue": cheap["venue"].lower(),
        "instrument": cheap["instrument"],
        "outcome": cheap["pay"],
        "pay": format(limit, "f"),
        "intent": cheap.get("intent") or "",
        "fee_coefficient": None,
    }
    built = live_lock_orders._spec_at_price(spec, limit)
    if built is None:
        return {"sent": False, "reason": "order body not sendable"}
    state = load_state()
    state.update({
        "status": "sending",
        "updated": datetime.now(ET).isoformat(timespec="seconds"),
        "attempt": {
            "game": cheap["game"],
            "sport": cheap["sport"],
            "market_type": cheap["market_type"],
            "side": cheap["side"],
            "buy_label": buy_label(cheap["market_type"], cheap["side"], cheap["pay"]),
            "number": cheap["number"],
            "pay": cheap["pay"],
            "buy_venue": cheap["venue"],
            "next_venue": nxt["venue"],
            "buy_price": money(again["price"]),
            "next_price": money(nxt["price"]),
            "gap_cents": choice["gap_cents"],
            "midpoint": money(mid),
            "limit": built["limit"],
            "instrument": cheap["instrument"],
            "event_ticker": cheap.get("event_ticker") or "",
            "intent": cheap.get("intent") or "",
            "size": money(again["size"]),
            "result": "sending",
        },
    })
    save_state(state)
    log(
        f"send {cheap['venue']} {cheap['instrument']} {cheap['pay']} limit {built['limit']} "
        f"ask {money(again['price'])} next {nxt['venue']} {money(nxt['price'])}"
    )
    status, text = send_ioc(built)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    order_id = live_lock_orders._order_id(payload)
    filled_n = live_lock_orders.filled_contracts(payload) if status in (200, 201) else Decimal("0")
    fill_price = live_lock_orders._execution_price(payload, cheap["pay"]) if status in (200, 201) else ""
    note = live_lock_orders._public_note(text)
    if status in (200, 201) and live_lock_orders.order_still_open(payload) and filled_n < SIZE:
        cancel_status, cancel_note = live_lock_orders._cancel(built, payload)
        log(f"cancel resting http {cancel_status} {cancel_note}")
        filled_n = Decimal("0")
        note = f"{note}; cancel {cancel_status} {cancel_note}"
    filled = filled_n >= SIZE
    result = f"http {status} filled {format(filled_n, 'f')} {note}"
    log(f"result {result} order {order_id} fill_price {fill_price or 'none'}")
    attempt = state["attempt"]
    attempt.update({
        "sent_at": datetime.now(ET).isoformat(timespec="seconds"),
        "http_status": status,
        "order_id": order_id,
        "fill_price": fill_price,
        "filled": filled,
        "result": result,
    })
    state["status"] = "filled" if filled else "attempted"
    state["updated"] = datetime.now(ET).isoformat(timespec="seconds")
    state["note"] = (
        f"One order sent on {cheap['venue']} for {cheap['game']} {cheap['market_type']} "
        f"{attempt['buy_label']} {cheap['number']}. Buy ask {money(again['price'])}, "
        f"next {nxt['venue']} {money(nxt['price'])}, midpoint {money(mid)}, limit {built['limit']}. {result}."
    )
    state["samples"] = []
    save_state(state)
    write_page(state)
    return {"sent": True, "filled": filled, "state": state, "game": game, "cheap": again, "next": nxt}


def sample_prices(state: dict, game: dict) -> None:
    attempt = state["attempt"]
    cheap = {
        "sport": attempt.get("sport") or "",
        "game": attempt.get("game") or "",
        "market_type": attempt.get("market_type") or "",
        "side": attempt.get("side") or "",
        "number": attempt.get("number") or "",
        "pay": attempt.get("pay") or "",
        "venue": attempt.get("buy_venue") or "",
        "instrument": attempt.get("instrument") or "",
        "event_ticker": attempt.get("event_ticker") or "",
        "intent": attempt.get("intent") or "",
    }
    nxt_venue = attempt.get("next_venue") or ""
    start = time.time()
    samples = []
    while time.time() - start < 600:
        buy_px = ""
        next_px = ""
        try:
            buy_leg = reload_leg(cheap, game)
            if buy_leg is not None:
                buy_px = money(buy_leg["price"])
        except Exception as exc:
            log(f"sample buy {type(exc).__name__}")
        try:
            _game, kalshi_events, gemini_events, poly = load_books(
                {"game": game, "sport": cheap["sport"], "title": cheap["game"]},
                nxt_venue == "Polymarket",
            )
            legs = fresh_legs(cheap["sport"], cheap["game"], kalshi_events, gemini_events, poly)
            for leg in legs:
                if leg["venue"] != nxt_venue:
                    continue
                if leg["market_type"] == cheap["market_type"] and leg["side"] == cheap["side"] and leg["number"] == cheap["number"] and leg["pay"] == cheap["pay"]:
                    next_px = money(leg["price"])
                    break
        except Exception as exc:
            log(f"sample next {type(exc).__name__}")
        samples.append({
            "at": datetime.now(ET).isoformat(timespec="seconds"),
            "buy": buy_px,
            "next": next_px,
        })
        state["samples"] = samples
        base = Decimal(attempt.get("buy_price") or "0")
        later = as_size(buy_px)
        if later is not None and base > 0:
            if later > base:
                state["moved"] = (
                    f"The buy-venue ask moved up, from {attempt.get('buy_price')} to {buy_px}. "
                    f"The other venue was {next_px or 'not read'}."
                )
            elif later == base:
                state["moved"] = f"The buy-venue ask was still {buy_px}. The other venue was {next_px or 'not read'}."
            else:
                state["moved"] = (
                    f"The buy-venue ask went down, from {attempt.get('buy_price')} to {buy_px}. "
                    f"The other venue was {next_px or 'not read'}."
                )
        else:
            state["moved"] = f"A later buy ask was not on the book. The other venue was {next_px or 'not read'}."
        state["updated"] = datetime.now(ET).isoformat(timespec="seconds")
        save_state(state)
        write_page(state)
        log(f"sample buy {buy_px or 'blank'} next {next_px or 'blank'}")
        remaining = 600 - (time.time() - start)
        if remaining <= 5:
            break
        time.sleep(min(60, remaining))
    state["status"] = "done"
    state["updated"] = datetime.now(ET).isoformat(timespec="seconds")
    save_state(state)
    write_page(state)


def one_pass(listed: list[dict]) -> dict | None:
    rows, counts = cheaper_same_bet.cheaper_rows()
    games = page_games(rows)
    log(f"page 10-cent groups {counts.get('c10')} games {len(games)}")
    if not games:
        return None
    for sport, game, want_poly in games:
        job = job_for(sport, game, listed)
        try:
            if job is not None:
                book_game, kalshi_events, gemini_events, poly = load_books(job, want_poly)
            else:
                k_tickers, g_tickers = saved_tickers(game)
                if not k_tickers and not g_tickers:
                    log(f"no tickers for {sport} {game}")
                    continue
                log(f"saved tickers {game} kalshi {len(k_tickers)} gemini {len(g_tickers)}")
                gemini_events = [scan.fetch_gemini_event(ticker) for ticker in g_tickers]
                kalshi_events = [scan.fetch_kalshi_event(ticker) for ticker in k_tickers]
                poly = []
                book_game = {"title_kalshi": game, "title_gemini": game}
                if want_poly:
                    import live_game_pollers
                    poly = live_game_pollers._polymarket_contracts(book_game, scan, kalshi_events, gemini_events)
            legs = fresh_legs(sport, game, kalshi_events, gemini_events, poly)
            choices = gaps_from_legs(legs)
        except Exception as exc:
            log(f"book read {game} {type(exc).__name__}: {exc}")
            continue
        if not choices:
            best = 0
            grouped: dict[tuple, list] = {}
            for leg in legs:
                grouped.setdefault((leg["market_type"], leg["side"], leg["number"], leg["pay"]), []).append(leg)
            for group in grouped.values():
                venues = {leg["venue"]: leg["price"] for leg in group}
                if len(venues) < 2:
                    continue
                ordered = sorted(venues.values())
                cents = int((ordered[1] - ordered[0]).quantize(CENT, rounding=ROUND_HALF_UP) / CENT)
                if cents > best:
                    best = cents
            log(f"no sized 10-cent gap {game} legs {len(legs)} best sized gap {best}")
            continue
        choice = choices[0]
        log(
            f"candidate {game} {choice['market_type']} {choice['side']} {choice['number']} "
            f"{choice['cheap']['venue']} {money(choice['cheap']['price'])} size {money(choice['cheap']['size'])} "
            f"next {choice['next']['venue']} {money(choice['next']['price'])} gap {choice['gap_cents']}"
        )
        outcome = attempt_order(choice, book_game)
        if outcome.get("sent"):
            return outcome
        log(f"not sent {outcome.get('reason')}")
    return None


def main() -> None:
    state = load_state()
    if state.get("status") in ("sending", "filled", "attempted", "done"):
        log(f"already attempted status {state.get('status')}")
        write_page(state)
        if state.get("status") == "filled" and not state.get("samples"):
            sample_prices(state, {})
        return
    log("watch start")
    state = {
        "status": "watching",
        "updated": datetime.now(ET).isoformat(timespec="seconds"),
        "note": "Watching for a same-side ask at least 10 cents cheaper, with size of at least 1. No order yet.",
        "samples": [],
    }
    save_state(state)
    write_page(state)
    while datetime.now(ET) < DEADLINE:
        began = time.time()
        try:
            outcome = one_pass(jobs())
        except Exception:
            log("pass failed\n" + traceback.format_exc().splitlines()[-1])
            outcome = None
        if outcome and outcome.get("sent"):
            if outcome.get("filled"):
                sample_prices(outcome["state"], outcome.get("game") or {})
            else:
                final = load_state()
                final["status"] = "done"
                final["moved"] = "The order did not fill. No second order was sent."
                final["updated"] = datetime.now(ET).isoformat(timespec="seconds")
                save_state(final)
                write_page(final)
            return
        elapsed = time.time() - began
        pause = max(0, 60 - elapsed)
        if pause:
            time.sleep(pause)
    state = load_state()
    state["status"] = "none"
    state["updated"] = datetime.now(ET).isoformat(timespec="seconds")
    state["note"] = "Watched until 8:00 AM ET on 2026-10-19. No same-side ask stayed at least 10 cents cheaper with size of at least 1, so no order was sent."
    state["moved"] = ""
    save_state(state)
    write_page(state)
    log("deadline none")


if __name__ == "__main__":
    main()
