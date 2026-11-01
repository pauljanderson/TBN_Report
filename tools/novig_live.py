"""Novig quotes and optional order placement for the same-bet compare.

Production host is https://api.novig.com (docs: Environments).
Every request, including a catalog GET, is signed NOVIG-V3
(docs: Sign a request, Odds Screens):

- GET /v3/catalog/events?league=
- GET /v3/catalog/markets?league=&marketType=
- GET /v3/catalog/markets/{id}/book
- GET /v3/ws for the book channel
- POST /v3/orders (IOC) when NOVIG_ORDERS_ENABLED is True and a trading key is present

The key id is secrets/novig_api_key.txt (also tries novig_key_id.txt).
The PKCS8 private key is secrets/novig_api_secret.txt (also tries
novig_private_key.pem). Headers are Novig-Key-Id, Novig-Timestamp,
and Novig-Signature. This module never logs those headers or key material.

Every book order is a bid. The ask for one outcome is 1 minus the best bid
on the other outcome, and the size is that bid's quantity. A bid with no
quantity is not an ask.

Fee, official sources (do not invent a coefficient):
- https://docs.novig.com/api/concepts/fees
- https://docs.novig.com/fees
- https://support.novig.com/en/articles/16195057-fees-on-novig

Taker only. Maker pays 0. Same formula on Yes and No (symmetric in P and 1-P).
Fee = c × P × (1 − P) × N where P is the fill price in (0, 1), c is
market.fee.coefficient, N is $1-payout contracts. API qty is 1-cent units:
N = qty / 100. House 1-contract lock is qty=100, so N=1 and the dollar fee
is c × P × (1 − P), half-up to $0.00001.

WHEN_LIVE (game lines, every sport including tennis and NFL) charges only
while event.status is OPEN_INGAME; pregame / delayed / suspended is $0.
ALWAYS (eligible futures) charges in every phase. Read c and charged from
the market. A missing coefficient or unrecognized charge rule is fee unknown
(skip send). Do not guess 0 or 0.06.

GET /v3/portfolio/fills puts `fee` on a charged fill and omits it when the
fill was not charged. Sibling settled-P&L: use that field after a fill;
absent fee on a found fill is $0 uncharged, not unknown.

Orders stay behind NOVIG_ORDERS_ENABLED (default False) until a dry-signed
check shows a trading (subaccount) key. A management key can read the catalog
and the cash wallet but cannot place.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

import venue_pace

ROOT = Path(__file__).resolve().parents[1]
# Prefer the names Paul updated; fall back to older key_id / pem names.
KEY_CANDIDATES = (
    ROOT / "secrets" / "novig_api_key.txt",
    ROOT / "secrets" / "novig_key_id.txt",
)
SECRET_CANDIDATES = (
    ROOT / "secrets" / "novig_api_secret.txt",
    ROOT / "secrets" / "novig_private_key.pem",
)
HOST = "https://api.novig.com"
WS_URL = "wss://api.novig.com/v3/ws"
WS_PATH = "/v3/ws"
UA = {"User-Agent": "stockresearch-public-quote-scan/1.0", "Accept": "application/json"}
ET = ZoneInfo("America/New_York")
ONE = Decimal("1")
HUNDRED = Decimal("100")
# One $1 lock leg is 100 native contracts (each pays 1 cent).
DOLLAR_QTY = 100
FEE_QUANT = Decimal("0.00001")
MILLI = Decimal("0.001")
EMPTY_BODY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
CACHE_SEC = 120
STATUS_CACHE_SEC = 20
PAGE_LIMIT = 500
MAX_PAGES = 12
# Hard switch. False: quotes only. True only when a trading subaccount key is wired.
NOVIG_ORDERS_ENABLED = True
ORDER_POLL_SEC = 0.15
ORDER_POLL_TRIES = 40
_trading_ok: bool | None = None
_trading_note = "not probed"

# League names from the documented catalog. Challenger and other unnamed
# leagues are not guessed.
LEAGUES = (
    "NCAAF", "NCAAB", "NCAAWB", "WNBA", "NBA", "NHL", "MLB", "NFL",
    "Champions League", "Europa League", "FIFA Club World Cup",
    "Bundesliga", "Serie A", "La Liga", "Ligue 1", "EPL", "MLS",
    "WTA", "ATP", "UFC", "PGA",
)
SPORT_LEAGUES = {
    "pro football": ("NFL",),
    "college football": ("NCAAF",),
    "pro basketball": ("NBA", "WNBA"),
    "basketball": ("NBA", "WNBA"),
    "pro baseball": ("MLB",),
    "pro hockey": ("NHL",),
    "hockey": ("NHL",),
    "mma": ("UFC",),
    "golf": ("PGA",),
    "tennis": ("ATP", "WTA"),
    "soccer": ("EPL", "MLS", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Champions League"),
}
# Fee is zero outside OPEN_INGAME when the market says WHEN_LIVE.
QUIET_STATUSES = {"OPEN_PREGAME", "DELAYED", "SUSPENDED", "CLOSED", "SETTLED", "CANCELED", "CANCELLED", "FINAL"}
FEE_CHARGED = {"WHEN_LIVE", "ALWAYS"}
_cache_lock = threading.Lock()
_league_cache: dict[str, tuple[float, list, list]] = {}
_status_cache: dict[str, tuple[float, str]] = {}
_fee_cache: dict[str, tuple[float, str | None, str]] = {}
_signer_lock = threading.Lock()
_signer: tuple | None = None
_signer_failed = False


def _first_secret_file(candidates: tuple[Path, ...]) -> Path | None:
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except OSError:
            continue
    return None


def keys_present() -> bool:
    """True when both key files exist and are non-empty. Does not read them aloud."""
    return _first_secret_file(KEY_CANDIDATES) is not None and _first_secret_file(SECRET_CANDIDATES) is not None


def _pct_decode(part: str) -> bytes:
    raw = part.encode("utf-8")
    out = bytearray()
    index = 0
    while index < len(raw):
        if raw[index] == 0x25 and index + 2 < len(raw):
            try:
                out.append(int(raw[index + 1:index + 3].decode("ascii"), 16))
                index += 3
                continue
            except ValueError:
                pass
        out.append(raw[index])
        index += 1
    return bytes(out)


def _pct_encode(raw: bytes) -> str:
    pieces = []
    for byte in raw:
        if byte in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~":
            pieces.append(chr(byte))
        else:
            pieces.append(f"%{byte:02X}")
    return "".join(pieces)


def canonical_query(raw: str) -> str:
    """Line 5 of NOVIG-V3. Empty when the request has no query."""
    pairs = []
    for pair in (raw or "").split("&"):
        if not pair:
            continue
        name, _, value = pair.partition("=")
        pairs.append((_pct_encode(_pct_decode(name)), _pct_encode(_pct_decode(value))))
    pairs.sort()
    return "&".join(f"{name}={value}" for name, value in pairs)


def _load_signer() -> tuple | None:
    """Key id plus private key object. None when a file is missing or not a signing key."""
    global _signer, _signer_failed
    with _signer_lock:
        if _signer is not None:
            return _signer
        if _signer_failed or not keys_present():
            return None
        try:
            key_path = _first_secret_file(KEY_CANDIDATES)
            secret_path = _first_secret_file(SECRET_CANDIDATES)
            if key_path is None or secret_path is None:
                _signer_failed = True
                return None
            key_id = key_path.read_text(encoding="utf-8").strip()
            pem = secret_path.read_bytes()
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec, ed25519
            private_key = serialization.load_pem_private_key(pem, password=None)
            if not isinstance(private_key, (ed25519.Ed25519PrivateKey, ec.EllipticCurvePrivateKey)):
                _signer_failed = True
                return None
            _signer = (key_id, private_key)
            return _signer
        except Exception:
            _signer_failed = True
            return None


def signature_headers(method: str, path: str, raw_query: str, body: bytes = b"") -> dict[str, str] | None:
    """NOVIG-V3 headers. Callers must not log the return value."""
    loaded = _load_signer()
    if loaded is None:
        return None
    key_id, private_key = loaded
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    timestamp = str(int(time.time() * 1000))
    digest = hashlib.sha256(body).hexdigest()
    signed = "\n".join(["NOVIG-V3", timestamp, method.upper(), path, canonical_query(raw_query), digest]).encode("utf-8")
    try:
        if isinstance(private_key, ed25519.Ed25519PrivateKey):
            raw = private_key.sign(signed)
        elif isinstance(private_key, ec.EllipticCurvePrivateKey):
            raw = private_key.sign(signed, ec.ECDSA(hashes.SHA256()))
        else:
            return None
    except Exception:
        return None
    return {
        "Novig-Key-Id": key_id,
        "Novig-Timestamp": timestamp,
        "Novig-Signature": base64.b64encode(raw).decode("ascii"),
    }


def snap_price(price: Decimal) -> Decimal | None:
    """Snap down to the documented Novig price grid. Never pay more than `price`."""
    try:
        milli = int((price * Decimal("1000")).to_integral_value(rounding=ROUND_HALF_UP))
    except Exception:
        return None
    if milli < 1 or milli > 999:
        return None
    if 1 <= milli <= 50 or 950 <= milli <= 999:
        snapped = milli
    elif 51 <= milli <= 949:
        snapped = milli - (milli % 5)
    else:
        return None
    if snapped < 1:
        return None
    out = (Decimal(snapped) / Decimal("1000")).quantize(MILLI)
    if out <= 0 or out >= ONE:
        return None
    return out


def iter_grid_prices():
    """Every submittable price from cheapest to dearest."""
    for milli in range(1, 51):
        yield Decimal(milli) / Decimal("1000")
    for milli in range(55, 950, 5):
        yield Decimal(milli) / Decimal("1000")
    for milli in range(950, 1000):
        yield Decimal(milli) / Decimal("1000")


def _signed_http(
    method: str,
    path: str,
    query: str = "",
    body: dict | None = None,
    pace: bool = True,
    timeout: float = 30,
    priority: bool = False,
) -> tuple[int, str]:
    """Signed REST call. Returns HTTP status and body text. Never logs auth headers."""
    held = False
    if pace or priority:
        prio = venue_pace.PRIORITY_SEND if priority else venue_pace.PRIORITY_BACKGROUND
        if not venue_pace.wait_turn("novig", priority=prio):
            return 0, getattr(venue_pace, "SKIPPED", "http budget skip")
        held = True
    try:
        data = b"" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        signed = signature_headers(method, path, query, data)
        if signed is None:
            return 0, "novig key files are missing or not a signing key"
        headers = dict(UA)
        headers.update(signed)
        if body is not None:
            headers["Content-Type"] = "application/json"
        url = HOST + path + (("?" + query) if query else "")
        req = urllib.request.Request(url, data=data or None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return 0, type(exc).__name__ + " " + str(exc)[:160]
    finally:
        if held:
            venue_pace.release_turn("novig")


def trading_key_ready() -> tuple[bool, str]:
    """True when the key can trade a subaccount. Management-only keys stay false.

    Dry check only: GET /v3/account/orders. A management key returns a map keyed
    by key id. A trading key returns a bare {seq, open} object. Does not place.
    """
    global _trading_ok, _trading_note
    if _trading_ok is not None:
        return _trading_ok, _trading_note
    if not keys_present() or _load_signer() is None:
        _trading_ok = False
        _trading_note = "signer unavailable"
        return _trading_ok, _trading_note
    status, body = _signed_http("GET", "/v3/account/orders", pace=True)
    if status != 200:
        _trading_ok = False
        _trading_note = f"account orders http {status}"
        return _trading_ok, _trading_note
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        _trading_ok = False
        _trading_note = "account orders not json"
        return _trading_ok, _trading_note
    # Trading / session key: bare snapshot. Management key: map of keyId -> snapshot.
    if isinstance(payload, dict) and "open" in payload and "seq" in payload:
        _trading_ok = True
        _trading_note = "trading key"
        return _trading_ok, _trading_note
    _trading_ok = False
    _trading_note = "management key only; open a funded trading subaccount key for orders"
    return _trading_ok, _trading_note


def orders_live() -> bool:
    """True when the flag is on and a trading key passed the dry check."""
    if not NOVIG_ORDERS_ENABLED:
        return False
    ok, _note = trading_key_ready()
    return ok


def balance_usd() -> tuple[int, Decimal | None]:
    """Buying power in dollars. Prefer the trading subaccount; fall back to wallet."""
    loaded = _load_signer()
    if loaded is None:
        return 0, None
    key_id, _private = loaded
    # Trading subaccount address is the trading key id.
    status, body = _signed_http("GET", f"/v3/account/subaccounts/{urllib.parse.quote(key_id, safe='')}/balance")
    if status == 200:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            amount = None
            try:
                amount = Decimal(str(payload.get("balance")))
            except Exception:
                amount = None
            if amount is not None:
                return status, amount
    # Management wallet (cash, not a trading desk).
    status2, body2 = _signed_http("GET", "/v3/account/balance")
    if status2 != 200:
        return status if status else status2, None
    try:
        payload = json.loads(body2)
        amount = Decimal(str(payload.get("balance")))
    except Exception:
        return status2, None
    return status2, amount


def order_body(outcome_id: str, price: Decimal, client_id: str | None = None) -> dict | None:
    """One $1-equivalent IOC buy. qty is 100 native contracts."""
    snapped = snap_price(price)
    if snapped is None or not outcome_id:
        return None
    body = {
        "outcomeId": outcome_id,
        "price": format(snapped, "f"),
        "qty": DOLLAR_QTY,
        "tif": "IOC",
    }
    if client_id:
        body["clientId"] = client_id
    return body


def place_order(body: dict) -> tuple[int, dict | None, str]:
    """POST /v3/orders. Does not place when orders_live() is false."""
    if not orders_live():
        return 0, None, "novig orders off or trading key missing"
    if not isinstance(body, dict):
        return 0, None, "missing body"
    status, text = _signed_http("POST", "/v3/orders", body=body, priority=True)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    payload = payload if isinstance(payload, dict) else None
    note = ""
    if isinstance(payload, dict):
        note = str(payload.get("code") or payload.get("message") or "")
    elif text:
        note = text[:200]
    return status, payload, note or f"http {status}"


def get_order(order_id: str) -> tuple[int, dict | None, str]:
    if not order_id:
        return 0, None, "no order id"
    status, text = _signed_http("GET", "/v3/orders/" + urllib.parse.quote(order_id, safe=""))
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and "orderId" in payload:
        return status, payload, str(payload.get("status") or "")
    # Management map unwrap.
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, dict) and value.get("orderId"):
                return status, value, str(value.get("status") or "")
    return status, payload if isinstance(payload, dict) else None, text[:200]


FILLS_PATH = "/v3/portfolio/fills"
# Docs: https://docs.novig.com/api-reference/execution/list-fills


def list_fills(query: dict | None = None, timeout: float = 30) -> tuple[int, str]:
    """GET /v3/portfolio/fills. Read-only. Does not place or cancel."""
    params = query or {}
    raw = urllib.parse.urlencode(params, doseq=True)
    return _signed_http("GET", FILLS_PATH, query=raw, timeout=timeout)


def cancel_order(order_id: str) -> tuple[int, str]:
    if not order_id or not orders_live():
        return 0, "no order id"
    status, text = _signed_http("DELETE", "/v3/orders/" + urllib.parse.quote(order_id, safe=""))
    return status, text[:200]


def wait_order_terminal(order_id: str, poll_sec: float = ORDER_POLL_SEC, tries: int = ORDER_POLL_TRIES) -> dict | None:
    """Poll GET /v3/orders/{id} until FILLED / CANCELED / REJECTED or tries run out."""
    last = None
    for _ in range(max(1, tries)):
        status, payload, _note = get_order(order_id)
        if status == 200 and isinstance(payload, dict):
            last = payload
            state = str(payload.get("status") or "").upper()
            if state in ("FILLED", "CANCELED", "REJECTED"):
                return payload
        time.sleep(poll_sec)
    return last


def filled_dollar_contracts(order_payload: dict | None) -> Decimal:
    """How many $1 lock units filled. Native qty 100 == size 1."""
    if not isinstance(order_payload, dict):
        return Decimal("0")
    try:
        qty = Decimal(str(order_payload.get("qty") or "0"))
        remaining = Decimal(str(order_payload.get("remaining") if order_payload.get("remaining") is not None else qty))
    except Exception:
        return Decimal("0")
    filled_native = qty - remaining
    if filled_native <= 0:
        state = str(order_payload.get("status") or "").upper()
        if state == "FILLED":
            filled_native = qty
        else:
            return Decimal("0")
    return (filled_native / HUNDRED).quantize(Decimal("0.01"))


def _error_code(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("code") or "")[:80]


def _get(path: str, query: dict | None = None, *, pace: bool = True, retry: bool = True) -> dict | list:
    """Signed catalog GET. Waits the Novig HTTP slot unless pace is off.

    A websocket apply must not call this. Catalog/live lock rechecks pass
    pace=False and retry=False so a 429 is named once instead of sleeping.
    """
    held = False
    if pace:
        if not venue_pace.wait_turn("novig"):
            return {}
        held = True
    try:
        raw_query = urllib.parse.urlencode(query or {}, doseq=True, quote_via=urllib.parse.quote)
        delay = 2
        last_error: Exception | None = None
        attempts = 3 if retry else 1
        for _ in range(attempts):
            signed = signature_headers("GET", path, raw_query, b"")
            if signed is None:
                raise RuntimeError("novig key files are missing or not a signing key")
            headers = dict(UA)
            headers.update(signed)
            url = HOST + path + (("?" + raw_query) if raw_query else "")
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    payload = json.load(response)
                return payload if isinstance(payload, (dict, list)) else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    last_error = RuntimeError("novig http 429")
                    if not retry:
                        raise last_error from None
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise RuntimeError(f"novig http {exc.code} {_error_code(exc)}".strip()) from None
            except Exception as exc:
                last_error = exc
                raise
        if last_error:
            raise last_error
        return {}
    finally:
        if held:
            venue_pace.release_turn("novig")


def _pages(path: str, query: dict) -> list[dict]:
    rows: list[dict] = []
    cursor = ""
    for _ in range(MAX_PAGES):
        params = dict(query)
        params["limit"] = str(PAGE_LIMIT)
        if cursor:
            params["after"] = cursor
        payload = _get(path, params)
        if not isinstance(payload, dict):
            break
        batch = payload.get("items") or []
        if not isinstance(batch, list):
            break
        rows.extend(row for row in batch if isinstance(row, dict))
        cursor = str(payload.get("next") or "")
        if not cursor or len(batch) < PAGE_LIMIT:
            break
    return rows


def _league_rows(league: str) -> tuple[list[dict], list[dict]]:
    now = time.time()
    with _cache_lock:
        cached = _league_cache.get(league)
        if cached and now - cached[0] < CACHE_SEC:
            return cached[1], cached[2]
    try:
        events = _pages("/v3/catalog/events", {"league": league})
        markets = _pages("/v3/catalog/markets", {"league": league, "marketType": "MONEY,SPREAD,TOTAL"})
    except Exception:
        with _cache_lock:
            cached = _league_cache.get(league)
        if cached:
            return cached[1], cached[2]
        return [], []
    with _cache_lock:
        _league_cache[league] = (time.time(), events, markets)
    return events, markets


def event_status(event_id: str, fallback: str = "") -> str:
    """Public event status. A failed refresh keeps the last known status."""
    if not event_id:
        return fallback
    now = time.time()
    with _cache_lock:
        cached = _status_cache.get(event_id)
        if cached and now - cached[0] < STATUS_CACHE_SEC:
            return cached[1]
    try:
        payload = _get("/v3/catalog/events/" + urllib.parse.quote(event_id, safe=""))
    except Exception:
        return fallback
    status = str(payload.get("status") or fallback) if isinstance(payload, dict) else fallback
    if status:
        with _cache_lock:
            _status_cache[event_id] = (time.time(), status)
    return status or fallback


def _fee_fields(market: dict | None) -> tuple[str | None, str]:
    """coefficient, charged from a catalog market. Empty when the object is missing."""
    if not isinstance(market, dict):
        return None, ""
    fee = market.get("fee") if isinstance(market.get("fee"), dict) else {}
    coef = None if fee.get("coefficient") in (None, "") else str(fee.get("coefficient"))
    return coef, str(fee.get("charged") or "")


def fetch_market(market_id: str, *, pace: bool = True, retry: bool = True) -> dict | None:
    """GET /v3/catalog/markets/{id}. Returns the market object or None."""
    if not market_id:
        return None
    try:
        payload = _get(
            "/v3/catalog/markets/" + urllib.parse.quote(market_id, safe=""),
            pace=pace,
            retry=retry,
        )
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def fetch_market_fee(market_id: str, *, pace: bool = True) -> tuple[str | None, str]:
    """Live coefficient and charged from GET /v3/catalog/markets/{id}. Cached."""
    if not market_id:
        return None, ""
    now = time.time()
    with _cache_lock:
        cached = _fee_cache.get(market_id)
        if cached and now - cached[0] < CACHE_SEC:
            return cached[1], cached[2]
    market = fetch_market(market_id, pace=pace)
    coef, charged = _fee_fields(market)
    with _cache_lock:
        _fee_cache[market_id] = (time.time(), coef, charged)
    return coef, charged


def ensure_fee_schedule(contract: dict, *, fetch: bool = True) -> dict:
    """Fill fee_coefficient / fee_charged from the catalog when missing. Does not invent 0.06."""
    if not isinstance(contract, dict):
        return contract
    coef = contract.get("fee_coefficient")
    charged = str(contract.get("fee_charged") or "")
    need_coef = coef in (None, "")
    need_charged = charged not in FEE_CHARGED
    # A named but unrecognized charged (tests, stale tape) stays unknown. Do not overwrite.
    if fetch and (need_coef or charged == ""):
        market_id = str(contract.get("market_id") or contract.get("ident") or "")
        if market_id:
            got_coef, got_charged = fetch_market_fee(market_id)
            if need_coef and got_coef not in (None, ""):
                contract["fee_coefficient"] = got_coef
                coef = got_coef
            if need_charged and got_charged in FEE_CHARGED:
                contract["fee_charged"] = got_charged
                charged = got_charged
    if charged == "WHEN_LIVE":
        status = str(contract.get("event_status") or "")
        if status != "OPEN_INGAME" and status not in QUIET_STATUSES:
            refreshed = event_status(str(contract.get("event_id") or ""), status)
            if refreshed:
                contract["event_status"] = refreshed
    return contract


def taker_fee(price: Decimal | None, coefficient, charged: str | None, event_status_value: str | None) -> Decimal | None:
    """Dollar fee for one $1-payout contract. None when the schedule is not on the market.

    Official: Fee = c × P × (1 − P) × N. This helper is N=1 (house $1 lock).
    Sibling settled-P&L: after a fill prefer fill.fee from GET /v3/portfolio/fills
    (fee_from_fills). Do not guess 0.06 when coefficient is missing.
    """
    if price is None:
        return None
    rule = str(charged or "")
    if rule == "WHEN_LIVE":
        status = str(event_status_value or "")
        if status == "OPEN_INGAME":
            pass
        elif status in QUIET_STATUSES or status == "OPEN":
            # Catalog event.status OPEN is not OPEN_INGAME. Docs: charge only
            # while OPEN_INGAME; pregame / delayed / suspended is $0.
            return Decimal("0")
        else:
            return None
    elif rule != "ALWAYS":
        return None
    if coefficient in (None, ""):
        return None
    try:
        coef = Decimal(str(coefficient))
    except Exception:
        return None
    if coef < 0:
        return None
    exact = coef * price * (ONE - price)
    return exact.quantize(FEE_QUANT, rounding=ROUND_HALF_UP)


def fee_from_fills(fills) -> Decimal | None:
    """Sum fill.fee from GET /v3/portfolio/fills.

    None when there are no fill rows. 0 when rows exist but `fee` is absent
    (docs: uncharged maker / non-live fill omits the field).
    """
    rows = [row for row in (fills or []) if isinstance(row, dict)]
    if not rows:
        return None
    total = Decimal("0")
    for row in rows:
        if row.get("fee") in (None, ""):
            continue
        try:
            total += Decimal(str(row.get("fee")))
        except Exception:
            continue
    return total.quantize(FEE_QUANT, rounding=ROUND_HALF_UP)


def _num_key(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        number = abs(Decimal(str(value)))
    except Exception:
        return None
    text = format(number.normalize(), "f")
    if text in ("-0", "-0.0"):
        return "0"
    return text


def _norm(text: str | None) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _split_sides(title: str) -> list[str]:
    parts = re.split(r"\s+(?:@|vs\.?|at)\s+", title or "", maxsplit=1, flags=re.I)
    return [part.strip() for part in parts if part.strip()]


def _names_match(left: str, right: str) -> bool:
    a = _norm(left)
    b = _norm(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    apart = a.split()
    bpart = b.split()
    if apart[-1] == bpart[-1] and len(apart[-1]) >= 3:
        return True
    return False


def _et_date(starts_ts) -> str:
    try:
        millis = int(starts_ts)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(millis / 1000, ET).date().isoformat()


def _best_level(orders: dict, outcome_id: str) -> tuple[Decimal | None, Decimal]:
    rows = orders.get(outcome_id) if isinstance(orders, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, Decimal("0")
    first = rows[0] if isinstance(rows[0], dict) else None
    if not first:
        return None, Decimal("0")
    try:
        price = Decimal(str(first.get("price")))
    except Exception:
        return None, Decimal("0")
    qty = Decimal("0")
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            row_price = Decimal(str(row.get("price")))
            row_qty = Decimal(str(row.get("qty")))
        except Exception:
            continue
        if row_price != price or row_qty <= 0:
            if qty > 0:
                break
            continue
        qty += row_qty
    if qty <= 0:
        return None, Decimal("0")
    # Native qty pays 1 cent each. Divide by 100 so size 1 pays $1, like the other books.
    return price, (qty / HUNDRED)


def _sized_ask(bid: Decimal | None, qty: Decimal) -> tuple[Decimal | None, Decimal]:
    """Ask on the other outcome. No bid, or a zero quantity, is not an ask."""
    if bid is None or qty <= 0:
        return None, Decimal("0")
    ask = ONE - bid
    if ask <= 0 or ask >= 1:
        return None, Decimal("0")
    return ask, qty


def refresh_quotes(contract: dict) -> bool:
    """Write yes/no asks from the stored bids. Returns whether the shown ask changed."""
    before = (
        contract.get("yes_ask"), contract.get("ask_size"),
        contract.get("no_ask"), contract.get("no_ask_size"),
    )
    orders = contract.get("orders") if isinstance(contract.get("orders"), dict) else {}
    yes_bid, yes_qty = _best_level(orders, str(contract.get("yes_outcome") or ""))
    no_bid, no_qty = _best_level(orders, str(contract.get("no_outcome") or ""))
    yes_ask, yes_size = _sized_ask(no_bid, no_qty)
    no_ask, no_size = _sized_ask(yes_bid, yes_qty)
    contract["yes_ask"] = yes_ask
    contract["ask_size"] = yes_size
    contract["no_ask"] = no_ask
    contract["no_ask_size"] = no_size
    after = (yes_ask, yes_size, no_ask, no_size)
    return after != before


def apply_rest_book(contract: dict, book: dict) -> bool:
    """Replace the ladders from a public REST book. Does not read a key."""
    orders = book.get("orders") if isinstance(book, dict) else None
    if not isinstance(orders, dict):
        return False
    contract["orders"] = orders
    if book.get("seq") is not None:
        contract["book_seq"] = book.get("seq")
    return refresh_quotes(contract)


def _order_key(row: dict) -> str:
    return str(row.get("orderId") or row.get("order") or "")


def apply_stream_book(contract: dict, book: dict) -> bool:
    """Snapshot or delta from the book channel. Gaps ask the caller to resnapshot."""
    if not isinstance(book, dict):
        return False
    if isinstance(book.get("orders"), dict):
        contract["book_gap"] = False
        return apply_rest_book(contract, book)
    deltas = book.get("deltas")
    if not isinstance(deltas, list):
        return False
    seq = book.get("seq")
    prev = contract.get("book_seq")
    if seq is not None and prev is not None:
        try:
            if int(seq) != int(prev) + 1:
                contract["book_gap"] = True
                return False
        except (TypeError, ValueError):
            contract["book_gap"] = True
            return False
    orders = contract.setdefault("orders", {})
    if not isinstance(orders, dict):
        orders = {}
        contract["orders"] = orders
    for delta in deltas:
        if not isinstance(delta, dict):
            continue
        kind = str(delta.get("kind") or "")
        if kind == "remove":
            order_id = _order_key(delta)
            for outcome_id, rows in list(orders.items()):
                if not isinstance(rows, list):
                    continue
                orders[outcome_id] = [row for row in rows if _order_key(row) != order_id]
        elif kind == "add":
            outcome_id = str(delta.get("outcome") or delta.get("outcomeId") or "")
            order_id = _order_key(delta)
            if not outcome_id or not order_id:
                continue
            rows = [row for row in (orders.get(outcome_id) or []) if _order_key(row) != order_id]
            rows.append({
                "orderId": order_id,
                "price": delta.get("price"),
                "qty": delta.get("qty"),
            })
            rows.sort(key=lambda row: Decimal(str(row.get("price") or "0")), reverse=True)
            orders[outcome_id] = rows
    if book.get("seq") is not None:
        contract["book_seq"] = book.get("seq")
    contract["book_gap"] = False
    return refresh_quotes(contract)


def on_stream_message(contracts: dict[str, dict], payload: dict) -> bool:
    """Apply one websocket JSON object. True when a shown ask changed."""
    if not isinstance(payload, dict):
        return False
    changed = False
    snapshot = payload.get("snapshot")
    delta = payload.get("delta")
    body = snapshot if isinstance(snapshot, dict) else delta if isinstance(delta, dict) else None
    if not isinstance(body, dict):
        return False
    for market_id, entry in body.items():
        contract = contracts.get(str(market_id))
        if contract is None or not isinstance(entry, dict):
            continue
        life = entry.get("lifecycle") if isinstance(entry.get("lifecycle"), dict) else None
        if life and life.get("status"):
            contract["market_status"] = str(life.get("status"))
        book = entry.get("book")
        if isinstance(book, dict) and apply_stream_book(contract, book):
            changed = True
    return changed


def _team_name(name: str) -> bool:
    text = (name or "").strip()
    if not text or text.lower() in ("yes", "no", "over", "under"):
        return False
    if re.search(r"[+-]\d", text):
        return False
    return True


def _spread_sides(outcomes: list[dict]) -> tuple[str, str, str, str, str] | None:
    """Minus side is 'wins by more than'. The plus side is that bet's No, not its own spread."""
    parsed = []
    for outcome in outcomes:
        name = str(outcome.get("name") or "").strip()
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]{1,8})\s+([+-])(\d+(?:\.\d+)?)", name)
        if not match:
            return None
        parsed.append((outcome, match.group(1).upper(), match.group(2), _num_key(match.group(3))))
    if len(parsed) != 2:
        return None
    minus = [row for row in parsed if row[2] == "-"]
    plus = [row for row in parsed if row[2] == "+"]
    if len(minus) != 1 or len(plus) != 1:
        return None
    if not minus[0][3] or minus[0][3] != plus[0][3] or minus[0][3] == "0":
        return None
    return (
        str(minus[0][0].get("outcomeId") or ""),
        minus[0][1],
        str(plus[0][0].get("outcomeId") or ""),
        plus[0][1],
        minus[0][3],
    )


def _spread_sides_named(outcomes: list[dict]) -> tuple[str, str, str, str, str] | None:
    """Tennis (and other) 'Name -3.5' / 'Name +3.5' where the name is not a team code."""
    parsed = []
    for outcome in outcomes:
        name = str(outcome.get("name") or "").strip()
        match = re.fullmatch(r"(.+?)\s+([+-])(\d+(?:\.\d+)?)", name)
        if not match:
            return None
        who = match.group(1).strip()
        if not who or who.lower() in ("over", "under", "yes", "no"):
            return None
        parsed.append((outcome, who, match.group(2), _num_key(match.group(3))))
    if len(parsed) != 2:
        return None
    minus = [row for row in parsed if row[2] == "-"]
    plus = [row for row in parsed if row[2] == "+"]
    if len(minus) != 1 or len(plus) != 1:
        return None
    if not minus[0][3] or minus[0][3] != plus[0][3] or minus[0][3] == "0":
        return None
    return (
        str(minus[0][0].get("outcomeId") or ""),
        minus[0][1],
        str(plus[0][0].get("outcomeId") or ""),
        plus[0][1],
        minus[0][3],
    )


def _total_sides(outcomes: list[dict]) -> tuple[str, str, str] | None:
    over_id = under_id = number = ""
    for outcome in outcomes:
        name = str(outcome.get("name") or "").strip()
        match = re.fullmatch(r"(Over|Under)\s+(\d+(?:\.\d+)?)", name, flags=re.I)
        if not match:
            return None
        key = _num_key(match.group(2))
        if number and key != number:
            return None
        number = key or ""
        if match.group(1).lower() == "over":
            over_id = str(outcome.get("outcomeId") or "")
        else:
            under_id = str(outcome.get("outcomeId") or "")
    if not over_id or not under_id or not number or number == "0":
        return None
    return over_id, under_id, number


def parse_market(market: dict, event_status_value: str, same_numbers: dict | None, sport: str = "") -> dict | None:
    """One full-game moneyline, favorite spread, or total. Anything else is skipped.

    Tennis spreads are recorded even when Kalshi/Gemini have not listed that
    number. Other sports still require the number to already be on the tape.
    """
    if not isinstance(market, dict):
        return None
    if str(market.get("status") or "").upper() not in ("", "OPEN"):
        return None
    kind = str(market.get("marketType") or "").upper()
    if kind not in ("MONEY", "SPREAD", "TOTAL"):
        return None
    outcomes = [row for row in (market.get("outcomes") or []) if isinstance(row, dict)]
    if len(outcomes) != 2:
        return None
    coef, charged = _fee_fields(market)
    base = {
        "market_id": str(market.get("marketId") or ""),
        "event_id": str(market.get("eventId") or ""),
        "fee_coefficient": coef,
        "fee_charged": charged,
        "event_status": event_status_value or "",
        "orders": {},
        "yes_ask": None,
        "ask_size": Decimal("0"),
        "no_ask": None,
        "no_ask_size": Decimal("0"),
    }
    if not base["market_id"]:
        return None
    if kind == "MONEY":
        if not all(_team_name(str(row.get("name") or "")) for row in outcomes):
            return None
        strike = _num_key(market.get("strike"))
        if strike not in (None, "0"):
            return None
        return {
            **base,
            "kind": "moneyline",
            "side": str(outcomes[0].get("name") or "").strip(),
            "other_side": str(outcomes[1].get("name") or "").strip(),
            "number": "",
            "yes_outcome": str(outcomes[0].get("outcomeId") or ""),
            "no_outcome": str(outcomes[1].get("outcomeId") or ""),
        }
    tennis = str(sport or "").strip().lower() == "tennis"
    allowed = {str(item) for item in ((same_numbers or {}).get("spread" if kind == "SPREAD" else "total") or set())}
    if kind == "SPREAD":
        sides = _spread_sides(outcomes)
        if sides is None and tennis:
            sides = _spread_sides_named(outcomes)
        if sides is None:
            return None
        yes_id, yes_name, no_id, _no_name, number = sides
        strike = _num_key(market.get("strike"))
        if strike and strike != number:
            return None
        if not tennis and number not in allowed:
            return None
        return {
            **base,
            "kind": "spread",
            "side": yes_name,
            "other_side": "",
            "number": number,
            "yes_outcome": yes_id,
            "no_outcome": no_id,
        }
    sides = _total_sides(outcomes)
    if sides is None:
        return None
    over_id, under_id, number = sides
    if number not in allowed:
        return None
    return {
        **base,
        "kind": "total",
        "side": "over",
        "other_side": "under",
        "number": number,
        "yes_outcome": over_id,
        "no_outcome": under_id,
    }


def _game_blob(game: dict) -> str:
    parts = [str(game.get(key) or "") for key in ("sport", "title_kalshi", "title_gemini", "title")]
    for key in ("teams", "codes", "gemini_teams"):
        value = game.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    for key in ("kalshi", "gemini"):
        value = game.get(key)
        if isinstance(value, dict):
            parts.extend(str(item) for item in value.values())
    return " ".join(parts).upper()


def leagues_for(game: dict, sport: str = "") -> list[str]:
    blob = _game_blob(game)
    compact = re.sub(r"[^A-Z0-9]+", "", blob)
    found = []
    remaining = compact
    for league in sorted(LEAGUES, key=len, reverse=True):
        token = re.sub(r"[^A-Z0-9]+", "", league.upper())
        if token and token in remaining:
            found.append(league)
            remaining = remaining.replace(token, "")
    if found:
        return found
    return list(SPORT_LEAGUES.get((sport or str(game.get("sport") or "")).lower(), ()))


def _codes(game: dict) -> set[str]:
    found = set()
    for key in ("teams", "codes", "gemini_teams", "kalshi_codes", "gemini_codes"):
        for code in game.get(key) or []:
            text = str(code).upper()
            if re.fullmatch(r"[A-Z]{2,8}", text):
                found.add(text)
    return found


def _titles(game: dict) -> list[str]:
    rows = []
    for key in ("title_kalshi", "title_gemini", "title"):
        text = str(game.get(key) or "").strip()
        if text:
            rows.append(text)
    return rows


def _event_matches(game: dict, event: dict, money: dict | None) -> bool:
    when = str(game.get("date") or "")
    if when and _et_date(event.get("startsTs")) != when:
        return False
    description = str(event.get("description") or "")
    outcome_names = []
    if money:
        outcome_names = [str(row.get("name") or "") for row in (money.get("outcomes") or []) if isinstance(row, dict)]
    codes = _codes(game)
    outcome_codes = {name.upper() for name in outcome_names if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,8}", name)}
    if codes and outcome_codes and outcome_codes <= codes:
        return True
    event_sides = _split_sides(description)
    if len(event_sides) != 2:
        return False
    for title in _titles(game):
        game_sides = _split_sides(title)
        if len(game_sides) != 2:
            continue
        direct = _names_match(game_sides[0], event_sides[0]) and _names_match(game_sides[1], event_sides[1])
        crossed = _names_match(game_sides[0], event_sides[1]) and _names_match(game_sides[1], event_sides[0])
        named = False
        if len(outcome_names) == 2:
            named = (
                (_names_match(game_sides[0], outcome_names[0]) and _names_match(game_sides[1], outcome_names[1]))
                or (_names_match(game_sides[0], outcome_names[1]) and _names_match(game_sides[1], outcome_names[0]))
            )
        if direct or crossed or named:
            return True
    return False


def live_tennis_games() -> list[dict]:
    """ATP and WTA events that still have an open Novig moneyline or spread.

    Challenger is not in this catalog. Used for in-match quote collection.
    Does not place an order.
    """
    out = []
    for league in SPORT_LEAGUES.get("tennis", ()):
        events, markets = _league_rows(league)
        buckets: dict[str, list[dict]] = {}
        for market in markets:
            if isinstance(market, dict):
                buckets.setdefault(str(market.get("eventId") or ""), []).append(market)
        for event in events:
            if not isinstance(event, dict):
                continue
            status = str(event.get("status") or "").upper()
            if status not in ("OPEN_PREGAME", "OPEN_INGAME", "OPEN", ""):
                continue
            event_id = str(event.get("eventId") or "")
            description = str(event.get("description") or "").strip()
            if not event_id or not description or "/" in description:
                continue
            parsed = []
            seen: set[str] = set()
            for market in buckets.get(event_id) or []:
                row = parse_market(market, status, None, "tennis")
                if not row or row.get("kind") not in ("moneyline", "spread") or row["market_id"] in seen:
                    continue
                seen.add(row["market_id"])
                parsed.append(row)
            if not parsed:
                continue
            start_iso = ""
            try:
                start_iso = datetime.fromtimestamp(int(event.get("startsTs")) / 1000, ET).isoformat()
            except (TypeError, ValueError, OSError):
                start_iso = ""
            out.append({
                "title": description,
                "date": _et_date(event.get("startsTs")),
                "novig_markets": parsed,
                "event_id": event_id,
                "startsTs": event.get("startsTs"),
                "status": status,
                "league": league,
                "startTime": start_iso,
            })
    return out


def markets_from_game(game: dict, same_numbers: dict | None = None, sport: str = "") -> list[dict]:
    """Public catalog rows for this game. Unmatched or ambiguous events are skipped."""
    preset = game.get("novig_markets")
    if isinstance(preset, list) and preset:
        return [dict(row) for row in preset if isinstance(row, dict)]
    leagues = leagues_for(game, sport)
    if not leagues:
        return []
    chosen: list[tuple[dict, dict | None]] = []
    buckets: dict[str, list[dict]] = {}
    statuses: dict[str, str] = {}
    for league in leagues:
        events, markets = _league_rows(league)
        for market in markets:
            buckets.setdefault(str(market.get("eventId") or ""), []).append(market)
        for event in events:
            event_id = str(event.get("eventId") or "")
            statuses[event_id] = str(event.get("status") or "")
            group = buckets.get(event_id) or []
            moneys = [row for row in group if str(row.get("marketType") or "").upper() == "MONEY"]
            money = moneys[0] if len(moneys) == 1 else None
            if len(moneys) > 1:
                continue
            if _event_matches(game, event, money):
                chosen.append((event, money))
    if len(chosen) != 1:
        return []
    event, _money = chosen[0]
    event_id = str(event.get("eventId") or "")
    status = statuses.get(event_id) or ""
    rows = []
    seen = set()
    for market in buckets.get(event_id) or []:
        parsed = parse_market(market, status, same_numbers, sport)
        if not parsed or parsed["market_id"] in seen:
            continue
        seen.add(parsed["market_id"])
        rows.append(parsed)
    return rows


def seed_books(contracts: list[dict]) -> None:
    for contract in contracts:
        market_id = str(contract.get("market_id") or "")
        if not market_id:
            continue
        try:
            book = _get("/v3/catalog/markets/" + urllib.parse.quote(market_id, safe="") + "/book", {"depth": "3"})
        except Exception:
            continue
        if isinstance(book, dict):
            apply_rest_book(contract, book)
        status = event_status(str(contract.get("event_id") or ""), str(contract.get("event_status") or ""))
        if status:
            contract["event_status"] = status
        ensure_fee_schedule(contract, fetch=True)


def refresh_books(contracts: list[dict]) -> bool:
    """Public HTTP book refresh. True when a shown ask changed."""
    changed = False
    seen_events: set[str] = set()
    for contract in contracts:
        market_id = str(contract.get("market_id") or "")
        if not market_id:
            continue
        event_id = str(contract.get("event_id") or "")
        if event_id and event_id not in seen_events:
            seen_events.add(event_id)
            status = event_status(event_id, str(contract.get("event_status") or ""))
            if status:
                contract["event_status"] = status
        elif event_id:
            for other in contracts:
                if str(other.get("event_id") or "") == event_id and other.get("event_status"):
                    contract["event_status"] = other.get("event_status")
                    break
        try:
            book = _get("/v3/catalog/markets/" + urllib.parse.quote(market_id, safe="") + "/book", {"depth": "3"})
        except Exception:
            continue
        if isinstance(book, dict) and apply_rest_book(contract, book):
            changed = True
        ensure_fee_schedule(contract, fetch=True)
    return changed


def contract_views(contract: dict) -> list[dict]:
    """Yes is buying that outcome. No is buying the other outcome. Size 0 is not a price."""
    ensure_fee_schedule(contract, fetch=True)
    theta = contract.get("fee_coefficient")
    charged = contract.get("fee_charged")
    status = contract.get("event_status")
    market_id = contract.get("market_id") or ""
    kind = contract.get("kind") or "moneyline"
    yes_id = str(contract.get("yes_outcome") or "")
    no_id = str(contract.get("no_outcome") or "")

    def row(side: str, code: str, yes, yes_size, no, no_size, buy_yes: str, buy_no: str) -> dict:
        return {
            "kind": kind,
            "side": side,
            "number": None if kind == "moneyline" else (contract.get("number") or None),
            "code": code or None,
            "yes": yes,
            "no": no,
            "yes_size": yes_size if isinstance(yes_size, Decimal) else Decimal("0"),
            "no_size": no_size if isinstance(no_size, Decimal) else Decimal("0"),
            "fee_coefficient": theta,
            "fee_charged": charged,
            "event_status": status,
            "ident": market_id,
            "buy_yes_outcome": buy_yes,
            "buy_no_outcome": buy_no,
            "label": side,
            "status": "open",
            "venue": "novig",
            "no_flipped_yes_bid": False,
            "no_reject": "",
        }

    yes_px, yes_sz = contract.get("yes_ask"), contract.get("ask_size")
    no_px, no_sz = contract.get("no_ask"), contract.get("no_ask_size")
    if kind == "total":
        return [
            row("over", "", yes_px, yes_sz, no_px, no_sz, yes_id, no_id),
            row("under", "", no_px, no_sz, yes_px, yes_sz, no_id, yes_id),
        ]
    side = str(contract.get("side") or "")
    code = side.upper() if re.fullmatch(r"[A-Z0-9]{2,8}", side.upper()) else ""
    rows = [row(side, code, yes_px, yes_sz, no_px, no_sz, yes_id, no_id)]
    other = str(contract.get("other_side") or "")
    if kind == "moneyline" and other:
        other_code = other.upper() if re.fullmatch(r"[A-Z0-9]{2,8}", other.upper()) else ""
        rows.append(row(other, other_code, no_px, no_sz, yes_px, yes_sz, no_id, yes_id))
    return rows


def _fee_for_leg(scan, venue: str, price: Decimal | None, view: dict) -> Decimal | None:
    if price is None:
        return None
    if venue == "kalshi":
        return Decimal("0")
    if venue == "gemini":
        return scan.gemini_fee(price)
    if venue == "polymarket":
        import polymarket_us_live
        return polymarket_us_live.taker_fee(price, view.get("fee_coefficient"))
    if venue == "novig":
        return taker_fee(price, view.get("fee_coefficient"), view.get("fee_charged"), view.get("event_status"))
    return None


def _money(scan, value: Decimal | None) -> str:
    if value is None:
        return ""
    return scan.money(value)


def _size(scan, value) -> str:
    return scan.size_text(value)


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
        if "novig" not in (yes_venue, no_venue):
            continue
        gross = yes_px + no_px
        fee_yes = _fee_for_leg(scan, yes_venue, yes_px, yes_view)
        fee_no = _fee_for_leg(scan, no_venue, no_px, no_view)
        fee_known = fee_yes is not None and fee_no is not None
        net = gross + fee_yes + fee_no if fee_known else None
        whole = isinstance(yes_sz, Decimal) and isinstance(no_sz, Decimal) and yes_sz > 0 and no_sz > 0
        novig_view = yes_view if yes_venue == "novig" else no_view
        novig_price = yes_px if yes_venue == "novig" else no_px
        novig_fee = fee_yes if yes_venue == "novig" else fee_no
        if not fee_known:
            label = "fee not documented"
        elif whole and net is not None and net < ONE:
            # Buyable for the lock path when Novig orders are live; otherwise still under-$1 for the compare.
            label = "yes" if orders_live() else "quote only"
        elif gross < ONE and not whole:
            label = "not a real offer"
        else:
            label = "no"
        novig_yes_outcome = ""
        novig_no_outcome = ""
        if yes_venue == "novig":
            novig_yes_outcome = str(yes_view.get("buy_yes_outcome") or "")
        if no_venue == "novig":
            # Pair No buys the other outcome on that Novig view.
            novig_no_outcome = str(no_view.get("buy_no_outcome") or "")
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
            "novig_fee": _money(scan, novig_fee) if novig_fee is not None else "",
            "novig_fee_note": "" if fee_known else "Novig fee is not documented for this market",
            "net": _money(scan, net) if net is not None else "",
            "gross_under_1": gross < ONE,
            "net_under_1": bool(fee_known and whole and net is not None and net < ONE),
            "size_both": whole,
            "fee_known": fee_known,
            "label": label,
            "kalshi_ticker": (left.get("ident") if left_name == "kalshi" else right.get("ident") if right_name == "kalshi" else "") or "",
            "gemini_symbol": (left.get("ident") if left_name == "gemini" else right.get("ident") if right_name == "gemini" else "") or "",
            "polymarket_slug": (left.get("ident") if left_name == "polymarket" else right.get("ident") if right_name == "polymarket" else "") or "",
            "novig_market": (novig_view.get("ident") if isinstance(novig_view, dict) else "") or "",
            "novig_yes_outcome": novig_yes_outcome,
            "novig_no_outcome": novig_no_outcome,
            "novig_price": _money(scan, novig_price),
            "fee_coefficient": (
                yes_view.get("fee_coefficient") if yes_venue == "polymarket"
                else no_view.get("fee_coefficient") if no_venue == "polymarket"
                else novig_view.get("fee_coefficient")
            ),
            "fee_charged": novig_view.get("fee_charged") if isinstance(novig_view, dict) else "",
            "event_status": novig_view.get("event_status") if isinstance(novig_view, dict) else "",
            "no_flipped_yes_bid": False,
            "no_reject": "",
        })
    return out


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


def novig_candidates(scan, game: dict, kalshi_events: list[dict], gemini_events: list[dict], contracts: list[dict], polymarket_contracts: list[dict] | None = None) -> list[dict]:
    """Same settlement only. A Novig pair with an unknown fee is not buyable."""
    if not contracts:
        return []
    novig_views = []
    for contract in contracts:
        novig_views.extend(contract_views(contract))
    rows = []
    kalshi_views = scan.load_views(kalshi_events or [], "kalshi")
    gemini_views = scan.load_views(gemini_events or [], "gemini")
    if kalshi_views:
        rows.extend(_pair_rows(scan, game, "kalshi", kalshi_views, "novig", novig_views))
    if gemini_views:
        rows.extend(_pair_rows(scan, game, "gemini", gemini_views, "novig", novig_views))
    if polymarket_contracts:
        import polymarket_us_live
        poly_views = []
        for contract in polymarket_contracts:
            poly_views.extend(polymarket_us_live.contract_views(contract))
        if poly_views:
            rows.extend(_pair_rows(scan, game, "polymarket", poly_views, "novig", novig_views))
    return rows


def subscribe_message(market_ids: list[str], nonce: int) -> dict:
    """Book channel only. No private channel and no place verb."""
    return {
        "nonce": nonce,
        "subscribe": {"markets": {market_id: "book" for market_id in market_ids}},
    }


def snapshot_message(market_ids: list[str], nonce: int) -> dict:
    return {
        "nonce": nonce,
        "snapshot": {"markets": {market_id: "book" for market_id in market_ids}},
    }


def ws_headers() -> dict[str, str] | None:
    """Signed handshake for GET /v3/ws. None when the key files are absent.

    Callers must not log these headers.
    """
    return signature_headers("GET", WS_PATH, "", b"")


def probe_catalog() -> dict:
    """One signed league list, then one market page if the list is non-empty.

    The return value has counts and status words only. No key, header, or book price.
    """
    result = {
        "keys_present": keys_present(),
        "signer": _load_signer() is not None,
        "leagues": 0,
        "markets": 0,
        "book": False,
        "error": "",
    }
    if not result["signer"]:
        result["error"] = "signer unavailable"
        return result
    try:
        leagues = _get("/v3/types/leagues")
    except Exception as exc:
        result["error"] = type(exc).__name__ + " " + str(exc)[:120]
        return result
    names = leagues if isinstance(leagues, list) else (leagues.get("items") or leagues.get("leagues") or [])
    if isinstance(names, list):
        result["leagues"] = len(names)
    league = "NFL"
    if isinstance(names, list) and names:
        first = names[0]
        if isinstance(first, str) and first:
            league = first
        elif isinstance(first, dict):
            league = str(first.get("name") or first.get("league") or "NFL")
    try:
        page = _get("/v3/catalog/markets", {"league": league, "limit": "1"})
    except Exception as exc:
        result["error"] = type(exc).__name__ + " " + str(exc)[:120]
        return result
    items = page.get("items") if isinstance(page, dict) else None
    if isinstance(items, list):
        result["markets"] = len(items)
        market_id = str(items[0].get("marketId") or "") if items and isinstance(items[0], dict) else ""
        if market_id:
            try:
                book = _get("/v3/catalog/markets/" + urllib.parse.quote(market_id, safe="") + "/book", {"depth": "1"})
                result["book"] = isinstance(book, dict) and isinstance(book.get("orders"), dict)
            except Exception as exc:
                result["error"] = type(exc).__name__ + " " + str(exc)[:120]
    return result
