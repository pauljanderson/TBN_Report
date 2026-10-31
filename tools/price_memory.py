"""Remember the price you pay on each Kalshi, Gemini, and Polymarket contract.

No orders. No secrets. History is raw/price_memory.jsonl. The latest price
for each contract key is raw/price_last.json.

A key is sport, game, market type, side, number, venue, and whether you pay
the Yes ask or the No ask. A Gemini No that is just one minus the Yes bid,
with no No size, is not stored. The Yes ask on that contract still is.
"""
from __future__ import annotations

import html
import json
import re
import statistics
import sys
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"
RAW = STAMP / "raw"
HISTORY = RAW / "price_memory.jsonl"
LAST = RAW / "price_last.json"
PAGE = STAMP / "price_moves.html"
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
DRASTIC = Decimal("0.05")
FLIP_TOL = Decimal("0.001")
SAME_QUOTE_SEC = 20
GET_CAP = 8

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML  # noqa: E402

_lock = threading.Lock()

PREFIX_SPORT = {
    "cfb": "college football",
    "nfl": "pro football",
    "mlb": "pro baseball",
    "soccer": "soccer",
    "golf": "golf",
    "motorsports": "motorsports",
    "mma": "mma",
    "nhl": "pro hockey",
    "chess": "chess",
    "tennis": "tennis",
    "tt": "table tennis",
    "tabletennis": "table tennis",
}
DURING_MINUTES = {
    "college football": 240,
    "pro football": 210,
    "soccer": 120,
    "pro hockey": 180,
    "pro baseball": 210,
    "mma": 180,
    "golf": 360,
    "motorsports": 180,
    "chess": 180,
    "tennis": 180,
    "table tennis": 90,
}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
TZ_BY_ABBR = {
    "ET": ET, "EST": ET, "EDT": ET,
    "CT": ZoneInfo("America/Chicago"), "CST": ZoneInfo("America/Chicago"), "CDT": ZoneInfo("America/Chicago"),
    "MT": ZoneInfo("America/Denver"), "MST": ZoneInfo("America/Denver"), "MDT": ZoneInfo("America/Denver"),
    "PT": ZoneInfo("America/Los_Angeles"), "PST": ZoneInfo("America/Los_Angeles"), "PDT": ZoneInfo("America/Los_Angeles"),
    "UTC": UTC, "GMT": UTC,
}
SKIP_NAMES = {
    "price_memory.jsonl", "price_last.json", "call_metrics.jsonl", "overnight_checkpoint.json",
    "last_gross.json", "overnight_scan.log",
}

ASKED = (
    "Bets moving most rapidly are probably games underway. Track historically the price moves "
    "over time from before game time through during game time. Keep prior prices for each spread "
    "(and moneyline and total) so a drastic move is visible. Later, when a Gemini API key exists "
    "and orders can be placed on both systems, place the order first on the side that moved the "
    "most since the last check, then the side that moved less."
)
PLAIN = (
    "We remember the last price on each line and compare how much it moves before the game and during the game. "
    "A line is one bet: who wins (moneyline), the point spread, or the total, on Kalshi, Gemini, or Polymarket US, "
    "and whether the price is the Yes ask or the No ask (the price you pay). "
    "A move of 5 cents or more since the prior saved price is a drastic move. "
    "Before means the quote is earlier than the listed start. During means the quote is after the start "
    "and still inside a typical game length (about four hours for college football, three and a half for pro football, "
    "two hours for soccer, three hours for hockey, three and a half for baseball, "
    "about three hours for tennis or MMA or chess, about ninety minutes for table tennis). "
    "If the start time is not in the ticker or the event text, the phase stays unknown. "
    "A Gemini No that is only one dollar minus the Yes bid, with no No contracts behind it, is left out. The Yes ask is kept."
)


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.0001")), "f")


def as_decimal(value) -> Decimal | None:
    if value is None or value == "" or value == "not offered" or value == "unknown":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def as_price(value) -> Decimal | None:
    number = as_decimal(value)
    if number is None or number < 0 or number > 1:
        return None
    return number.quantize(Decimal("0.0001"))


def to_et(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def parse_time(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return to_et(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def iso_et(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return to_et(dt).isoformat()


def norm_number(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("", "none", "null"):
        return ""
    number = as_decimal(text)
    if number is None:
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return ""
        number = as_decimal(match.group(0))
    if number is None:
        return ""
    if number == number.to_integral():
        return str(int(number))
    return format(number.quantize(Decimal("0.01")).normalize(), "f")


def norm_side(label: str, kind: str) -> str:
    text = unicodedata.normalize("NFKD", label or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    low = text.lower().strip()
    if kind == "total":
        if re.search(r"\bunder\b", low):
            return "under"
        return "over"
    low = re.split(r"\bwins\b|\bmore than\b|\bover\b|\bby\b", low, maxsplit=1)[0]
    low = re.sub(r"[^a-z0-9 ]+", " ", low)
    low = re.sub(r"\s+", " ", low).strip()
    return low or "side"


def market_type_from(*parts: str) -> str | None:
    """Totals and spreads win over the word Game, which also appears in total titles."""
    blob = " ".join(p for p in parts if p).upper()
    if "TOTAL" in blob or re.search(r"[-_]T([-_]|$)", blob):
        return "total"
    if "SPREAD" in blob or re.search(r"[-_]S([-_]|$)|[-_]REGS([-_]|$)", blob):
        return "spread"
    if "MONEYLINE" in blob or re.search(r"[-_]M([-_]|$)", blob) or "GAME" in blob:
        return "moneyline"
    return None


def ticker_start(text: str) -> datetime | None:
    match = re.search(r"[A-Z]{2,}-(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})-", text or "")
    if not match:
        return None
    yy, month, day, hour, minute = (int(x) for x in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31 and hour <= 23 and minute <= 59):
        return None
    try:
        return datetime(2000 + yy, month, day, hour, minute, tzinfo=UTC).astimezone(ET)
    except ValueError:
        return None


def _clock_to_hm(clock: str) -> tuple[int, int] | None:
    match = re.search(r"(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?", clock, re.I)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    ampm = (match.group(3) or "").lower().replace(".", "")
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def description_start(text: str) -> datetime | None:
    if not text:
        return None
    iso_match = re.search(
        r"(\d{4})-(\d{2})-(\d{2})\s+at\s+(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?)\s*([A-Z]{2,3})?",
        text,
        re.I,
    )
    if iso_match:
        year, month, day = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        hm = _clock_to_hm(iso_match.group(4))
        zone = TZ_BY_ABBR.get((iso_match.group(5) or "ET").upper(), ET)
        if hm:
            try:
                return datetime(year, month, day, hm[0], hm[1], tzinfo=zone).astimezone(ET)
            except ValueError:
                return None
    named = re.search(
        r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)(?:\s*([A-Z]{2,3}))?",
        text,
    )
    if not named:
        return None
    month = MONTHS.get(named.group(1).lower())
    if not month:
        return None
    hm = _clock_to_hm(named.group(4))
    if not hm:
        return None
    zone = TZ_BY_ABBR.get((named.group(5) or "ET").upper(), ET)
    try:
        return datetime(int(named.group(3)), month, int(named.group(2)), hm[0], hm[1], tzinfo=zone).astimezone(ET)
    except ValueError:
        return None


def phase_of(seen: datetime, start: datetime | None, sport: str) -> str:
    if start is None:
        return "unknown"
    seen = to_et(seen)
    start = to_et(start)
    if seen < start:
        return "before"
    length = DURING_MINUTES.get(sport, 180)
    if seen < start + timedelta(minutes=length):
        return "during"
    return "after"


def contract_key(sport: str, game: str, kind: str, side: str, number: str, venue: str, pay: str) -> str:
    return "|".join([sport, game, kind, side, number, venue, pay])


def size_positive(value) -> bool | None:
    if value is None or value == "" or value == "unknown":
        return None
    if value is False:
        return False
    if value is True:
        return True
    number = as_decimal(value)
    if number is None:
        return None
    return number > 0


def gemini_no_price(buy_no, sell_yes, yes_bid, no_size) -> Decimal | None:
    """Skip a flipped Gemini No (buy.no = 1 - the Yes bid, and no No size)."""
    price = as_price(buy_no)
    if price is None:
        return None
    flipped = False
    for bid_raw in (sell_yes, yes_bid):
        bid = as_price(bid_raw)
        if bid is None:
            continue
        if abs(price - (Decimal("1") - bid)) <= FLIP_TOL:
            flipped = True
            break
    known = size_positive(no_size)
    if flipped and known is not True:
        return None
    if known is False:
        return None
    return price


def quote_row(sport, game, kind, side_label, number, venue, pay, price: Decimal, seen: datetime, start: datetime | None) -> dict:
    side = norm_side(side_label, kind)
    if kind == "moneyline":
        number = ""
    else:
        number = norm_number(number)
    return {
        "sport": sport or "unknown",
        "game": game or "unknown",
        "market_type": kind,
        "side_label": side_label or side,
        "side": side,
        "number": number,
        "venue": venue,
        "pay": pay,
        "price": price,
        "seen_at": to_et(seen),
        "game_start": to_et(start) if start else None,
    }


def consider_start(bucket: dict, sport: str, game: str, when: datetime | None, quality: int) -> None:
    if when is None or not sport or not game:
        return
    key = sport + "|" + game
    prev = bucket.get(key)
    if prev is None or quality > prev[0]:
        bucket[key] = (quality, to_et(when))


def iter_events(events):
    if isinstance(events, dict):
        for key, value in events.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("event_ticker", key)
                item.setdefault("ticker", key)
                yield item
    elif isinstance(events, list):
        for value in events:
            if isinstance(value, dict):
                yield value


def quotes_from_kalshi_contract(contract: dict, event: dict, sport: str, game: str, seen: datetime, starts: dict) -> list[dict]:
    ticker = str(contract.get("ticker") or event.get("event_ticker") or "")
    kind = market_type_from(ticker, str(event.get("event_ticker") or ""), str(contract.get("title") or ""))
    if kind is None:
        return []
    label = str(contract.get("yes_sub_title") or contract.get("title") or "")
    number = contract.get("floor_strike")
    if number is None:
        number = norm_number(label) if kind != "moneyline" else ""
    start = ticker_start(ticker) or description_start(str(contract.get("rules_primary") or ""))
    consider_start(starts, sport, game, start, 2 if ticker_start(ticker) else 1)
    out = []
    for pay, field in (("yes", "yes_ask_dollars"), ("no", "no_ask_dollars")):
        price = as_price(contract.get(field))
        if price is None:
            continue
        out.append(quote_row(sport, game, kind, label, number, "Kalshi", pay, price, seen, start))
    return out


def quotes_from_gemini_contract(contract: dict, event: dict, sport: str, game: str, seen: datetime, starts: dict) -> list[dict]:
    symbol = str(contract.get("instrumentSymbol") or contract.get("ticker") or "")
    event_ticker = str(event.get("ticker") or "")
    strike = contract.get("strike") if isinstance(contract.get("strike"), dict) else {}
    kind = market_type_from(symbol, event_ticker, str(strike.get("type") or ""), str(event.get("title") or ""))
    if kind is None and strike.get("type") in ("moneyline", "spread", "total"):
        kind = strike["type"]
    if kind is None:
        return []
    label = str(contract.get("label") or contract.get("abbreviatedName") or contract.get("title") or "")
    number = strike.get("value")
    if number is None and kind != "moneyline":
        number = norm_number(label)
    desc = json.dumps(contract.get("description") or "", ensure_ascii=False)
    start = ticker_start(symbol) or ticker_start(event_ticker) or description_start(desc)
    consider_start(starts, sport, game, ticker_start(symbol) or ticker_start(event_ticker), 2)
    consider_start(starts, sport, game, description_start(desc), 1)
    event_start = parse_time(event.get("startTime") if isinstance(event.get("startTime"), str) else None)
    consider_start(starts, sport, game, event_start, 3)
    if start is None:
        start = event_start
    prices = contract.get("prices") if isinstance(contract.get("prices"), dict) else {}
    buy = prices.get("buy") if isinstance(prices.get("buy"), dict) else {}
    sell = prices.get("sell") if isinstance(prices.get("sell"), dict) else {}
    out = []
    yes = as_price(buy.get("yes"))
    if yes is not None:
        out.append(quote_row(sport, game, kind, label, number, "Gemini", "yes", yes, seen, start))
    no_size = None
    for bucket in (buy, prices, contract):
        if not isinstance(bucket, dict):
            continue
        if bucket.get("no_size") is not None:
            no_size = bucket.get("no_size")
        elif bucket.get("noSize") is not None:
            no_size = bucket.get("noSize")
    no = gemini_no_price(buy.get("no"), sell.get("yes"), prices.get("bestBid"), no_size)
    if no is not None:
        out.append(quote_row(sport, game, kind, label, number, "Gemini", "no", no, seen, start))
    return out


def quotes_from_book(payload: dict, sport: str, game: str, starts: dict) -> list[dict]:
    seen = parse_time(payload.get("fetched_at"))
    if seen is None:
        return []
    sport = payload.get("sport") or sport
    game = payload.get("game") or game
    out = []
    for event in iter_events(payload.get("events")):
        for contract in event.get("contracts") or []:
            if not isinstance(contract, dict):
                continue
            if "yes_ask_dollars" in contract or "no_ask_dollars" in contract:
                out.extend(quotes_from_kalshi_contract(contract, event, sport, game, seen, starts))
            elif "prices" in contract or "instrumentSymbol" in contract:
                out.extend(quotes_from_gemini_contract(contract, event, sport, game, seen, starts))
    return out


def candidate_quotes(cand: dict, sport: str, game: str, seen: datetime, starts: dict) -> list[dict]:
    if not isinstance(cand, dict):
        return []
    kind = cand.get("market_type") or cand.get("type") or ""
    if kind not in ("moneyline", "spread", "total"):
        return []
    side = str(cand.get("side") or cand.get("side_label") or "")
    number = cand.get("number")
    start = ticker_start(str(cand.get("gemini_symbol") or "")) or ticker_start(str(cand.get("kalshi_ticker") or ""))
    consider_start(starts, sport, game, start, 2)
    note = str(cand.get("quote_note") or cand.get("label") or "")
    flipped = bool(cand.get("no_flipped_yes_bid") or cand.get("flipped_yes_bid"))
    if "flipped" in note.lower() or "not a no offer" in note.lower():
        flipped = True
    out = []
    pairs = (
        ("Kalshi", "yes", cand.get("kalshi_yes")),
        ("Kalshi", "no", cand.get("kalshi_no")),
        ("Gemini", "yes", cand.get("gemini_yes") if cand.get("gemini_yes") not in ("", None) else cand.get("buy_yes")),
    )
    for venue, pay, raw in pairs:
        price = as_price(raw)
        if price is None:
            continue
        out.append(quote_row(sport, game, kind, side, number, venue, pay, price, seen, start))
    gemini_no = cand.get("gemini_no")
    if gemini_no in (None, "", "not offered"):
        if str(cand.get("no_venue") or "").lower() == "gemini":
            gemini_no = cand.get("no_ask") if cand.get("no_ask") not in (None, "") else cand.get("no_price")
    no_size = cand.get("gemini_no_size")
    if no_size in (None, ""):
        no_size = cand.get("no_size") if str(cand.get("no_venue") or "").lower() == "gemini" else no_size
    if cand.get("gemini_no_size_gt_0") is False:
        no_size = 0
    price = None if flipped else gemini_no_price(gemini_no, cand.get("sell_yes"), cand.get("yes_bid") or cand.get("best_bid"), no_size)
    if price is not None and size_positive(no_size) is True:
        out.append(quote_row(sport, game, kind, side, number, "Gemini", "no", price, seen, start))
    if not any(c.get("kalshi_yes") or c.get("gemini_yes") for c in [cand]):
        yes_venue = str(cand.get("yes_venue") or "")
        no_venue = str(cand.get("no_venue") or "")
        yes_raw = cand.get("yes_ask") if cand.get("yes_ask") not in (None, "") else cand.get("yes_price")
        no_raw = cand.get("no_ask") if cand.get("no_ask") not in (None, "") else cand.get("no_price")
        if yes_venue.lower() == "kalshi":
            price = as_price(yes_raw)
            if price is not None:
                out.append(quote_row(sport, game, kind, side, number, "Kalshi", "yes", price, seen, start))
        elif yes_venue.lower() == "gemini":
            price = as_price(yes_raw)
            if price is not None:
                out.append(quote_row(sport, game, kind, side, number, "Gemini", "yes", price, seen, start))
        elif yes_venue.lower() == "polymarket":
            price = as_price(yes_raw)
            if price is not None:
                out.append(quote_row(sport, game, kind, side, number, "Polymarket", "yes", price, seen, start))
        if no_venue.lower() == "kalshi":
            price = as_price(no_raw)
            if price is not None:
                out.append(quote_row(sport, game, kind, side, number, "Kalshi", "no", price, seen, start))
        elif no_venue.lower() == "polymarket":
            price = as_price(no_raw)
            if price is not None:
                out.append(quote_row(sport, game, kind, side, number, "Polymarket", "no", price, seen, start))
    return out


def quotes_from_result(row: dict, sport: str, game: str, starts: dict) -> list[dict]:
    seen = parse_time(row.get("fetched_at") or row.get("timestamp") or row.get("first_seen") or row.get("corrected_at"))
    sport = row.get("sport") or sport
    game = row.get("game") or game
    if seen is None or not game:
        return []
    found = []
    for key in ("closest", "candidate"):
        item = row.get(key)
        if isinstance(item, dict):
            found.extend(candidate_quotes(item, sport, game, seen, starts))
    for key in ("under", "candidates"):
        for item in row.get(key) or []:
            if isinstance(item, dict):
                found.extend(candidate_quotes(item, sport, game, parse_time(item.get("fetched_at")) or seen, starts))
    for key, item in row.items():
        if not str(key).startswith("page_at") or not isinstance(item, dict):
            continue
        page_seen = parse_time(item.get("fetched_at")) or seen
        found.extend(candidate_quotes(item, sport, game, page_seen, starts))
    return found


def quotes_from_flat(payload: dict, sport: str, game: str, starts: dict) -> list[dict]:
    times = payload.get("times") if isinstance(payload.get("times"), dict) else {}
    seen = parse_time(times.get("kalshi_received") or times.get("book_received") or payload.get("fetched_at"))
    if seen is None:
        return []
    game = payload.get("game") or game
    market = str(payload.get("market") or "")
    kind = "moneyline"
    if "spread" in market.lower():
        kind = "spread"
    elif "total" in market.lower():
        kind = "total"
    side = market.split(" ", 1)[1] if " " in market else market
    out = []
    yes = as_price(payload.get("kalshi_yes_ask"))
    if yes is not None:
        out.append(quote_row(sport, game, kind, side, "", "Kalshi", "yes", yes, seen, None))
    if not payload.get("flipped_yes_bid"):
        no = gemini_no_price(payload.get("gemini_buy_no"), None, None, 0 if payload.get("gemini_no_size_gt_0") is False else payload.get("gemini_no_size"))
        if no is not None and size_positive(0 if payload.get("gemini_no_size_gt_0") is False else payload.get("no_size")) is True:
            out.append(quote_row(sport, game, kind, side, "", "Gemini", "no", no, seen, None))
    book = payload.get("book") if isinstance(payload.get("book"), dict) else None
    if book and isinstance(book.get("asks"), list) and book["asks"]:
        ask_prices = [as_price(a.get("price")) for a in book["asks"] if isinstance(a, dict)]
        ask_prices = [p for p in ask_prices if p is not None]
        if ask_prices and payload.get("no_size") in (0, "0", None) or payload.get("note"):
            label = str(payload.get("label") or side)
            symbol = str(payload.get("instrument") or "")
            kind2 = market_type_from(symbol) or kind
            start = ticker_start(symbol)
            consider_start(starts, sport, game, start, 2)
            number = norm_number(label) if kind2 != "moneyline" else ""
            out.append(quote_row(sport, game, kind2, label, number, "Gemini", "yes", min(ask_prices), seen, start))
    return out


def sport_from_name(name: str) -> str:
    stem = name.split("_")[0].lower()
    if stem == "opportunity":
        return ""
    return PREFIX_SPORT.get(stem, "")


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_sources() -> tuple[list[dict], dict]:
    starts: dict = {}
    quotes: list[dict] = []
    game_sport: dict[str, str] = {}
    if not RAW.exists():
        return quotes, starts
    paths = sorted(RAW.iterdir(), key=lambda p: p.name)
    for path in paths:
        if path.name in SKIP_NAMES or path.suffix.lower() not in (".json", ".jsonl"):
            continue
        sport_hint = sport_from_name(path.name)
        if path.suffix.lower() == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                found = quotes_from_result(row, sport_hint, str(row.get("game") or ""), starts)
                if not found and row.get("fetched_at") and row.get("events"):
                    found = quotes_from_book(row, sport_hint, str(row.get("game") or ""), starts)
                for item in found:
                    if item["sport"] and item["sport"] != "unknown":
                        game_sport[item["game"]] = item["sport"]
                    quotes.append(item)
            continue
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        found = []
        if payload.get("events"):
            found = quotes_from_book(payload, sport_hint, str(payload.get("game") or path.stem), starts)
        if not found:
            found = quotes_from_flat(payload, sport_hint, str(payload.get("game") or ""), starts)
        if not found and (payload.get("closest") or payload.get("candidates")):
            found = quotes_from_result(payload, sport_hint, str(payload.get("game") or ""), starts)
        for item in found:
            if item["sport"] and item["sport"] != "unknown":
                game_sport[item["game"]] = item["sport"]
            quotes.append(item)
    for item in quotes:
        if item["sport"] in ("", "unknown") and game_sport.get(item["game"]):
            item["sport"] = game_sport[item["game"]]
    return quotes, starts


def apply_starts(quotes: list[dict], starts: dict) -> None:
    for item in quotes:
        key = item["sport"] + "|" + item["game"]
        if item["game_start"] is None and key in starts:
            item["game_start"] = starts[key][1]
        elif key in starts and starts[key][0] >= 2:
            item["game_start"] = starts[key][1]


def games_with_two_prices(quotes: list[dict]) -> set[str]:
    seen: dict[str, set] = {}
    for item in quotes:
        key = contract_key(item["sport"], item["game"], item["market_type"], item["side"], item["number"], item["venue"], item["pay"])
        seen.setdefault(key, set()).add(item["seen_at"].isoformat())
    games = set()
    for item in quotes:
        key = contract_key(item["sport"], item["game"], item["market_type"], item["side"], item["number"], item["venue"], item["pay"])
        if len(seen.get(key, ())) >= 2:
            games.add(item["sport"] + "|" + item["game"])
    return games


def gemini_event_urls() -> dict[str, str]:
    """Map sport|game to one public Gemini event URL already saved on disk."""
    found = {}
    for path in RAW.glob("*gemini.json"):
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        sport = payload.get("sport") or sport_from_name(path.name)
        game = str(payload.get("game") or "")
        if not game:
            continue
        for event in iter_events(payload.get("events")):
            url = event.get("url") or ""
            if "gemini.com" in url and "/events/" in url:
                found.setdefault(sport + "|" + game, url)
                break
    return found


def pull_start_time(url: str) -> datetime | str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 stockresearch-price-memory/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if getattr(resp, "status", 200) == 429:
                return "429"
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return "429"
        return None
    except (OSError, json.JSONDecodeError, TimeoutError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("startTime")
    if not raw and isinstance(payload.get("event"), dict):
        raw = payload["event"].get("startTime")
    return parse_time(raw) if isinstance(raw, str) else None


def fill_missing_starts(quotes: list[dict], starts: dict) -> str:
    need = []
    two = games_with_two_prices(quotes)
    urls = gemini_event_urls()
    for game_key in sorted(two):
        if game_key in starts:
            continue
        url = urls.get(game_key)
        if url:
            need.append((game_key, url))
    note = "No public start-time lookup was needed."
    if not need:
        return note
    looked = 0
    for game_key, url in need:
        if looked >= GET_CAP:
            note = f"Stopped after {GET_CAP} public start-time lookups."
            break
        looked += 1
        found = pull_start_time(url)
        if found == "429":
            note = "Stopped start-time lookups after HTTP 429."
            break
        if isinstance(found, datetime):
            sport, game = game_key.split("|", 1)
            consider_start(starts, sport, game, found, 3)
    else:
        note = f"Looked up {looked} game start time(s) from public Gemini event pages."
    apply_starts(quotes, starts)
    return note


def fold(quotes: list[dict]) -> list[dict]:
    quotes = sorted(quotes, key=lambda item: (item["seen_at"], item["venue"], item["pay"]))
    last: dict[str, dict] = {}
    rows = []
    for item in quotes:
        key = contract_key(item["sport"], item["game"], item["market_type"], item["side"], item["number"], item["venue"], item["pay"])
        prev = last.get(key)
        seen = item["seen_at"]
        price = item["price"]
        if prev is not None:
            prev_seen = datetime.fromisoformat(prev["seen_at"])
            prev_price = Decimal(prev["price"])
            gap = (seen - prev_seen).total_seconds()
            if gap < 0:
                continue
            if price == prev_price and gap <= SAME_QUOTE_SEC:
                continue
            move = (price - prev_price).quantize(Decimal("0.0001"))
            prior = prev["price"]
            prior_seen = prev["seen_at"]
        else:
            move = None
            prior = None
            prior_seen = None
            gap = None
        start = item["game_start"]
        row = {
            "key": key,
            "sport": item["sport"],
            "game": item["game"],
            "market_type": item["market_type"],
            "side": item["side_label"],
            "side_key": item["side"],
            "number": item["number"],
            "venue": item["venue"],
            "pay": item["pay"],
            "seen_at": iso_et(seen),
            "price": money(price),
            "prior_price": prior,
            "prior_seen_at": prior_seen,
            "move": money(move) if move is not None else None,
            "gap_seconds": None if gap is None else round(gap, 1),
            "game_start": iso_et(start),
            "phase": phase_of(seen, start, item["sport"]),
            "drastic": bool(move is not None and abs(move) >= DRASTIC),
        }
        rows.append(row)
        last[key] = {
            "price": row["price"],
            "seen_at": row["seen_at"],
            "sport": item["sport"],
            "game": item["game"],
            "market_type": item["market_type"],
            "side": item["side_label"],
            "number": item["number"],
            "venue": item["venue"],
            "pay": item["pay"],
            "game_start": row["game_start"],
        }
    return rows


def write_store(rows: list[dict]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    last = {}
    for row in rows:
        last[row["key"]] = {
            "price": row["price"],
            "seen_at": row["seen_at"],
            "sport": row["sport"],
            "game": row["game"],
            "market_type": row["market_type"],
            "side": row["side"],
            "number": row["number"],
            "venue": row["venue"],
            "pay": row["pay"],
            "game_start": row["game_start"],
        }
    LAST.write_text(json.dumps(last, indent=2), encoding="utf-8")


def load_last() -> dict:
    if not LAST.exists():
        return {}
    try:
        data = json.loads(LAST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def quotes_from_polymarket(contracts, sport: str, game: str, seen: datetime, starts: dict) -> list[dict]:
    """Yes and No pay prices. No is $1 minus the bid, and only when that bid has size."""
    out = []
    for contract in contracts or []:
        if not isinstance(contract, dict):
            continue
        kind = str(contract.get("kind") or "moneyline")
        if kind not in ("moneyline", "spread", "total"):
            continue
        number = "" if kind == "moneyline" else contract.get("number")
        ask = as_price(contract.get("yes_ask"))
        bid = as_price(contract.get("yes_bid"))
        ask_sz = contract.get("ask_size")
        bid_sz = contract.get("bid_size")
        yes_px = ask if ask is not None and size_positive(ask_sz) is True else None
        no_px = None
        if bid is not None and size_positive(bid_sz) is True:
            no_px = as_price(Decimal("1") - bid)
        long_name = str(contract.get("long_name") or "")
        short_name = str(contract.get("short_name") or "")
        sides = (
            (long_name, yes_px, no_px),
            (short_name, no_px, yes_px),
        )
        for label, yes, no in sides:
            if not label:
                continue
            if yes is not None:
                out.append(quote_row(sport, game, kind, label, number, "Polymarket", "yes", yes, seen, None))
            if no is not None:
                out.append(quote_row(sport, game, kind, label, number, "Polymarket", "no", no, seen, None))
    return out


def remember_books(sport: str, game: str, seen_at, kalshi_events=None, gemini_events=None, game_date: str | None = None, moves_out: list | None = None, polymarket_contracts=None) -> int:
    """Append new pay-prices from one scan. Safe to call after each fetch or stream update. Places no orders.

    This does not wait on venue_pace. HTTP reads wait before they fetch. A websocket compare calls this with books already in memory.
    """
    seen = parse_time(seen_at) if isinstance(seen_at, str) else seen_at
    if seen is None:
        seen = datetime.now(ET)
    seen = to_et(seen)
    payload_k = {"fetched_at": iso_et(seen), "sport": sport, "game": game, "game_date": game_date, "events": kalshi_events or []}
    payload_g = {"fetched_at": iso_et(seen), "sport": sport, "game": game, "game_date": game_date, "events": gemini_events or []}
    starts: dict = {}
    quotes = quotes_from_book(payload_k, sport, game, starts) + quotes_from_book(payload_g, sport, game, starts)
    quotes.extend(quotes_from_polymarket(polymarket_contracts, sport, game, seen, starts))
    apply_starts(quotes, starts)
    if not quotes:
        return 0
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import venue_pace
    with _lock:
        with venue_pace.FileLock(RAW / "price_memory.lock"):
            return _remember_locked(quotes, seen, moves_out)


def _remember_locked(quotes: list[dict], seen: datetime, moves_out: list | None) -> int:
    last = load_last()
    fresh = []
    for item in quotes:
        key = contract_key(item["sport"], item["game"], item["market_type"], item["side"], item["number"], item["venue"], item["pay"])
        prev = last.get(key)
        price = item["price"]
        if isinstance(prev, dict) and prev.get("price"):
            prev_seen = parse_time(prev.get("seen_at"))
            prev_price = as_price(prev.get("price"))
            if prev_seen is not None and prev_price is not None:
                gap = (seen - prev_seen).total_seconds()
                if gap < 0:
                    continue
                if price == prev_price and gap <= SAME_QUOTE_SEC:
                    continue
                move = (price - prev_price).quantize(Decimal("0.0001"))
                prior = money(prev_price)
                prior_seen = iso_et(prev_seen)
                gap_val = round(gap, 1)
            else:
                move = None
                prior = None
                prior_seen = None
                gap_val = None
        else:
            move = None
            prior = None
            prior_seen = None
            gap_val = None
        start = item["game_start"]
        if start is None and isinstance(prev, dict):
            start = parse_time(prev.get("game_start"))
        row = {
            "key": key,
            "sport": item["sport"],
            "game": item["game"],
            "market_type": item["market_type"],
            "side": item["side_label"],
            "side_key": item["side"],
            "number": item["number"],
            "venue": item["venue"],
            "pay": item["pay"],
            "seen_at": iso_et(seen),
            "price": money(price),
            "prior_price": prior,
            "prior_seen_at": prior_seen,
            "move": money(move) if move is not None else None,
            "gap_seconds": gap_val,
            "game_start": iso_et(start),
            "phase": phase_of(seen, start, item["sport"]),
            "drastic": bool(move is not None and abs(move) >= DRASTIC),
        }
        fresh.append(row)
        last[key] = {
            "price": row["price"],
            "seen_at": row["seen_at"],
            "sport": item["sport"],
            "game": item["game"],
            "market_type": item["market_type"],
            "side": item["side_label"],
            "number": item["number"],
            "venue": item["venue"],
            "pay": item["pay"],
            "game_start": row["game_start"],
        }
    if moves_out is not None:
        moves_out.extend(fresh)
    if not fresh:
        return 0
    RAW.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as handle:
        for row in fresh:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp = LAST.parent / "price_last.json.tmp"
    tmp.write_text(json.dumps(last, indent=2), encoding="utf-8")
    tmp.replace(LAST)
    return len(fresh)


def read_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    rows = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def rephase(rows: list[dict]) -> None:
    best: dict[str, datetime] = {}
    for row in rows:
        start = parse_time(row.get("game_start"))
        if start is None:
            continue
        key = str(row.get("sport") or "") + "|" + str(row.get("game") or "")
        best[key] = start
    for row in rows:
        key = str(row.get("sport") or "") + "|" + str(row.get("game") or "")
        start = parse_time(row.get("game_start")) or best.get(key)
        seen = parse_time(row.get("seen_at"))
        if start is not None:
            row["game_start"] = iso_et(start)
        if seen is not None:
            row["phase"] = phase_of(seen, start, str(row.get("sport") or ""))


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def gap_text(seconds) -> str:
    if seconds is None or seconds == "":
        return ""
    total = int(float(seconds))
    if total < 0:
        total = 0
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {secs} sec"
    return f"{secs} sec"


def median_abs(moves: list[Decimal]) -> Decimal | None:
    if not moves:
        return None
    return Decimal(str(statistics.median(moves))).quantize(Decimal("0.0001"))


def fmt_move(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value.quantize(Decimal("0.0001")), "f")
    return text


def write_page(rows: list[dict], start_note: str) -> Path:
    rephase(rows)
    moves = []
    for row in rows:
        move = as_decimal(row.get("move"))
        if move is None:
            continue
        moves.append((row, move))
    by_phase: dict[tuple[str, str], list[Decimal]] = {}
    phase_rows: dict[str, int] = {"before": 0, "during": 0, "after": 0, "unknown": 0}
    for row, move in moves:
        phase = row.get("phase") or "unknown"
        phase_rows[phase] = phase_rows.get(phase, 0) + 1
        by_phase.setdefault((row.get("sport") or "", phase), []).append(abs(move))
    summary_keys = sorted(by_phase, key=lambda item: (item[0], item[1]))
    body_rows = []
    for sport, phase in summary_keys:
        vals = by_phase[(sport, phase)]
        med = median_abs(vals)
        largest = max(vals) if vals else None
        body_rows.append(
            "<tr>"
            f"<td>{esc(sport)}</td><td>{esc(phase)}</td>"
            f"<td>{len(vals)}</td><td>{esc(fmt_move(med))}</td><td>{esc(fmt_move(largest))}</td>"
            "</tr>"
        )
    if not body_rows:
        body_rows.append("<tr><td>No price has been seen twice yet.</td><td></td><td>0</td><td></td><td></td></tr>")
    summary = (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + th("Sport", "text") + th("Phase", "text") + th("Price updates", "num")
        + th("Median absolute move", "num") + th("Largest move", "num")
        + "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table></div>"
    )
    ranked = sorted(moves, key=lambda item: abs(item[1]), reverse=True)[:60]
    move_rows = []
    for row, move in ranked:
        move_rows.append(
            "<tr>"
            f"<td>{esc(row.get('game'))}</td><td>{esc(row.get('sport'))}</td><td>{esc(row.get('market_type'))}</td>"
            f"<td>{esc(row.get('side'))}</td><td>{esc(row.get('number'))}</td><td>{esc(row.get('pay'))}</td>"
            f"<td>{esc(row.get('venue'))}</td><td>{esc(row.get('prior_price'))}</td><td>{esc(row.get('price'))}</td>"
            f"<td>{esc(fmt_move(move))}</td><td>{esc(row.get('phase'))}</td><td>{esc(gap_text(row.get('gap_seconds')))}</td>"
            "</tr>"
        )
    if not move_rows:
        move_rows.append("<tr><td>No second quote yet, so there is no move.</td>" + "<td></td>" * 11 + "</tr>")
    largest_table = (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + th("Game", "text") + th("Sport", "text") + th("Type", "text") + th("Side", "text")
        + th("Number", "num") + th("You pay", "text") + th("Venue", "text")
        + th("Prior price", "num") + th("New price", "num") + th("Move", "num")
        + th("Phase", "text") + th("Time between quotes", "text")
        + "</tr></thead><tbody>" + "".join(move_rows) + "</tbody></table></div>"
    )
    before_vals = [abs(move) for row, move in moves if row.get("phase") == "before"]
    during_vals = [abs(move) for row, move in moves if row.get("phase") == "during"]
    before_med = median_abs(before_vals)
    during_med = median_abs(during_vals)
    chart = chart_svg(before_med, during_med, len(before_vals), len(during_vals))
    phase_notes = []
    for name in ("before", "during", "after"):
        count = sum(1 for row in rows if row.get("phase") == name)
        if count == 0:
            phase_notes.append(f"No {name}-game rows.")
    if phase_rows.get("during", 0) == 0:
        phase_notes.append("No during-game move is shown, because no saved quote falls inside a game that had already started.")
    drastic_n = sum(1 for row, move in moves if abs(move) >= DRASTIC)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Price moves — Kalshi vs Gemini</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.later {{ background: #fffbeb; border: 1px solid #f59e0b; padding: 12px 14px; margin: 12px 0; }}
.later h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Price moves — Kalshi vs Gemini</h1>
<p class="note">Research only. No orders. This page stays on Drive for Paul. It is not published to GitHub Pages. Annualized rate of return is not computed: these are quote changes, not a closed trade book. {esc(start_note)}</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>
<div class="later"><h2>Later, when both orders can be sent</h2>
<p>Send the first order on the venue whose price moved more since the last check, then send the other leg on the quieter venue. No orders are sent now. The Kalshi balance is $0 and there is no Gemini trading key in use.</p></div>
<p><strong>{len(rows)} history rows.</strong> {len(moves)} of those are a new price compared with the prior saved price. {drastic_n} moved by at least 5 cents. {' '.join(phase_notes)}</p>
<h2>By sport and phase</h2>
<p class="note">A price update is a quote compared with the prior saved price for that same line. Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{summary}
<h2>Before the game versus during the game</h2>
{chart}
<h2>Largest moves</h2>
<p class="note">Up to 60 largest absolute moves. You pay Yes or No is the ask on that venue. Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
{largest_table}
<p class="note">History file raw/price_memory.jsonl. Latest price per line raw/price_last.json. Written {esc(datetime.now(ET).strftime("%Y-%m-%d %I:%M:%S %p"))} Eastern Time. The overnight watcher stopped at 8:00 AM ET on 2026-10-18 as scheduled.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    return PAGE


def chart_svg(before_med: Decimal | None, during_med: Decimal | None, before_n: int, during_n: int) -> str:
    if before_med is None or during_med is None or before_n == 0 or during_n == 0:
        missing = []
        if before_n == 0:
            missing.append("before the game")
        if during_n == 0:
            missing.append("during the game")
        which = " and ".join(missing) if missing else "one phase"
        return f"<p>No bar chart. {esc(which)} has no price-move rows, so a during-game or before-game bar is not drawn.</p>"
    vals = [float(before_med), float(during_med)]
    top = max(vals) or 1
    width = 420
    height = 200
    base = 160
    labels = [
        (f"Before ({before_n})", vals[0], "#1d4ed8"),
        (f"During ({during_n})", vals[1], "#b45309"),
    ]
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Median absolute move before the game versus during the game">']
    parts.append('<text x="8" y="22" font-size="14" fill="#1e293b">Median absolute move (dollars)</text>')
    for index, (label, value, color) in enumerate(labels):
        bar_h = 0 if top == 0 else int((value / top) * 110)
        x = 70 + index * 160
        y = base - bar_h
        parts.append(f'<rect x="{x}" y="{y}" width="80" height="{bar_h}" fill="{color}"></rect>')
        parts.append(f'<text x="{x + 40}" y="{y - 6}" text-anchor="middle" font-size="13" fill="#1e293b">{value:.4f}</text>')
        parts.append(f'<text x="{x + 40}" y="{base + 20}" text-anchor="middle" font-size="13" fill="#334155">{esc(label)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def backfill() -> tuple[list[dict], str]:
    quotes, starts = collect_sources()
    apply_starts(quotes, starts)
    note = fill_missing_starts(quotes, starts)
    apply_starts(quotes, starts)
    rows = fold(quotes)
    with _lock:
        write_store(rows)
    return rows, note


def summarize(rows: list[dict]) -> dict:
    rephase(rows)
    def med(phase: str):
        vals = []
        for row in rows:
            if row.get("phase") != phase:
                continue
            move = as_decimal(row.get("move"))
            if move is not None:
                vals.append(abs(move))
        if not any(row.get("phase") == phase for row in rows):
            return "no during-game rows" if phase == "during" else "no before-game rows"
        if not vals:
            return "no moves"
        return format(median_abs(vals), "f")
    largest = None
    largest_row = None
    for row in rows:
        move = as_decimal(row.get("move"))
        if move is None:
            continue
        if largest is None or abs(move) > abs(largest):
            largest = move
            largest_row = row
    return {
        "rows": len(rows),
        "before": med("before"),
        "during": med("during"),
        "largest": None if largest is None else format(largest, "f"),
        "largest_row": largest_row,
    }


def main() -> None:
    rows, note = backfill()
    write_page(rows, note)
    stats = summarize(rows)
    print(json.dumps({"history_rows": stats["rows"], "median_abs_before": stats["before"], "median_abs_during": stats["during"], "largest_move": stats["largest"], "start_note": note}, indent=2))


if __name__ == "__main__":
    main()
