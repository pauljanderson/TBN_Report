"""Four shared platform websockets for many live games. No orders.

One Kalshi socket, one Gemini socket, one Polymarket US socket, one Novig
socket. Games subscribe and unsubscribe as they enter or leave the live
window. HTTP fallback is still paced by venue_pace and stays quiet while
that venue's socket is up. This module does not load the lock sender
and does not place a bet.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable
from urllib.parse import urlparse

import websockets

import live_quote_stream as lqs
import novig_live
import polymarket_us_live

WS_URLS = {
    "kalshi": lqs.KALSHI_WS,
    "gemini": lqs.GEMINI_WS,
    "polymarket": polymarket_us_live.WS_URL,
    "novig": novig_live.WS_URL,
}
WS_HOSTS = {name: (urlparse(url).hostname or "") for name, url in WS_URLS.items()}


def socket_host_list() -> list[str]:
    """The four websocket hosts. Test seam: length is 4."""
    return [WS_HOSTS["kalshi"], WS_HOSTS["gemini"], WS_HOSTS["polymarket"], WS_HOSTS["novig"]]


class SharedStreams:
    """Union of many games on four sockets. Apply mutates the caller's contract dicts."""

    def __init__(
        self,
        on_change: Callable[[str, set[str]], None],
        log: Callable[[str], None],
        on_quote: Callable[[str, str, bool], None] | None = None,
    ):
        self.on_change = on_change
        self.on_quote = on_quote
        self.log = log
        self.kalshi: dict[str, dict] = {}
        self.gemini: dict[str, dict] = {}
        self.polymarket: dict[str, dict] = {}
        self.novig: dict[str, dict] = {}
        self.owners: dict[tuple[str, str], set[str]] = {}
        self.by_game: dict[str, dict[str, set[str]]] = {}
        self.novig_socket_up = False
        self.polymarket_socket_up = False
        self.gemini_messages = 0
        self.kalshi_messages = 0
        self.polymarket_messages = 0
        self.novig_messages = 0
        self._ws: dict[str, object] = {}
        self._pending: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sub_id = 1
        self._novig_nonce = 1

    def instruments_for(self, venue: str) -> dict[str, dict]:
        return {
            "kalshi": self.kalshi,
            "gemini": self.gemini,
            "polymarket": self.polymarket,
            "novig": self.novig,
        }[venue]

    def games_for(self, venue: str, instrument: str) -> set[str]:
        return set(self.owners.get((venue, str(instrument)), ()))

    def plan_set_game(
        self,
        key: str,
        *,
        kalshi: dict[str, dict] | None = None,
        gemini: dict[str, dict] | None = None,
        polymarket: dict[str, dict] | None = None,
        novig: dict[str, dict] | None = None,
    ) -> list[tuple[str, str, list[str]]]:
        """Replace one game's instruments. Returns subscribe/unsubscribe commands."""
        wanted = {
            "kalshi": dict(kalshi or {}),
            "gemini": dict(gemini or {}),
            "polymarket": dict(polymarket or {}),
            "novig": dict(novig or {}),
        }
        old = self.by_game.get(key) or {venue: set() for venue in wanted}
        cmds: list[tuple[str, str, list[str]]] = []
        new_map: dict[str, set[str]] = {}
        for venue, mapping in wanted.items():
            new_ids = set(mapping)
            new_map[venue] = new_ids
            prev = set(old.get(venue) or ())
            added = sorted(new_ids - prev)
            dropped = sorted(prev - new_ids)
            book = self.instruments_for(venue)
            for instrument in added:
                book[instrument] = mapping[instrument]
                self.owners.setdefault((venue, instrument), set()).add(key)
            if added:
                cmds.append((venue, "subscribe", added))
            for instrument in dropped:
                owners = self.owners.get((venue, instrument)) or set()
                owners.discard(key)
                if not owners:
                    self.owners.pop((venue, instrument), None)
                    book.pop(instrument, None)
                    cmds.append((venue, "unsubscribe", [instrument]))
                else:
                    self.owners[(venue, instrument)] = owners
        if any(new_map.values()):
            self.by_game[key] = new_map
        else:
            self.by_game.pop(key, None)
        return cmds

    def plan_drop_game(self, key: str) -> list[tuple[str, str, list[str]]]:
        return self.plan_set_game(key)

    def enqueue(self, cmds: list[tuple[str, str, list[str]]]) -> None:
        if not cmds:
            return
        pending = self._pending
        loop = self._loop
        if pending is None or loop is None:
            return
        try:
            loop.call_soon_threadsafe(pending.put_nowait, cmds)
        except RuntimeError:
            pass

    def set_game(self, key: str, **maps) -> list[tuple[str, str, list[str]]]:
        cmds = self.plan_set_game(key, **maps)
        self.enqueue(cmds)
        return cmds

    def drop_game(self, key: str) -> list[tuple[str, str, list[str]]]:
        cmds = self.plan_drop_game(key)
        self.enqueue(cmds)
        return cmds

    def _emit(self, venue: str, instrument: str, changed: bool) -> None:
        keys = self.games_for(venue, instrument)
        if self.on_quote is not None:
            for key in keys:
                try:
                    self.on_quote(venue, key, changed)
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
        elif venue == "novig":
            self.novig_messages += 1
        if keys:
            try:
                self.on_change(venue, keys)
            except Exception:
                pass

    def _on_gemini(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            fields = lqs._gemini_fields(item)
            if not fields:
                continue
            symbol = str(fields.get("s") or fields.get("symbol") or fields.get("instrument") or "")
            contract = self.gemini.get(symbol)
            if contract is None:
                continue
            before = lqs._gemini_fp(contract)
            if not lqs.apply_gemini_book(contract, fields):
                continue
            self._emit("gemini", symbol, lqs._gemini_fp(contract) != before)

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
            self._emit("kalshi", ticker, False)
            return
        before = lqs._kalshi_fp(contract)
        if not lqs.apply_kalshi_ticker(contract, message):
            return
        self._emit("kalshi", ticker, lqs._kalshi_fp(contract) != before)

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
        before = lqs._poly_fp(contract)
        applied = polymarket_us_live.apply_book_levels(contract, book.get("bids") or [], book.get("offers") or [])
        self._emit("polymarket", slug, bool(applied and lqs._poly_fp(contract) != before))

    def _on_novig(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        before = {market_id: lqs._novig_fp(row) for market_id, row in self.novig.items()}
        applied = novig_live.on_stream_message(self.novig, payload)
        if "snapshot" not in payload and "delta" not in payload:
            return
        changed_ids = [
            market_id
            for market_id, row in self.novig.items()
            if lqs._novig_fp(row) != before.get(market_id)
        ]
        if not applied:
            if self.novig:
                self._emit("novig", next(iter(self.novig)), False)
            return
        if changed_ids:
            for market_id in changed_ids:
                self._emit("novig", market_id, True)
        elif self.novig:
            self._emit("novig", next(iter(self.novig)), False)

    def _subscribe_payloads(self, venue: str, ids: list[str]) -> list[dict]:
        ids = [i for i in ids if i]
        if not ids:
            return []
        if venue == "gemini":
            self._sub_id += 1
            return [{
                "id": str(self._sub_id),
                "method": "SUBSCRIBE",
                "params": [f"{symbol}@bookTicker" for symbol in ids],
            }]
        if venue == "kalshi":
            out = []
            for ticker in ids:
                self._sub_id += 1
                out.append({
                    "id": self._sub_id,
                    "cmd": "subscribe",
                    "params": {"channels": ["ticker"], "market_ticker": ticker},
                })
                out.append({
                    "id": 10000 + self._sub_id,
                    "cmd": "subscribe",
                    "params": {"channels": ["orderbook_delta"], "market_ticker": ticker},
                })
            return out
        if venue == "polymarket":
            out = []
            for index in range(0, len(ids), 100):
                chunk = ids[index:index + 100]
                self._sub_id += 1
                out.append(polymarket_us_live.subscribe_message(chunk, f"md-sub-{self._sub_id}"))
            return out
        if venue == "novig":
            self._novig_nonce += 1
            return [novig_live.subscribe_message(ids, self._novig_nonce)]
        return []

    def _unsubscribe_payloads(self, venue: str, ids: list[str]) -> list[dict]:
        ids = [i for i in ids if i]
        if not ids:
            return []
        if venue == "gemini":
            self._sub_id += 1
            return [{
                "id": str(self._sub_id),
                "method": "UNSUBSCRIBE",
                "params": [f"{symbol}@bookTicker" for symbol in ids],
            }]
        if venue == "kalshi":
            out = []
            for ticker in ids:
                self._sub_id += 1
                out.append({
                    "id": self._sub_id,
                    "cmd": "unsubscribe",
                    "params": {"channels": ["ticker"], "market_ticker": ticker},
                })
                out.append({
                    "id": 10000 + self._sub_id,
                    "cmd": "unsubscribe",
                    "params": {"channels": ["orderbook_delta"], "market_ticker": ticker},
                })
            return out
        if venue == "polymarket":
            self._sub_id += 1
            return [{
                "unsubscribe": {
                    "requestId": f"md-unsub-{self._sub_id}",
                    "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
                    "marketSlugs": ids,
                }
            }]
        if venue == "novig":
            self._novig_nonce += 1
            return [{"nonce": self._novig_nonce, "unsubscribe": {"markets": {i: "book" for i in ids}}}]
        return []

    async def _send_cmds(self, cmds: list[tuple[str, str, list[str]]]) -> None:
        for venue, op, ids in cmds:
            ws = self._ws.get(venue)
            if ws is None or not ids:
                continue
            payloads = self._subscribe_payloads(venue, ids) if op == "subscribe" else self._unsubscribe_payloads(venue, ids)
            for payload in payloads:
                try:
                    await ws.send(json.dumps(payload))
                except Exception as exc:
                    self.log(f"{venue} {op} send {type(exc).__name__}")
                    break

    async def _pump(self, stop: Callable[[], bool]) -> None:
        pending = self._pending
        if pending is None:
            return
        while not stop():
            try:
                cmds = await asyncio.wait_for(pending.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            await self._send_cmds(cmds)

    async def _open_and_read(
        self,
        venue: str,
        url: str,
        headers: dict | None,
        stop: Callable[[], bool],
        on_raw,
        *,
        after_open=None,
        heartbeat=None,
    ) -> None:
        delay = 2
        while not stop():
            try:
                kwargs = {"open_timeout": 20, "ping_interval": 20}
                if headers:
                    kwargs["additional_headers"] = headers
                async with websockets.connect(url, **kwargs) as ws:
                    delay = 2
                    self._ws[venue] = ws
                    ids = list(self.instruments_for(venue))
                    await self._send_cmds([(venue, "subscribe", ids)])
                    self.log(f"{venue} stream open {len(ids)} contracts host {WS_HOSTS.get(venue) or ''}")
                    if after_open is not None:
                        after_open(True)
                    last_heartbeat = 0.0
                    async for raw in ws:
                        if stop():
                            return
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="replace")
                        if heartbeat is not None and heartbeat(raw):
                            now = time.time()
                            if now - last_heartbeat >= 10:
                                await ws.send(heartbeat(raw) if not isinstance(heartbeat(raw), bool) else '{"heartbeat":{}}')
                                last_heartbeat = now
                            continue
                        on_raw(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                self.log(f"{venue} stream closed {type(exc).__name__} {status or ''}".strip())
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
            finally:
                if self._ws.get(venue) is not None:
                    self._ws.pop(venue, None)
                if after_open is not None:
                    after_open(False)

    async def gemini_forever(self, stop: Callable[[], bool]) -> None:
        await self._open_and_read("gemini", lqs.GEMINI_WS, None, stop, self._on_gemini)

    async def kalshi_forever(self, stop: Callable[[], bool]) -> None:
        while not stop():
            try:
                headers = lqs.kalshi_headers()
            except Exception as exc:
                self.log(f"kalshi headers {type(exc).__name__}")
                await asyncio.sleep(15)
                continue
            await self._open_and_read("kalshi", lqs.KALSHI_WS, headers, stop, self._on_kalshi)
            if stop():
                return

    async def polymarket_forever(self, stop: Callable[[], bool]) -> None:
        missing_logged = False
        while not stop():
            if not self.polymarket:
                await asyncio.sleep(1)
                continue
            headers = polymarket_us_live.auth_headers()
            if headers is None:
                if not missing_logged:
                    self.log("polymarket stream waiting; API key file missing. Kalshi and Gemini keep running.")
                    missing_logged = True
                await asyncio.sleep(15)
                continue
            missing_logged = False

            def _flag(up: bool) -> None:
                self.polymarket_socket_up = up

            def _beat(raw: str):
                if lqs._polymarket_heartbeat(raw):
                    return '{"heartbeat":{}}'
                return False

            await self._open_and_read(
                "polymarket",
                polymarket_us_live.WS_URL,
                headers,
                stop,
                self._on_polymarket,
                after_open=_flag,
                heartbeat=_beat,
            )
            if stop():
                return

    async def novig_forever(self, stop: Callable[[], bool]) -> None:
        if not novig_live.keys_present():
            self.log("novig stream skipped; no trading::read key. Signed HTTP quotes continue.")
            return
        while not stop():
            if not self.novig:
                await asyncio.sleep(1)
                continue
            headers = novig_live.ws_headers()
            if headers is None:
                self.log("novig stream skipped; key file unreadable. Signed HTTP quotes continue.")
                return

            def _flag(up: bool) -> None:
                self.novig_socket_up = up

            await self._open_and_read(
                "novig",
                novig_live.WS_URL,
                headers,
                stop,
                self._on_novig,
                after_open=_flag,
            )
            if stop():
                return

    async def polymarket_http_forever(self, stop: Callable[[], bool]) -> None:
        while not stop():
            await asyncio.sleep(lqs.HTTP_FALLBACK_SEC)
            if stop():
                return
            if self.polymarket_socket_up or not self.polymarket:
                continue
            try:
                before = {slug: lqs._poly_fp(row) for slug, row in self.polymarket.items()}
                await asyncio.to_thread(polymarket_us_live.seed_books, list(self.polymarket.values()))
                for slug, row in self.polymarket.items():
                    self._emit("polymarket", slug, lqs._poly_fp(row) != before.get(slug))
            except Exception as exc:
                self.log(f"polymarket http {type(exc).__name__}")

    async def novig_http_forever(self, stop: Callable[[], bool]) -> None:
        if not novig_live.keys_present():
            self.log("novig websocket needs secrets/novig_api_key.txt and secrets/novig_api_secret.txt. Signed HTTP fallback.")
        while not stop():
            await asyncio.sleep(lqs.HTTP_FALLBACK_SEC)
            if stop():
                return
            if self.novig_socket_up or not self.novig:
                continue
            try:
                before = {market_id: lqs._novig_fp(row) for market_id, row in self.novig.items()}
                await asyncio.to_thread(novig_live.refresh_books, list(self.novig.values()))
                for market_id, row in self.novig.items():
                    self._emit("novig", market_id, lqs._novig_fp(row) != before.get(market_id))
            except Exception as exc:
                self.log(f"novig http {type(exc).__name__}")

    async def run(self, stop: Callable[[], bool], sync_once: Callable[[], None], sync_sec: float = 60.0) -> None:
        """Four sockets plus two HTTP fallbacks plus a live-window sync loop. No orders."""
        logging.getLogger("websockets").setLevel(logging.WARNING)
        self._loop = asyncio.get_running_loop()
        self._pending = asyncio.Queue()

        async def _sync() -> None:
            while not stop():
                try:
                    await asyncio.to_thread(sync_once)
                except Exception as exc:
                    self.log(f"mux sync {type(exc).__name__}")
                slept = 0.0
                while slept < sync_sec and not stop():
                    await asyncio.sleep(1)
                    slept += 1

        await asyncio.gather(
            self.gemini_forever(stop),
            self.kalshi_forever(stop),
            self.polymarket_forever(stop),
            self.polymarket_http_forever(stop),
            self.novig_forever(stop),
            self.novig_http_forever(stop),
            self._pump(stop),
            _sync(),
        )


def run_mux(on_change, log, on_quote, stop, sync_once, sync_sec: float = 60.0) -> None:
    streams = SharedStreams(on_change, log, on_quote)
    asyncio.run(streams.run(stop, sync_once, sync_sec=sync_sec))
    return streams
