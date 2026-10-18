"""Live quote streams for one matched game. No orders.

Gemini's public book stream does not need a key. Kalshi's stream uses the
signed headers already used for a private read. The first prices still come
from the ordinary event request. After that, each message updates the price
and the size in memory and the compare runs on that update. The apply path
does not wait on venue_pace. HTTP seed and HTTP fallback still do.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Callable

import websockets

import kalshi_private
import polymarket_us_live

GEMINI_WS = "wss://ws.gemini.com"
KALSHI_WS = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
KALSHI_PATH = "/trade-api/ws/v2"
ONE = Decimal("1")


def _d(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _money(value: Decimal) -> str:
    return format(value, "f")


def _size(value) -> str:
    number = _d(value)
    if number is None:
        return "0"
    return format(number, "f")


def gemini_symbols(events: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for event in events or []:
        for raw in event.get("contracts") or []:
            if not isinstance(raw, dict):
                continue
            symbol = raw.get("instrumentSymbol") or raw.get("ticker") or ""
            if symbol:
                found[str(symbol)] = raw
    return found


def kalshi_contracts(events: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for event in events or []:
        for raw in event.get("contracts") or []:
            if not isinstance(raw, dict):
                continue
            ticker = raw.get("ticker") or ""
            if ticker:
                found[str(ticker)] = raw
    return found


def apply_gemini_book(contract: dict, fields: dict) -> bool:
    bid = _d(fields.get("b"))
    ask = _d(fields.get("a"))
    if bid is None and ask is None:
        return False
    prices = contract.setdefault("prices", {})
    if not isinstance(prices, dict):
        prices = {}
        contract["prices"] = prices
    buy = prices.get("buy") if isinstance(prices.get("buy"), dict) else {}
    sell = prices.get("sell") if isinstance(prices.get("sell"), dict) else {}
    prices["buy"] = buy
    prices["sell"] = sell
    if ask is not None:
        buy["yes"] = _money(ask)
        prices["bestAsk"] = _money(ask)
        contract["yes_size"] = _size(fields.get("A"))
        buy["yes_size"] = contract["yes_size"]
    if bid is not None:
        sell["yes"] = _money(bid)
        prices["bestBid"] = _money(bid)
        contract["book_yes_bid"] = _money(bid)
        no_px = ONE - bid
        buy["no"] = _money(no_px)
        contract["no_size"] = _size(fields.get("B"))
        buy["no_size"] = contract["no_size"]
    return True


def apply_kalshi_ticker(contract: dict, fields: dict) -> bool:
    yes_ask = _d(fields.get("yes_ask_dollars"))
    yes_bid = _d(fields.get("yes_bid_dollars"))
    if yes_ask is None and yes_bid is None:
        return False
    if yes_ask is not None:
        contract["yes_ask_dollars"] = _money(yes_ask)
        contract["yes_ask_size_fp"] = _size(fields.get("yes_ask_size_fp"))
    if yes_bid is not None:
        contract["yes_bid_dollars"] = _money(yes_bid)
        contract["no_ask_dollars"] = _money(ONE - yes_bid)
        contract["no_ask_size_fp"] = _size(fields.get("yes_bid_size_fp"))
    return True


def _walk_dicts(payload):
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _walk_dicts(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _walk_dicts(item)


def _gemini_fields(payload: dict) -> dict | None:
    for item in _walk_dicts(payload):
        if "b" in item or "a" in item:
            symbol = item.get("s") or item.get("symbol") or item.get("instrument") or ""
            if symbol or item.get("e") == "bookTicker":
                return item
    return None


def _gemini_fp(contract: dict) -> tuple:
    prices = contract.get("prices") if isinstance(contract.get("prices"), dict) else {}
    buy = prices.get("buy") if isinstance(prices.get("buy"), dict) else {}
    sell = prices.get("sell") if isinstance(prices.get("sell"), dict) else {}
    return (
        buy.get("yes"), prices.get("bestAsk"), contract.get("yes_size"),
        sell.get("yes"), prices.get("bestBid"), contract.get("book_yes_bid"),
        buy.get("no"), contract.get("no_size"),
    )


def _kalshi_fp(contract: dict) -> tuple:
    return (
        contract.get("yes_ask_dollars"), contract.get("yes_ask_size_fp"),
        contract.get("yes_bid_dollars"), contract.get("no_ask_dollars"),
        contract.get("no_ask_size_fp"),
    )


def _poly_fp(contract: dict) -> tuple:
    return (
        contract.get("yes_bid"), contract.get("bid_size"),
        contract.get("yes_ask"), contract.get("ask_size"),
    )


def _polymarket_heartbeat(raw: str) -> bool:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and "heartbeat" in payload and "marketData" not in payload


def kalshi_headers() -> dict[str, str]:
    import base64
    import time

    key_id = kalshi_private.load_key_id()
    private_key = kalshi_private.load_private_key()
    timestamp = str(int(time.time() * 1000))
    signed = f"{timestamp}GET{KALSHI_PATH}".encode("utf-8")
    signature = base64.b64encode(private_key.sign(signed)).decode("ascii")
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }


class GameStreams:
    def __init__(self, gemini_events: list[dict], kalshi_events: list[dict], on_change: Callable[[str], None], log: Callable[[str], None], polymarket_contracts: list[dict] | None = None, on_quote: Callable[[str, bool], None] | None = None):
        self.gemini = gemini_symbols(gemini_events)
        self.kalshi = kalshi_contracts(kalshi_events)
        self.polymarket = {str(row.get("slug")): row for row in (polymarket_contracts or []) if row.get("slug")}
        self.on_change = on_change
        self.on_quote = on_quote
        self.log = log
        self.gemini_messages = 0
        self.kalshi_messages = 0
        self.polymarket_messages = 0

    def _emit(self, venue: str, changed: bool) -> None:
        """Count a price update only when the stored quote changed. Still report the message."""
        if self.on_quote is not None:
            try:
                self.on_quote(venue, changed)
            except Exception:
                pass
        if not changed:
            return
        if venue == "gemini":
            self.gemini_messages += 1
        elif venue == "kalshi":
            self.kalshi_messages += 1
        elif venue == "polymarket":
            self.polymarket_messages += 1
        self.on_change(venue)

    async def gemini_forever(self, stop: Callable[[], bool]) -> None:
        symbols = list(self.gemini)
        if not symbols:
            self.log("gemini stream skipped; no instrument symbols")
            return
        delay = 2
        while not stop():
            try:
                async with websockets.connect(GEMINI_WS, open_timeout=20, ping_interval=20) as ws:
                    delay = 2
                    await ws.send(json.dumps({
                        "id": "1",
                        "method": "SUBSCRIBE",
                        "params": [f"{symbol}@bookTicker" for symbol in symbols],
                    }))
                    self.log(f"gemini stream open {len(symbols)} contracts")
                    async for raw in ws:
                        if stop():
                            return
                        self._on_gemini(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log(f"gemini stream closed {exc}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    def _on_gemini(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        items = payload if isinstance(payload, list) else [payload]
        changed = False
        saw = False
        for item in items:
            if not isinstance(item, dict):
                continue
            fields = _gemini_fields(item)
            if not fields:
                continue
            symbol = str(fields.get("s") or fields.get("symbol") or fields.get("instrument") or "")
            contract = self.gemini.get(symbol)
            if contract is None and len(self.gemini) == 1 and ("b" in fields or "a" in fields):
                contract = next(iter(self.gemini.values()))
            if contract is None:
                continue
            before = _gemini_fp(contract)
            if not apply_gemini_book(contract, fields):
                continue
            saw = True
            if _gemini_fp(contract) != before:
                changed = True
        if saw:
            self._emit("gemini", changed)

    async def kalshi_forever(self, stop: Callable[[], bool]) -> None:
        tickers = list(self.kalshi)
        if not tickers:
            self.log("kalshi stream skipped; no market tickers")
            return
        delay = 2
        while not stop():
            try:
                headers = kalshi_headers()
                async with websockets.connect(
                    KALSHI_WS,
                    additional_headers=headers,
                    open_timeout=20,
                    ping_interval=20,
                ) as ws:
                    delay = 2
                    for index, ticker in enumerate(tickers, start=1):
                        await ws.send(json.dumps({
                            "id": index,
                            "cmd": "subscribe",
                            "params": {"channels": ["ticker"], "market_ticker": ticker},
                        }))
                        await ws.send(json.dumps({
                            "id": 10000 + index,
                            "cmd": "subscribe",
                            "params": {"channels": ["orderbook_delta"], "market_ticker": ticker},
                        }))
                    self.log(f"kalshi stream open {len(tickers)} contracts")
                    async for raw in ws:
                        if stop():
                            return
                        self._on_kalshi(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log(f"kalshi stream closed {exc}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    def _on_kalshi(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        message = payload.get("msg") if isinstance(payload.get("msg"), dict) else payload
        ticker = str(message.get("market_ticker") or message.get("market_id") or "")
        contract = self.kalshi.get(ticker)
        if contract is None:
            return
        kind = str(payload.get("type") or message.get("type") or "")
        if kind == "orderbook_delta":
            self._emit("kalshi", False)
            return
        before = _kalshi_fp(contract)
        if not apply_kalshi_ticker(contract, message):
            return
        self._emit("kalshi", _kalshi_fp(contract) != before)

    async def polymarket_forever(self, stop: Callable[[], bool]) -> None:
        """US markets socket only. Waits for a key without stopping the other venues."""
        slugs = list(self.polymarket)
        if not slugs:
            self.log("polymarket stream skipped; no market slug")
            return
        delay = 2
        missing_logged = False
        while not stop():
            headers = polymarket_us_live.auth_headers()
            if headers is None:
                if not missing_logged:
                    self.log("polymarket stream waiting; API key file missing. Kalshi and Gemini keep running.")
                    missing_logged = True
                await asyncio.sleep(15)
                continue
            missing_logged = False
            try:
                async with websockets.connect(
                    polymarket_us_live.WS_URL,
                    additional_headers=headers,
                    open_timeout=20,
                    ping_interval=20,
                ) as ws:
                    delay = 2
                    for index in range(0, len(slugs), 100):
                        chunk = slugs[index:index + 100]
                        await ws.send(json.dumps(polymarket_us_live.subscribe_message(chunk, f"md-sub-{index // 100 + 1}")))
                    self.log(f"polymarket stream open {len(slugs)} contracts")
                    last_heartbeat = 0.0
                    async for raw in ws:
                        if stop():
                            return
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="replace")
                        if _polymarket_heartbeat(raw):
                            now = time.time()
                            if now - last_heartbeat >= 10:
                                await ws.send('{"heartbeat":{}}')
                                last_heartbeat = now
                            continue
                        self._on_polymarket(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                self.log(f"polymarket stream closed {type(exc).__name__} {status or ''}".strip())
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    def _on_polymarket(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict) or "heartbeat" in payload:
            return
        if payload.get("error"):
            self.log("polymarket stream subscription error")
            return
        book = payload.get("marketData") or payload.get("market_data")
        if not isinstance(book, dict):
            return
        slug = str(book.get("marketSlug") or book.get("market_slug") or "")
        contract = self.polymarket.get(slug)
        if contract is None:
            return
        before = _poly_fp(contract)
        applied = polymarket_us_live.apply_book_levels(contract, book.get("bids") or [], book.get("offers") or [])
        changed = bool(applied and _poly_fp(contract) != before)
        self._emit("polymarket", changed)


def run_until_done(scan, spec: dict, gemini_events: list[dict], kalshi_events: list[dict], stop: Callable[[], bool], log: Callable[[str], None], on_change: Callable[[str], None], polymarket_contracts: list[dict] | None = None, on_quote: Callable[[str, bool], None] | None = None) -> None:
    """Block until stop() is true. Reconnects each stream on its own. No orders."""
    logging.getLogger("websockets").setLevel(logging.WARNING)
    streams = GameStreams(gemini_events, kalshi_events, on_change, log, polymarket_contracts, on_quote)

    async def _main() -> None:
        await asyncio.gather(
            streams.gemini_forever(stop),
            streams.kalshi_forever(stop),
            streams.polymarket_forever(stop),
        )

    asyncio.run(_main())
