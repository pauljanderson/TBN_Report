"""Polymarket US public books, the signed markets websocket, and signed order calls.

Order calls are used only by tools/live_lock_orders.py. Do not log auth headers.

Docs: https://docs.polymarket.us/api-reference/websocket/markets
and https://docs.polymarket.us/api-reference/authentication
The international book at ws-subscriptions-clob.polymarket.com is a different
venue and is not used here.

The markets socket is wss://api.polymarket.us/v1/ws/markets. The handshake
signs timestamp + GET + /v1/ws/markets with the Ed25519 secret. Subscribe
uses the markets-page JSON (camelCase, string subscription type), which is
also what the official US SDK sends. Public REST books do not need a key.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

import venue_pace
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW, ROOT
KEY_FILE = ROOT / "secrets" / "polymarket_api_key.txt"
SECRET_FILE = ROOT / "secrets" / "polymarket_api_secret.txt"
CACHE = RAW / "polymarket_tennis_matches.json"
ALL_CACHE = RAW / "tennis_all_books.json"
GATEWAY = "https://gateway.polymarket.us"
# Men's ATP, ATP Challenger, and WTA moneylines. An empty series list is skipped.
KALSHI_TENNIS_SERIES = (
    "KXATPMATCH",
    "KXATPCHALLENGERMATCH",
    "KXWTAMATCH",
    "KXWTACHALLENGERMATCH",
)
# Tennis spreads are their own series (game handicap / set handicap). Empty is OK.
KALSHI_TENNIS_SPREAD_SERIES = (
    "KXATPGSPREAD",
    "KXATPSSPREAD",
    "KXATPGAMESPREAD",
    "KXWTAGSPREAD",
    "KXWTASSPREAD",
    "KXWTAGAMESPREAD",
    "KXATPCHALLENGERGSPREAD",
    "KXATPCHALLENGERSSPREAD",
    "KXWTACHALLENGERGSPREAD",
    "KXWTACHALLENGERSSPREAD",
    "KXITFGSPREAD",
    "KXITFWGSPREAD",
)
WS_URL = "wss://api.polymarket.us/v1/ws/markets"
WS_PATH = "/v1/ws/markets"
UA = {"User-Agent": "stockresearch-public-quote-scan/1.0", "Accept": "application/json"}
ONE = Decimal("1")
CENT = Decimal("0.01")
CACHE_MINUTES = 10
MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def keys_present() -> bool:
    try:
        return KEY_FILE.is_file() and SECRET_FILE.is_file() and KEY_FILE.stat().st_size > 0 and SECRET_FILE.stat().st_size > 0
    except OSError:
        return False


def load_key_material() -> tuple[str, str] | None:
    """Key ID and secret. None when either file is missing. Caller must not log these."""
    if not keys_present():
        return None
    try:
        key_id = KEY_FILE.read_text(encoding="utf-8").strip()
        secret = SECRET_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not key_id or not secret:
        return None
    return key_id, secret


def sign_request(method: str, path: str) -> dict[str, str] | None:
    """Headers for one Polymarket US call. None when the key files are absent.

    The signature is timestamp + method + path. Callers must not log these headers.
    """
    loaded = load_key_material()
    if loaded is None:
        return None
    key_id, secret = loaded
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        raw = base64.b64decode(secret)
        if len(raw) < 32:
            return None
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32])
    except Exception:
        return None
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}".encode("utf-8")
    signature = base64.b64encode(private_key.sign(message)).decode("ascii")
    return {
        "X-PM-Access-Key": key_id,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature,
    }


def auth_headers() -> dict[str, str] | None:
    """Handshake headers for GET /v1/ws/markets. None when the key files are absent."""
    return sign_request("GET", WS_PATH)


def signed_json(
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
    timeout: float = 30,
) -> tuple[int, str]:
    """Signed REST call to api.polymarket.us. The path has no query string."""
    if "?" in path or not path.startswith("/v1/"):
        raise ValueError("sign the path only")
    headers = sign_request(method, path)
    if headers is None:
        return 0, ""
    headers = dict(headers)
    headers["Accept"] = "application/json"
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = "https://api.polymarket.us" + path
    if query:
        url = url + "?" + urllib.parse.urlencode(query, doseq=True)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, detail


ACTIVITIES_PATH = "/v1/portfolio/activities"
# Docs: https://docs.polymarket.us/api-reference/portfolio/get-activities
# Host api.polymarket.us matches this US live client. Global CLOB (clob.polymarket.com)
# and institutional report (api.prod.polymarketexchange.com) are different products.


def get_activities(query: dict | None = None, timeout: float = 30) -> tuple[int, str]:
    """GET /v1/portfolio/activities. Read-only. Does not place or cancel."""
    return signed_json("GET", ACTIVITIES_PATH, query=query, timeout=timeout)


def taker_fee(price: Decimal, theta) -> Decimal | None:
    """One-contract taker fee. Theta is the market feeCoefficient. Banker's cent.

    US fee page: Fee = theta x C x p x (1 - p), rounded half to even to $0.01.
    Table tennis uses a higher coefficient on the market, not a guessed 0.10.
    Missing coefficient is unknown, not the standard 0.0695.
    """
    if theta is None or price is None:
        return None
    try:
        coefficient = Decimal(str(theta))
    except Exception:
        return None
    exact = coefficient * ONE * price * (ONE - price)
    return exact.quantize(CENT, rounding=ROUND_HALF_EVEN)


def _get(url: str) -> dict:
    """Public GET. Polymarket hosts wait their HTTP slot. A stream update must not call this."""
    paced = "polymarket.us" in url.lower()
    ok = True
    if paced:
        ok = venue_pace.wait_turn("polymarket")
        if not ok:
            return {}
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=45) as response:
            payload = json.load(response)
        return payload if isinstance(payload, dict) else {}
    finally:
        if paced and ok:
            venue_pace.release_turn("polymarket")


def _norm(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _split_vs(title: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s+vs\.?\s+", title or "", maxsplit=1, flags=re.I) if part.strip()]


def _date_from_slug(slug: str) -> str | None:
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", slug or "")
    return match.group(1) if match else None


def _event_period(event: dict) -> str:
    """Polymarket sports event.period (SUS, POST, S1, NS). Empty if the feed omitted it."""
    period = str(event.get("period") or "").strip()
    if period:
        return period
    state = event.get("eventState")
    if isinstance(state, dict):
        return str(state.get("period") or "").strip()
    return ""


def _date_from_kalshi(ticker: str) -> str | None:
    match = re.search(r"(\d{2})([A-Z]{3})(\d{2})", ticker or "")
    if not match:
        return None
    year = 2000 + int(match.group(1))
    month = MONTHS.get(match.group(2))
    if not month:
        return None
    return f"{year:04d}-{month:02d}-{int(match.group(3)):02d}"


def kalshi_tennis_tail(ticker: str) -> str:
    """Date+player blob shared by MATCH and GSPREAD, e.g. 26OCT30PAUALC."""
    match = re.search(r"-(\d{2}[A-Z]{3}\d{2}[A-Z0-9]+)$", str(ticker or "").upper())
    return match.group(1) if match else ""


def _names_match(left: str, right: str) -> bool:
    a = _norm(left)
    b = _norm(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    apart = [tok for tok in a.split() if tok not in SUFFIXES]
    bpart = [tok for tok in b.split() if tok not in SUFFIXES]
    if not apart or not bpart:
        return False
    if apart[-1] != bpart[-1]:
        return False
    return len(apart) == 1 or len(bpart) == 1 or bool(set(apart) & set(bpart))


def _players_match(kalshi_title: str, poly_title: str) -> bool:
    left = _split_vs(kalshi_title)
    right = _split_vs(poly_title)
    if len(left) != 2 or len(right) != 2:
        return False
    direct = _names_match(left[0], right[0]) and _names_match(left[1], right[1])
    crossed = _names_match(left[0], right[1]) and _names_match(left[1], right[0])
    return direct or crossed


def two_way_moneyline(market: dict) -> dict | None:
    """A two-player moneyline. Skips spreads, totals, set markets, and 3-way Yes/No books."""
    if not isinstance(market, dict):
        return None
    kind = str(market.get("sportsMarketTypeV2") or "")
    legacy = str(market.get("marketType") or "").lower()
    detail = str(market.get("sportsMarketType") or "").lower()
    if kind == "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME":
        return None
    if "SPREAD" in kind or "TOTAL" in kind or "PROP" in kind:
        return None
    if kind and "MONEYLINE" not in kind and legacy != "moneyline":
        return None
    if legacy in ("spread", "spreads", "total", "totals", "prop"):
        return None
    # full_game_winner is the match moneyline. Set-winner and game-total are not.
    if any(word in detail for word in ("spread", "total", "prop", "set_winner", "set-winner", "game_total", "games_total")):
        return None
    if market.get("line") not in (None, "", 0):
        return None
    sides = market.get("marketSides") or []
    if not isinstance(sides, list) or len(sides) != 2:
        return None
    long_side = next((side for side in sides if isinstance(side, dict) and side.get("long") is True), None)
    short_side = next((side for side in sides if isinstance(side, dict) and side.get("long") is False), None)
    if long_side is None or short_side is None:
        return None
    long_name = str(long_side.get("description") or "").strip()
    short_name = str(short_side.get("description") or "").strip()
    if long_name.lower() in ("", "yes", "no") or short_name.lower() in ("", "yes", "no"):
        return None
    slug = str(market.get("slug") or "").strip()
    if not slug:
        return None
    theta = market.get("feeCoefficient")
    return {
        "slug": slug,
        "fee_coefficient": None if theta is None else str(theta),
        "long_name": long_name,
        "short_name": short_name,
        "kind": "moneyline",
        "number": "",
    }


def two_way_spread(market: dict) -> dict | None:
    """Full-match tennis (or other) spread. Skips totals, props, and set-winner books."""
    if not isinstance(market, dict):
        return None
    kind = str(market.get("sportsMarketTypeV2") or "")
    legacy = str(market.get("marketType") or "").lower()
    detail = str(market.get("sportsMarketType") or "").lower()
    blob = " ".join([
        detail,
        str(market.get("slug") or "").lower(),
        str(market.get("question") or "").lower(),
    ])
    if any(word in blob for word in _PARTIAL):
        return None
    if "TOTAL" in kind or "PROP" in kind or legacy in ("total", "totals", "prop"):
        return None
    if "SPREAD" not in kind and legacy not in ("spread", "spreads") and "spread" not in detail and "handicap" not in detail:
        return None
    number = _num_key(market.get("line"))
    if not number or number == "0":
        return None
    sides = market.get("marketSides") or []
    if not isinstance(sides, list) or len(sides) != 2:
        return None
    long_side = next((side for side in sides if isinstance(side, dict) and side.get("long") is True), None)
    short_side = next((side for side in sides if isinstance(side, dict) and side.get("long") is False), None)
    if long_side is None or short_side is None:
        return None
    long_name = str(long_side.get("description") or "").strip()
    short_name = str(short_side.get("description") or "").strip()
    if long_name.lower() in ("", "yes", "no") or short_name.lower() in ("", "yes", "no"):
        return None
    slug = str(market.get("slug") or "").strip()
    if not slug:
        return None
    theta = market.get("feeCoefficient")
    return {
        "slug": slug,
        "fee_coefficient": None if theta is None else str(theta),
        "long_name": long_name,
        "short_name": short_name,
        "kind": "spread",
        "number": number,
    }


def _level(row: dict) -> tuple[Decimal | None, Decimal | None]:
    if not isinstance(row, dict):
        return None, None
    px = row.get("px")
    if isinstance(px, dict):
        price = px.get("value")
    else:
        price = px
    try:
        price_d = Decimal(str(price))
    except Exception:
        return None, None
    try:
        qty = Decimal(str(row.get("qty")))
    except Exception:
        qty = None
    return price_d, qty


def apply_book_levels(contract: dict, bids, offers) -> bool:
    """Full book snapshot. Best bid is first; best offer is first. Size 0 clears that side."""
    bid_px, bid_qty = _level(bids[0]) if isinstance(bids, list) and bids else (None, None)
    ask_px, ask_qty = _level(offers[0]) if isinstance(offers, list) and offers else (None, None)
    if bid_px is None and ask_px is None:
        return False
    contract["yes_bid"] = bid_px
    contract["bid_size"] = bid_qty if bid_qty is not None else Decimal("0")
    contract["yes_ask"] = ask_px
    contract["ask_size"] = ask_qty if ask_qty is not None else Decimal("0")
    return True


def apply_market_message(contracts: dict[str, dict], payload: dict) -> str | None:
    """Update the slug's book. Returns the slug when the top of book changed."""
    if not isinstance(payload, dict):
        return None
    book = payload.get("marketData") or payload.get("market_data")
    if not isinstance(book, dict):
        return None
    slug = str(book.get("marketSlug") or book.get("market_slug") or "")
    contract = contracts.get(slug)
    if contract is None:
        return None
    if apply_book_levels(contract, book.get("bids") or [], book.get("offers") or []):
        return slug
    return None


def fetch_book(slug: str) -> dict | None:
    try:
        payload = _get(f"{GATEWAY}/v1/markets/{urllib.parse.quote(slug)}/book")
    except Exception:
        return None
    book = payload.get("marketData") if isinstance(payload.get("marketData"), dict) else payload
    return book if isinstance(book, dict) else None


def seed_books(contracts: list[dict]) -> None:
    for contract in contracts:
        book = fetch_book(str(contract.get("slug") or ""))
        if not book:
            continue
        apply_book_levels(contract, book.get("bids") or [], book.get("offers") or [])


def _known_codes(game: dict) -> set[str]:
    found = set()
    for key in ("codes", "kalshi_codes", "gemini_codes", "teams"):
        for code in game.get(key) or []:
            text = str(code).upper()
            if re.fullmatch(r"[A-Z]{2,6}", text):
                found.add(text)
    return found


def assign_codes(game: dict, contract: dict) -> None:
    """Map Texans/Jaguars nicknames onto HOU/JAC when the event title carries the code."""
    known = _known_codes(game)
    parts = _split_vs(str(contract.get("event_title") or ""))
    for label, field in (("long_name", "long_code"), ("short_name", "short_code")):
        name = _norm(contract.get(label))
        contract[field] = ""
        if not name:
            continue
        for part in parts:
            if name not in _norm(part):
                continue
            for token in re.findall(r"[A-Za-z]{2,6}", part):
                upper = token.upper()
                if upper in known:
                    contract[field] = upper
                    break
            break


def _sized(price: Decimal | None, qty: Decimal | None) -> tuple[Decimal | None, Decimal]:
    if price is None or qty is None or qty <= 0:
        return None, Decimal("0")
    return price, qty


def contract_views(contract: dict) -> list[dict]:
    """Yes is the long side of the single instrument. No is the short, $1 minus the bid.

    The US market has one instrument. Buying the short side pays one dollar minus
    the best bid, and the size is that bid's quantity. A zero bid size is not a buy.
    """
    ask, ask_sz = _sized(contract.get("yes_ask"), contract.get("ask_size"))
    bid = contract.get("yes_bid")
    bid_qty = contract.get("bid_size")
    no_px, no_sz = (None, Decimal("0"))
    if isinstance(bid, Decimal) and isinstance(bid_qty, Decimal) and bid_qty > 0:
        no_px, no_sz = _sized(ONE - bid, bid_qty)
    theta = contract.get("fee_coefficient")
    slug = contract.get("slug") or ""
    rows = []
    # price.value on Polymarket US is always the long (Yes) price. Buying the short
    # side at a No price of X sends 1-X. The long row's No buy is that short.
    specs = (
        (contract.get("long_name") or "", contract.get("long_code") or "", ask, ask_sz, no_px, no_sz,
         "ORDER_INTENT_BUY_LONG", ask, "ORDER_INTENT_BUY_SHORT", bid),
        (contract.get("short_name") or "", contract.get("short_code") or "", no_px, no_sz, ask, ask_sz,
         "ORDER_INTENT_BUY_SHORT", bid, "ORDER_INTENT_BUY_LONG", ask),
    )
    for side, code, yes, yes_sz, no, no_size, yes_intent, yes_api, no_intent, no_api in specs:
        rows.append({
            "kind": contract.get("kind") or "moneyline",
            "side": side,
            "number": None if (contract.get("kind") or "moneyline") == "moneyline" else (contract.get("number") or None),
            "code": code or None,
            "yes": yes,
            "no": no,
            "yes_size": yes_sz,
            "no_size": no_size,
            "fee_coefficient": theta,
            "ident": slug,
            "label": side,
            "status": "open",
            "venue": "polymarket",
            "poly_yes_intent": yes_intent,
            "poly_no_intent": no_intent,
            "poly_yes_api_price": yes_api,
            "poly_no_api_price": no_api,
        })
    return rows


def _money(scan, value: Decimal | None) -> str:
    if value is None:
        return ""
    return scan.money(value)


def _size(scan, value) -> str:
    return scan.size_text(value)


def _fee_for_leg(scan, venue: str, price: Decimal | None, view: dict) -> Decimal | None:
    if price is None:
        return None
    if venue == "kalshi":
        return Decimal("0")
    if venue == "gemini":
        return scan.gemini_fee(price)
    if venue == "polymarket":
        return taker_fee(price, view.get("fee_coefficient"))
    return None


def _pair_rows(scan, game: dict, left_name: str, left_rows: list[dict], right_name: str, right_rows: list[dict]) -> list[dict]:
    amap = scan.alias_map(game)
    both = left_rows + right_rows
    name_map = scan.build_name_map(both, amap)
    buckets: dict[tuple, list] = {}
    for source, rows in ((left_name, left_rows), (right_name, right_rows)):
        for view in rows:
            key = (view["kind"], scan.side_key(view, amap, name_map), view.get("number"))
            buckets.setdefault(key, []).append((source, view))
    out = []
    for key, rows in buckets.items():
        left = [view for source, view in rows if source == left_name]
        right = [view for source, view in rows if source == right_name]
        if len(left) != 1 or len(right) != 1:
            continue
        if left[0]["kind"] != right[0]["kind"]:
            continue
        same = getattr(scan, "views_same_settlement", None)
        if callable(same) and not same(left[0], right[0]):
            continue
        out.extend(_directions(scan, key, left_name, left[0], right_name, right[0]))
    return out


def _directions(scan, key, left_name: str, left: dict, right_name: str, right: dict) -> list[dict]:
    kind, side, number = key
    out = []
    specs = (
        (left_name, right_name, left, right, left.get("yes"), right.get("no"), left.get("yes_size"), right.get("no_size")),
        (right_name, left_name, right, left, right.get("yes"), left.get("no"), right.get("yes_size"), left.get("no_size")),
    )
    for yes_venue, no_venue, yes_view, no_view, yes_px, no_px, yes_sz, no_sz in specs:
        if yes_px is None or no_px is None:
            continue
        gross = yes_px + no_px
        fee_yes = _fee_for_leg(scan, yes_venue, yes_px, yes_view)
        fee_no = _fee_for_leg(scan, no_venue, no_px, no_view)
        if fee_yes is None or fee_no is None:
            net = None
        else:
            net = gross + fee_yes + fee_no
        poly_view = yes_view if yes_venue == "polymarket" else no_view if no_venue == "polymarket" else {}
        if yes_venue == "polymarket":
            poly_intent = yes_view.get("poly_yes_intent") or ""
            poly_api = yes_view.get("poly_yes_api_price")
        elif no_venue == "polymarket":
            poly_intent = no_view.get("poly_no_intent") or ""
            poly_api = no_view.get("poly_no_api_price")
        else:
            poly_intent = ""
            poly_api = None
        whole = (
            isinstance(yes_sz, Decimal) and isinstance(no_sz, Decimal) and yes_sz >= 1 and no_sz >= 1
        )
        gross_under = gross < ONE
        net_under = bool(whole and net is not None and net < ONE)
        out.append({
            "market_type": kind,
            "side": yes_view.get("label") or side,
            "side_key": side,
            "number": number or "",
            "yes_venue": yes_venue,
            "no_venue": no_venue,
            "yes_price": _money(scan, yes_px),
            "no_price": _money(scan, no_px),
            "yes_size": _size(scan, yes_sz),
            "no_size": _size(scan, no_sz),
            "gross": _money(scan, gross),
            "gemini_fee": _money(scan, fee_yes if yes_venue == "gemini" else fee_no if no_venue == "gemini" else None),
            "polymarket_fee": _money(scan, fee_yes if yes_venue == "polymarket" else fee_no if no_venue == "polymarket" else None),
            "net": _money(scan, net) if net is not None else "",
            "gross_under_1": gross_under,
            "net_under_1": net_under,
            "size_both": whole,
            "label": "trade" if net_under else "no",
            "kalshi_ticker": (left.get("ident") if left_name == "kalshi" else right.get("ident") if right_name == "kalshi" else "") or "",
            "gemini_symbol": (left.get("ident") if left_name == "gemini" else right.get("ident") if right_name == "gemini" else "") or "",
            "polymarket_slug": (yes_view.get("ident") if yes_venue == "polymarket" else no_view.get("ident") if no_venue == "polymarket" else "") or "",
            "polymarket_intent": poly_intent,
            "polymarket_api_price": format(poly_api, "f") if isinstance(poly_api, Decimal) else "",
            "fee_coefficient": poly_view.get("fee_coefficient") if isinstance(poly_view, dict) else None,
            "no_flipped_yes_bid": False,
            "no_reject": "",
        })
    return out


def polymarket_candidates(scan, game: dict, kalshi_events: list[dict], gemini_events: list[dict], contracts: list[dict]) -> list[dict]:
    """Same settlement only: moneyline player or team, Yes on one venue and No on the other."""
    if not contracts:
        return []
    for contract in contracts:
        assign_codes(game, contract)
    pm_views = []
    for contract in contracts:
        pm_views.extend(contract_views(contract))
    kalshi_views = scan.load_views(kalshi_events or [], "kalshi")
    gemini_views = scan.load_views(gemini_events or [], "gemini")
    rows = []
    if kalshi_views:
        rows.extend(_pair_rows(scan, game, "kalshi", kalshi_views, "polymarket", pm_views))
    if gemini_views:
        rows.extend(_pair_rows(scan, game, "gemini", gemini_views, "polymarket", pm_views))
    return rows


def _kalshi_open(series: str) -> list[dict]:
    rows = []
    cursor = ""
    for _ in range(10):
        query = {"series_ticker": series, "status": "open", "limit": "200"}
        if cursor:
            query["cursor"] = cursor
        payload = _get("https://api.elections.kalshi.com/trade-api/v2/events?" + urllib.parse.urlencode(query))
        batch = payload.get("events") or []
        if not isinstance(batch, list):
            break
        for event in batch:
            if isinstance(event, dict):
                event = dict(event)
                event["series"] = series
                rows.append(event)
        cursor = str(payload.get("cursor") or "")
        if not batch or not cursor:
            break
    return rows


def _polymarket_atp_events() -> list[dict]:
    found = []
    offset = 0
    for _ in range(20):
        query = urllib.parse.urlencode({"limit": 100, "offset": offset})
        payload = _get(f"{GATEWAY}/v2/sports/tennis/events?{query}")
        batch = payload.get("events") or []
        if not isinstance(batch, list) or not batch:
            break
        for event in batch:
            if not isinstance(event, dict):
                continue
            if event.get("seriesSlug") != "atp-2026":
                continue
            title = str(event.get("title") or "")
            if "/" in title:
                continue
            markets = []
            for market in event.get("markets") or []:
                parsed = two_way_moneyline(market)
                if parsed:
                    parsed["event_title"] = title
                    parsed["date"] = _date_from_slug(parsed["slug"]) or ""
                    markets.append(parsed)
            if len(markets) == 1:
                market = dict(markets[0])
                start = (
                    event.get("startTime")
                    or event.get("startDate")
                    or market.get("gameStartTime")
                    or market.get("endDate")
                    or ""
                )
                market["startTime"] = start
                market["gameStartTime"] = market.get("gameStartTime") or event.get("startTime") or ""
                market["period"] = _event_period(event)
                found.append({"title": title, "market": market, "startTime": start, "period": market["period"]})
        offset += len(batch)
        if len(batch) < 100:
            break
    return found


def _stamp_tennis_market(parsed: dict, event: dict, title: str) -> dict:
    row = dict(parsed)
    row["event_title"] = title
    row["date"] = _date_from_slug(row.get("slug") or "") or ""
    start = (
        event.get("startTime")
        or event.get("startDate")
        or row.get("gameStartTime")
        or row.get("endDate")
        or ""
    )
    row["startTime"] = start
    row["gameStartTime"] = row.get("gameStartTime") or event.get("startTime") or ""
    row["period"] = _event_period(event)
    return row


def _polymarket_tennis_event_books(event: dict) -> dict | None:
    """One moneyline plus any spreads on the same Polymarket US tennis event."""
    if not isinstance(event, dict):
        return None
    title = str(event.get("title") or "")
    if "/" in title:
        return None
    moneylines = []
    spreads = []
    for market in event.get("markets") or []:
        parsed = two_way_moneyline(market)
        if parsed:
            moneylines.append(_stamp_tennis_market(parsed, event, title))
            continue
        spr = two_way_spread(market)
        if spr:
            spreads.append(_stamp_tennis_market(spr, event, title))
    if len(moneylines) > 1:
        return None
    if len(moneylines) == 1:
        market = dict(moneylines[0])
        market["spread_markets"] = spreads
        return {"title": title, "market": market, "startTime": market.get("startTime") or "", "period": market.get("period") or ""}
    if not spreads:
        return None
    market = dict(spreads[0])
    market["spread_markets"] = spreads
    return {"title": title, "market": market, "startTime": market.get("startTime") or "", "period": market.get("period") or ""}


def _polymarket_tennis_events() -> list[dict]:
    """Polymarket US tennis moneylines and spreads, including WTA. Doubles are skipped."""
    found = []
    offset = 0
    for _ in range(20):
        query = urllib.parse.urlencode({"limit": 100, "offset": offset})
        payload = _get(f"{GATEWAY}/v2/sports/tennis/events?{query}")
        batch = payload.get("events") or []
        if not isinstance(batch, list) or not batch:
            break
        for event in batch:
            parsed = _polymarket_tennis_event_books(event)
            if parsed:
                found.append(parsed)
        offset += len(batch)
        if len(batch) < 100:
            break
    return found


def _kalshi_tennis_events() -> list[dict]:
    rows = []
    for series in KALSHI_TENNIS_SERIES:
        try:
            rows.extend(_kalshi_open(series))
        except Exception:
            continue
    return rows


def _short_tennis_title(title: str, market: dict | None = None) -> str:
    cleaned = re.sub(r"\s*\([^)]*\)", "", str(title or "")).strip()
    cleaned = re.sub(
        r"\s*:\s*(game spread|set spread|spread)\s*$",
        "",
        cleaned,
        flags=re.I,
    ).strip()
    if cleaned:
        return cleaned
    market = market or {}
    long_name = str(market.get("long_name") or "").strip()
    short_name = str(market.get("short_name") or "").strip()
    if long_name and short_name:
        return f"{long_name} vs {short_name}"
    return cleaned


def discover_tennis_matches() -> list[dict]:
    """Open Kalshi ATP and ATP Challenger matches with one Polymarket US moneyline twin."""
    kalshi = _kalshi_open("KXATPMATCH") + _kalshi_open("KXATPCHALLENGERMATCH")
    polymarket = _polymarket_atp_events()
    claimed: dict[str, int] = {}
    matches = []
    for event in kalshi:
        ticker = str(event.get("event_ticker") or "")
        title = re.sub(r"\s*\([^)]*\)", "", str(event.get("title") or event.get("sub_title") or "")).strip()
        when = _date_from_kalshi(ticker)
        if not ticker or not when or "/" in title:
            continue
        hits = []
        for row in polymarket:
            market = row["market"]
            if market.get("date") != when:
                continue
            if _players_match(title, row["title"]) or _players_match(title, f"{market['long_name']} vs {market['short_name']}"):
                hits.append(row)
        if len(hits) != 1:
            continue
        slug = hits[0]["market"]["slug"]
        claimed[slug] = claimed.get(slug, 0) + 1
        market = hits[0]["market"]
        start = (
            event.get("target_datetime")
            or event.get("strike_date")
            or hits[0].get("startTime")
            or market.get("startTime")
            or market.get("gameStartTime")
            or ""
        )
        matches.append({
            **market,
            "event_ticker": ticker,
            "title": title,
            "date": when,
            "series": event.get("series") or "",
            "startTime": start,
            "event_title": hits[0].get("title") or market.get("event_title") or title,
        })
    unique = [row for row in matches if claimed.get(row["slug"]) == 1]
    return unique


def _attach_kalshi_tennis_spreads(unique: list[dict]) -> list[dict]:
    """Hang GSPREAD/SSPREAD tickers on the MATCH row. Unmatched spreads stay as rows."""
    by_tail: dict[str, list] = {}
    for row in unique:
        tail = kalshi_tennis_tail(str(row.get("event_ticker") or ""))
        if tail:
            by_tail.setdefault(tail, []).append(row)
    spread_events = []
    for series in KALSHI_TENNIS_SPREAD_SERIES:
        try:
            spread_events.extend(_kalshi_open(series))
        except Exception:
            continue
    for event in spread_events:
        ticker = str(event.get("event_ticker") or "")
        if not ticker:
            continue
        tail = kalshi_tennis_tail(ticker)
        title = _short_tennis_title(str(event.get("title") or event.get("sub_title") or ""))
        when = _date_from_kalshi(ticker)
        start = event.get("target_datetime") or event.get("strike_date") or ""
        hits = by_tail.get(tail) or []
        if hits:
            for row in hits:
                bag = row.setdefault("spread_tickers", [])
                if isinstance(bag, list) and ticker not in bag:
                    bag.append(ticker)
                row.setdefault("spread_ticker", ticker)
            continue
        if not when or "/" in title:
            continue
        added = {
            "slug": "",
            "event_ticker": ticker,
            "title": title,
            "date": when,
            "series": event.get("series") or "",
            "startTime": start,
            "event_title": title,
            "long_name": "",
            "short_name": "",
            "kind": "spread",
            "number": "",
            "spread_tickers": [ticker],
            "spread_ticker": ticker,
        }
        unique.append(added)
        if tail:
            by_tail.setdefault(tail, []).append(added)
    return unique


def discover_all_tennis_books() -> list[dict]:
    """Every open Kalshi tennis moneyline/spread and every Polymarket US tennis book.

    Twins are merged into one row. Unmatched Kalshi or Polymarket books are kept.
    This is lookback tape, not the lock-only twin list.
    """
    kalshi = _kalshi_tennis_events()
    polymarket = _polymarket_tennis_events()
    claimed: dict[str, int] = {}
    used_tickers: set[str] = set()
    matches = []
    for event in kalshi:
        ticker = str(event.get("event_ticker") or "")
        title = _short_tennis_title(str(event.get("title") or event.get("sub_title") or ""))
        when = _date_from_kalshi(ticker)
        if not ticker or not when or "/" in title:
            continue
        hits = []
        for row in polymarket:
            market = row["market"]
            if market.get("date") != when:
                continue
            if _players_match(title, row["title"]) or _players_match(title, f"{market['long_name']} vs {market['short_name']}"):
                hits.append(row)
        if len(hits) != 1:
            continue
        slug = hits[0]["market"]["slug"]
        claimed[slug] = claimed.get(slug, 0) + 1
        market = hits[0]["market"]
        start = (
            event.get("target_datetime")
            or event.get("strike_date")
            or hits[0].get("startTime")
            or market.get("startTime")
            or market.get("gameStartTime")
            or ""
        )
        used_tickers.add(ticker)
        matches.append({
            **market,
            "event_ticker": ticker,
            "title": title,
            "date": when,
            "series": event.get("series") or "",
            "startTime": start,
            "event_title": hits[0].get("title") or market.get("event_title") or title,
        })
    unique = [row for row in matches if claimed.get(row["slug"]) == 1]
    used_slugs = {row["slug"] for row in unique if row.get("slug")}
    used_tickers = {row["event_ticker"] for row in unique if row.get("event_ticker")}
    for event in kalshi:
        ticker = str(event.get("event_ticker") or "")
        title = _short_tennis_title(str(event.get("title") or event.get("sub_title") or ""))
        when = _date_from_kalshi(ticker)
        if not ticker or ticker in used_tickers or not when or "/" in title:
            continue
        start = event.get("target_datetime") or event.get("strike_date") or ""
        unique.append({
            "slug": "",
            "event_ticker": ticker,
            "title": title,
            "date": when,
            "series": event.get("series") or "",
            "startTime": start,
            "event_title": title,
            "long_name": "",
            "short_name": "",
            "kind": "moneyline",
            "number": "",
        })
        used_tickers.add(ticker)
    for row in polymarket:
        market = row["market"]
        slug = str(market.get("slug") or "")
        if not slug or slug in used_slugs:
            continue
        title = _short_tennis_title(row.get("title") or "", market)
        if "/" in title:
            continue
        unique.append({
            **market,
            "event_ticker": "",
            "title": title,
            "date": market.get("date") or "",
            "series": "",
            "startTime": row.get("startTime") or market.get("startTime") or "",
            "event_title": row.get("title") or market.get("event_title") or title,
        })
        used_slugs.add(slug)
    return _attach_kalshi_tennis_spreads(unique)


def match_listed_start(match: dict):
    """Clocked match start from catalog / Polymarket / Kalshi metadata. None if date-only."""
    if not isinstance(match, dict):
        return None
    from price_memory import parse_time, to_et

    keys = (
        "startTime",
        "gameStartTime",
        "occurrence_datetime",
        "target_datetime",
        "listed_start",
        "start",
        "endDate",
        "startDate",
    )
    for key in keys:
        raw = match.get(key)
        if not raw or not isinstance(raw, str):
            continue
        text = raw.strip()
        if len(text) <= 10:
            continue
        when = parse_time(text)
        if when is not None:
            return to_et(when)
    return None


def load_tennis_matches(log=None, force: bool = False) -> list[dict]:
    """Cached public match list. A failed refresh keeps the previous list."""
    if not force and CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
            stamped = datetime.fromisoformat(str(cached.get("fetched_at")))
            if datetime.now(stamped.tzinfo) - stamped < timedelta(minutes=CACHE_MINUTES):
                rows = cached.get("matches")
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)]
        except Exception:
            pass
    try:
        matches = discover_tennis_matches()
    except Exception as exc:
        if log:
            log(f"polymarket tennis list failed {type(exc).__name__}")
        if CACHE.exists():
            try:
                cached = json.loads(CACHE.read_text(encoding="utf-8"))
                rows = cached.get("matches")
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)]
            except Exception:
                return []
        return []
    payload = {"fetched_at": datetime.now().astimezone().isoformat(), "matches": matches}
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass
    if log:
        log(f"polymarket tennis twins {len(matches)}")
    return matches


def load_all_tennis_books(log=None, force: bool = False) -> list[dict]:
    """Cached Kalshi + Polymarket tennis books, including singles without a twin."""
    if not force and ALL_CACHE.exists():
        try:
            cached = json.loads(ALL_CACHE.read_text(encoding="utf-8"))
            stamped = datetime.fromisoformat(str(cached.get("fetched_at")))
            if datetime.now(stamped.tzinfo) - stamped < timedelta(minutes=CACHE_MINUTES):
                rows = cached.get("matches")
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)]
        except Exception:
            pass
    try:
        matches = discover_all_tennis_books()
    except Exception as exc:
        if log:
            log(f"tennis all-books list failed {type(exc).__name__}")
        if ALL_CACHE.exists():
            try:
                cached = json.loads(ALL_CACHE.read_text(encoding="utf-8"))
                rows = cached.get("matches")
                if isinstance(rows, list) and rows:
                    return [row for row in rows if isinstance(row, dict)]
            except Exception:
                pass
        return load_tennis_matches(log=log, force=force)
    payload = {"fetched_at": datetime.now().astimezone().isoformat(), "matches": matches}
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        ALL_CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass
    if log:
        log(f"tennis books {len(matches)} (twins plus unmatched Kalshi/Polymarket)")
    return matches


def _num_key(value) -> str | None:
    """Same magnitude text the catalog uses, so 3.5 matches 3.50."""
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    number = abs(number)
    text = format(number.normalize(), "f")
    if text in ("-0", "-0.0"):
        return "0"
    return text


_PARTIAL = (
    "first_half", "second_half", "quarter", "inning", "first_five",
    "set_winner", "set-winner", "player", "prop", "team_total", "futures",
)


def _ou_name(text: str) -> str:
    low = _norm(text)
    if low == "over" or low.startswith("over "):
        return "over"
    if low == "under" or low.startswith("under "):
        return "under"
    return ""


def listed_handicap(market: dict, same_numbers: dict) -> dict | None:
    """Full-game spread or total whose number is already listed on Kalshi or Gemini."""
    if not isinstance(market, dict) or not isinstance(same_numbers, dict):
        return None
    detail = str(market.get("sportsMarketType") or "").lower()
    v2 = str(market.get("sportsMarketTypeV2") or "").upper()
    blob = " ".join([
        detail,
        str(market.get("slug") or "").lower(),
        str(market.get("question") or "").lower(),
    ])
    if any(word in blob for word in _PARTIAL):
        return None
    if "full_game_spread" in detail or (v2.endswith("SPREAD") and "full_game" in detail):
        kind = "spread"
    elif "full_game_total" in detail or (v2.endswith("TOTAL") and "full_game" in detail):
        kind = "total"
    else:
        return None
    number = _num_key(market.get("line"))
    if not number or number == "0":
        return None
    allowed = {str(item) for item in (same_numbers.get(kind) or set())}
    if number not in allowed:
        return None
    sides = market.get("marketSides") or []
    if not isinstance(sides, list) or len(sides) != 2:
        return None
    long_side = next((side for side in sides if isinstance(side, dict) and side.get("long") is True), None)
    short_side = next((side for side in sides if isinstance(side, dict) and side.get("long") is False), None)
    if long_side is None or short_side is None:
        return None
    long_name = str(long_side.get("description") or "").strip()
    short_name = str(short_side.get("description") or "").strip()
    if kind == "total":
        long_name = _ou_name(long_name)
        short_name = _ou_name(short_name)
        if {long_name, short_name} != {"over", "under"}:
            return None
    elif long_name.lower() in ("", "yes", "no") or short_name.lower() in ("", "yes", "no"):
        return None
    slug = str(market.get("slug") or "").strip()
    if not slug:
        return None
    theta = market.get("feeCoefficient")
    return {
        "slug": slug,
        "fee_coefficient": None if theta is None else str(theta),
        "long_name": long_name,
        "short_name": short_name,
        "kind": kind,
        "number": number,
    }


def _event_on_date(event: dict, date: str) -> bool:
    if not date:
        return True
    title = str(event.get("title") or "")
    if date in title:
        return True
    blob = " ".join(str(event.get(key) or "") for key in ("slug", "startTime", "startDate"))
    return date in blob


def markets_from_search(game: dict, same_numbers: dict | None = None) -> list[dict]:
    """Public search. One moneyline twin, plus a spread or total only when that number is already listed.

    same_numbers maps "spread" and "total" to the numbers on Kalshi or Gemini.
    No trading key. The international book is not called.
    """
    preset = game.get("polymarket_markets")
    if isinstance(preset, list) and preset:
        return [dict(row) for row in preset if isinstance(row, dict)]
    names = []
    for key in ("title_gemini", "title_kalshi"):
        title = str(game.get(key) or "")
        names.extend(_split_vs(title))
    query = " ".join(dict.fromkeys(part for part in names if part))
    if not query:
        return []
    date = str(game.get("date") or "")
    try:
        payload = _get(f"{GATEWAY}/v1/search?" + urllib.parse.urlencode({"query": query, "limit": "10"}))
    except Exception:
        return []
    hits = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict) or not _event_on_date(event, date):
            continue
        title = str(event.get("title") or "")
        for market in event.get("markets") or []:
            parsed = two_way_moneyline(market)
            if not parsed:
                continue
            parsed["event_title"] = title
            parsed["date"] = _date_from_slug(parsed["slug"]) or date
            if date and parsed["date"] and parsed["date"] != date:
                continue
            hits.append((event, parsed))
    slugs = {row["slug"] for _, row in hits}
    if len(slugs) != 1:
        return []
    event, moneyline = hits[0]
    rows = [moneyline]
    if not isinstance(same_numbers, dict):
        return rows
    title = str(event.get("title") or "")
    for market in event.get("markets") or []:
        parsed = listed_handicap(market, same_numbers)
        if not parsed:
            continue
        parsed["event_title"] = title
        parsed["date"] = _date_from_slug(parsed["slug"]) or date
        rows.append(parsed)
    seen = set()
    out = []
    for row in rows:
        slug = row.get("slug")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(row)
    return out


def blank_contracts(markets: list[dict]) -> list[dict]:
    rows = []
    for market in markets:
        if not isinstance(market, dict) or not market.get("slug"):
            continue
        rows.append({
            "slug": market.get("slug"),
            "fee_coefficient": market.get("fee_coefficient"),
            "long_name": market.get("long_name") or "",
            "short_name": market.get("short_name") or "",
            "long_code": market.get("long_code") or "",
            "short_code": market.get("short_code") or "",
            "event_title": market.get("event_title") or "",
            "kind": market.get("kind") or "moneyline",
            "number": market.get("number") or "",
            "yes_ask": None,
            "ask_size": Decimal("0"),
            "yes_bid": None,
            "bid_size": Decimal("0"),
        })
    return rows


def subscribe_message(slugs: list[str], request_id: str) -> dict:
    """Markets page subscribe. Full book, debounced, no trade or private channel."""
    return {
        "subscribe": {
            "requestId": request_id,
            "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
            "marketSlugs": slugs,
            "responsesDebounced": True,
        }
    }
