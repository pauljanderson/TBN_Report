"""Send a 1-contract lock when the live compare nets at or under NET_MAX.

Paul authorized this on 2026-10-18: execute when the locked profit is at least
$0.05 a contract. Research only. Not gold. Not DailyRun. The size cap stays 1.

A lock is Yes on one venue and No on the other for the same settlement. The
fee is the documented taker fee on every charging leg, including Kalshi
(0.07 × p × (1 − p) to $0.0001). After a fill, Kalshi POST average_fee_paid
overwrites that estimate. Wire is never treated as after-fee. The closed
Tennessee vs Indianapolis 13.5 trade is never sent.

Secrets stay in secrets/. This module logs status, instrument, side, limit, and
size. It does not log keys, signatures, or auth headers.

Paul turned the gap lock back on (2026-10-18). ORDERS_ENABLED is True.
A qualifying pair is any two of Kalshi, Gemini, Polymarket, and Novig when
Novig orders are live (novig_live.NOVIG_ORDERS_ENABLED plus a trading key).
There is no Polymarket-first (or Gemini-first) preference. Both books are
rechecked immediately before either HTTP leaves. If either book is empty,
has no takeable size of 1, or would make after-fee net above NET_MAX, send
NEITHER leg. Dual send is sequential hard-first (frozen 2026-10-24, Paul):
REST recheck both books, then IOC the thinner displayed ask (hard) first, 1
contract. Hard = smaller REST ask size; size tie uses VENUE_MISS_RANK (the
venue that missed more often on historical one-legs), then the more expensive
cash leg. Simultaneous both-at-once IOC is not the default. If the hard leg
misses, do not send the easy leg (hard_miss_abort): recheck the gap, give up
if it closed, no leftover, no flatten, no orders_stopped latch from a no-fill.
If hard fills, REST-recheck the easy book and recompute after-fee net. If net
is above NET_MAX, easy size is under 1, or the gap closed, flatten the hard
fill (same-shop opposite, not a 0.984 lock) and do not send easy. If the gap
is still legal, IOC the easy leg. Drive HTML (orders.html, opportunities.html,
orders_performance.html) is not rebuilt between the hard IOC and the easy IOC.
Those pages flush once after both attempts, or after flatten/abort. That is a
latency fix (Bobichon 2026-10-26: Poly fill 15:30:03, easy book 15:31:23,
Kalshi IOC 15:33:00 while orders.html sat on the send path). Not a strategy
knob. Both fill as a true lock (Yes+No same
player, or dual-Yes on opposite tennis names) → keep them. If easy misses,
flatten the hard fill. Do not leftover-watch a directional dog. If flatten
also misses, leftover watch may buy only a true hedge of the filled player:
the missed intended instrument, same-player No on another venue, or opponent
Yes that completes a dual-Yes lock. Never opponent-No when we already hold
dog Yes (Goffin / Onclin). IOC cannot guarantee both fills; that is why
flatten exists. One-leg leftover is still possible if hard fills then easy
misses and flatten also misses.
If neither fills, the latch is not written. If both fill, balances refresh.
At most MAX_OPEN_LOCKS live lock-bot games (same idea as Strategy B's
MAX_OPEN_B_MATCHES; Paul's systems.json max_open wins when set). A slot is a
unique game with venue-confirmed qty still unsettled on a true lock or
leftover — same overlay as C/D/B. Kalshi counts qty >= 1. Polymarket counts
qty > 0. Catalog claims, HTTP without confirm, empty Kalshi 201, flattened-
closed, settled, and Strategy B tennis-b keys do not occupy a slot. When
venues show 0 lock holdings, max 3 (or Paul's json max) must allow a send
even if the house tape still lists three opens. Extra qualifying pairs stay
alerts until a slot frees. Change the constant and restart pollers.
orders_stopped.json is written only after a one-leg miss whose flatten also
missed. That file is leftover metadata (reconstruct the watch, leftover HTML).
The send switch is systems.json lock.on: a one-leg miss turns Lock gap (A) off
and does not turn Tennis crossover / CFB favorite / T0 spreads / tennis T0 dog
off. New lock pairs stay off until leftover is fully hedged/flattened or Paul
runs `python tools/prediction_job_control.py systems --lock on`. Leftover watch
keeps running. B/C/D/E keep sending.
A one_leg_watch.json file then rechecks quotes continuously (same cadence as
live ticks, sleep at most 1 second) for a true hedge on Kalshi, Gemini,
Polymarket US, and Novig, including Yes+No on the origin market. Among venues
whose after-fee net of (fill cash + fill fee + hedge cash + hedge fee) is at
or under NET_MAX, the first time the rechecked ask is in cap we send one
immediate-or-cancel, 1 contract, cheapest qualifying venue. A fill of at
least one contract stops that leftover. A partial fill counts as filled qty
and marks that leftover attempt done — it is never a miss that retries. A
zero-fill miss also marks that ticket done; we do not fire another IOC for
the same leftover. A single-venue HTTP 404 is not “market closed”: skip that
venue and keep looking. Novig is quoted always; Novig orders stay off unless
NOVIG_ORDERS_ENABLED is already True. The watch stops (latch stays on) if a
venue reports a real resolved status, the remaining ask can never be
profitable, or both legs are already held. There is no clock cutoff.
Leftover watch runs until the game settles, flatten/hedge fills, or Paul
turns lock off / max-open. Same as jobs: max-open is the stop, not a clock.
A Kalshi send that comes back HTTP 404 with insufficient_shard_balance or
"Exchange user not found" is the same limit posted again, up to two more
times, two seconds apart. That wait is only for that Kalshi shard 404; it
does not delay the parallel partner post. A normal reject, a 201 with
nothing filled, and an immediate-or-cancel cancel are not repeated. Each
post is one line in order_io.jsonl.
After every order HTTP return, the bot reads that venue's fill or order-history
API (Kalshi fills, Gemini order history, Polymarket US activities, Novig fills)
and uses that confirm — not the order tape — to decide fill vs empty cancel vs
leftover vs both-legs. A confirm timeout is unknown: it does not invent a fill.
The first write of the latch pings Paul's phone once (Lock gap A off, B–E stay
on), in a detached process.
Each order HTTP request that is actually sent also pings Paul's phone. Skips
do not ping.

Available dollars for Kalshi, Gemini, Polymarket, and Novig live on a local
slip (raw/venue_cash_local.json, shared by lock children and B/C/D/E). A send
reads that slip. After order HTTP, venue fill-history confirm is truth: qty
>= 1 debits after-fee cost (a confirmed SELL credits proceeds). Kalshi HTTP
201 with fill_count 0 is an empty cancel and does not debit. The venue wallet
GET runs at most once per hour per venue; a 429 keeps the slip and backs off.
Skip send only when local cash is too low, or missing and the hourly confirm
failed. Do not GET the wallet on every book or every game.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

import gemini_private
import kalshi_private
import novig_live
import polymarket_us_live
import venue_cash_local
import venue_fill_confirm
import venue_pace
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW, ROOT

# Hard switch. False: log a skip and return before any venue order HTTP.
ORDERS_ENABLED = True
ORDERS = RAW / "orders.jsonl"
ORDER_IO = RAW / "order_io.jsonl"
ORDER_LOCK = RAW / "orders.lock"
ORDERS_STOP = RAW / "orders_stopped.json"
ONE_LEG_WATCH = RAW / "one_leg_watch.json"
LAST_SKIP = RAW / "lock_last_skip.json"
STRATEGY_B_STATE = RAW / "strategy_b_watch.json"
CFB_FAVORITE_STATE = RAW / "cfb_favorite_watch.json"
SPREAD_T0_STATE = RAW / "spread_t0_watch.json"
TENNIS_T0_DOG_STATE = RAW / "tennis_t0_dog_watch.json"
TENNIS_T0_SPREAD_STATE = RAW / "tennis_t0_spread_watch.json"
SOCCER_T0_TOTAL_STATE = RAW / "soccer_t0_total_watch.json"
POLLER_STATUS = RAW / "live_pollers_status.json"
_STRATEGY_B_OPEN = {
    "waiting_t0",
    "t0_filled_waiting_50_cross",
    "waiting_cross",
    "waiting_fav_dip",
    "fav_gtc_resting",
    "one_leg_miss",
    "absorbed",
}
_DIRECTIONAL_OPEN = {
    "waiting_t0",
    "filled",
    "holding",
    "open",
}
_DIRECTIONAL_SYSTEMS = {
    "cfb_favorite",
    "spread_t0",
    "tennis_crossover",
    "tennis_t0_dog",
    "tennis_t0_spread",
    "soccer_t0_total",
}
# one_leg_watch leftover is lock-A only. C/D/E/F/G (and B) are one-way Yes.
_DIRECTIONAL_BET_PREFIXES = frozenset({
    "tennis-t0-dog",
    "tennis_t0_dog",
    "tennis-t0-spread",
    "tennis_t0_spread",
    "soccer-t0-total",
    "soccer_t0_total",
    "cfb-favorite",
    "cfb_favorite",
    "spread-t0",
    "spread_t0",
    "tennis-b",
    "tennis_crossover",
})
_DIRECTIONAL_STEP_PREFIXES = ("c-", "d-", "e-", "f-", "g-", "b-")
WATCH_LOCK = RAW / "one_leg_watch.lock"
BALANCES_FILE = RAW / "balances.json"
WS_WATCH_FRESH_SEC = 20
WS_PRICE_SEC = 2
IO_CAP = 100_000
ONE = Decimal("1")
CENT = Decimal("0.01")
_DEFAULT_NET_MAX = Decimal("0.984")
NET_MAX = Decimal("0.984")
MAX_OPEN_LOCKS = 3
# Sequential hard-then-easy: do not rewrite Drive HTML until both IOCs finish.
_send_html_hold = 0
_send_html_pending = False
_send_perf_pending: list[tuple] = []


def effective_net_max() -> Decimal:
    """systems.json lock.net_max when Paul set it; else Decimal('0.984').

    Full precision Decimal. Do not round to 2dp before the net > cap compare.
    Reread each tick like D max / lock.max_open. Missing key keeps the default.
    Tests that assign NET_MAX away from the default pin that cap.
    """
    current = Decimal(str(NET_MAX))
    if current != _DEFAULT_NET_MAX:
        return current
    try:
        import prediction_systems

        raw = getattr(prediction_systems.get_system("lock"), "net_max", None)
        if raw is not None:
            val = Decimal(str(raw))
            if val > 0:
                return val
    except Exception:
        pass
    return current
# Frozen 2026-10-24 from orders.jsonl lock one_leg miss-venue counts (inception):
# gemini 22, kalshi 17, polymarket 8, novig 0. Higher = historically worse fill.
# Used only when REST ask sizes tie. Size is the primary hard-leg signal.
VENUE_MISS_RANK = {
    "gemini": 3,
    "kalshi": 2,
    "polymarket": 1,
    "novig": 0,
}


def send_line() -> str:
    """User-facing send cap from systems.json lock.net_max, else NET_MAX."""
    return format(effective_net_max(), "f")


def rewrite_send_line_copy(text: str) -> str:
    """Show the live NET_MAX in skip/status copy that still names a prior cap.

    Leaves the 0.99 log/alert band alone.
    Does not rewrite an "above" cap to the live send line when the named
    after-fee cost is at or under NET_MAX — that sentence would be false.
    """
    import re

    line = send_line()
    cap = effective_net_max()
    out = str(text or "")

    def _amt(raw: str) -> Decimal | None:
        try:
            return Decimal(raw)
        except Exception:
            return None

    def swap(pattern: str, repl: str) -> None:
        nonlocal out

        def sub(match: re.Match) -> str:
            if match.group("n") == "0.99":
                return match.group(0)
            return repl

        out = re.sub(pattern, sub, out)

    def cost_above_line(match: re.Match) -> str:
        if match.group("n") == "0.99":
            return match.group(0)
        amount = _amt(match.group("amt"))
        if amount is None or amount <= cap:
            return match.group(0)
        return f"{match.group('lead')}{match.group('amt')} is above the {line} send line"

    out = re.sub(
        r"(?P<lead>After-fee cost )(?P<amt>\d+\.\d+) is above the (?P<n>\d+\.\d+) send line",
        cost_above_line,
        out,
    )
    # Do not touch "above the X send line" here; cost_above_line already decided.
    swap(r"(?<!above the )(?P<n>\d+\.\d+) send line", f"{line} send line")
    swap(r"the (?P<n>\d+\.\d+) cap", f"the {line} cap")
    swap(r"net at or under (?P<n>\d+\.\d+)", f"net at or under {line}")
    swap(r"net <= (?P<n>\d+\.\d+)", f"net <= {line}")
    swap(r"net is \$(?P<n>\d+\.\d+)", f"net is ${line}")

    def net_above(match: re.Match) -> str:
        if match.group("n") == "0.99":
            return match.group(0)
        amount = _amt(match.group("amt"))
        if amount is None or amount <= cap:
            return match.group(0)
        return f"net {match.group('amt')} is above {line}"

    out = re.sub(r"net (?P<amt>\d+\.\d+) is above (?P<n>\d+\.\d+)", net_above, out)
    return out


SIZE = Decimal("1")
POLY_TIF_FOK = "TIME_IN_FORCE_FILL_OR_KILL"
POLY_TIF_GTC = "TIME_IN_FORCE_GOOD_TILL_CANCEL"
POLY_SIZE_LT_QTY_SKIP = "poly_size_lt_qty_skip"
POLY_FOK_PARTIAL_UNEXPECTED = "poly_fok_partial_unexpected"
QUOTE_KEYS = (
    "quote_source", "quote_price", "quote_seen_at",
    "sent_at", "lag_seconds",
    "trigger_venue", "trigger_side", "trigger_price", "trigger_seen_at", "trigger_source",
    "quote_size",
)
# Touch size + traded $ / OI for orders.jsonl. Not sent to the venue.
MARKET_SIZE_KEYS = (
    "ask_size",
    "volume_fp",
    "volume_24h_fp",
    "open_interest_fp",
    "volume",
    "volume24h",
    "volume24hr",
    "liquidity",
    "openInterest",
    "open_interest",
)
_MARKET_SIZE_FETCH_ENABLED = True
_MARKET_SIZE_CACHE_SEC = 60.0
_market_size_cache: dict[tuple[str, str], tuple[float, dict]] = {}
LEFTOVER_STATS_NAME = "leftover_watch_stats.jsonl"
SEND_QUOTE_AGE_NAME = "send_quote_age.jsonl"
ET = ZoneInfo("America/New_York")
WATCH_MODE = "continuous_quote"
WATCH_TICK_SEC = 1
WATCH_MIN_GAP_SEC = 0
# Same limit again after HTTP 404 insufficient_shard_balance / exchange user not found.
SHARD_USER_EXTRA_TRIES = 2
SHARD_USER_WAIT_SEC = 2
KALSHI_TICK = Decimal("0.0001")
POLY_TICK = Decimal("0.001")
CLOSED = {"closed", "settled", "determined", "finalized", "inactive"}
_capability: dict[str, tuple[float, bool, str]] = {}
_venue_balances: dict[str, Decimal] = {}
_venue_balance_live_at: dict[str, float] = {}
_balances_seeded = False
_balances_at: datetime | None = None
_BALANCE_TTL_SEC = 3600
_CAPABILITY_OK_TTL_SEC = 300
_CAPABILITY_FAIL_TTL_SEC = 15
_UNREAD_ALERT_SEC = 300
_UNREAD_ALERT = RAW / "kalshi_unread_alert.json"
_BALANCE_VENUES = ("kalshi", "gemini", "polymarket", "novig")
_VENUE_LABEL = {
    "kalshi": "Kalshi",
    "gemini": "Gemini",
    "polymarket": "Polymarket",
    "novig": "Novig",
}
_ORDER_VENUES = ("kalshi", "gemini", "polymarket", "novig")
_watch_thread: threading.Thread | None = None
_watch_thread_lock = threading.Lock()
_balance_skip_keys: set[str] = set()


def _money(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _net_text(value: Decimal) -> str:
    """After-fee cost as the Decimal is. At least four decimal places; never round to cents."""
    text = format(value, "f")
    if "." not in text:
        return text + ".0000"
    frac = text.split(".", 1)[1]
    if len(frac) < 4:
        text = text + ("0" * (4 - len(frac)))
    return text


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", ""))
    except Exception:
        return None


def _iso_now() -> str:
    return datetime.now(ET).isoformat(timespec="milliseconds")


def _parse_ts(value) -> datetime | None:
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


def _hhmmss(value) -> str:
    """Compact Eastern clock for supervisor lines. Empty when the stamp is missing."""
    stamp = _parse_ts(value)
    if stamp is None:
        text = str(value or "")
        if "T" in text:
            text = text.split("T", 1)[1]
        return text[:8]
    return stamp.strftime("%H:%M:%S")


def _lag_seconds(seen_at, sent_at) -> str:
    start = _parse_ts(seen_at)
    end = _parse_ts(sent_at)
    if start is None or end is None:
        return ""
    return format(Decimal(str(round((end - start).total_seconds(), 3))), "f")


def _short_source(source: str) -> str:
    raw = str(source or "").strip().lower()
    if raw in {"websocket", "ws", "simultaneous", "watch-ws"}:
        return "ws"
    if raw in {"book", "watch-book"}:
        return "book"
    if raw in {"recovery-cap", "midway", "recovery"}:
        return "cap"
    if raw == "watch":
        return "watch"
    return raw or "ws"


def quote_source_for_step(step: str) -> str:
    """Where the limit came from. Hard/easy dual send uses the REST book recheck."""
    raw = str(step or "").strip().lower()
    if raw in {"simultaneous", "websocket", "ws"}:
        return "websocket"
    if raw in {"book", "hard", "easy"}:
        return "book"
    if raw in {"midway", "recovery", "recovery-cap"}:
        return "recovery-cap"
    if raw in {"watch", "watch-ws"}:
        return "websocket"
    if raw == "watch-book":
        return "book"
    return raw or "websocket"


def _fresh_for_leg(fresh: list[dict] | None, spec: dict) -> dict | None:
    """Latest remember_books row for this leg. Price match first, then venue+side."""
    venue = str(spec.get("venue") or "").lower()
    pay = str(spec.get("outcome") or spec.get("side") or "").lower()
    want = _dec(spec.get("pay") or spec.get("quote_price") or spec.get("limit"))
    ranked: list[dict] = []
    for row in fresh or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("venue") or "").lower() != venue:
            continue
        if str(row.get("pay") or "").lower() != pay:
            continue
        ranked.append(row)
    if not ranked:
        return None

    def _seen(row: dict) -> str:
        return str(row.get("seen_at") or "")

    if want is not None:
        priced = [row for row in ranked if _dec(row.get("price")) == want]
        if priced:
            return max(priced, key=_seen)
    return max(ranked, key=_seen)


def _leg_quote_meta(spec: dict, fresh: list[dict] | None, compared_at: str, source: str) -> dict:
    """Quote we would pay on this leg: websocket ask (not bid) from this compare, or the fresh print."""
    row = _fresh_for_leg(fresh, spec)
    price = spec.get("pay") or spec.get("quote_price") or ""
    seen = compared_at
    size = spec.get("quote_size") or ""
    if row is not None:
        if row.get("price") not in (None, ""):
            price = row.get("price")
        if row.get("seen_at"):
            seen = str(row.get("seen_at"))
        for key in ("size", "ask_size", "yes_size", "qty", "amount"):
            if row.get(key) not in (None, ""):
                size = row.get(key)
                break
    if size not in (None, ""):
        _attach_quote_size(spec, size)
    return {
        "venue": str(spec.get("venue") or ""),
        "side": str(spec.get("outcome") or spec.get("side") or ""),
        "price": str(price or ""),
        "seen_at": seen,
        "source": source,
        "size": str(size or ""),
    }


def _pick_trigger(quotes: list[dict], fresh: list[dict] | None) -> dict:
    """The quote print that caused this claim: newest matching move, else newest quote."""
    venues = {str(item.get("venue") or "").lower() for item in quotes if item.get("venue")}
    pays = {str(item.get("side") or "").lower() for item in quotes if item.get("side")}
    moved = []
    for row in fresh or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("venue") or "").lower() not in venues:
            continue
        if pays and str(row.get("pay") or "").lower() not in pays:
            continue
        move = _dec(row.get("move"))
        if move is None or move == 0:
            continue
        moved.append(row)
    if moved:
        row = max(moved, key=lambda item: str(item.get("seen_at") or ""))
        return {
            "venue": str(row.get("venue") or "").lower(),
            "side": str(row.get("pay") or ""),
            "price": str(row.get("price") or ""),
            "seen_at": str(row.get("seen_at") or ""),
            "source": "websocket",
        }
    if quotes:
        newest = max(quotes, key=lambda item: str(item.get("seen_at") or ""))
        return {
            "venue": str(newest.get("venue") or ""),
            "side": str(newest.get("side") or ""),
            "price": str(newest.get("price") or ""),
            "seen_at": str(newest.get("seen_at") or ""),
            "source": str(newest.get("source") or "websocket"),
        }
    return {}


def _attach_quote(spec: dict, meta: dict, trigger: dict, source: str | None = None) -> dict:
    """Copy public quote fields onto the spec that will be posted. No secrets."""
    used = source or meta.get("source") or spec.get("quote_source") or "websocket"
    spec["quote_source"] = quote_source_for_step(used)
    spec["quote_price"] = str(meta.get("price") or spec.get("pay") or spec.get("quote_price") or "")
    spec["quote_seen_at"] = str(meta.get("seen_at") or spec.get("quote_seen_at") or "")
    _attach_quote_size(spec, meta.get("size") or spec.get("quote_size"))
    spec["trigger_venue"] = str(trigger.get("venue") or spec.get("trigger_venue") or "")
    spec["trigger_side"] = str(trigger.get("side") or spec.get("trigger_side") or "")
    spec["trigger_price"] = str(trigger.get("price") or spec.get("trigger_price") or "")
    spec["trigger_seen_at"] = str(trigger.get("seen_at") or spec.get("trigger_seen_at") or "")
    spec["trigger_source"] = quote_source_for_step(
        str(trigger.get("source") or spec.get("trigger_source") or spec["quote_source"])
    )
    return spec


def _carry_quote_fields(src: dict | None, dest: dict | None) -> dict | None:
    if not isinstance(dest, dict) or not isinstance(src, dict):
        return dest
    for key in QUOTE_KEYS:
        if dest.get(key) in (None, "") and src.get(key) not in (None, ""):
            dest[key] = src.get(key)
    return dest


def _quote_envelope(spec: dict | None) -> dict | None:
    """Public quote block for order_io.jsonl. Not sent to the venue."""
    if not isinstance(spec, dict):
        return None
    env = {}
    for key in QUOTE_KEYS:
        value = spec.get(key)
        if value not in (None, ""):
            env[key] = value
    return env or None


def _research_jsonl(name: str) -> Path:
    """Tracker files sit next to the live tape the tests already redirect."""
    if name == LEFTOVER_STATS_NAME:
        return ONE_LEG_WATCH.parent / name
    return ORDER_IO.parent / name


def _append_research_jsonl(name: str, row: dict) -> None:
    """Fail-soft research line. Never raises into the send or watch path."""
    try:
        path = _research_jsonl(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _attach_quote_size(spec: dict | None, size, overwrite: bool = False) -> None:
    if not isinstance(spec, dict) or size in (None, ""):
        return
    if not overwrite and spec.get("quote_size") not in (None, ""):
        return
    spec["quote_size"] = str(size)


def _market_size_from_payload(venue: str, payload) -> dict:
    """Public volume / OI fields from a market GET we already have a helper for."""
    if not isinstance(payload, dict):
        return {}
    market = payload.get("market") if isinstance(payload.get("market"), dict) else payload
    if not isinstance(market, dict):
        return {}
    inner = market.get("marketData") if isinstance(market.get("marketData"), dict) else None
    if inner:
        merged = dict(market)
        merged.update(inner)
        market = merged
    out = {}
    venue = str(venue or "").lower()
    if venue == "kalshi":
        keys = ("volume_fp", "volume_24h_fp", "open_interest_fp")
    elif venue == "polymarket":
        keys = ("volume", "volume24hr", "volume24h", "liquidity", "openInterest", "open_interest")
    elif venue == "gemini":
        keys = ("volume", "volume24h")
    else:
        return {}
    for key in keys:
        value = market.get(key)
        if value not in (None, ""):
            out[key] = str(value)
    return out


def _fetch_market_size(spec: dict | None) -> dict:
    """One extra market GET at send/skip. Cached. Not a polling loop. Fail-soft."""
    if not _MARKET_SIZE_FETCH_ENABLED or not isinstance(spec, dict):
        return {}
    venue = str(spec.get("venue") or "").lower()
    instrument = str(spec.get("instrument") or "")
    if not instrument or venue not in ("kalshi", "polymarket"):
        return {}
    cache_key = (venue, instrument)
    now = time.time()
    cached = _market_size_cache.get(cache_key)
    if cached and now - cached[0] <= _MARKET_SIZE_CACHE_SEC:
        return dict(cached[1])
    url = ""
    if venue == "kalshi":
        url = (
            "https://api.elections.kalshi.com/trade-api/v2/markets/"
            + urllib.parse.quote(instrument, safe="")
        )
    elif venue == "polymarket":
        url = polymarket_us_live.GATEWAY + "/v1/markets/" + urllib.parse.quote(instrument, safe="")
    if not url:
        return {}
    try:
        try:
            got = venue_pace.wait_turn(venue, priority=venue_pace.PRIORITY_BACKGROUND)
        except Exception:
            got = True
        if not got:
            return {}
        try:
            status, body = _http_get(url)
            payload = json.loads(body) if status == 200 else None
            got = _market_size_from_payload(venue, payload)
        finally:
            try:
                venue_pace.release_turn(venue)
            except Exception:
                pass
    except Exception:
        got = {}
    _market_size_cache[cache_key] = (now, dict(got))
    return dict(got)


def _attach_market_size(spec: dict | None) -> None:
    """Copy touch size and, when fetchable, $ volume / OI onto the spec. No secrets."""
    if not isinstance(spec, dict):
        return
    if spec.get("quote_size") not in (None, "") and spec.get("ask_size") in (None, ""):
        spec["ask_size"] = str(spec.get("quote_size"))
    for key, value in _fetch_market_size(spec).items():
        if spec.get(key) in (None, ""):
            spec[key] = value


def _size_log_fields(spec: dict | None) -> dict:
    """orders.jsonl fields: ask_size plus volume / OI when present."""
    if not isinstance(spec, dict):
        return {}
    out = {}
    ask = spec.get("ask_size") or spec.get("quote_size")
    if ask not in (None, ""):
        out["ask_size"] = str(ask)
    for key in MARKET_SIZE_KEYS:
        if key == "ask_size":
            continue
        value = spec.get(key)
        if value not in (None, ""):
            out[key] = str(value)
    return out


def _trigger_log_bits(spec: dict) -> str:
    quotes = []
    venue = str(spec.get("venue") or "")
    side = str(spec.get("outcome") or spec.get("side") or "")
    price = spec.get("quote_price") or spec.get("pay") or ""
    seen = _hhmmss(spec.get("quote_seen_at"))
    src = _short_source(str(spec.get("quote_source") or "websocket"))
    if venue or price:
        quotes.append(f"{venue} {side} {price} seen {seen} {src}".strip())
    trigger = ""
    if spec.get("trigger_venue") or spec.get("trigger_price"):
        trigger = (
            f"trigger {spec.get('trigger_venue') or ''} {spec.get('trigger_side') or ''} "
            f"{spec.get('trigger_price') or ''} seen {_hhmmss(spec.get('trigger_seen_at'))} "
            f"{_short_source(str(spec.get('trigger_source') or 'websocket'))}"
        ).strip()
    return " ".join(part for part in (trigger, "; ".join(quotes)) if part)


_KEEP_RESPONSE = {
    "message", "reason", "error", "status", "code", "result", "details",
    "orderid", "hashorderid", "clientorderid", "globalorderid",
    "filledquantity", "remainingquantity", "quantity", "price",
    "avgexecutionprice", "averagefillprice", "averagefeepaid", "feecost",
    "takerfees", "takerfeedollars", "fees", "fee",
    "cancelreason", "rejectionreason", "outcome", "side",
    "timeinforce", "symbol",
}


def _secret_blobs() -> tuple[str, ...]:
    """File contents used only to strip secrets out of a stored line. Never printed."""
    names = (
        "gemini_api_key.txt",
        "gemini_api_secret.txt",
        "kalshi_key_id.txt",
        "kalshi_private_key.pem",
        "polymarket_api_key.txt",
        "polymarket_api_secret.txt",
        "novig_api_key.txt",
        "novig_api_secret.txt",
        "novig_key_id.txt",
        "novig_private_key.pem",
    )
    found = []
    for name in names:
        path = ROOT / "secrets" / name
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if len(text) >= 8:
            found.append(text)
    return tuple(found)


def _redact_secrets(text: str) -> str:
    out = text
    for secret in _secret_blobs():
        out = out.replace(secret, "[redacted]")
    return out


def _redact_obj(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in ("signature", "secret", "apikey", "api_key", "authorization", "password")):
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = _redact_obj(item)
        return cleaned
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, str):
        return _redact_secrets(value)
    return value


def _harvest_kept(value, found: dict) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().replace("_", "") in _KEEP_RESPONSE or "filled" in str(key).lower():
                found[str(key)] = _redact_obj(item)
            _harvest_kept(item, found)
    elif isinstance(value, list):
        for item in value:
            _harvest_kept(item, found)


def _response_for_store(body: str):
    text = _redact_secrets(body or "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if len(text) <= IO_CAP and parsed is not None:
        return _redact_obj(parsed)
    if len(text) <= IO_CAP:
        return text
    kept: dict = {}
    if parsed is not None:
        _harvest_kept(parsed, kept)
    return {"truncated": True, "head": text[:80_000], "kept": kept}


def record_order_io(venue: str, kind: str, request, status: int, body: str, attempt: int | None = None, quote: dict | None = None) -> None:
    """One JSON line per attempt. Secrets are stripped. The summary ledger is separate."""
    row = {
        "timestamp": datetime.now(ET).isoformat(timespec="seconds"),
        "venue": venue,
        "kind": kind,
        "request": _redact_obj(request),
        "http_status": status,
        "response": _response_for_store(body or ""),
    }
    if attempt is not None:
        row["attempt"] = attempt
    env = quote if isinstance(quote, dict) else None
    if env:
        public = {key: env[key] for key in QUOTE_KEYS if env.get(key) not in (None, "")}
        if public:
            row["quote"] = public
            for key, value in public.items():
                row.setdefault(key, value)
    line = json.dumps(row, ensure_ascii=False, default=str)
    line = _redact_secrets(line)
    ORDER_IO.parent.mkdir(parents=True, exist_ok=True)
    with ORDER_IO.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def gemini_taker_fee(price: Decimal) -> Decimal:
    """0.07 * price * (1 - price), rounded up to the next cent. Gemini leg only."""
    raw = Decimal("0.07") * price * (ONE - price)
    if raw < 0:
        raw = Decimal("0")
    return raw.quantize(CENT, rounding=ROUND_CEILING)


def kalshi_fee_amount(price: Decimal, payload=None) -> Decimal:
    """Fee on the Kalshi fill. Venue average_fee_paid / fee_cost wins.

    Pre-send estimate is 0.07 × p × (1 − p) to the nearest ten-thousandth.
    Carolina vs Philadelphia: Yes fill 0.11, fee 0.0069.
    Bobichon: 0.07 × 0.49 × 0.51 = 0.0175; POST average_fee_paid 0.0175.
    A 0 on the body is missing, not a $0 fee.
    """
    returned = fee_returned(payload)
    if returned is not None:
        return returned
    raw = Decimal("0.07") * price * (ONE - price)
    if raw < 0:
        raw = Decimal("0")
    return raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def max_gemini_price(kalshi_fill: Decimal, kalshi_fee: Decimal) -> Decimal | None:
    """Highest cent still at or under NET_MAX after the Kalshi fill, Kalshi fee, and Gemini taker fee.

    Carolina example: Kalshi Yes 0.11, fee 0.0069, max Gemini No 0.81.
    """
    best = None
    price = CENT
    cap = effective_net_max()
    while price < ONE:
        net = kalshi_fill + kalshi_fee + price + gemini_taker_fee(price)
        if net <= cap:
            best = price
        else:
            break
        price += CENT
    return best


def gemini_book_ask(events, symbol: str, outcome: str) -> Decimal | None:
    """Current ask from the in-memory book the websocket updates. Top of book only."""
    for event in events or []:
        if not isinstance(event, dict):
            continue
        for raw in event.get("contracts") or []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("instrumentSymbol") or raw.get("ticker") or "") != symbol:
                continue
            prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
            buy = prices.get("buy") if isinstance(prices.get("buy"), dict) else {}
            if outcome == "yes":
                return _dec(buy.get("yes") if buy.get("yes") not in (None, "") else prices.get("bestAsk"))
            if outcome == "no":
                return _dec(buy.get("no"))
    return None


def venue_tick(venue: str) -> Decimal:
    if venue == "gemini":
        return CENT
    if venue == "polymarket":
        return POLY_TICK
    if venue == "novig":
        return novig_live.MILLI
    return KALSHI_TICK


def snap_pay(venue: str, price: Decimal) -> Decimal | None:
    """Round down to the venue increment so the order does not pay more than this price."""
    if venue == "novig":
        return novig_live.snap_price(price)
    snapped = price.quantize(venue_tick(venue), rounding=ROUND_DOWN)
    if snapped <= 0 or snapped >= ONE:
        return None
    return snapped


def _positive_fee_in(payload, keys) -> Decimal | None:
    """First strictly positive fee on the payload for these keys. 0 is missing."""
    if not isinstance(payload, (dict, list)):
        return None
    for node in _walk(payload):
        for key in keys:
            if key not in node or node.get(key) in (None, ""):
                continue
            number = _dec(node.get(key))
            if number is not None and number > 0:
                return number
    return None


def fee_returned(payload) -> Decimal | None:
    """A fee the venue put on the response. Missing or 0 means the venue did not send one.

    Kalshi POST truth is average_fee_paid (Bobichon 0.0175). fee_cost / taker_fees
    on a later GET are the same all-in fee. Do not treat a missing key as $0.

    Novig GET /v3/portfolio/fills: `fee` is present on a charged fill and
    omitted when uncharged. Confirm overlay stores that (0 included). A 0 on
    Kalshi `fee` is still missing.
    """
    confirm = venue_fill_confirm.from_payload(payload)
    if isinstance(confirm, dict) and confirm.get("known") and str(confirm.get("venue") or "").lower() == "novig":
        if "fee" in confirm and confirm.get("fee") not in (None, ""):
            number = _dec(confirm.get("fee"))
            if number is not None:
                return number
    found = _positive_fee_in(payload, ("average_fee_paid", "fee_cost", "taker_fees", "taker_fee_dollars"))
    if found is not None:
        return found
    return _positive_fee_in(payload, ("fees", "fee"))


def leg_fee(spec: dict, price: Decimal, payload=None) -> Decimal | None:
    """Documented 1-contract taker fee. None only when the venue schedule is unknown.

    Kalshi: POST average_fee_paid when present, else 0.07 × p × (1 − p). Never $0
    because the key was missing. Gemini: 0.07 × p × (1 − p) ceil-cent.
    Polymarket: theta × p × (1 − p) banker's cent. Novig: fill.fee from GET
    fills when present (0 = uncharged); else c × p × (1 − p) from
    market.fee.coefficient. Missing coefficient → None (do not invent; skip send).
    """
    returned = fee_returned(payload)
    venue = spec.get("venue")
    if venue == "kalshi":
        return kalshi_fee_amount(price, payload)
    if venue == "gemini":
        return returned if returned is not None else gemini_taker_fee(price)
    if venue == "polymarket":
        if returned is not None:
            return returned
        return polymarket_us_live.taker_fee(price, spec.get("fee_coefficient"))
    if venue == "novig":
        if returned is not None:
            return returned
        return novig_live.taker_fee(
            price,
            spec.get("fee_coefficient"),
            spec.get("fee_charged"),
            spec.get("event_status"),
        )
    return Decimal("0")


def _profit_block(spec: dict, limit: Decimal | None, other_price: Decimal | None, other_fee: Decimal | None) -> str:
    """Empty when this limit is still a profitable pair. Otherwise a skip reason with the prices and the cap.

    Profitable means the two prices are under $1 and the two prices plus the documented fee are at or under NET_MAX.
    Every venue uses its documented taker formula (Kalshi included). Unknown fee → not sent.
    """
    if limit is None or other_price is None or other_fee is None:
        return "other leg price missing; not sent"
    fee = leg_fee(spec, limit)
    if fee is None:
        return "fee unknown; not sent"
    gross = limit + other_price
    net = gross + fee + other_fee
    if gross >= ONE or net > effective_net_max():
        return (
            f"limit={_money(limit)} other={_money(other_price)} gross={_money(gross)} "
            f"fee={_money(fee)} other_fee={_money(other_fee)} net={_net_text(net)} "
            f"cap gross under 1 net at or under {send_line()}"
        )
    return ""


def max_leg_price(venue: str, other_price: Decimal, other_fee: Decimal, fee_coefficient=None, fee_charged=None, event_status=None) -> Decimal | None:
    """Highest price on this leg that still keeps the pair under $1 and at or under NET_MAX after fees."""
    if other_price is None or other_fee is None:
        return None
    fee_spec = {
        "venue": venue,
        "fee_coefficient": fee_coefficient,
        "fee_charged": fee_charged,
        "event_status": event_status,
    }
    cap = effective_net_max()
    if venue == "novig":
        best = None
        for price in novig_live.iter_grid_prices():
            if other_price + price >= ONE:
                break
            fee = leg_fee(fee_spec, price)
            if fee is None:
                return None
            if other_price + other_fee + price + fee <= cap:
                best = price
            else:
                break
        return best
    tick = venue_tick(venue)
    best = None
    price = tick
    while price < ONE:
        if other_price + price >= ONE:
            break
        fee = leg_fee(fee_spec, price)
        if fee is None:
            return None
        if other_price + other_fee + price + fee <= cap:
            best = price
        else:
            break
        price += tick
    return best


def midway_limit(quoted: Decimal, maximum: Decimal | None, tick: Decimal) -> Decimal | None:
    """Halfway from the quote to the most we can pay, rounded so it does not go past that max."""
    if quoted is None or maximum is None:
        return None
    mid = (quoted + maximum) / 2
    if mid > maximum:
        return None
    snapped = mid.quantize(tick, rounding=ROUND_DOWN)
    if snapped <= 0 or snapped >= ONE or snapped > maximum:
        return None
    return snapped


def shard_user_missing(status: int, payload, note: str) -> bool:
    """HTTP 404 when the account is not open on that venue's matching shard.

    Kalshi names this insufficient_shard_balance and "Exchange user not found."
    A short cash balance is a different reject and stays false here.
    """
    if int(status or 0) != 404:
        return False
    parts = [str(note or "")]
    if payload is not None:
        parts.append(json.dumps(payload, default=str))
    blob = " ".join(parts).lower()
    return "insufficient_shard_balance" in blob or "exchange user not found" in blob


def ioc_nothing_filled(status: int, payload) -> bool:
    """True when the venue cancelled an immediate-or-cancel and filled nothing.

    That is HTTP 201 with status cancelled and filled 0, or Gemini's email case:
    the order was cancelled because no part would fill immediately.
    """
    if filled_contracts(payload) > 0:
        return False
    text = json.dumps(payload, default=str).lower() if payload is not None else ""
    compact = text.replace("-", "").replace(" ", "")
    email = "nopartoftheorderwouldbefilled" in compact or "immediateorcancel" in compact
    cancelled = False
    if isinstance(payload, (dict, list)):
        for node in _walk(payload):
            state = str(node.get("status") or node.get("state") or node.get("orderState") or "").lower()
            if state in ("cancelled", "canceled"):
                cancelled = True
    if status in (200, 201) and cancelled:
        return True
    return email


def memory_ask(spec: dict, books) -> Decimal | None:
    """Ask we would pay, from the in-memory book the websocket updates."""
    books = books or {}
    venue = spec.get("venue")
    outcome = str(spec.get("outcome") or "")
    instrument = str(spec.get("instrument") or "")
    if venue == "gemini":
        return gemini_book_ask(books.get("gemini"), instrument, outcome)
    if venue == "kalshi":
        field = "yes_ask_dollars" if outcome == "yes" else "no_ask_dollars"
        for event in books.get("kalshi") or []:
            if not isinstance(event, dict):
                continue
            for raw in event.get("contracts") or []:
                if isinstance(raw, dict) and str(raw.get("ticker") or "") == instrument:
                    return _dec(raw.get(field))
        return None
    if venue == "polymarket":
        intent = str(spec.get("intent") or "")
        for raw in books.get("polymarket") or []:
            if not isinstance(raw, dict) or str(raw.get("slug") or "") != instrument:
                continue
            yes_ask = _dec(raw.get("yes_ask"))
            yes_bid = _dec(raw.get("yes_bid"))
            if intent == "ORDER_INTENT_BUY_SHORT" or (not intent and outcome == "no"):
                return None if yes_bid is None else ONE - yes_bid
            return yes_ask
    if venue == "novig":
        for raw in books.get("novig") or []:
            if not isinstance(raw, dict) or str(raw.get("market_id") or "") != instrument:
                continue
            if outcome == "yes":
                return _dec(raw.get("yes_ask"))
            if outcome == "no":
                return _dec(raw.get("no_ask"))
    return None


def read_websocket_price(spec: dict, books, timeout: float = WS_PRICE_SEC, clock=None, sleep=None) -> tuple[Decimal | None, str]:
    """Wait briefly for the stream price. A miss at the end of the wait is a timeout."""
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    deadline = clock() + timeout
    while True:
        price = memory_ask(spec, books)
        if price is not None and Decimal("0") < price < ONE:
            return price, "ok"
        if clock() >= deadline:
            return None, "timeout"
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(0.05, remaining))


def _level_px_sz(level) -> tuple[Decimal | None, Decimal | None]:
    size = None
    if isinstance(level, dict):
        raw = level.get("price") if level.get("price") is not None else level.get("price_dollars")
        if raw is None and isinstance(level.get("px"), dict):
            raw = level["px"].get("value")
        price = _dec(raw)
        for key in ("amount", "qty", "quantity", "size", "count"):
            value = level.get(key)
            if isinstance(value, dict):
                value = value.get("value")
            size = _dec(value)
            if size is not None:
                break
    elif isinstance(level, (list, tuple)) and level:
        price = _dec(level[0])
        size = _dec(level[1]) if len(level) > 1 else None
    else:
        price = None
    if price is not None and price >= 1 and price == price.to_integral_value() and price <= 100:
        price = price / Decimal("100")
    return price, size


def _best_price(levels, want_low: bool) -> Decimal | None:
    price, _size = _best_px_sz(levels, want_low)
    return price


def _best_px_sz(levels, want_low: bool) -> tuple[Decimal | None, Decimal | None]:
    best = None
    best_size = None
    for level in levels or []:
        price, size = _level_px_sz(level)
        if price is None:
            continue
        if best is None or (want_low and price < best) or ((not want_low) and price > best):
            best = price
            best_size = size
    return best, best_size


def _http_get(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "stockresearch-lock"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, type(exc).__name__


def fetch_book_ask(spec: dict, *, pace: bool = True, priority: bool = False) -> tuple[Decimal | None, str]:
    """Current ask from the same public book HTTP the catalog already uses.

    pace=True is catalog / leftover / slate: background HTTP budget, skip the
    tick when the in-flight cap is full.
    pace=False or priority=True is send-path REST confirm (B 50-cross, T0 send,
    lock send, dip GTC, catalog verify): reserved seat, never skip, does not
    sit behind catalog/leftover/C-D-E walks. Novig 429 retry stays off when
    pace is False.
    """
    venue = spec.get("venue")
    instrument = str(spec.get("instrument") or "")
    outcome = str(spec.get("outcome") or "")
    if not instrument:
        return None, "missing instrument"
    send = bool(priority) or (not pace)
    ok = False
    try:
        try:
            ok = venue_pace.wait_turn(
                str(venue or "book"),
                priority=venue_pace.PRIORITY_SEND if send else venue_pace.PRIORITY_BACKGROUND,
            )
        except Exception:
            ok = True
        if not ok:
            return None, getattr(venue_pace, "SKIPPED", "http budget skip")
        return _fetch_book_ask_http(
            spec, venue, instrument, outcome, pace=False, retry=bool(pace)
        )
    finally:
        if ok:
            try:
                venue_pace.release_turn(str(venue or "book"))
            except Exception:
                pass


def _fetch_book_ask_http(
    spec: dict, venue, instrument: str, outcome: str, *, pace: bool, retry: bool
) -> tuple[Decimal | None, str]:
    if venue == "gemini":
        url = "https://api.gemini.com/v1/book/" + urllib.parse.quote(instrument, safe="")
    elif venue == "kalshi":
        url = "https://api.elections.kalshi.com/trade-api/v2/markets/" + urllib.parse.quote(instrument, safe="") + "/orderbook"
    elif venue == "polymarket":
        url = polymarket_us_live.GATEWAY + "/v1/markets/" + urllib.parse.quote(instrument, safe="") + "/book"
    elif venue == "novig":
        path = "/v3/catalog/markets/" + urllib.parse.quote(instrument, safe="") + "/book"
        try:
            book = novig_live._get(path, {"depth": "3"}, pace=pace, retry=retry)
        except Exception as exc:
            return None, type(exc).__name__
        try:
            record_order_io("novig", "book", {"path": path}, 200, json.dumps(book, default=str)[:8000])
        except Exception:
            pass
        if not isinstance(book, dict):
            return None, "novig book missing"
        orders = book.get("orders") if isinstance(book.get("orders"), dict) else {}
        outcome_id = str(spec.get("outcome_id") or "")
        other_id = ""
        # Ask for this outcome is 1 - best bid on the other outcome.
        for oid, rows in orders.items():
            if str(oid) == outcome_id:
                continue
            other_id = str(oid)
            break
        if not other_id and len(orders) == 2 and outcome_id:
            other_id = next((str(oid) for oid in orders if str(oid) != outcome_id), "")
        bid, qty = novig_live._best_level(orders, other_id) if other_id else (None, Decimal("0"))
        if bid is None:
            return None, "novig ask missing"
        ask = ONE - bid
        if ask <= 0 or ask >= ONE:
            return None, "novig ask off grid"
        _attach_quote_size(spec, qty, overwrite=True)
        return ask, "book"
    else:
        return None, "unknown venue"
    status, body = _http_get(url)
    try:
        record_order_io(str(venue), "book", {"url": url}, status, body)
    except Exception:
        pass
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    if status != 200 or not isinstance(payload, dict):
        return None, f"book http {status}"
    if venue == "gemini":
        if outcome == "yes":
            price, size = _best_px_sz(payload.get("asks") or [], want_low=True)
        else:
            bid, size = _best_px_sz(payload.get("bids") or [], want_low=False)
            price = None if bid is None else ONE - bid
        _attach_quote_size(spec, size, overwrite=True)
        return price, "book"
    if venue == "kalshi":
        fp = payload.get("orderbook_fp") if isinstance(payload.get("orderbook_fp"), dict) else {}
        book = payload.get("orderbook") if isinstance(payload.get("orderbook"), dict) else payload
        if outcome == "yes":
            levels = fp.get("no_dollars") or book.get("no") or book.get("no_dollars")
            bid, size = _best_px_sz(levels, want_low=False)
        else:
            levels = fp.get("yes_dollars") or book.get("yes") or book.get("yes_dollars")
            bid, size = _best_px_sz(levels, want_low=False)
        _attach_quote_size(spec, size, overwrite=True)
        return (None if bid is None else ONE - bid), "book"
    book = payload.get("marketData") if isinstance(payload.get("marketData"), dict) else payload
    bids = book.get("bids") or []
    offers = book.get("offers") or []
    yes_bid, bid_sz = _best_px_sz(bids[:1], want_low=True) if bids else (None, None)
    yes_ask, ask_sz = _best_px_sz(offers[:1], want_low=True) if offers else (None, None)
    intent = str(spec.get("intent") or "")
    if intent == "ORDER_INTENT_BUY_SHORT" or (not intent and outcome == "no"):
        _attach_quote_size(spec, bid_sz, overwrite=True)
        return (None if yes_bid is None else ONE - yes_bid), "book"
    _attach_quote_size(spec, ask_sz, overwrite=True)
    return yes_ask, "book"


def orders_halted() -> bool:
    """True when the leftover latch file is present. New lock pairs use lock.on."""
    global ORDERS_ENABLED
    try:
        present = ORDERS_STOP.exists()
    except OSError:
        return False
    if not present:
        return False
    ORDERS_ENABLED = False
    return True


def _should_write_lock_system_flag() -> bool:
    """Skip live systems.json when tests redirected only the leftover latch."""
    try:
        import prediction_systems

        live_cfg = (RAW / "systems.json").resolve()
        live_stop = (RAW / "orders_stopped.json").resolve()
        cfg = Path(prediction_systems.CONFIG_PATH).resolve()
        stop = Path(ORDERS_STOP).resolve()
    except OSError:
        return False
    if stop == live_stop:
        return True
    return cfg != live_cfg


def set_lock_system_on(on: bool) -> bool:
    """Write systems.json lock.on only. Never flips B/C/D/E. Does not spawn."""
    if not _should_write_lock_system_flag():
        return False
    try:
        import prediction_systems

        cfg = prediction_systems.get_system("lock")
        if bool(cfg.on) == bool(on):
            return False
        prediction_systems.apply_updates({"lock": {"on": bool(on)}}, spawn=False)
        return True
    except Exception:
        return False


def clear_one_leg_new_pair_latch() -> bool:
    """Paul turned A on (or leftover completed). Drop the leftover latch file."""
    global ORDERS_ENABLED, _halt_logged
    removed = False
    try:
        if ORDERS_STOP.exists():
            ORDERS_STOP.unlink()
            removed = True
    except OSError:
        return False
    ORDERS_ENABLED = True
    _halt_logged = False
    return removed


def stop_orders(reason: str, filled: dict | None = None, missed: dict | None = None) -> None:
    """Turn Lock gap (A) off after a one-leg miss. B/C/D/E stay on.

    Writes leftover latch metadata. The send switch is systems.json lock.on.
    The phone ping runs only after this call creates the latch file.
    """
    global ORDERS_ENABLED
    ORDERS_ENABLED = False
    set_lock_system_on(False)
    ORDERS_STOP.parent.mkdir(parents=True, exist_ok=True)
    try:
        if ORDERS_STOP.exists():
            return
    except OSError:
        return
    row = {
        "stopped": True,
        "reason": reason,
        "timestamp": datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds"),
        "scope": "lock",
        "letter": "A",
    }
    ORDERS_STOP.write_text(json.dumps(row), encoding="utf-8")
    _phone_orders_off(filled or {}, missed or {})


def _watch_key(row: dict | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("bet_key") or "")


def strategy_b_blocks_lock(sport: str, title: str) -> bool:
    """True when Strategy B has this tennis match open, or still holds T0.

    Reads B's state file only. Does not import live_strategy_b (that module
    pulls the research sim). Does not touch orders_stopped.json. Same-match
    skip so lock-bot does not double-buy an open B game. Absorbed is included
    because B still holds the T0 both-Yes after the 50-cross window dies.
    """
    if str(sport or "").strip().lower() != "tennis":
        return False
    want = " ".join(str(title or "").lower().split())
    if not want:
        return False
    try:
        if not STRATEGY_B_STATE.exists():
            return False
        data = json.loads(STRATEGY_B_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    for row in data.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("stage") or "") not in _STRATEGY_B_OPEN:
            continue
        game = " ".join(str(row.get("game") or "").lower().split())
        if game and game == want:
            return True
    return False


def _watch_blocks_lock(path: Path, title: str, open_stages: set[str]) -> bool:
    want = " ".join(str(title or "").lower().split())
    if not want or not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    for row in data.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("stage") or "") not in open_stages:
            continue
        game = " ".join(str(row.get("game") or "").lower().split())
        if game and game == want:
            return True
    return False


def leftover_watch_skipped(spec: dict | None = None, bet_key: str = "") -> bool:
    """True for directional C/D/E/F (and B) fills. Lock A leftover stays.

    Do not leftover-watch a directional dog, favorite, or tennis spread. Those
    are one-way Yes, not a two-leg lock. A 55¢ favorite hedge on an E
    tennis-t0-dog key is this leak. F tennis-t0-spread must not be hedged.
    G soccer-t0-total must not be hedged.
    Lock bet_keys (sport\\tgame\\tdate...) are not skipped.
    """
    spec = spec if isinstance(spec, dict) else {}
    if spec.get("_strategy_b"):
        return True
    system = str(spec.get("_system") or spec.get("system") or "").strip().lower()
    if system in _DIRECTIONAL_SYSTEMS:
        return True
    key = str(bet_key or spec.get("_bet_key") or spec.get("bet_key") or "")
    head = key.split("\t", 1)[0].strip().lower()
    if head in _DIRECTIONAL_BET_PREFIXES:
        return True
    if head.replace("-", "_") in _DIRECTIONAL_SYSTEMS:
        return True
    step = str(spec.get("_step") or spec.get("step") or "").strip().lower()
    if step.startswith(_DIRECTIONAL_STEP_PREFIXES):
        return True
    return False


def directional_blocks_lock(sport: str, title: str) -> bool:
    """True when C, D, or E holds a directional Yes on this event.

    Same idea as skip-absorbed B: lock does not hunt a game C/D/E just filled.
    C/D/E are directional Yes; skip lock on that event while the ticket is open.
    """
    if not str(title or "").strip():
        return False
    if _watch_blocks_lock(CFB_FAVORITE_STATE, title, _DIRECTIONAL_OPEN):
        return True
    if _watch_blocks_lock(SPREAD_T0_STATE, title, _DIRECTIONAL_OPEN):
        return True
    if _watch_blocks_lock(TENNIS_T0_DOG_STATE, title, _DIRECTIONAL_OPEN):
        return True
    if _watch_blocks_lock(TENNIS_T0_SPREAD_STATE, title, _DIRECTIONAL_OPEN):
        return True
    if _watch_blocks_lock(SOCCER_T0_TOTAL_STATE, title, _DIRECTIONAL_OPEN):
        return True
    return False


def watch_is_active(row: dict | None = None) -> bool:
    """True when a one-leg leftover watch is open. Stopped watches do not count."""
    if row is None:
        return any(watch_is_active(item) for item in load_all_watches())
    if isinstance(row.get("watches"), list) and not row.get("bet_key"):
        return any(watch_is_active(item) for item in row["watches"] if isinstance(item, dict))
    if not row.get("bet_key") and not row.get("filled_venue"):
        return False
    return not bool(row.get("stopped"))


def load_all_watches() -> list[dict]:
    """Every leftover row. A single-object file is one row. Wrapper {watches: [...]} is many."""
    try:
        if not ONE_LEG_WATCH.exists():
            return []
        data = json.loads(ONE_LEG_WATCH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("watches")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and (item.get("bet_key") or item.get("filled_venue"))]
    if data.get("bet_key") or data.get("filled_venue"):
        return [data]
    return []


def load_one_leg_watch() -> dict | None:
    """First active leftover, else the latest row. None when the file is missing or unreadable."""
    rows = load_all_watches()
    for row in rows:
        if watch_is_active(row):
            return row
    return rows[-1] if rows else None


def clear_one_leg_watch() -> None:
    try:
        if ONE_LEG_WATCH.exists():
            ONE_LEG_WATCH.unlink()
    except OSError:
        pass


def _write_one_leg_watch(row: dict) -> None:
    ONE_LEG_WATCH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ONE_LEG_WATCH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(ONE_LEG_WATCH)


def _write_all_watches(rows: list[dict]) -> None:
    kept = [item for item in rows if isinstance(item, dict) and (item.get("bet_key") or item.get("filled_venue"))]
    if not kept:
        clear_one_leg_watch()
        return
    if len(kept) == 1:
        _write_one_leg_watch(kept[0])
        return
    _write_one_leg_watch({"watches": kept})


def _replace_watch(watch: dict) -> None:
    key = _watch_key(watch)
    rows = load_all_watches()
    out = []
    replaced = False
    for row in rows:
        if key and _watch_key(row) == key:
            out.append(watch)
            replaced = True
        else:
            out.append(row)
    if not replaced:
        out.append(watch)
    _write_all_watches(out)


def _drop_watch(watch: dict | None) -> list[dict]:
    key = _watch_key(watch)
    if not key:
        return [item for item in load_all_watches() if watch_is_active(item)]
    kept = [item for item in load_all_watches() if _watch_key(item) != key]
    _write_all_watches(kept)
    return [item for item in kept if watch_is_active(item)]


def _watch_claim_bits() -> dict:
    cand = getattr(_consider, "cand", None)
    out = {
        "sport": str(getattr(_consider, "sport", "") or ""),
        "market_type": "",
        "claim_side": "",
        "number": "",
    }
    if isinstance(cand, dict):
        out["market_type"] = str(cand.get("market_type") or "")
        out["claim_side"] = str(cand.get("side") or "")
        out["number"] = str(cand.get("number") or "")
        if not out["sport"]:
            out["sport"] = str(cand.get("sport") or "")
    return out


def opposite_side_of(side: str) -> str:
    """Yes if we hold No, No if we hold Yes. Empty when the fill side is unknown."""
    text = str(side or "").lower()
    if text == "yes":
        return "no"
    if text == "no":
        return "yes"
    return ""


def _same_instrument(left: str, right: str) -> bool:
    return str(left or "").strip().lower() == str(right or "").strip().lower() and bool(str(left or "").strip())


def record_send_skip(reason: str, title: str = "", key: str = "", spec: dict | None = None) -> None:
    """Write the last send-gate / flatten skip to orders.jsonl and lock_last_skip.json."""
    row = {
        "event": "skip",
        "reason": str(reason or "").strip()[:400],
        "game": title,
        "bet_key": key,
        "at": _iso_now(),
    }
    if isinstance(spec, dict):
        try:
            _attach_market_size(spec)
        except Exception:
            pass
        if spec.get("venue"):
            row["venue"] = spec.get("venue")
        if spec.get("instrument"):
            row["instrument"] = spec.get("instrument")
        row.update(_size_log_fields(spec))
    try:
        _append(row)
    except Exception:
        pass
    try:
        LAST_SKIP.parent.mkdir(parents=True, exist_ok=True)
        LAST_SKIP.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
    except Exception:
        pass


def record_research_row(row: dict) -> None:
    """Append a reconstructable T0/cross/E snapshot to orders.jsonl. No page rebuild.

    event t0/cross/e/b_skip is not in the fill/skip refresh set. Fail-soft.
    Does not write lock_last_skip.json.
    """
    if not isinstance(row, dict):
        return
    payload = {key: value for key, value in row.items() if value not in (None,)}
    payload.setdefault("at", _iso_now())
    try:
        _append(payload)
    except Exception:
        pass


def _takeable_size(spec: dict | None) -> Decimal | None:
    size = _dec((spec or {}).get("quote_size"))
    if size is None:
        return None
    return size


def order_qty_of(spec: dict | None) -> Decimal:
    """Whole contracts this order is sending. Default 1."""
    qty = venue_fill_confirm.house_size_of(spec)
    return qty if qty > 0 else SIZE


def poly_size_lt_qty_skip(spec: dict | None, *, rest: bool = True) -> str:
    """If Poly displayed ask size < this order's qty, return skip reason.

    REST recheck attaches quote_size. Even FOK would reject a thin book; we
    do not POST. Log token: poly_size_lt_qty_skip.
    """
    if not isinstance(spec, dict):
        return ""
    if str(spec.get("venue") or "").lower() != "polymarket":
        return ""
    qty = order_qty_of(spec)
    if rest:
        fetch_book_ask(spec, pace=False)
    size = _takeable_size(spec)
    if size is None or size < qty:
        saw = "missing" if size is None else format(size, "f")
        return f"{POLY_SIZE_LT_QTY_SKIP} need>={format(qty, 'f')} saw={saw}"
    return ""


def poly_partial_unexpected(spec: dict | None, filled: Decimal) -> bool:
    """True when Poly filled some but not the qty we ordered (FOK should be 0 or >=qty)."""
    if not isinstance(spec, dict):
        return False
    if str(spec.get("venue") or "").lower() != "polymarket":
        return False
    qty = order_qty_of(spec)
    return Decimal("0") < filled < qty


def note_poly_fok_partial(spec: dict, filled: Decimal, log=None) -> None:
    """Log + ntfy a Poly partial. Do not treat as a house fill. Do not flatten as 1."""
    qty = order_qty_of(spec)
    msg = (
        f"{POLY_FOK_PARTIAL_UNEXPECTED} venue=polymarket "
        f"instrument={spec.get('instrument') or ''} "
        f"cum={format(filled, 'f')} qty={format(qty, 'f')}; "
        "not a house 1-contract fill; not flattening as 1; no second IOC"
    )
    if log:
        try:
            log(msg)
        except Exception:
            pass
    record_send_skip(msg, str(spec.get("game") or ""), str(spec.get("_bet_key") or ""), spec=spec)
    _phone_watch_note(
        "Poly FOK partial",
        f"Polymarket FOK still returned a partial. {msg}. Did not treat as filled. Did not flatten as 1.",
    )


def _venue_miss_rank(spec: dict | None) -> int:
    """Higher = historically more one-leg misses. Frozen VENUE_MISS_RANK."""
    venue = str((spec or {}).get("venue") or "").lower()
    return int(VENUE_MISS_RANK.get(venue, 0))


def _live_from_book(spec: dict, *, pace: bool = True) -> tuple[str, dict | None]:
    """REST ask + displayed size. Drops stale websocket size. Empty reason means takeable."""
    live = dict(spec)
    live.pop("quote_size", None)
    try:
        ask, note = fetch_book_ask(live, pace=pace)
    except TypeError:
        ask, note = fetch_book_ask(live)
    venue = str(live.get("venue") or "")
    if ask is None:
        return f"{venue} book empty ({note})", None
    size = _takeable_size(live)
    qty = order_qty_of(live)
    if str(venue).lower() == "polymarket" and (size is None or size < qty):
        saw = "missing" if size is None else format(size, "f")
        return f"{POLY_SIZE_LT_QTY_SKIP} need>={format(qty, 'f')} saw={saw}", None
    if size is None or size < SIZE:
        saw = "missing" if size is None else format(size, "f")
        return f"{venue} no takeable size (need >= 1, saw {saw})", None
    snapped = snap_pay(venue, ask)
    if snapped is None:
        return f"{venue} ask not sendable", None
    live["pay"] = format(snapped, "f")
    live["quote_source"] = "book"
    live["quote_price"] = format(snapped, "f")
    live["quote_seen_at"] = _iso_now()
    return "", live


def _pick_hard_leg(first: dict, second: dict) -> tuple[dict, dict]:
    """Hard = smaller REST ask size. Tie: worse fill venue, else pricier cash.

    Research freeze 2026-10-24 (Paul sequential hard-first). Size is primary.
    Simultaneous dual IOC is not this path.
    """
    sa = _takeable_size(first)
    sb = _takeable_size(second)
    if sa is None:
        sa = Decimal("0")
    if sb is None:
        sb = Decimal("0")
    if sa < sb:
        return first, second
    if sb < sa:
        return second, first
    ra, rb = _venue_miss_rank(first), _venue_miss_rank(second)
    if ra > rb:
        return first, second
    if rb > ra:
        return second, first
    pa = _dec(first.get("pay")) or Decimal("0")
    pb = _dec(second.get("pay")) or Decimal("0")
    if pa > pb:
        return first, second
    if pb > pa:
        return second, first
    ordered = _sort_legs_for_log([first, second])
    return ordered[0], ordered[1]


def _live_pair_from_books(
    first: dict, second: dict, *, pace: bool = True
) -> tuple[str, dict | None, dict | None]:
    """REST both legs in parallel. Empty reason means both books came back."""
    slots: list[tuple[str, dict | None] | None] = [None, None]

    def _one(idx: int, spec: dict) -> None:
        try:
            slots[idx] = _live_from_book(spec, pace=pace)
        except Exception as exc:
            slots[idx] = (type(exc).__name__, None)

    workers = [
        threading.Thread(target=_one, args=(0, first), daemon=True),
        threading.Thread(target=_one, args=(1, second), daemon=True),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    gate_a, live_a = slots[0] if slots[0] is not None else ("book recheck failed", None)
    gate_b, live_b = slots[1] if slots[1] is not None else ("book recheck failed", None)
    if live_a is None:
        return gate_a or "book recheck failed", None, None
    if live_b is None:
        return gate_b or "book recheck failed", None, None
    ok, why = same_settlement_legs(first, second, live_a, live_b)
    if not ok:
        return why, live_a, live_b
    return "", live_a, live_b


def _quote_size_token(spec: dict | None) -> str:
    size = (spec or {}).get("quote_size")
    if size in (None, ""):
        return "missing"
    return str(size)


def _recheck_pair_books(first: dict, second: dict) -> tuple[str, dict | None, dict | None]:
    """Recheck both books before either HTTP. Empty reason means both still takeable under cap."""
    gate, live_a, live_b = _live_pair_from_books(first, second, pace=False)
    if gate or live_a is None or live_b is None:
        return gate or "book recheck failed", live_a, live_b
    pa, pb = _dec(live_a.get("pay")), _dec(live_b.get("pay"))
    fa = leg_fee(live_a, pa) if pa is not None else None
    fb = leg_fee(live_b, pb) if pb is not None else None
    block_a = _profit_block(live_a, pa, pb, fb)
    block_b = _profit_block(live_b, pb, pa, fa)
    block = block_a or block_b
    if block:
        limit_s, other_s = (live_a, live_b) if block_a else (live_b, live_a)
        extra = (
            f" limit_size={_quote_size_token(limit_s)} other_size={_quote_size_token(other_s)}"
            f" limit_venue={limit_s.get('venue') or ''} other_venue={other_s.get('venue') or ''}"
        )
        # Keep the live specs so the skip row can log REST sizes. Caller still
        # bails on a non-empty gate and does not POST.
        return f"over cap after book recheck {block}{extra}", live_a, live_b
    return "", live_a, live_b


def _hedge_outcome_for_venue(watch: dict, venue: str, instrument: str) -> str:
    """Side that completes a true lock. Never opponent-No of a filled Yes-dog (Goffin)."""
    filled_instr = str(watch.get("filled_instrument") or "")
    missed_instr = str(watch.get("missed_instrument") or "")
    missed_side = str(watch.get("missed_side") or "").lower()
    filled_side = str(watch.get("filled_side") or "").lower()
    filled_venue = str(watch.get("filled_venue") or "").lower()
    missed_venue = str(watch.get("missed_venue") or "").lower()
    venue = str(venue or "").lower()
    if _same_instrument(instrument, missed_instr) or (not instrument and venue == missed_venue):
        outcome = missed_side
    elif _same_instrument(instrument, filled_instr) or venue == filled_venue:
        outcome = opposite_side_of(filled_side)
    else:
        outcome = missed_side if missed_side in {"yes", "no"} else opposite_side_of(filled_side)
    if outcome not in {"yes", "no"}:
        return ""
    if (
        _same_instrument(instrument, missed_instr)
        and filled_side == "yes"
        and missed_side == "yes"
        and outcome == "no"
    ):
        return ""
    if venue == filled_venue and _same_instrument(instrument, filled_instr) and outcome == filled_side:
        return ""
    return outcome


def hedge_spec_for_venue(watch: dict, venue: str, info: dict | None) -> dict | None:
    """True-hedge send spec for one venue. Missed intended, origin Yes+No, or opponent Yes."""
    venue = str(venue or "").lower()
    info = info if isinstance(info, dict) else {}
    instrument = str(info.get("instrument") or "")
    if venue == str(watch.get("filled_venue") or "").lower() and not instrument:
        instrument = str(watch.get("filled_instrument") or "")
    if venue == str(watch.get("missed_venue") or "").lower() and not instrument:
        instrument = str(watch.get("missed_instrument") or "")
    opp = _hedge_outcome_for_venue(watch, venue, instrument)
    if venue not in _ORDER_VENUES or not instrument or opp not in {"yes", "no"}:
        return None
    intent = str(info.get("intent") or "")
    if venue == "polymarket":
        intent = "ORDER_INTENT_BUY_SHORT" if opp == "no" else "ORDER_INTENT_BUY_LONG"
    spec = {
        "venue": venue,
        "instrument": instrument,
        "outcome": opp,
        "intent": intent,
        "fee_coefficient": info.get("fee_coefficient"),
        "fee_charged": info.get("fee_charged"),
        "event_status": info.get("event_status"),
        "pay": "",
        "_watch_recovery": True,
    }
    if venue == "novig":
        oid = info.get("outcome_id") or ""
        if opp == "yes":
            oid = info.get("yes_outcome_id") or oid
        elif opp == "no":
            oid = info.get("no_outcome_id") or oid
        spec["outcome_id"] = str(oid or "")
        if not spec["outcome_id"]:
            return None
    return spec


def hedge_specs_from_watch(watch: dict) -> list[dict]:
    """Hedges of the filled player only. Never same-bet opponent-No of a Yes-dog."""
    venues: dict[str, dict] = {}
    stored = watch.get("venues") if isinstance(watch.get("venues"), dict) else {}
    for name, info in stored.items():
        if isinstance(info, dict):
            _merge_venue(venues, str(name), info)
    _merge_venue(venues, str(watch.get("filled_venue") or ""), {
        "instrument": watch.get("filled_instrument"),
    })
    _merge_venue(venues, str(watch.get("missed_venue") or ""), {
        "instrument": watch.get("missed_instrument"),
        "intent": watch.get("missed_intent"),
        "outcome_id": watch.get("missed_outcome_id"),
        "yes_outcome_id": watch.get("missed_outcome_id") if str(watch.get("missed_side") or "").lower() == "yes" else "",
        "no_outcome_id": watch.get("missed_outcome_id") if str(watch.get("missed_side") or "").lower() == "no" else "",
        "fee_coefficient": watch.get("missed_fee_coefficient"),
        "fee_charged": watch.get("missed_fee_charged"),
        "event_status": watch.get("missed_event_status"),
    })
    specs = []
    seen = set()
    for venue in _ORDER_VENUES:
        spec = hedge_spec_for_venue(watch, venue, venues.get(venue) or {})
        if spec is None:
            continue
        key = (spec["venue"], spec["instrument"], spec["outcome"])
        if key in seen:
            continue
        seen.add(key)
        specs.append(spec)
    return specs


def _flatten_spec(filled_spec: dict) -> dict | None:
    """Buy the opposite on the same venue/instrument as the filled contract."""
    venue = str(filled_spec.get("venue") or "")
    instrument = str(filled_spec.get("instrument") or "")
    book = _book_side(filled_spec) or str(filled_spec.get("outcome") or "")
    opp = opposite_side_of(book)
    if venue not in _ORDER_VENUES or not instrument or opp not in {"yes", "no"}:
        return None
    spec = {
        "venue": venue,
        "instrument": instrument,
        "outcome": opp,
        "intent": str(filled_spec.get("intent") or ""),
        "fee_coefficient": filled_spec.get("fee_coefficient"),
        "fee_charged": filled_spec.get("fee_charged"),
        "event_status": filled_spec.get("event_status"),
        "outcome_id": str(filled_spec.get("outcome_id") or ""),
        "yes_outcome_id": str(filled_spec.get("yes_outcome_id") or ""),
        "no_outcome_id": str(filled_spec.get("no_outcome_id") or ""),
        "pay": "",
        "_flatten": True,
        "_watch_recovery": True,
        "_strategy_b": bool(filled_spec.get("_strategy_b")),
        "_bet_key": filled_spec.get("_bet_key") or "",
    }
    if venue == "polymarket":
        spec["intent"] = "ORDER_INTENT_BUY_SHORT" if opp == "no" else "ORDER_INTENT_BUY_LONG"
    if venue == "novig":
        oid = str(filled_spec.get("outcome_id") or "")
        if opp == "yes":
            oid = str(filled_spec.get("yes_outcome_id") or oid)
        elif opp == "no":
            oid = str(filled_spec.get("no_outcome_id") or oid)
        spec["outcome_id"] = oid
        if not spec["outcome_id"]:
            return None
    return spec


def flatten_filled_leg(log, key: str, title: str, filled_spec: dict) -> dict:
    """IOC buy opposite on the filled venue/instrument. Not a NET_MAX lock; an unwind."""
    blank = {
        "filled": False,
        "advance": False,
        "payload": None,
        "status": 0,
        "note": "flatten spec missing",
        "pay": "",
        "spec": filled_spec,
        "step": "flatten",
        "posted": False,
    }
    held = _dec(
        filled_spec.get("fill_qty") or filled_spec.get("confirm_qty") or filled_spec.get("qty")
    )
    if held is not None and Decimal("0") < held < SIZE:
        blank["note"] = f"not flattening as 1 (venue qty {format(held, 'f')})"
        record_send_skip(blank["note"], title, key)
        return blank
    spec = _flatten_spec(filled_spec)
    if spec is None:
        record_send_skip("flatten spec missing", title, key)
        return blank
    ask, note = fetch_book_ask(spec, pace=False)
    if ask is None:
        blank["note"] = f"flatten book empty ({note})"
        record_send_skip(blank["note"], title, key)
        _phone_watch_note("Flatten missed", f"Flatten not sent. {title}. {blank['note']}.")
        return blank
    size = _takeable_size(spec)
    if size is None or size < SIZE:
        saw = "missing" if size is None else format(size, "f")
        blank["note"] = f"flatten no takeable size (saw {saw})"
        record_send_skip(blank["note"], title, key)
        _phone_watch_note("Flatten missed", f"Flatten not sent. {title}. {blank['note']}.")
        return blank
    spec["quote_source"] = "book"
    spec["quote_price"] = format(ask, "f")
    spec["quote_seen_at"] = _iso_now()
    spec["_bet_key"] = key
    _phone_watch_note(
        "Flatten sent",
        f"Flatten send. {title}. {spec['venue']} {spec['instrument']} {spec['outcome']} ask {spec['quote_price']}.",
    )
    outcome = _one_ioc(log, key, spec, ask, "flatten", _send, None, None)
    filled = leg_filled_at_least_one(outcome)
    _append({
        "event": "flatten_filled" if filled else "flatten_miss",
        "bet_key": key,
        "game": title,
        "venue": spec["venue"],
        "instrument": spec["instrument"],
        "side": spec["outcome"],
        "limit_price": outcome.get("pay") or spec.get("quote_price"),
        "http_status": outcome.get("status"),
        "note": outcome.get("note") or "",
        "step": "flatten",
    })
    if filled:
        try:
            import orders_performance_refresh
            orders_performance_refresh.maybe_after_flatten(title, key, filled=True)
        except Exception:
            pass
    record_send_skip("flatten filled" if filled else f"flatten missed {outcome.get('note') or ''}", title, key)
    _phone_watch_note(
        "Flatten filled" if filled else "Flatten missed",
        f"Flatten {'filled' if filled else 'missed'}. {title}. {spec['venue']} {spec['instrument']} {spec['outcome']}.",
    )
    return outcome


def _merge_venue(venues: dict, venue: str, entry: dict | None) -> None:
    venue = str(venue or "").lower()
    if venue not in _ORDER_VENUES or not isinstance(entry, dict):
        return
    instrument = str(entry.get("instrument") or "")
    if not instrument:
        return
    cur = venues.setdefault(venue, {})
    if not cur.get("instrument"):
        cur["instrument"] = instrument
    for key in (
        "intent", "outcome_id", "yes_outcome_id", "no_outcome_id",
        "fee_coefficient", "fee_charged", "event_status",
    ):
        value = entry.get(key)
        if value not in (None, "") and cur.get(key) in (None, ""):
            cur[key] = value


def _venues_from_cand(cand: dict | None) -> dict:
    if not isinstance(cand, dict):
        return {}
    out: dict[str, dict] = {}
    _merge_venue(out, "kalshi", {"instrument": cand.get("kalshi_ticker")})
    _merge_venue(out, "gemini", {"instrument": cand.get("gemini_symbol")})
    _merge_venue(out, "polymarket", {
        "instrument": cand.get("polymarket_slug"),
        "fee_coefficient": cand.get("fee_coefficient"),
    })
    _merge_venue(out, "novig", {
        "instrument": cand.get("novig_market"),
        "yes_outcome_id": cand.get("novig_yes_outcome"),
        "no_outcome_id": cand.get("novig_no_outcome"),
        "fee_coefficient": cand.get("fee_coefficient"),
        "fee_charged": cand.get("fee_charged"),
        "event_status": cand.get("event_status"),
    })
    return out


def _venues_from_books(watch: dict, books: dict | None) -> dict:
    """Match extra venue instruments on the same settlement. Fail-soft. No orders."""
    if not isinstance(books, dict):
        return {}
    out: dict[str, dict] = {}
    kind = str(watch.get("market_type") or "")
    number = _norm_num(watch.get("number"))
    for raw in books.get("polymarket") or []:
        if not isinstance(raw, dict):
            continue
        slug = str(raw.get("slug") or raw.get("instrument") or "")
        raw_kind = str(raw.get("kind") or raw.get("market_type") or "")
        raw_num = _norm_num(raw.get("number") or raw.get("line"))
        if not slug:
            continue
        if kind and raw_kind and raw_kind != kind:
            continue
        if number and raw_num and raw_num != number:
            continue
        _merge_venue(out, "polymarket", {
            "instrument": slug,
            "fee_coefficient": raw.get("fee_coefficient"),
        })
    for raw in books.get("novig") or []:
        if not isinstance(raw, dict):
            continue
        market = str(raw.get("market_id") or raw.get("instrument") or "")
        raw_kind = str(raw.get("kind") or raw.get("market_type") or "")
        raw_num = _norm_num(raw.get("number") or raw.get("line"))
        if not market:
            continue
        if kind and raw_kind and raw_kind != kind:
            continue
        if number and raw_num and raw_num != number:
            continue
        _merge_venue(out, "novig", {
            "instrument": market,
            "yes_outcome_id": raw.get("buy_yes_outcome") or raw.get("yes_outcome_id"),
            "no_outcome_id": raw.get("buy_no_outcome") or raw.get("no_outcome_id"),
            "fee_coefficient": raw.get("fee_coefficient"),
            "fee_charged": raw.get("fee_charged"),
            "event_status": raw.get("event_status"),
        })
    return out


def _venue_entry_from_spec(spec: dict) -> dict:
    outcome = str(spec.get("outcome") or spec.get("side") or "").lower()
    oid = str(spec.get("outcome_id") or "")
    entry = {
        "instrument": str(spec.get("instrument") or ""),
        "intent": str(spec.get("intent") or ""),
        "outcome_id": oid,
        "fee_coefficient": spec.get("fee_coefficient"),
        "fee_charged": spec.get("fee_charged"),
        "event_status": spec.get("event_status"),
    }
    if oid and outcome == "yes":
        entry["yes_outcome_id"] = oid
    if oid and outcome == "no":
        entry["no_outcome_id"] = oid
    return entry


def migrate_watch_schema(watch: dict) -> dict:
    """Rewrite a leftover watch to the continuous-quote schema. Does not un-stop."""
    row = dict(watch or {})
    filled_side = str(row.get("filled_side") or "").lower()
    row["origin_venue"] = str(row.get("origin_venue") or row.get("filled_venue") or "")
    row["opposite_side"] = str(row.get("opposite_side") or opposite_side_of(filled_side) or "")
    row["watch_mode"] = WATCH_MODE
    row["watch_tick_sec"] = WATCH_TICK_SEC
    row["watch_cadence"] = "continuous / tick"
    if not row.get("date"):
        parts = str(row.get("bet_key") or "").split("\t")
        if len(parts) > 2:
            row["date"] = parts[2]
    venues: dict[str, dict] = {}
    if isinstance(row.get("venues"), dict):
        for name, info in row["venues"].items():
            if isinstance(info, dict):
                _merge_venue(venues, str(name), info)
    _merge_venue(venues, str(row.get("filled_venue") or ""), {
        "instrument": row.get("filled_instrument"),
        "intent": row.get("filled_intent") or "",
        "outcome_id": row.get("filled_outcome_id") or "",
    })
    missed_side = str(row.get("missed_side") or "").lower()
    missed_oid = str(row.get("missed_outcome_id") or "")
    missed_entry = {
        "instrument": row.get("missed_instrument"),
        "intent": row.get("missed_intent"),
        "outcome_id": missed_oid,
        "fee_coefficient": row.get("missed_fee_coefficient"),
        "fee_charged": row.get("missed_fee_charged"),
        "event_status": row.get("missed_event_status"),
    }
    if missed_oid and missed_side == "yes":
        missed_entry["yes_outcome_id"] = missed_oid
    if missed_oid and missed_side == "no":
        missed_entry["no_outcome_id"] = missed_oid
    _merge_venue(venues, str(row.get("missed_venue") or ""), missed_entry)
    for name, info in _venues_from_cand(getattr(_consider, "cand", None)).items():
        _merge_venue(venues, name, info)
    row["venues"] = venues
    return row


def persist_one_leg_watch(
    key: str,
    title: str,
    filled_spec: dict,
    missed_spec: dict,
    fill_px: Decimal,
    fill_fee: Decimal,
    books: dict | None = None,
) -> dict | None:
    """Write the leftover watch after recovery still left one fill. Latch stays on.

    A second leftover on a different settlement is added. The same bet_key that
    is already stopped is left stopped (no catch-up). Same active key is updated.
    Directional C/D/E fills do not open a lock leftover.
    """
    if leftover_watch_skipped(filled_spec, key):
        return None
    for existing in load_all_watches():
        if str(existing.get("bet_key") or "") != key:
            continue
        if existing.get("stopped"):
            return existing
        break
    maximum = max_leg_price(
        str(missed_spec.get("venue") or ""),
        fill_px,
        fill_fee,
        missed_spec.get("fee_coefficient"),
        missed_spec.get("fee_charged"),
        missed_spec.get("event_status"),
    )
    bits = _watch_claim_bits()
    filled_side = _book_side(filled_spec) or str(filled_spec.get("outcome") or "")
    parts = str(key).split("\t")
    row = {
        "bet_key": key,
        "game": title,
        "sport": bits.get("sport") or (parts[0] if parts else ""),
        "date": parts[2] if len(parts) > 2 else "",
        "market_type": bits.get("market_type") or "",
        "claim_side": bits.get("claim_side") or "",
        "number": bits.get("number") or "",
        "started_at": _iso_now(),
        "filled_venue": str(filled_spec.get("venue") or ""),
        "filled_instrument": str(filled_spec.get("instrument") or ""),
        "filled_side": filled_side,
        "fill_px": format(fill_px, "f"),
        "fill_fee": format(fill_fee, "f"),
        "origin_venue": str(filled_spec.get("venue") or ""),
        "opposite_side": opposite_side_of(filled_side),
        "missed_venue": str(missed_spec.get("venue") or ""),
        "missed_instrument": str(missed_spec.get("instrument") or ""),
        "missed_side": str(missed_spec.get("outcome") or missed_spec.get("side") or ""),
        "missed_intent": str(missed_spec.get("intent") or ""),
        "missed_fee_coefficient": missed_spec.get("fee_coefficient"),
        "missed_fee_charged": missed_spec.get("fee_charged"),
        "missed_event_status": missed_spec.get("event_status"),
        "missed_outcome_id": str(missed_spec.get("outcome_id") or ""),
        "max_other_price": format(maximum, "f") if maximum is not None else None,
        "watch_mode": WATCH_MODE,
        "watch_tick_sec": WATCH_TICK_SEC,
        "watch_cadence": "continuous / tick",
        "stopped": False,
        "venues": {},
    }
    for existing in load_all_watches():
        if str(existing.get("bet_key") or "") == key and existing.get("started_at"):
            row["started_at"] = existing.get("started_at")
            break
    venues: dict[str, dict] = {}
    _merge_venue(venues, str(filled_spec.get("venue") or ""), _venue_entry_from_spec(filled_spec))
    _merge_venue(venues, str(missed_spec.get("venue") or ""), _venue_entry_from_spec(missed_spec))
    for name, info in _venues_from_cand(getattr(_consider, "cand", None)).items():
        _merge_venue(venues, name, info)
    for name, info in _venues_from_books(row, books).items():
        _merge_venue(venues, name, info)
    row["venues"] = venues
    _replace_watch(row)
    return row


def missed_spec_from_watch(watch: dict) -> dict | None:
    """Rebuild a sendable missed-leg spec from the watch file. Pay is cash of that leg."""
    venue = str(watch.get("missed_venue") or "").lower()
    info = {}
    stored = watch.get("venues") if isinstance(watch.get("venues"), dict) else {}
    if isinstance(stored.get(venue), dict):
        info = dict(stored[venue])
    info.setdefault("instrument", watch.get("missed_instrument"))
    info.setdefault("intent", watch.get("missed_intent"))
    info.setdefault("outcome_id", watch.get("missed_outcome_id"))
    info.setdefault("fee_coefficient", watch.get("missed_fee_coefficient"))
    info.setdefault("fee_charged", watch.get("missed_fee_charged"))
    info.setdefault("event_status", watch.get("missed_event_status"))
    spec = opposite_spec_for_venue(watch, venue, info)
    if spec is None:
        return None
    spec["outcome"] = str(watch.get("missed_side") or spec.get("outcome") or "").lower()
    spec["pay"] = watch.get("max_other_price") or spec.get("pay") or ""
    return spec


def opposite_spec_for_venue(watch: dict, venue: str, info: dict | None) -> dict | None:
    """Opposite-side send spec for one venue. Origin uses the filled instrument."""
    venue = str(venue or "").lower()
    info = info if isinstance(info, dict) else {}
    opp = str(watch.get("opposite_side") or opposite_side_of(watch.get("filled_side") or "") or "").lower()
    instrument = str(info.get("instrument") or "")
    if venue == str(watch.get("filled_venue") or "").lower() and not instrument:
        instrument = str(watch.get("filled_instrument") or "")
    if venue not in _ORDER_VENUES or not instrument or opp not in {"yes", "no"}:
        return None
    intent = str(info.get("intent") or "")
    if venue == "polymarket":
        intent = "ORDER_INTENT_BUY_SHORT" if opp == "no" else "ORDER_INTENT_BUY_LONG"
    spec = {
        "venue": venue,
        "instrument": instrument,
        "outcome": opp,
        "intent": intent,
        "fee_coefficient": info.get("fee_coefficient"),
        "fee_charged": info.get("fee_charged"),
        "event_status": info.get("event_status"),
        "pay": "",
        "_watch_recovery": True,
    }
    if venue == "novig":
        oid = info.get("outcome_id") or ""
        if opp == "yes":
            oid = info.get("yes_outcome_id") or oid
        elif opp == "no":
            oid = info.get("no_outcome_id") or oid
        spec["outcome_id"] = str(oid or "")
        if not spec["outcome_id"]:
            return None
    return spec


def opposite_specs_from_watch(watch: dict) -> list[dict]:
    """True hedges of the filled player. Delegates to hedge_specs_from_watch (Goffin)."""
    return hedge_specs_from_watch(watch)


def _polymarket_fill_cash(
    side: str,
    ledger_price: Decimal | None,
    sent_limit: Decimal | None,
    *,
    spread=None,
    quote=None,
    intent: str = "",
) -> Decimal | None:
    """Pay-side cash for a Polymarket fill. Per-order venue debit, not a global invert."""
    cash = venue_fill_confirm.poly_house_cash(
        avg=ledger_price,
        spread=spread,
        quote=quote,
        pay=sent_limit if quote is None else quote,
        api_limit=sent_limit,
        intent=intent or ("ORDER_INTENT_BUY_SHORT" if str(side or "").lower() == "no" else ""),
    )
    if cash is not None:
        return cash
    if ledger_price is None:
        return None
    side = str(side or "").lower()
    if side != "no":
        return ledger_price if Decimal("0") < ledger_price < ONE else None
    if not (Decimal("0") < ledger_price < ONE):
        return None
    if sent_limit is not None and Decimal("0") < sent_limit < ONE:
        if abs(ledger_price - sent_limit) <= Decimal("0.05"):
            return ledger_price
        if abs(ledger_price - (ONE - sent_limit)) <= Decimal("0.05"):
            return sent_limit
    return None


def reconstruct_watch_from_orders(rows: list[dict] | None = None) -> tuple[dict | None, str]:
    """Build a watch from the latest one_leg + fill. Empty when that pair is ambiguous."""
    rows = rows if rows is not None else _read_orders()
    one = None
    for row in reversed(rows):
        if isinstance(row, dict) and row.get("event") == "one_leg":
            one = row
            break
    if one is None:
        return None, "no one_leg row"
    key = str(one.get("bet_key") or "")
    if not key:
        return None, "one_leg missing bet_key"
    claim = None
    filled_event = None
    missed_sent = None
    filled_sent = None
    filled_venues = set()
    for row in rows:
        if not isinstance(row, dict) or str(row.get("bet_key") or "") != key:
            continue
        event = row.get("event")
        if event == "claim":
            claim = row
        elif event == "filled":
            filled_event = row
            filled_venues.add(str(row.get("venue") or ""))
        elif event == "sent":
            venue = str(row.get("venue") or "")
            if venue == str(one.get("second_venue") or ""):
                missed_sent = row
            if venue == str(one.get("venue") or ""):
                filled_sent = row
    missed_venue = str(one.get("second_venue") or "")
    filled_venue = str(one.get("venue") or "")
    if missed_venue in filled_venues and filled_venue in filled_venues:
        return None, "latest one_leg already has both venues filled"
    if not filled_venue or not missed_venue:
        return None, "one_leg missing filled or missed venue"
    if missed_sent is None or not missed_sent.get("instrument"):
        return None, "missed venue has no sent instrument"
    fill_px = _dec((filled_event or {}).get("price") or one.get("price"))
    filled_side = str((filled_event or {}).get("side") or one.get("side") or "")
    filled_limit = _dec((filled_sent or {}).get("limit_price"))
    filled_quote = _dec((filled_sent or {}).get("quote_price") or (filled_sent or {}).get("house_cash") or (filled_sent or {}).get("wire"))
    if filled_venue == "polymarket":
        fill_px = _polymarket_fill_cash(
            filled_side,
            fill_px,
            filled_limit,
            quote=filled_quote,
            intent="ORDER_INTENT_BUY_SHORT" if filled_side == "no" else "ORDER_INTENT_BUY_LONG",
        )
    if fill_px is None or fill_px <= 0 or fill_px >= ONE:
        return None, "fill cash price missing or ambiguous"
    filled_spec = {
        "venue": filled_venue,
        "instrument": str(one.get("instrument") or (filled_event or {}).get("instrument") or ""),
        "outcome": filled_side,
        "intent": "ORDER_INTENT_BUY_SHORT" if filled_venue == "polymarket" and filled_side == "no" else (
            "ORDER_INTENT_BUY_LONG" if filled_venue == "polymarket" else ""
        ),
    }
    fill_fee = leg_fee(filled_spec, fill_px)
    if fill_fee is None:
        return None, "fill fee unknown"
    missed_side = str(missed_sent.get("side") or "")
    missed_spec = {
        "venue": missed_venue,
        "instrument": str(missed_sent.get("instrument") or ""),
        "outcome": missed_side,
        "intent": "",
        "fee_coefficient": None,
        "fee_charged": None,
        "event_status": None,
        "outcome_id": "",
    }
    if missed_venue == "polymarket":
        missed_spec["intent"] = "ORDER_INTENT_BUY_SHORT" if missed_side == "no" else "ORDER_INTENT_BUY_LONG"
        return None, "missed Polymarket leg needs fee_coefficient; watch only future one-legs"
    if missed_venue == "novig" and not missed_spec.get("outcome_id"):
        return None, "missed Novig leg needs outcome_id; watch only future one-legs"
    maximum = max_leg_price(missed_venue, fill_px, fill_fee)
    title = str((claim or {}).get("game") or "")
    sport = str((claim or {}).get("sport") or (key.split("\t", 1)[0] if key else ""))
    row = {
        "bet_key": key,
        "game": title,
        "sport": sport,
        "market_type": str((claim or {}).get("market_type") or ""),
        "claim_side": str((claim or {}).get("side") or ""),
        "number": str((claim or {}).get("number") or ""),
        "started_at": _iso_now(),
        "reconstructed": True,
        "filled_venue": filled_venue,
        "filled_instrument": filled_spec["instrument"],
        "filled_side": filled_side,
        "fill_px": format(fill_px, "f"),
        "fill_fee": format(fill_fee, "f"),
        "missed_venue": missed_venue,
        "missed_instrument": missed_spec["instrument"],
        "missed_side": missed_side,
        "missed_intent": missed_spec.get("intent") or "",
        "missed_fee_coefficient": None,
        "missed_fee_charged": None,
        "missed_event_status": None,
        "missed_outcome_id": "",
        "max_other_price": format(maximum, "f") if maximum is not None else None,
        "stopped": False,
    }
    if not row["filled_instrument"] or not row["missed_instrument"] or missed_side not in {"yes", "no"}:
        return None, "reconstruction missing instrument or side"
    return migrate_watch_schema(row), "ok"


def maybe_resume_one_leg_watch(log) -> str:
    """On supervisor start: keep existing watches, or rebuild one from the latest one_leg."""
    rows = load_all_watches()
    active = [row for row in rows if watch_is_active(row)]
    if active:
        changed = False
        migrated = []
        for row in rows:
            if watch_is_active(row) and str(row.get("watch_mode") or "") != WATCH_MODE:
                row = migrate_watch_schema(row)
                changed = True
            migrated.append(row)
        if changed:
            _write_all_watches(migrated)
        current = active[0]
        log(
            f"order watch resume {current.get('game')} origin {current.get('origin_venue') or current.get('filled_venue')} "
            f"opposite {current.get('opposite_side') or opposite_side_of(current.get('filled_side') or '')} "
            f"cadence=continuous/tick tick={WATCH_TICK_SEC}s max={current.get('max_other_price')}"
        )
        return "watching"
    if rows:
        return "stopped"
    try:
        latch_on = ORDERS_STOP.exists()
    except OSError:
        latch_on = False
    if not latch_on:
        return "no latch"
    watch, note = reconstruct_watch_from_orders()
    if watch is None:
        log(f"order watch reconstruct skipped {note}")
        return note
    _write_one_leg_watch(watch)
    log(
        f"order watch reconstructed {watch.get('game')} filled {watch.get('filled_venue')} "
        f"{watch.get('fill_px')} missed {watch.get('missed_venue')} max={watch.get('max_other_price')}"
    )
    return "reconstructed"


def _phone_watch_note(title: str, message: str) -> None:
    """Detached ntfy. Does not wait. Does not place an order."""
    script = ROOT / "tools" / "ntfy_job_done.py"
    route = STAMP / "progress.html"
    try:
        import subprocess
        import sys
        import win_hidden

        win_hidden.popen(
            [sys.executable, "-u", str(script), "--path", str(route), "-t", title, "-m", message],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            new_group=True,
        )
    except Exception:
        pass


def resume_orders_after_lock(log, title: str, watch: dict | None = None) -> None:
    """This leftover filled. Drop it. Lock gap (A) stays off if another leftover is open.

    When no leftover remains, turn A back on (same leftover policy as the old
    latch delete). B/C/D/E were never flipped by the one-leg flag.
    """
    global ORDERS_ENABLED, _halt_logged
    remaining = _drop_watch(watch or load_one_leg_watch())
    if remaining:
        log(f"order watch complete {title}; other leftovers still open; Lock gap stays off")
        _refresh_order_pages()
        return
    if not clear_one_leg_new_pair_latch() and ORDERS_STOP.exists():
        log(f"order watch latch delete failed")
        return
    ORDERS_ENABLED = True
    _halt_logged = False
    set_lock_system_on(True)
    clear_one_leg_watch()
    message = f"Lock completed. Both legs filled. Lock gap (A) is on again. {title}."
    log(f"order watch complete {title}; Lock gap on")
    _phone_watch_note("Lock gap on", message)
    try:
        refresh_balances(log)
    except Exception as exc:
        log(f"order watch balances {type(exc).__name__}")
    _refresh_order_pages()


def stop_watch_keep_latch(log, watch: dict, reason: str) -> None:
    """Stop this leftover loop. Leave Lock gap (A) off and the latch file. Ping once."""
    if watch.get("notified_stop"):
        return
    row = dict(watch)
    row["stopped"] = True
    row["stop_reason"] = reason
    row["stopped_at"] = _iso_now()
    row["notified_stop"] = True
    _replace_watch(row)
    log(f"order watch stop {reason}; Lock gap stays off")
    _phone_watch_note(
        "One-leg watch stopped",
        f"Watch stopped. Lock gap (A) stays off. B–E stay on. {watch.get('game') or ''} {reason}.",
    )
    try:
        import orders_performance_refresh
        orders_performance_refresh.maybe_after_watch_stop(reason, row)
    except Exception:
        pass


def _watch_never_profitable(watch: dict) -> bool:
    fill_px = _dec(watch.get("fill_px"))
    fill_fee = _dec(watch.get("fill_fee"))
    if fill_px is None or fill_fee is None:
        return True
    if fill_px + fill_fee + KALSHI_TICK > effective_net_max():
        return True
    return max_leg_price("kalshi", fill_px, fill_fee) is None


def _watch_already_both(watch: dict) -> bool:
    """True when a true hedge already filled. Same-bet opponent-No of a Yes-dog is not a lock."""
    key = str(watch.get("bet_key") or "")
    if not key:
        return False
    hedges = {
        (
            str(spec.get("venue") or "").lower(),
            str(spec.get("instrument") or "").strip().lower(),
            str(spec.get("outcome") or "").lower(),
        )
        for spec in hedge_specs_from_watch(watch)
    }
    filled_v = str(watch.get("filled_venue") or "").lower()
    filled_i = str(watch.get("filled_instrument") or "")
    filled_s = str(watch.get("filled_side") or "").lower()
    missed_v = str(watch.get("missed_venue") or "").lower()
    missed_i = str(watch.get("missed_instrument") or "")
    missed_s = str(watch.get("missed_side") or "").lower()
    for row in _read_orders():
        if str(row.get("bet_key") or "") != key or row.get("event") != "filled":
            continue
        venue = str(row.get("venue") or "").lower()
        instr = str(row.get("instrument") or "")
        side = str(row.get("side") or "").lower()
        if venue == filled_v and _same_instrument(instr, filled_i) and side == filled_s:
            continue
        if (venue, instr.strip().lower(), side) in hedges:
            return True
        if venue == missed_v and _same_instrument(instr, missed_i) and side == missed_s:
            return True
        if venue == filled_v and _same_instrument(instr, filled_i) and side == opposite_side_of(filled_s):
            return True
    return False


def _status_closed(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("status", "state", "marketStatus", "event_status"):
        raw = str(payload.get(key) or "").lower()
        if raw in CLOSED or raw in {"resolved", "settled"}:
            return True
    inner = payload.get("market") if isinstance(payload.get("market"), dict) else None
    if inner and inner is not payload:
        return _status_closed(inner)
    return False


def missed_market_closed(spec: dict) -> tuple[bool, str]:
    """True when the remaining market looks resolved. Unknown stays open (keep watching)."""
    venue = str(spec.get("venue") or "")
    instrument = str(spec.get("instrument") or "")
    if not instrument:
        return False, "missing instrument"
    try:
        if venue == "kalshi":
            url = "https://api.elections.kalshi.com/trade-api/v2/markets/" + urllib.parse.quote(instrument, safe="")
            status, body = _http_get(url)
            if status == 404:
                return False, "kalshi 404 keep watching"
            payload = json.loads(body) if status == 200 else None
            market = payload.get("market") if isinstance(payload, dict) else payload
            if _status_closed(market if isinstance(market, dict) else payload):
                return True, "kalshi closed"
            return False, "kalshi open"
        if venue == "polymarket":
            url = polymarket_us_live.GATEWAY + "/v1/markets/" + urllib.parse.quote(instrument, safe="")
            status, body = _http_get(url)
            if status == 404:
                return False, "polymarket 404 keep watching"
            payload = json.loads(body) if status == 200 else None
            if _status_closed(payload):
                return True, "polymarket closed"
            return False, "polymarket open"
        if venue == "gemini":
            price, note = fetch_book_ask(spec)
            if "404" in str(note):
                return False, "gemini 404 keep watching"
            return False, "gemini open"
        if venue == "novig":
            price, note = fetch_book_ask(spec)
            if "404" in str(note) or "missing" in str(note):
                return False, str(note)
            return False, "novig open"
    except Exception as exc:
        return False, type(exc).__name__
    return False, "unknown venue"


def _watch_ws_live(watch: dict, venue: str) -> bool:
    parts = str(watch.get("bet_key") or "").split("\t")
    if len(parts) < 3:
        return False
    key = f"{parts[0].replace(' ', '_')}_{parts[1]}_{parts[2].replace('-', '_')}"
    path = RAW / "live_health" / f"{key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    last = ""
    if isinstance(data, dict):
        stamps = data.get("last_update") if isinstance(data.get("last_update"), dict) else {}
        last = str(stamps.get(venue) or "")
        transport = str(data.get("transport") or "").lower()
        if venue not in transport:
            return False
    seen = _parse_ts(last)
    if seen is None:
        return False
    age = (datetime.now(ET) - seen).total_seconds()
    return 0 <= age <= WS_WATCH_FRESH_SEC


def current_watch_ask(watch: dict, spec: dict) -> tuple[Decimal | None, str, str]:
    """Ask we would take now. Websocket last quote when that stream is live, else book HTTP."""
    seen_at = _iso_now()
    if _watch_ws_live(watch, str(spec.get("venue") or "")):
        try:
            import price_memory

            last = price_memory.load_last_game(
                str(watch.get("sport") or ""),
                str(watch.get("game") or ""),
            )
            venue_name = {
                "kalshi": "Kalshi",
                "gemini": "Gemini",
                "polymarket": "Polymarket",
                "novig": "Novig",
            }.get(str(spec.get("venue") or ""), str(spec.get("venue") or ""))
            key = price_memory.contract_key(
                str(watch.get("sport") or ""),
                str(watch.get("game") or ""),
                str(watch.get("market_type") or ""),
                str(watch.get("claim_side") or ""),
                str(watch.get("number") or ""),
                venue_name,
                str(spec.get("outcome") or ""),
            )
            row = last.get(key) if isinstance(last, dict) else None
            if isinstance(row, dict):
                price = _dec(row.get("price"))
                quote_seen = str(row.get("seen_at") or seen_at)
                if price is not None and Decimal("0") < price < ONE:
                    stamp = _parse_ts(quote_seen)
                    if stamp is None or (datetime.now(ET) - stamp).total_seconds() <= WS_WATCH_FRESH_SEC:
                        for key_sz in ("size", "ask_size", "yes_size", "qty"):
                            if row.get(key_sz) not in (None, ""):
                                _attach_quote_size(spec, row.get(key_sz))
                                break
                        return price, "websocket", quote_seen
        except Exception:
            pass
    price, note = fetch_book_ask(spec)
    if price is None:
        return None, str(note or "book"), seen_at
    return price, "book", seen_at


def tick_one_leg_watch(log) -> str:
    """One leftover quote check. Fail-soft: errors log and return. Cadence is continuous / tick."""
    try:
        with venue_pace.FileLock(WATCH_LOCK):
            return _tick_one_leg_watch_locked(log)
    except Exception as exc:
        try:
            log(f"order watch error {type(exc).__name__}")
        except Exception:
            pass
        return "error"


def ensure_watch_ticker(log) -> None:
    """Dedicated leftover loop: quote checks every ≤1s. Supervisor status HTML stays on 60s."""
    global _watch_thread
    with _watch_thread_lock:
        if _watch_thread is not None and _watch_thread.is_alive():
            return

        def _run() -> None:
            while True:
                try:
                    if watch_is_active():
                        tick_one_leg_watch(log)
                except Exception as exc:
                    try:
                        log(f"order watch loop {type(exc).__name__}")
                    except Exception:
                        pass
                time.sleep(max(0.0, float(WATCH_TICK_SEC)))

        _watch_thread = threading.Thread(target=_run, name="one-leg-watch-tick", daemon=True)
        _watch_thread.start()


def _minutes_open(watch: dict, now: datetime | None = None) -> float | None:
    started = _parse_ts(watch.get("started_at"))
    if started is None:
        return None
    stamp = now or datetime.now(ET)
    return round((stamp - started).total_seconds() / 60.0, 2)


def _log_leftover(watch: dict, event: str, extra: dict | None = None) -> None:
    now = datetime.now(ET)
    row = {
        "event": event,
        "seen_at": _iso_now(),
        "game": watch.get("game") or "",
        "bet_key": watch.get("bet_key") or "",
        "filled_side": watch.get("filled_side") or "",
        "origin_venue": watch.get("origin_venue") or watch.get("filled_venue") or "",
        "opposite_side": watch.get("opposite_side") or opposite_side_of(watch.get("filled_side") or ""),
        "missed_venue": watch.get("missed_venue") or "",
        "missed_instrument": watch.get("missed_instrument") or "",
        "missed_side": watch.get("missed_side") or "",
        "max_other_price": watch.get("max_other_price"),
        "minutes_open": _minutes_open(watch, now),
        "source": "live_watch",
    }
    if extra:
        row.update(extra)
    _append_research_jsonl(LEFTOVER_STATS_NAME, row)


def _maybe_log_hour(watch: dict) -> None:
    minutes = _minutes_open(watch)
    if minutes is None or minutes < 60:
        return
    if watch.get("logged_60m"):
        return
    watch["logged_60m"] = True
    try:
        _replace_watch(watch)
    except Exception:
        pass
    _log_leftover(watch, "still_watching_60m", {"buyable": False})


def _tick_too_soon(watch: dict, now: datetime) -> bool:
    if WATCH_MIN_GAP_SEC <= 0:
        return False
    last = _parse_ts(watch.get("last_tick_at"))
    if last is None:
        return False
    return (now - last).total_seconds() < WATCH_MIN_GAP_SEC


def _origin_closed(watch: dict) -> tuple[bool, str]:
    spec = {
        "venue": str(watch.get("filled_venue") or ""),
        "instrument": str(watch.get("filled_instrument") or ""),
        "outcome": str(watch.get("filled_side") or ""),
    }
    if not spec["venue"] or not spec["instrument"]:
        return False, "missing origin"
    return missed_market_closed(spec)


def _rank_qualifying_opposites(log, watch: dict, specs: list[dict], fill_px: Decimal, fill_fee: Decimal) -> list[dict]:
    """Quote every opposite. Keep only after-fee net ≤ NET_MAX. Cheapest opposite first."""
    ranked = []
    cap = effective_net_max()
    for spec in specs:
        ask, source, seen_at = current_watch_ask(watch, spec)
        live_max = max_leg_price(
            spec["venue"],
            fill_px,
            fill_fee,
            spec.get("fee_coefficient"),
            spec.get("fee_charged"),
            spec.get("event_status"),
        )
        extra = {
            "venue": spec["venue"],
            "instrument": spec["instrument"],
            "quote_source": source,
            "quote_seen_at": seen_at,
            "quote_size": spec.get("quote_size") or "",
        }
        if ask is None:
            _log_leftover(watch, "ask_missing", {**extra, "buyable": False})
            log(f"order watch ask missing venue={spec['venue']} instrument={spec['instrument']} {source}")
            continue
        extra["ask"] = format(ask, "f")
        if live_max is None:
            _log_leftover(watch, "no_cap", {**extra, "buyable": False})
            continue
        extra["max_other_price"] = format(live_max, "f")
        if ask > live_max:
            _log_leftover(watch, "ask_above_max", {**extra, "buyable": False})
            log(
                f"order watch skip ask={format(ask, 'f')} max={format(live_max, 'f')} "
                f"venue={spec['venue']} instrument={spec['instrument']} source={source} "
                f"quote_seen {_hhmmss(seen_at)}"
            )
            continue
        limit = min(ask, live_max)
        fee = leg_fee(spec, limit)
        if fee is None:
            _log_leftover(watch, "fee_unknown", {**extra, "buyable": False})
            continue
        skip_poly = poly_size_lt_qty_skip(spec)
        if skip_poly:
            extra["quote_size"] = spec.get("quote_size") or extra.get("quote_size") or ""
            _log_leftover(watch, POLY_SIZE_LT_QTY_SKIP, {**extra, "buyable": False, "note": skip_poly})
            log(
                f"order watch skip {skip_poly} venue={spec['venue']} "
                f"instrument={spec['instrument']} source={source}"
            )
            continue
        gross = limit + fill_px
        net = gross + fee + fill_fee
        if gross >= ONE or net > cap:
            _log_leftover(
                watch,
                "ask_above_max",
                {**extra, "buyable": False, "limit": format(limit, "f"), "net": format(net, "f")},
            )
            continue
        remaining = cap - net
        ranked.append({
            "remaining": remaining,
            "limit": limit,
            "ask": ask,
            "fee": fee,
            "net": net,
            "live_max": live_max,
            "spec": spec,
            "source": source,
            "seen_at": seen_at,
        })
    ranked.sort(key=lambda row: (-row["remaining"], row["limit"], row["spec"]["venue"]))
    return ranked


def _send_watch_ioc(log, watch: dict, row: dict, fill_px: Decimal, fill_fee: Decimal) -> str:
    """One IOC at the quoted opposite. Recheck the cap using the price about to be sent."""
    spec = dict(row["spec"])
    limit = row["limit"]
    ask = row["ask"]
    source = row["source"]
    seen_at = row["seen_at"]
    live_max = row["live_max"]
    if spec.get("venue") == "novig" and not novig_live.orders_live():
        _log_leftover(
            watch,
            "novig_quote_only",
            {
                "buyable": True,
                "venue": "novig",
                "instrument": spec.get("instrument") or "",
                "ask": format(ask, "f"),
                "limit": format(limit, "f"),
                "quote_source": source,
                "quote_seen_at": seen_at,
                "quote_size": spec.get("quote_size") or "",
            },
        )
        log(
            f"order watch skip novig quote only ask={format(ask, 'f')} "
            f"instrument={spec.get('instrument') or ''} source={source}"
        )
        return "novig quote only"
    skip_poly = poly_size_lt_qty_skip(spec)
    if skip_poly:
        _log_leftover(
            watch,
            POLY_SIZE_LT_QTY_SKIP,
            {
                "buyable": False,
                "venue": spec.get("venue") or "",
                "instrument": spec.get("instrument") or "",
                "ask": format(ask, "f"),
                "note": skip_poly,
                "quote_source": source,
                "quote_size": spec.get("quote_size") or "",
            },
        )
        log(
            f"order watch skip {skip_poly} venue={spec.get('venue')} "
            f"instrument={spec.get('instrument') or ''} source={source}"
        )
        record_send_skip(skip_poly, str(watch.get("game") or ""), str(watch.get("bet_key") or ""))
        return POLY_SIZE_LT_QTY_SKIP
    spec["_watch_recovery"] = True
    spec["quote_source"] = source
    spec["quote_price"] = format(limit, "f")
    spec["quote_seen_at"] = seen_at or _iso_now()
    spec["trigger_venue"] = spec["venue"]
    spec["trigger_side"] = spec["outcome"]
    spec["trigger_price"] = spec["quote_price"]
    spec["trigger_seen_at"] = spec["quote_seen_at"]
    spec["trigger_source"] = source
    blocked = _profit_block(spec, limit, fill_px, fill_fee)
    if blocked:
        _log_leftover(
            watch,
            "send_recheck_fail",
            {
                "buyable": False,
                "venue": spec["venue"],
                "instrument": spec["instrument"],
                "ask": format(ask, "f"),
                "limit": format(limit, "f"),
                "note": blocked,
            },
        )
        log(f"order watch skip not profitable venue={spec['venue']} instrument={spec['instrument']} {blocked}")
        return "not profitable"
    _log_leftover(
        watch,
        "buyable_send",
        {
            "buyable": True,
            "venue": spec["venue"],
            "instrument": spec["instrument"],
            "ask": format(ask, "f"),
            "max_other_price": format(live_max, "f"),
            "limit": format(limit, "f"),
            "net": format(row["net"], "f"),
            "remaining": format(row["remaining"], "f"),
            "quote_source": source,
            "quote_seen_at": spec["quote_seen_at"],
            "quote_size": spec.get("quote_size") or "",
        },
    )
    log(
        f"order watch send venue={spec['venue']} instrument={spec['instrument']} "
        f"ask={format(ask, 'f')} max={format(live_max, 'f')} limit={format(limit, 'f')} "
        f"source={source} quote_seen {_hhmmss(spec['quote_seen_at'])} "
        f"book_size={spec.get('quote_size') or ''} orders {_hhmmss(_iso_now())}"
    )
    watch["ioc_sent"] = True
    try:
        _replace_watch(watch)
    except Exception:
        pass
    outcome = _one_ioc(log, str(watch.get("bet_key") or ""), spec, limit, "watch", _send, fill_px, fill_fee)
    if not outcome.get("posted"):
        watch["ioc_sent"] = False
        try:
            _replace_watch(watch)
        except Exception:
            pass
        return "not posted"
    qty = outcome_fill_qty(outcome)
    if qty >= SIZE or leg_filled_at_least_one(outcome):
        _log_leftover(
            watch,
            "ioc_filled",
            {
                "buyable": True,
                "ioc_filled": True,
                "venue": spec["venue"],
                "instrument": spec["instrument"],
                "ask": format(ask, "f"),
                "fill_qty": format(qty, "f"),
                "quote_source": source,
                "quote_seen_at": spec["quote_seen_at"],
                "quote_size": spec.get("quote_size") or "",
            },
        )
        _record_filled(str(watch.get("bet_key") or ""), spec, outcome)
        resume_orders_after_lock(log, str(watch.get("game") or watch.get("bet_key") or ""), watch)
        return "filled"
    if qty > 0:
        _log_leftover(
            watch,
            "ioc_partial",
            {
                "buyable": True,
                "ioc_filled": True,
                "venue": spec["venue"],
                "instrument": spec["instrument"],
                "ask": format(ask, "f"),
                "fill_qty": format(qty, "f"),
                "quote_source": source,
                "quote_seen_at": spec["quote_seen_at"],
                "quote_size": spec.get("quote_size") or "",
            },
        )
        log(
            f"order watch partial venue={spec['venue']} instrument={spec['instrument']} "
            f"fill_qty={format(qty, 'f')}; leftover attempt done, not retrying"
        )
        stop_watch_keep_latch(log, watch, f"partial leftover fill {format(qty, 'f')}; attempt done")
        return "partial"
    _log_leftover(
        watch,
        "ioc_miss",
        {
            "buyable": True,
            "ioc_filled": False,
            "venue": spec["venue"],
            "instrument": spec["instrument"],
            "ask": format(ask, "f"),
            "fill_qty": format(qty, "f"),
            "http_status": outcome.get("status"),
            "note": outcome.get("note") or "",
            "quote_source": source,
            "quote_seen_at": spec["quote_seen_at"],
            "quote_size": spec.get("quote_size") or "",
        },
    )
    log(
        f"order watch miss venue={spec['venue']} instrument={spec['instrument']} "
        f"http={outcome.get('status')} {outcome.get('note') or ''}; leftover attempt done, not retrying"
    )
    stop_watch_keep_latch(log, watch, "leftover IOC miss; attempt done")
    return "miss"


def _tick_one_leg_watch_locked(log) -> str:
    rows = [row for row in load_all_watches() if watch_is_active(row)]
    if not rows:
        return "idle"
    last = "idle"
    for watch in rows:
        last = _tick_single_watch(log, watch)
    return last


def _tick_single_watch(log, watch: dict) -> str:
    if leftover_watch_skipped(watch, str(watch.get("bet_key") or "")):
        row = dict(watch)
        row["stopped"] = True
        row["stop_reason"] = "directional fill; leftover watch not used"
        row["stopped_at"] = _iso_now()
        try:
            _replace_watch(row)
        except Exception:
            pass
        log(
            "order watch skip directional leftover "
            f"{watch.get('game') or watch.get('bet_key') or ''}"
        )
        return "directional skip"
    now = datetime.now(ET)
    if _tick_too_soon(watch, now):
        return "too soon"
    watch["last_tick_at"] = _iso_now()
    try:
        _replace_watch(watch)
    except Exception:
        pass
    _maybe_log_hour(watch)
    if watch.get("ioc_sent"):
        stop_watch_keep_latch(log, watch, "leftover IOC already sent; attempt done")
        return "already sent"
    if _watch_already_both(watch):
        _log_leftover(watch, "already_both", {"buyable": True, "ioc_filled": True})
        resume_orders_after_lock(log, str(watch.get("game") or watch.get("bet_key") or ""), watch)
        return "complete"
    if _watch_never_profitable(watch):
        _log_leftover(watch, "never_profitable", {"buyable": False})
        stop_watch_keep_latch(log, watch, "remaining ask can never be profitable")
        return "never profitable"
    specs = opposite_specs_from_watch(watch)
    if not specs:
        _log_leftover(watch, "bad_watch", {"buyable": False})
        stop_watch_keep_latch(log, watch, "watch missing send fields")
        return "bad watch"
    closed, why = _origin_closed(watch)
    if closed and "404" in str(why):
        _log_leftover(watch, "origin_404", {"buyable": False, "closed_why": why})
        log(f"order watch origin 404 {why}; keep watching other venues")
    elif closed:
        _log_leftover(watch, "resolved_first", {"buyable": False, "closed_why": why})
        stop_watch_keep_latch(log, watch, f"market closed ({why})")
        return "closed"
    fill_px = _dec(watch.get("fill_px"))
    fill_fee = _dec(watch.get("fill_fee"))
    if fill_px is None or fill_fee is None:
        _log_leftover(watch, "no_cap", {"buyable": False})
        stop_watch_keep_latch(log, watch, "watch cap missing")
        return "no cap"
    ranked = _rank_qualifying_opposites(log, watch, specs, fill_px, fill_fee)
    if not ranked:
        return "no qualifying"
    last = "no qualifying"
    for row in ranked:
        last = _send_watch_ioc(log, watch, row, fill_px, fill_fee)
        if last in {"filled", "partial", "miss"}:
            return last
    return last


_PUBLIC_SECRET_WORDS = (
    "signature", "secret", "bearer", "api key", "apikey", "authorization", "password",
)


def _scrub_public_text(text: str) -> str:
    """User-facing venue text. Strip secrets. Never log keys or signatures."""
    cleaned = _redact_secrets(" ".join(str(text or "").split()))[:240]
    lowered = cleaned.lower()
    if any(word in lowered for word in _PUBLIC_SECRET_WORDS):
        return "rejected"
    return cleaned


def _qty_public_label(node: dict) -> str:
    """Kalshi fill_count is the public cancel/fill field. Other qty keys are the fill column."""
    if not isinstance(node, dict):
        return ""
    if node.get("fill_count") not in (None, ""):
        number = _dec(node.get("fill_count"))
        if number is None:
            return f"fill_count {node.get('fill_count')}"
        if number == 0:
            return "fill_count 0"
        return f"fill_count {format(number, 'f')}"
    return ""


def public_venue_note(payload, fallback: str = "") -> str:
    """Cancel, reject, or fill note the venue returned. No secrets."""
    nodes: list[dict] = []
    if isinstance(payload, dict):
        nodes.append(payload)
        inner = payload.get("order")
        if isinstance(inner, dict):
            nodes.append(inner)
        error = payload.get("error")
        if isinstance(error, dict):
            nodes.append(error)
        elif error not in (None, ""):
            nodes.append({"message": str(error)})
    elif isinstance(payload, list):
        nodes.extend(item for item in payload if isinstance(item, dict))
    message = ""
    code = ""
    status = ""
    fill_bit = ""
    for node in nodes:
        if not message:
            for key in (
                "message", "reason", "cancelReason", "cancel_reason",
                "rejectionReason", "rejection_reason",
            ):
                value = node.get(key)
                if value not in (None, ""):
                    message = str(value)
                    break
        if not code:
            code = str(node.get("code") or "")
        if not status:
            status = str(node.get("status") or node.get("state") or node.get("orderState") or "")
        if not fill_bit:
            fill_bit = _qty_public_label(node)
    if code and message and code not in message:
        text = f"{code}: {message}"
    else:
        text = message or code
    bits = []
    use_fallback = not (status or fill_bit or text)
    for bit in (status, fill_bit, text, fallback if use_fallback else ""):
        compact = " ".join(str(bit).split())
        if not compact:
            continue
        key = compact.lower()
        blob = " ".join(bits).lower()
        if key in blob:
            continue
        bits.append(compact)
    return _scrub_public_text(" ".join(bits))


def _public_note(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "response was not json"
    if not isinstance(data, (dict, list)):
        return "response was not an object"
    return public_venue_note(data) or "no message"


def same_settlement_candidate(cand: dict) -> tuple[bool, str]:
    """Send-time gate. Team total ≠ game total ≠ spread ≠ moneyline."""
    import price_memory

    row = cand if isinstance(cand, dict) else {}
    why = price_memory.settlement_mismatch_reason(
        row.get("market_type"),
        row.get("kalshi_ticker"),
        row.get("gemini_symbol"),
        row.get("polymarket_slug"),
    )
    if why:
        return False, why
    return True, ""


def same_settlement_legs(*specs: dict) -> tuple[bool, str]:
    """REST recheck sees bet type on each instrument, not the line number alone."""
    import price_memory

    parts: list[str] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        parts.append(str(spec.get("instrument") or ""))
        parts.append(str(spec.get("market_type") or ""))
    why = price_memory.settlement_mismatch_reason(*parts)
    if why:
        return False, why
    return True, ""


def historical_tennessee_13_5(title: str, game: dict, cand: dict) -> bool:
    """The already-closed Tennessee vs Indianapolis 13.5. Never send it."""
    blob = " ".join(
        str(part)
        for part in (
            title,
            game.get("title_gemini") if isinstance(game, dict) else "",
            game.get("title_kalshi") if isinstance(game, dict) else "",
            game.get("codes") if isinstance(game, dict) else "",
            cand.get("side"),
            cand.get("number"),
            cand.get("kalshi_ticker"),
            cand.get("gemini_symbol"),
            cand.get("market_type"),
        )
    ).lower()
    teams = ("tennessee" in blob or "titans" in blob) and ("indianapolis" in blob or "colts" in blob)
    line = str(cand.get("number") or "") in ("13.5", "13.50") or "13.5" in blob
    return bool(teams and line)


def whole_size(value) -> bool:
    number = _dec(value)
    return number is not None and number >= SIZE


def pair_net(scan, cand: dict) -> Decimal | None:
    """Gross plus the documented fee on each charging leg. None when a fee is unknown.

    yes_price / no_price are already house cash. Kalshi No is 1 − Yes-wire
    (no_price_dollars), inverted once at the book, not the POST ask. This
    sum is unrounded Decimal; qualifies compares it to NET_MAX with no
    extra invert.
    """
    yes = _dec(cand.get("yes_price"))
    no = _dec(cand.get("no_price"))
    if yes is None or no is None:
        return None
    fee = Decimal("0")
    for venue, price in ((str(cand.get("yes_venue") or "").lower(), yes), (str(cand.get("no_venue") or "").lower(), no)):
        if venue == "kalshi":
            fee += kalshi_fee_amount(price)
            continue
        if venue == "gemini":
            fee += scan.gemini_fee(price)
            continue
        if venue == "polymarket":
            part = polymarket_us_live.taker_fee(price, cand.get("fee_coefficient"))
            if part is None:
                saved = _dec(cand.get("polymarket_fee"))
                if saved is None:
                    return None
                part = saved
            fee += part
            continue
        if venue == "novig":
            part = novig_live.taker_fee(
                price,
                cand.get("fee_coefficient"),
                cand.get("fee_charged"),
                cand.get("event_status"),
            )
            if part is None:
                saved = _dec(cand.get("novig_fee"))
                if saved is None:
                    return None
                part = saved
            fee += part
            continue
        return None
    return yes + no + fee


def qualifies(scan, cand: dict, title: str, game: dict) -> tuple[bool, str]:
    if historical_tennessee_13_5(title, game, cand):
        return False, "closed Tennessee vs Indianapolis 13.5 is not sent"
    ok, why = same_settlement_candidate(cand)
    if not ok:
        return False, why
    if scan.gemini_no_rejection(cand):
        return False, "Gemini No is not a buyable offer"
    for field in ("kalshi_status", "gemini_status"):
        if str(cand.get(field) or "").lower() in CLOSED:
            return False, "contract is closed"
    if not whole_size(cand.get("yes_size")) or not whole_size(cand.get("no_size")):
        return False, "both books need at least 1 contract"
    net = pair_net(scan, cand)
    if net is None:
        return False, "fee unknown"
    if net > effective_net_max():
        return False, f"net {_net_text(net)} is above {send_line()}"
    return True, f"net {_net_text(net)}"


def _norm_num(value) -> str:
    number = _dec(value)
    if number is None:
        return ""
    if number == number.to_integral():
        return str(int(number))
    return format(number.normalize(), "f")


def leg_moves(fresh: list[dict], cand: dict) -> tuple[Decimal | None, Decimal | None]:
    """Absolute move since the last check for the Yes leg and the No leg."""
    found = {"yes": None, "no": None}
    kind = str(cand.get("market_type") or "")
    number = _norm_num(cand.get("number"))
    for outcome, venue_key in (("yes", "yes_venue"), ("no", "no_venue")):
        venue = str(cand.get(venue_key) or "").lower()
        best: Decimal | None = None
        seen = False
        for row in fresh or []:
            if str(row.get("venue") or "").lower() != venue:
                continue
            if str(row.get("pay") or "").lower() != outcome:
                continue
            if str(row.get("market_type") or "") != kind:
                continue
            if _norm_num(row.get("number")) != number:
                continue
            move = _dec(row.get("move"))
            if move is None:
                continue
            seen = True
            size = abs(move)
            if best is None or size > best:
                best = size
        found[outcome] = best if seen else None
    return found["yes"], found["no"]


def ordered_outcomes(cand: dict, fresh: list[dict]) -> list[str]:
    """Yes or No labels in send order. Missing moves send Kalshi first."""
    yes_move, no_move = leg_moves(fresh, cand)
    venues = {
        "yes": str(cand.get("yes_venue") or "").lower(),
        "no": str(cand.get("no_venue") or "").lower(),
    }
    if yes_move is None or no_move is None:
        if "kalshi" in venues.values():
            first = "yes" if venues["yes"] == "kalshi" else "no"
            return [first, "no" if first == "yes" else "yes"]
        return ["yes", "no"]
    if yes_move > no_move:
        return ["yes", "no"]
    if no_move > yes_move:
        return ["no", "yes"]
    if venues["yes"] == "kalshi":
        return ["yes", "no"]
    if venues["no"] == "kalshi":
        return ["no", "yes"]
    return ["yes", "no"]


def kalshi_order_body(ticker: str, outcome: str, pay: Decimal, client_order_id: str) -> dict:
    """V2 event order. bid buys Yes. ask sells Yes, which buys No at 1 - price."""
    if outcome == "yes":
        price = pay.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
        side = "bid"
    elif outcome == "no":
        price = (ONE - pay).quantize(KALSHI_TICK, rounding=ROUND_CEILING)
        side = "ask"
    else:
        raise ValueError("outcome")
    return {
        "ticker": ticker,
        "client_order_id": client_order_id,
        "side": side,
        "count": "1.00",
        "price": format(price, "f"),
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
    }


def gemini_order_payload(symbol: str, outcome: str, pay: Decimal) -> dict:
    price = pay.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
    return {
        "symbol": symbol,
        "orderType": "limit",
        "side": "buy",
        "quantity": "1",
        "price": format(price, "f"),
        "outcome": outcome,
        "timeInForce": "immediate-or-cancel",
    }


def polymarket_api_price(intent: str, pay: Decimal) -> Decimal:
    """Long-side price. A short buy at `pay` is sent as 1 - pay, rounded so we do not pay more."""
    if intent in ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_SELL_LONG"):
        return pay.quantize(POLY_TICK, rounding=ROUND_DOWN)
    if intent in ("ORDER_INTENT_BUY_SHORT", "ORDER_INTENT_SELL_SHORT"):
        return (ONE - pay).quantize(POLY_TICK, rounding=ROUND_CEILING)
    raise ValueError("intent")


def polymarket_order_body(slug: str, intent: str, api_price: Decimal, quantity: int = 1) -> dict:
    """Live Poly buy. Official consumer tif includes FILL_OR_KILL (gtc_feasibility).

    Qty is whole contracts, default 1. IOC allows partials; FOK is 0 or the
    qty we send. Do not invent a flag — TIME_IN_FORCE_FILL_OR_KILL is the
    documented enum on POST /v1/orders.
    """
    qty = max(1, int(quantity))
    return {
        "marketSlug": slug,
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": format(api_price, "f"), "currency": "USD"},
        "quantity": qty,
        "tif": POLY_TIF_FOK,
        "intent": intent,
        "participateDontInitiate": False,
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        "synchronousExecution": True,
        "maxBlockTime": "3",
    }


def _walk(value):
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key == venue_fill_confirm.PAYLOAD_KEY:
                continue
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def venue_confirm_of(payload) -> dict | None:
    return venue_fill_confirm.from_payload(payload)


def venue_confirm_known(payload) -> bool:
    row = venue_confirm_of(payload)
    return bool(row and row.get("known"))


def confirm_venue_after_order(spec: dict, status: int, payload) -> dict:
    """Read-only fill/history confirm. Bounded. Does not place or cancel."""
    venue = str((spec or {}).get("venue") or "")
    tape = venue_fill_confirm.tape_filled_qty(payload)
    return venue_fill_confirm.confirm_order(venue, payload, spec, tape_qty=tape)


def filled_contracts(payload) -> Decimal:
    """Contracts filled. Venue confirm wins over the order HTTP tape.

    A known confirm qty is used even when the tape said fill_count 0 or
    status=filled with no qty. An unknown/timeout confirm is 0: do not invent
    a fill. With no confirm overlay, the tape fields are used (tests, ledger).
    Novig native qty is in 1-cent contracts; remaining on a FILLED order means
    a full $1 unit when qty was 100. Prefer dollar units for the size-1 lock.
    A Kalshi HTTP 201 with fill_count >= 1 counts even when the body has no
    status field (21 Oct 2026 Landaluce No).
    A status of filled/executed/complete with no qty field is unknown, not 1
    (21 Oct 2026 SHSU 9.5 22:58: HTTP 201 flatten-miss with fill 0).
    """
    confirm = venue_confirm_of(payload)
    if confirm is not None:
        return venue_fill_confirm.qty_of(confirm)
    if not isinstance(payload, (dict, list)):
        return Decimal("0")
    if isinstance(payload, dict) and payload.get("tif") == "IOC" and payload.get("orderId"):
        dollars = novig_live.filled_dollar_contracts(payload)
        if dollars > 0:
            return dollars
        state = str(payload.get("status") or "").upper()
        if state == "FILLED":
            return SIZE
    # Same tape as posted_leg_returns: THIS-order fill_count / cumQuantity only.
    # Nested book qtyDecimal is not a fill (26 Oct 2026 TB-CAR ghost).
    return venue_fill_confirm.tape_filled_qty(payload)


def outcome_fill_qty(outcome: dict | None) -> Decimal:
    """Filled contracts on an IOC result. Partial qty is kept; it is not a zero miss."""
    if not outcome:
        return Decimal("0")
    qty = filled_contracts(outcome.get("payload"))
    extra = _dec(outcome.get("fill_qty"))
    if extra is not None and extra > qty:
        return extra
    return qty


def order_still_open(payload) -> bool:
    if not isinstance(payload, (dict, list)):
        return False
    for node in _walk(payload):
        status = str(node.get("status") or node.get("state") or node.get("orderState") or "").lower()
        remaining = _dec(node.get("remaining_count") or node.get("remainingQuantity") or node.get("leavesQuantity"))
        if status in ("open", "resting", "new", "accepted", "pending"):
            return True
        if remaining is not None and remaining > 0 and status not in ("canceled", "cancelled", "expired", "rejected"):
            return True
    return False


def bet_blocked(rows: list[dict], bet_key: str, pid_alive) -> bool:
    """True when this bet is open, filled, or claimed by a process that is still alive."""
    phase = "clear"
    claim_pid = None
    for row in rows:
        if row.get("bet_key") != bet_key:
            continue
        event = row.get("event")
        if event == "claim":
            if phase != "position":
                phase = "working"
                claim_pid = row.get("pid")
        elif event == "sent":
            if phase != "position":
                phase = "sent"
        elif event in ("filled", "one_leg"):
            phase = "position"
        elif event == "both_unfilled" and phase != "position":
            phase = "clear"
        elif event in ("preflight_skip", "skip") and phase == "working":
            phase = "clear"
    if phase in ("position", "sent"):
        return True
    if phase == "working":
        try:
            return bool(claim_pid) and bool(pid_alive(int(claim_pid)))
        except (TypeError, ValueError):
            return True
    return False


def _norm_title(title: str) -> str:
    return " ".join(str(title or "").lower().split())


def _poller_code_date(key: str) -> tuple[str, str] | None:
    parts = str(key or "").split("_")
    if len(parts) < 4:
        return None
    year, month, day = parts[-3], parts[-2], parts[-1]
    if len(year) == 4 and year.isdigit() and month.isdigit() and day.isdigit():
        return parts[-4].lower(), f"{year}-{int(month):02d}-{int(day):02d}"
    return None


def _poller_status(status: dict | None = None) -> dict | None:
    if status is not None:
        return status if isinstance(status, dict) else None
    try:
        if not POLLER_STATUS.exists():
            return None
        data = json.loads(POLLER_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def poller_live_sets(status: dict | None = None) -> tuple[set[str], set[tuple[str, str]]]:
    """Game titles and (code, date) still listed in live_pollers_status.json."""
    titles: set[str] = set()
    codes: set[tuple[str, str]] = set()
    data = _poller_status(status)
    if not isinstance(data, dict):
        return titles, codes
    for row in data.get("games") or []:
        if not isinstance(row, dict):
            continue
        title = _norm_title(str(row.get("game") or ""))
        if title:
            titles.add(title)
        parsed = _poller_code_date(str(row.get("key") or ""))
        if parsed:
            codes.add(parsed)
    return titles, codes


def poller_pid_map(status: dict | None = None) -> dict[str, int]:
    """Normalized title and 'code|date' -> current live-poller pid."""
    out: dict[str, int] = {}
    data = _poller_status(status)
    if not isinstance(data, dict):
        return out
    for row in data.get("games") or []:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get("pid"))
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        title = _norm_title(str(row.get("game") or ""))
        if title:
            out[title] = pid
        parsed = _poller_code_date(str(row.get("key") or ""))
        if parsed:
            out[f"{parsed[0]}|{parsed[1]}"] = pid
    return out


def _watch_has_inventory(item: dict) -> bool:
    """True when a leftover watch row names a filled contract."""
    return bool(
        str(item.get("filled_venue") or "").strip()
        or str(item.get("filled_instrument") or "").strip()
    )


def _claim_pid(info: dict) -> int | None:
    try:
        pid = int(info.get("pid"))
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _game_poller_pid(bet_key: str, game: str, pid_map: dict[str, int]) -> int | None:
    title = _norm_title(game)
    if title and title in pid_map:
        return pid_map[title]
    parsed = _bet_code_date(bet_key)
    if parsed:
        return pid_map.get(f"{parsed[0]}|{parsed[1]}")
    return None


def _bet_code_date(bet_key: str) -> tuple[str, str] | None:
    parts = str(bet_key or "").split("\t")
    if len(parts) < 3:
        return None
    code = parts[1].strip().lower()
    date = parts[2].strip()
    if not code or not date:
        return None
    return code, date


def lock_game_id(bet_key: str, game: str = "") -> str:
    """One game is one slot. Code+date when the bet_key has it; else the title."""
    parsed = _bet_code_date(bet_key)
    if parsed:
        return f"{parsed[0]}|{parsed[1]}"
    title = _norm_title(game)
    return title or str(bet_key or "").strip()


def _unique_lock_keys(keys: list[str], games: dict[str, str] | None = None) -> list[str]:
    """First bet_key per unique game."""
    seen: set[str] = set()
    out: list[str] = []
    games = games or {}
    for key in keys:
        gid = lock_game_id(key, games.get(key, ""))
        if not gid or gid in seen:
            continue
        seen.add(gid)
        out.append(key)
    return out


def _lock_game_live(
    bet_key: str,
    game: str,
    live_titles: set[str],
    live_codes: set[tuple[str, str]],
) -> bool:
    title = _norm_title(game)
    if title and title in live_titles:
        return True
    parsed = _bet_code_date(bet_key)
    return bool(parsed and parsed in live_codes)


def effective_max_open_locks() -> int:
    """CLI systems.json max when present; otherwise the live constant 3."""
    try:
        import prediction_systems

        n = int(prediction_systems.get_system("lock").max_open)
        if n >= 1:
            return n
    except Exception:
        pass
    return int(MAX_OPEN_LOCKS)


def lock_system_on() -> bool:
    """False when Lock gap (A) is off. Leftover/flatten still run. B–E ignore this."""
    try:
        import prediction_systems

        return bool(prediction_systems.get_system("lock").on)
    except Exception:
        return True


def lock_open_denial(open_n: int | None = None) -> str:
    """Opportunities skip when live lock-bot pairs are already at MAX_OPEN_LOCKS."""
    cap = effective_max_open_locks()
    n = int(cap if open_n is None else open_n)
    return f"Already have {n} open lock pair(s); max_open_locks={cap}."


def lock_open_line(open_n: int | None = None) -> str:
    """Status text: currently_open / MAX_OPEN_LOCKS."""
    cap = effective_max_open_locks()
    n = int(cap if open_n is None else open_n)
    return f"{n} / {cap}"


_LOCK_VENUE_SNAPSHOT = None


def _lock_venue_snapshot(snapshot=None):
    """Cached C/D/B overlay book. Tests inject _LOCK_VENUE_SNAPSHOT. No live GET."""
    if snapshot is not None:
        return snapshot
    injected = _LOCK_VENUE_SNAPSHOT
    if injected is not None:
        return injected
    try:
        import open_count_sync

        return open_count_sync._read_cache()
    except Exception:
        return None


def _lock_watch_rows(watches: list[dict] | None, include_watches: bool) -> list[dict]:
    if not include_watches:
        return []
    try:
        items = watches if watches is not None else load_all_watches()
    except Exception:
        items = []
    out = []
    for item in items:
        if not isinstance(item, dict) or item.get("_strategy_b"):
            continue
        key = str(item.get("bet_key") or "")
        if key.startswith("tennis-b") or not key:
            continue
        out.append(item)
    return out


def _house_open_lock_keys(
    rows: list[dict] | None = None,
    pid_alive=None,
    live_titles: set[str] | None = None,
    live_codes: set[tuple[str, str]] | None = None,
    watches: list[dict] | None = None,
    include_watches: bool = True,
    poller_pids: dict[str, int] | None = None,
) -> list[str]:
    """House tape thought: filled/leftover/in-flight claim. Not the send cap."""
    alive_fn = pid_alive or _pid_alive
    tape = rows if rows is not None else _read_orders()
    if live_titles is None or live_codes is None:
        titles, codes = poller_live_sets()
        if live_titles is None:
            live_titles = titles
        if live_codes is None:
            live_codes = codes
        if poller_pids is None:
            poller_pids = poller_pid_map()
    if poller_pids is None:
        poller_pids = {}
    watch_keys: set[str] = set()
    for item in _lock_watch_rows(watches, include_watches):
        key = str(item.get("bet_key") or "")
        if watch_is_active(item) and _watch_has_inventory(item):
            watch_keys.add(key)

    state: dict[str, dict] = {}
    order: list[str] = []
    for row in tape:
        if not isinstance(row, dict):
            continue
        key = str(row.get("bet_key") or "")
        if not key or key.startswith("tennis-b"):
            continue
        info = state.get(key)
        if info is None:
            info = {"phase": "clear", "pid": None, "flattened": False, "game": ""}
            state[key] = info
            order.append(key)
        event = row.get("event")
        game = str(row.get("game") or "")
        if game:
            info["game"] = game
        if event == "claim":
            if info["phase"] != "position":
                info["phase"] = "working"
                info["pid"] = row.get("pid")
        elif event == "sent":
            if info["phase"] != "position":
                info["phase"] = "sent"
        elif event == "filled":
            info["phase"] = "position"
        elif event == "one_leg":
            info["phase"] = "position"
            info["flattened"] = False
        elif event == "flatten_filled":
            info["flattened"] = True
        elif event == "both_unfilled" and info["phase"] != "position":
            info["phase"] = "clear"
        elif event in ("preflight_skip", "skip") and info["phase"] == "working":
            info["phase"] = "clear"

    out: list[str] = []
    games = {key: str((state.get(key) or {}).get("game") or "") for key in order}
    for key in order:
        info = state[key]
        live = _lock_game_live(key, str(info.get("game") or ""), live_titles, live_codes)
        watching = key in watch_keys
        phase = info["phase"]
        occupy = False
        if phase in ("working", "sent"):
            claim_pid = _claim_pid(info)
            game_pid = _game_poller_pid(key, str(info.get("game") or ""), poller_pids)
            occupy = (
                claim_pid is not None
                and game_pid is not None
                and claim_pid == game_pid
                and bool(alive_fn(claim_pid))
            )
        elif phase == "position" and not info["flattened"]:
            occupy = live or watching
        if occupy:
            out.append(key)
    for key in watch_keys:
        if key not in out:
            out.append(key)
            games.setdefault(key, "")
    return out


def _lock_tag_instruments(tape: list[dict], watch_rows: list[dict]) -> dict[tuple[str, str], dict]:
    """(venue, instrument) -> lock/leftover bet_key. Claims and empty HTTP do not tag."""
    tags: dict[tuple[str, str], dict] = {}
    games: dict[str, str] = {}

    def add(venue, ident, key, game) -> None:
        shop = str(venue or "").lower()
        ticker = str(ident or "").strip()
        bet = str(key or "")
        if not shop or not ticker or not bet or bet.startswith("tennis-b"):
            return
        tags[(shop, ticker)] = {"bet_key": bet, "game": str(game or games.get(bet) or "")}

    def drop(venue, ident) -> None:
        shop = str(venue or "").lower()
        ticker = str(ident or "").strip()
        if shop and ticker:
            tags.pop((shop, ticker), None)

    for row in tape:
        if not isinstance(row, dict):
            continue
        key = str(row.get("bet_key") or "")
        if not key or key.startswith("tennis-b"):
            continue
        game = str(row.get("game") or "")
        if game:
            games[key] = game
        sid = str(row.get("system") or "")
        if sid in {"tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog", "tennis_t0_spread"}:
            continue
        event = row.get("event")
        venue = row.get("venue")
        ident = row.get("instrument")
        shop = str(venue or "").lower()
        confirm = _dec(row.get("confirm_qty"))
        confirm_n = abs(confirm) if confirm is not None else Decimal("0")
        if event in ("filled", "one_leg"):
            if confirm is not None and confirm_n <= 0:
                continue
            add(venue, ident, key, game or games.get(key, ""))
        elif event == "sent" and row.get("confirm_known") and (
            (shop == "polymarket" and confirm_n > 0) or confirm_n >= 1
        ):
            add(venue, ident, key, game or games.get(key, ""))
        elif event == "flatten_filled":
            drop(venue, ident)
    for item in watch_rows:
        if not watch_is_active(item) or not _watch_has_inventory(item):
            continue
        key = str(item.get("bet_key") or "")
        add(
            item.get("filled_venue"),
            item.get("filled_instrument"),
            key,
            str(item.get("game") or games.get(key) or ""),
        )
    return tags


def _venue_open_lock_keys(tape: list[dict], watch_rows: list[dict], snapshot: dict) -> list[str]:
    """Unique games with venue-confirmed qty still unsettled on a true lock or leftover."""
    try:
        import open_count_sync as ocs
    except Exception:
        ocs = None
    tags = _lock_tag_instruments(tape, watch_rows)
    held: list[str] = []
    games: dict[str, str] = {}
    for (shop, ident), info in tags.items():
        key = str(info.get("bet_key") or "")
        game = str(info.get("game") or "")
        if ocs is not None:
            closed, _why = ocs.market_info_is_final(
                ocs.market_status_of(snapshot, shop, ident), venue=shop
            )
            if closed:
                continue
            qty = ocs.venue_qty(snapshot, shop, ident)
            if qty is None:
                continue
            if not ocs._counts_as_held(shop, qty):
                continue
        else:
            blob = {}
            if shop == "kalshi":
                blob = (snapshot.get("kalshi_by_ticker") or {}).get(ident) or {}
            elif shop == "polymarket":
                blob = (snapshot.get("poly_by_slug") or {}).get(ident) or {}
            qty = _dec((blob or {}).get("qty")) or Decimal("0")
            if qty <= 0:
                continue
            if shop != "polymarket" and qty < 1:
                continue
        games[key] = game
        held.append(key)
    return _unique_lock_keys(held, games)


def open_lock_keys(
    rows: list[dict] | None = None,
    pid_alive=None,
    live_titles: set[str] | None = None,
    live_codes: set[tuple[str, str]] | None = None,
    watches: list[dict] | None = None,
    include_watches: bool = True,
    poller_pids: dict[str, int] | None = None,
    snapshot=None,
    overlay: bool = True,
) -> list[str]:
    """Unique games occupying a MAX_OPEN_LOCKS slot.

    Default (overlay=True): venue-confirmed qty still unsettled on a true lock
    or leftover, same overlay as C/D/B. Catalog claims, HTTP without confirm,
    empty Kalshi 201, flattened-closed, and settled games do not count.
    overlay=False is the house tape thought (tests of claim/fill/flatten).
    Do not call with include_watches=True while holding ORDER_LOCK.
    """
    tape = rows if rows is not None else _read_orders()
    watch_rows = _lock_watch_rows(watches, include_watches)
    house = _house_open_lock_keys(
        tape,
        pid_alive=pid_alive,
        live_titles=live_titles,
        live_codes=live_codes,
        watches=watch_rows,
        include_watches=include_watches,
        poller_pids=poller_pids,
    )
    if not overlay:
        return house
    snap = _lock_venue_snapshot(snapshot)
    book_ok = bool(isinstance(snap, dict) and (snap.get("kalshi_ok") or snap.get("poly_ok")))
    if not book_ok:
        games = {}
        for row in tape:
            if isinstance(row, dict) and row.get("bet_key"):
                games[str(row.get("bet_key"))] = str(row.get("game") or "")
        for item in watch_rows:
            games[str(item.get("bet_key") or "")] = str(item.get("game") or "")
        return _unique_lock_keys(house, games)
    return _venue_open_lock_keys(tape, watch_rows, snap)


def lock_slots_full(open_keys: list[str] | None = None, this_key: str = "") -> bool:
    """True when a new pair would exceed MAX_OPEN_LOCKS. Same game already open is not extra."""
    keys = list(open_keys if open_keys is not None else open_lock_keys())
    if this_key:
        if this_key in keys:
            return False
        this_game = lock_game_id(this_key)
        if this_game and any(lock_game_id(k) == this_game for k in keys):
            return False
    return len(keys) >= effective_max_open_locks()


def _read_orders() -> list[dict]:
    if not ORDERS.exists():
        return []
    rows = []
    for line in ORDERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _append_unlocked(row: dict) -> None:
    ORDERS.parent.mkdir(parents=True, exist_ok=True)
    with ORDERS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _hold_send_html() -> None:
    """Defer orders.html / opportunities / orders_performance until the pair flushes."""
    global _send_html_hold
    _send_html_hold += 1


def _release_send_html() -> None:
    """One deferred page rewrite after both IOCs (or flatten / hard-miss abort)."""
    global _send_html_hold, _send_html_pending
    if _send_html_hold > 0:
        _send_html_hold -= 1
    if _send_html_hold > 0:
        return
    pending_pages = _send_html_pending
    _send_html_pending = False
    queued = list(_send_perf_pending)
    _send_perf_pending.clear()
    if pending_pages:
        _refresh_order_pages()
    for payload, status in queued:
        try:
            _maybe_performance_after_order(payload, status)
        except Exception:
            pass


def _refresh_order_pages() -> None:
    """Rewrite orders.html and opportunities.html. Never sends an order.

    Standalone sends rewrite when the request is sent and when the result is
    known. During a hard-then-easy pair this only marks dirty; the pair flushes
    once after both attempts. A catalog scan is not required.
    """
    global _send_html_pending
    if _send_html_hold > 0:
        _send_html_pending = True
        return
    _rewrite_order_pages_now()


def _rewrite_order_pages_now() -> None:
    """Blocking Drive HTML rewrite. Callers must not sit this on an IOC send."""
    import importlib

    for label, module_name, fn_name in (
        ("orders", "order_ledger", "write_page"),
        ("opportunities", "opportunity_considerations", "write_page"),
    ):
        try:
            module = importlib.reload(__import__(module_name))
            getattr(module, fn_name)()
        except Exception as exc:
            try:
                RAW.mkdir(parents=True, exist_ok=True)
                with (RAW / "live_supervisor.log").open("a", encoding="utf-8") as handle:
                    handle.write(f"order page rebuild {label} {type(exc).__name__}\n")
            except Exception:
                pass


def _maybe_performance_after_order(payload, status=None) -> bool:
    """Background rebuild of orders_performance.html on a confirmed venue fill.

    Qty > 0 is the only yes. Denies, skips, and empty Kalshi 201s do not queue it.
    Never blocks leftover watch or IOC send.
    """
    try:
        import orders_performance_refresh
        return bool(orders_performance_refresh.maybe_after_order(payload, status=status))
    except Exception:
        return False


def _maybe_performance_after_game(kind: str, *, game_key: str = "", title: str = "", we_touched=None) -> bool:
    """Background rebuild when a game we touched settles, voids, or leaves the books."""
    try:
        import orders_performance_refresh
        return bool(orders_performance_refresh.maybe_after_game_complete(
            kind, game_key=game_key, title=title, we_touched=we_touched,
        ))
    except Exception:
        return False


def _is_sell_intent(spec: dict) -> bool:
    return "SELL" in str((spec or {}).get("intent") or "").upper()


def _apply_confirmed_fill_to_local_cash(spec: dict, payload) -> None:
    """Debit local cash only after venue fill-history confirm qty >= 1.

    Kalshi 201 + fill_count 0 is an empty cancel (confirm qty 0): no debit.
    Flatten is a buy of the opposite contract, so it still spends cash. A
    true SELL intent credits proceeds.
    """
    if spec is None:
        return
    qty = filled_contracts(payload) if payload is not None else Decimal("0")
    if qty < ONE:
        return
    venue = str(spec.get("venue") or "")
    if venue not in _BALANCE_VENUES:
        return
    cash_px = _actual_fill_cash(spec, payload)
    fee = leg_fee(spec, cash_px, payload) if cash_px is not None else None
    if cash_px is None or fee is None:
        unit = contract_cost(spec, _leg_cash_price(spec))
        if unit is None:
            return
        notional = unit * qty
    else:
        notional = (cash_px + fee) * qty
    if notional <= 0:
        return
    delta = notional if _is_sell_intent(spec) else -notional
    order_id = _order_id(payload) if payload is not None else ""
    updated = None
    try:
        updated = venue_cash_local.apply_delta(
            venue,
            delta,
            order_id=order_id,
            reason="flatten" if spec.get("_flatten") else "fill",
        )
    except Exception:
        updated = None
    if updated is not None:
        _venue_balances[venue] = updated
        return
    if venue not in _venue_balances:
        return
    _venue_balances[venue] = _venue_balances[venue] + delta
    try:
        _persist_balances()
    except Exception:
        pass


def _after_send_hooks(spec: dict, payload, status=None) -> None:
    """Watch latch + local cash debit + performance page. Fail-soft. Does not send.

    orders_performance.html is queued, not spawned, while a hard-then-easy pair
    is still in flight.
    """
    try:
        _apply_confirmed_fill_to_local_cash(spec, payload)
    except Exception:
        pass
    try:
        _register_send_fill_watch(spec, payload)
    except Exception:
        pass
    try:
        if _send_html_hold > 0:
            _send_perf_pending.append((payload, status))
        else:
            _maybe_performance_after_order(payload, status)
    except Exception:
        pass


def _append(row: dict) -> None:
    with venue_pace.FileLock(ORDER_LOCK):
        _append_unlocked(row)
    if row.get("event") in {"sent", "filled", "one_leg", "both_unfilled", "hard_miss_abort", "skip", "flatten_filled", "flatten_miss"}:
        _refresh_order_pages()


def _fee_tape(spec: dict, payload=None) -> dict:
    """wire / fee / after_fee for orders.jsonl. Fill overwrites the pre-send estimate.

    Unfilled: no after-fee (do not print wire as all-in). Unknown schedule: fee_source
    unknown, not 0. Kalshi estimate is 0.07×p×(1−p); POST average_fee_paid is truth.
    Novig fill overwrites with GET /v3/portfolio/fills `fee` (absent = $0 uncharged).
    """
    qty = filled_contracts(payload) if payload is not None else Decimal("0")
    filled = payload is not None and qty >= ONE
    wire = None
    if filled:
        wire = _actual_fill_cash(spec, payload)
    if wire is None:
        wire = _leg_cash_price(spec)
    fee = leg_fee(spec, wire, payload) if wire is not None else None
    returned = fee_returned(payload) if payload is not None else None
    out: dict = {}
    if not filled and payload is not None:
        out["wire"] = ""
        out["fee"] = ""
        out["after_fee"] = ""
        out["fee_source"] = "no_fill"
        if fee is not None:
            out["fee_estimate"] = format(fee, "f")
        return out
    if wire is not None:
        out["wire"] = format(wire, "f")
    if fee is None:
        out["fee"] = ""
        out["after_fee"] = ""
        out["fee_source"] = "unknown"
        return out
    out["fee"] = format(fee, "f")
    if wire is not None:
        out["after_fee"] = format(wire + fee, "f")
    if filled:
        out["fee_source"] = "venue" if returned is not None else "formula"
    else:
        out["fee_source"] = "estimate"
        out["fee_estimate"] = format(fee, "f")
    return out


def _sent_row(spec: dict, status, payload, note: str) -> dict:
    row = {
        "event": "sent",
        "bet_key": spec.get("_bet_key"),
        "venue": spec.get("venue"),
        "instrument": spec.get("instrument"),
        "side": _book_side(spec),
        "limit_price": spec.get("limit"),
        "size": "1",
        "http_status": status,
        "note": note,
        "order_id": _order_id(payload) if payload else "",
        "step": spec.get("_step") or "",
        "attempt": int(spec.get("_attempt") or 1),
        "system": spec.get("_system") or "",
        "game": spec.get("game") or "",
        "sport": spec.get("sport") or "",
        "side_label": spec.get("player") or spec.get("side_label") or "",
    }
    confirm = venue_confirm_of(payload)
    if confirm:
        row["confirm_known"] = bool(confirm.get("known"))
        row["confirm_qty"] = confirm.get("qty") or "0"
        row["confirm_note"] = confirm.get("note") or ""
        row["confirm_mismatch"] = bool(confirm.get("mismatch"))
        row["tape_qty"] = confirm.get("tape_qty") or ""
        if confirm.get("house_cash"):
            row["house_cash"] = confirm.get("house_cash")
        if confirm.get("order_id") and not row.get("order_id"):
            row["order_id"] = confirm.get("order_id")
    row.update(_fee_tape(spec, payload))
    if row.get("wire") and not row.get("house_cash"):
        row["house_cash"] = row.get("wire")
    for key in QUOTE_KEYS:
        value = spec.get(key)
        if value not in (None, ""):
            row[key] = value
    row.update(_size_log_fields(spec))
    return row


def _begin_order_post(spec: dict) -> None:
    """Record the send. Page rebuild is immediate unless a pair is in flight."""
    try:
        _attach_market_size(spec)
    except Exception:
        pass
    if not spec.get("_bet_key"):
        _refresh_order_pages()
        return
    _append(_sent_row(spec, "pending", None, "request sent"))


def _write_orders_lines(lines: list[str]) -> None:
    """Replace orders.jsonl. Retry Windows/Drive access-denied. Raises the last OSError."""
    ORDERS.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + ("\n" if lines else "")
    tmp = ORDERS.with_suffix(".jsonl.tmp")
    tmp.write_text(text, encoding="utf-8")
    last_err: OSError | None = None
    for attempt in range(6):
        try:
            tmp.replace(ORDERS)
            return
        except OSError as exc:
            last_err = exc
            time.sleep(0.05 * (attempt + 1))
    if last_err is not None:
        raise last_err


def _complete_order_post(spec: dict, status: int, payload, note: str) -> None:
    """Store the venue result on the send row. HTML rebuild waits if a pair is in flight.

    A Drive/Windows replace failure must not raise. Venue fill/history confirm is
    the fill source of truth; the caller latches from that overlay even if this
    ledger write does not land.
    """
    if not spec.get("_bet_key"):
        try:
            _refresh_order_pages()
        except Exception:
            pass
        return
    attempt = int(spec.get("_attempt") or 1)
    venue = str(spec.get("venue") or "")
    key = spec.get("_bet_key")
    finished = _sent_row(spec, status, payload, note)
    try:
        with venue_pace.FileLock(ORDER_LOCK):
            lines = ORDERS.read_text(encoding="utf-8").splitlines() if ORDERS.exists() else []
            replaced = False
            for index in range(len(lines) - 1, -1, -1):
                try:
                    row = json.loads(lines[index])
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("event") != "sent" or row.get("bet_key") != key or str(row.get("venue") or "") != venue:
                    continue
                try:
                    same_attempt = int(row.get("attempt") or 0) == attempt
                except (TypeError, ValueError):
                    same_attempt = False
                if not same_attempt or str(row.get("http_status") or "") not in {"", "pending"}:
                    continue
                lines[index] = json.dumps(finished, ensure_ascii=False, default=str)
                replaced = True
                break
            if not replaced:
                lines.append(json.dumps(finished, ensure_ascii=False, default=str))
            _write_orders_lines(lines)
    except Exception:
        try:
            with venue_pace.FileLock(ORDER_LOCK):
                _append_unlocked(finished)
        except Exception:
            pass
    try:
        fill_qty = filled_contracts(payload) if payload is not None else Decimal("0")
        _append_research_jsonl(
            SEND_QUOTE_AGE_NAME,
            {
                "event": "send_quote_age",
                "venue": venue,
                "instrument": spec.get("instrument") or "",
                "side": _book_side(spec),
                "bet_key": key,
                "step": spec.get("_step") or "",
                "quote_source": spec.get("quote_source") or "",
                "quote_price": spec.get("quote_price") or spec.get("pay") or "",
                "quote_seen_at": spec.get("quote_seen_at") or "",
                "sent_at": spec.get("sent_at") or "",
                "lag_seconds": spec.get("lag_seconds") or "",
                "quote_size": spec.get("quote_size") or "",
                "fill_qty": format(fill_qty, "f"),
                "http_status": status,
                "note": note,
            },
        )
    except Exception:
        pass
    try:
        _refresh_order_pages()
    except Exception:
        pass


def _leg_spec(cand: dict, outcome: str) -> dict | None:
    venue = str(cand.get(f"{outcome}_venue") or "").lower()
    pay = _dec(cand.get(f"{outcome}_price"))
    if pay is None or pay <= 0 or pay >= 1:
        return None
    if venue == "kalshi":
        ticker = str(cand.get("kalshi_ticker") or "")
        if not ticker:
            return None
        body = kalshi_order_body(ticker, outcome, pay, str(uuid.uuid4()))
        return {"venue": "kalshi", "instrument": ticker, "outcome": outcome, "pay": format(pay, "f"), "limit": body["price"], "body": body, "intent": "", "fee_coefficient": None, "market_type": str(cand.get("market_type") or "")}
    if venue == "gemini":
        symbol = str(cand.get("gemini_symbol") or "")
        if not symbol:
            return None
        payload = gemini_order_payload(symbol, outcome, pay)
        return {"venue": "gemini", "instrument": symbol, "outcome": outcome, "pay": format(pay, "f"), "limit": payload["price"], "body": payload, "intent": "", "fee_coefficient": None, "market_type": str(cand.get("market_type") or "")}
    if venue == "polymarket":
        slug = str(cand.get("polymarket_slug") or "")
        intent = str(cand.get("polymarket_intent") or "")
        if not slug or not intent:
            return None
        try:
            api_price = polymarket_api_price(intent, pay)
        except ValueError:
            return None
        if api_price < Decimal("0.01") or api_price > Decimal("0.99"):
            return None
        body = polymarket_order_body(slug, intent, api_price)
        return {
            "venue": "polymarket",
            "instrument": slug,
            "outcome": outcome,
            "pay": format(pay, "f"),
            "limit": body["price"]["value"],
            "body": body,
            "intent": intent,
            "fee_coefficient": cand.get("fee_coefficient"),
            "market_type": str(cand.get("market_type") or ""),
        }
    if venue == "novig":
        if not novig_live.orders_live():
            return None
        market = str(cand.get("novig_market") or "")
        outcome_id = str(cand.get(f"novig_{outcome}_outcome") or "")
        if not market or not outcome_id:
            return None
        body = novig_live.order_body(outcome_id, pay, str(uuid.uuid4()))
        if body is None:
            return None
        return {
            "venue": "novig",
            "instrument": market,
            "outcome": outcome,
            "outcome_id": outcome_id,
            "pay": format(pay, "f"),
            "limit": body["price"],
            "body": body,
            "intent": "",
            "fee_coefficient": cand.get("fee_coefficient"),
            "fee_charged": cand.get("fee_charged"),
            "event_status": cand.get("event_status"),
            "market_type": str(cand.get("market_type") or ""),
        }
    return None


def _leg_deny_reason(cand: dict, outcome: str) -> str:
    """Name why _leg_spec returned None. Do not send. Do not print secrets."""
    venue = str(cand.get(f"{outcome}_venue") or "").lower()
    pay = _dec(cand.get(f"{outcome}_price"))
    missing: list[str] = []
    if not venue:
        missing.append(f"{outcome}_venue")
    if pay is None or pay <= 0 or pay >= 1:
        px = cand.get(f"{outcome}_price")
        missing.append(f"{outcome}_price={px!r}")
    if not venue:
        return f"Missing order fields for {outcome}: " + ", ".join(missing) + "."
    if venue == "kalshi":
        if not str(cand.get("kalshi_ticker") or ""):
            missing.append("kalshi_ticker")
        if missing:
            return f"Missing order fields for {outcome} (kalshi): " + ", ".join(missing) + "."
        return f"Missing order fields for {outcome} (kalshi)."
    if venue == "gemini":
        if not str(cand.get("gemini_symbol") or ""):
            missing.append("gemini_symbol")
        if missing:
            return f"Missing order fields for {outcome} (gemini): " + ", ".join(missing) + "."
        return f"Missing order fields for {outcome} (gemini)."
    if venue == "polymarket":
        if not str(cand.get("polymarket_slug") or ""):
            missing.append("polymarket_slug")
        intent = str(cand.get("polymarket_intent") or "")
        if not intent:
            missing.append("polymarket_intent")
        if missing:
            return f"Missing order fields for {outcome} (polymarket): " + ", ".join(missing) + "."
        try:
            api_price = polymarket_api_price(intent, pay)
        except ValueError:
            return (
                f"Polymarket {outcome} price {pay} could not be converted "
                f"(intent {intent})."
            )
        if api_price < Decimal("0.01") or api_price > Decimal("0.99"):
            return (
                f"Polymarket {outcome} api price {api_price} is outside 0.01–0.99."
            )
        return f"Missing order fields for {outcome} (polymarket)."
    if venue == "novig":
        if not novig_live.orders_live():
            return f"Novig orders not live; cannot build {outcome} leg."
        if not str(cand.get("novig_market") or ""):
            missing.append("novig_market")
        if not str(cand.get(f"novig_{outcome}_outcome") or ""):
            missing.append(f"novig_{outcome}_outcome")
        if missing:
            return f"Missing order fields for {outcome} (novig): " + ", ".join(missing) + "."
        return f"Novig {outcome} order body could not be built."
    return f"Unknown venue {venue} for {outcome} leg."


def _capability_ok(venue: str, now: float) -> tuple[bool, str]:
    cached = _capability.get(venue)
    ttl = _CAPABILITY_OK_TTL_SEC
    if cached and not cached[1]:
        ttl = _CAPABILITY_FAIL_TTL_SEC
    if cached and now - cached[0] < ttl:
        return cached[1], cached[2]
    ok, reason = _probe(venue)
    _capability[venue] = (now, ok, reason)
    return ok, reason


def _kalshi_last_good() -> Decimal | None:
    """Disk or memory cash after a flaky GET. Does not call Kalshi."""
    _seed_balances_from_disk()
    _note_newer_balance_file()
    return _venue_balances.get("kalshi")


def _probe(venue: str) -> tuple[bool, str]:
    try:
        if venue == "kalshi":
            cached = _kalshi_last_good()
            if cached is not None:
                return True, "kalshi last-good local"
            cash = ensure_venue_balance("kalshi")
            if cash is not None:
                return True, "kalshi last-good local"
            return False, "kalshi balance unread"
        if venue == "gemini":
            status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "GET")
            if status != 200:
                status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "POST")
            if status != 200:
                return False, f"gemini terms http {status} {_public_note(body)}"
            data = json.loads(body)
            if data.get("hasAcceptedLatest") is True:
                return True, "gemini terms accepted"
            return False, "gemini prediction-market terms are not accepted"
        if venue == "polymarket":
            cash = ensure_venue_balance("polymarket")
            if cash is not None:
                return True, "polymarket last-good local"
            return False, "polymarket balance unread"
        if venue == "novig":
            if not novig_live.orders_live():
                ok, note = novig_live.trading_key_ready()
                return False, f"novig orders off ({note})"
            cash = ensure_venue_balance("novig")
            if cash is not None:
                return True, "novig last-good local"
            return False, "novig balance unread"
    except Exception as exc:
        return False, type(exc).__name__
    return False, "unknown venue"


def _leg_cash_price(spec: dict) -> Decimal | None:
    """Pay-side cash of this spec. Kalshi No is house pay, not POST Yes-wire limit.

    `_leg_spec` / `_spec_at_price` store pay = No cash and limit = 1 − pay
    (the ask that sells Yes). Cost, funds, and fee tape use pay. Invert
    limit only when pay is missing. Never invert twice.
    """
    spec = spec or {}
    pay = _dec(spec.get("pay"))
    if pay is not None and Decimal("0") < pay < ONE:
        return pay
    limit = _dec(spec.get("limit"))
    venue = str(spec.get("venue") or "")
    side = _book_side(spec) or str(spec.get("outcome") or "")
    if venue == "kalshi" and side == "no" and limit is not None and Decimal("0") < limit < ONE:
        cash = ONE - limit
        if Decimal("0") < cash < ONE:
            return cash
    if limit is not None and Decimal("0") < limit < ONE:
        return limit
    return None


def contract_cost(spec: dict, limit) -> Decimal | None:
    """One contract at this house cash, plus the fee that leg would charge at that price."""
    price = _dec(limit)
    if price is None or price <= 0:
        return None
    fee = leg_fee(spec, price)
    if fee is None:
        return None
    return price + fee


def _balance_stamp(value) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ZoneInfo("America/New_York"))
    return stamp


def _apply_balance_file(data: dict) -> None:
    """Copy stored dollars into this process. A null venue stays missing.

    last_venue_confirm_ts is the hourly GET clock. A local debit does not
    reset it.
    """
    global _balances_at
    venues_meta = data.get("venues") if isinstance(data.get("venues"), dict) else {}
    for venue in _BALANCE_VENUES:
        meta = venues_meta.get(venue) if isinstance(venues_meta.get(venue), dict) else {}
        raw = meta.get("cash") if isinstance(meta, dict) and meta.get("cash") not in (None, "") else data.get(venue)
        if venue not in data and not meta:
            continue
        number = _dec(raw)
        if number is None:
            _venue_balances.pop(venue, None)
            _venue_balance_live_at.pop(venue, None)
            continue
        _venue_balances[venue] = number
        confirm_ts = 0.0
        try:
            confirm_ts = float((meta or {}).get("last_venue_confirm_ts") or 0)
        except (TypeError, ValueError):
            confirm_ts = 0.0
        if confirm_ts > 0:
            _venue_balance_live_at[venue] = confirm_ts
    _balances_at = _balance_stamp(data.get("timestamp"))
    if _balances_at is not None:
        epoch = _balances_at.timestamp()
        for venue in _BALANCE_VENUES:
            if venue in _venue_balances and venue not in _venue_balance_live_at:
                _venue_balance_live_at[venue] = epoch


def _cash_files() -> tuple[Path, ...]:
    paths = []
    cash = getattr(venue_cash_local, "CASH_FILE", None)
    if cash is not None:
        paths.append(cash)
    if BALANCES_FILE not in paths:
        paths.append(BALANCES_FILE)
    return tuple(paths)


def _read_cash_file() -> dict | None:
    for path in _cash_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _seed_balances_from_disk() -> None:
    global _balances_seeded
    if _balances_seeded:
        return
    _balances_seeded = True
    data = _read_cash_file()
    if isinstance(data, dict):
        _apply_balance_file(data)


def _note_newer_balance_file() -> None:
    """Pick up dollars another game process wrote after this copy."""
    data = _read_cash_file()
    if not isinstance(data, dict):
        return
    stamp = _balance_stamp(data.get("timestamp"))
    if stamp is None:
        return
    if _balances_at is not None and stamp <= _balances_at:
        return
    _apply_balance_file(data)


def _persist_balances() -> None:
    """Write the dollar amounts and a timestamp. No secrets."""
    global _balances_at
    _balances_at = datetime.now(ZoneInfo("America/New_York")).replace(microsecond=0)
    row = {"timestamp": _balances_at.isoformat(timespec="seconds")}
    for venue in _BALANCE_VENUES:
        amount = _venue_balances.get(venue)
        row[venue] = None if amount is None else format(amount, "f")
    BALANCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(row, indent=2) + "\n"
    with venue_pace.FileLock(BALANCES_FILE.with_suffix(".lock")):
        BALANCES_FILE.write_text(text, encoding="utf-8")
    try:
        venue_cash_local.sync_memory(_venue_balances, _venue_balance_live_at)
    except Exception:
        pass


def _parse_gemini_usd(body: str) -> Decimal | None:
    data = json.loads(body)
    if not isinstance(data, list):
        return None
    for row in data:
        if isinstance(row, dict) and str(row.get("currency") or "").upper() == "USD":
            return _dec(row.get("available"))
    return None


def _parse_polymarket_buying_power(body: str) -> Decimal | None:
    data = json.loads(body)
    rows = data.get("balances") if isinstance(data, dict) else None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("currency") or "USD").upper() != "USD":
            continue
        number = _dec(row.get("buyingPower"))
        if number is None:
            number = _dec(row.get("cash"))
        if number is not None:
            return number
    return None


def _fetch_venue_balance(venue: str) -> Decimal | None:
    """Dollars available to trade, or None when the read fails. Does not guess."""
    try:
        if venue == "kalshi":
            status, usd = kalshi_private.balance_usd()
            if status == 200 and usd is not None:
                return Decimal(usd)
            return None
        if venue == "gemini":
            status, body = gemini_private.private_call("/v1/balances", None, "POST")
            if status != 200:
                return None
            return _parse_gemini_usd(body)
        if venue == "polymarket":
            status, body = polymarket_us_live.signed_json("GET", "/v1/account/balances")
            if status != 200:
                return None
            return _parse_polymarket_buying_power(body)
        if venue == "novig":
            status, usd = novig_live.balance_usd()
            if status == 200 and usd is not None:
                return usd
            return None
    except Exception:
        return None
    return None


def _balance_is_fresh(venue: str) -> bool:
    live_at = _venue_balance_live_at.get(venue)
    if live_at is None:
        return False
    return (time.time() - live_at) < _BALANCE_TTL_SEC


def _store_live_balance(venue: str, amount: Decimal, persist: bool = True) -> None:
    """Keep a venue-confirmed dollar amount. persist=False during a bulk refresh."""
    _venue_balances[venue] = amount
    _venue_balance_live_at[venue] = time.time()
    if not persist:
        return
    try:
        _persist_balances()
    except OSError:
        pass


def _hourly_confirm_due(venue: str) -> bool:
    if venue not in _venue_balances:
        return True
    try:
        store = venue_cash_local.load()
        if not venue_cash_local.confirm_due(store, venue):
            return False
    except Exception:
        pass
    return not _balance_is_fresh(venue)


def ensure_venue_balance(venue: str, refresh: bool = False) -> Decimal | None:
    """Dollars for this venue from the local slip. Venue GET at most once an hour.

    Skip send when local cash is too low, or missing and the hourly confirm
    failed. A failed GET keeps the last good amount.
    """
    _seed_balances_from_disk()
    _note_newer_balance_file()
    cached = _venue_balances.get(venue) if venue in _venue_balances else None
    if not refresh and venue in _venue_balances and _balance_is_fresh(venue):
        return _venue_balances[venue]
    if not refresh and venue in _venue_balances and not _hourly_confirm_due(venue):
        return _venue_balances[venue]
    amount = None
    try:
        amount = venue_cash_local.confirm_from_venue(
            venue,
            lambda: _fetch_venue_balance(venue),
            force=refresh,
        )
    except Exception:
        amount = _fetch_venue_balance(venue) if refresh or cached is None else None
        if amount is not None:
            _store_live_balance(venue, amount)
            return amount
        return cached
    if amount is None:
        return cached
    _venue_balances[venue] = amount
    try:
        store = venue_cash_local.load()
        row = ((store.get("venues") or {}).get(venue) or {})
        ts = float(row.get("last_venue_confirm_ts") or 0)
        if ts > 0:
            _venue_balance_live_at[venue] = ts
        else:
            _venue_balance_live_at[venue] = time.time()
    except Exception:
        _venue_balance_live_at[venue] = time.time()
    try:
        _persist_balances()
    except OSError:
        pass
    return amount


def refresh_balances(log=None) -> None:
    """Re-read the local slip. GET a venue only if its hourly confirm is due."""
    global _balances_seeded
    _balances_seeded = True
    _note_newer_balance_file()
    for venue in _BALANCE_VENUES:
        ensure_venue_balance(venue)
    if log is None:
        return
    bits = []
    for venue in _BALANCE_VENUES:
        amount = _venue_balances.get(venue)
        bits.append(f"{venue}={'unread' if amount is None else _money(amount)}")
    log("balances after fill " + " ".join(bits))


def _read_balances() -> dict[str, Decimal]:
    """Last known dollars in this process. Does not call the venues."""
    _seed_balances_from_disk()
    _note_newer_balance_file()
    return dict(_venue_balances)


def _affordable(spec: dict, balances: dict[str, Decimal]) -> bool:
    cash = balances.get(spec["venue"])
    cost = contract_cost(spec, _leg_cash_price(spec))
    if cash is None or cost is None:
        return False
    return cash >= cost


def _funds_block(built: dict) -> str:
    """Empty when this venue can pay for one contract. Otherwise venue, cost, and balance."""
    venue = str(built.get("venue") or "")
    price = _leg_cash_price(built)
    cost = contract_cost(built, price)
    cash = ensure_venue_balance(venue)
    cost_text = "unknown" if cost is None else _money(cost)
    cash_text = "unread" if cash is None else _money(cash)
    if cost is None or cash is None or cash < cost:
        return f"venue={venue} cost={cost_text} balance={cash_text}"
    return ""


def _venue_display_name(venue: str) -> str:
    name = str(venue or "").strip().lower()
    labels = {
        "kalshi": "Kalshi",
        "gemini": "Gemini",
        "polymarket": "Polymarket",
        "novig": "Novig",
    }
    return labels.get(name) or (name.title() if name else "Venue")


def _venue_from_text(text: str) -> str:
    lower = str(text or "").lower()
    for venue in _BALANCE_VENUES:
        if venue in lower:
            return venue
    return ""


def _balance_deny_reason(venue: str, cash: Decimal | None = None, cost: Decimal | None = None) -> str:
    """User-visible skip: which venue, and whether cash was missing vs too small."""
    label = _venue_display_name(venue)
    if cash is None:
        return f"{label} balance unreadable"
    if cost is None:
        return f"{label} balance too low (${_money(cash)})"
    return f"{label} balance too low (${_money(cash)} need ${_money(cost)})"


def _balance_deny_from_probe(why: str, venue: str = "") -> str:
    name = venue or _venue_from_text(why)
    lower = str(why or "").lower()
    if any(bit in lower for bit in ("too low", "does not cover", "insufficient")):
        return f"{_venue_display_name(name)} balance too low"
    return _balance_deny_reason(name, None, None)


def _balance_deny_from_funds(funds: str) -> str:
    venue = ""
    cost = None
    cash = None
    unread = False
    for part in str(funds or "").split():
        key, _, raw = part.partition("=")
        if key == "venue":
            venue = raw
        elif key == "cost":
            cost = None if raw in ("", "unknown") else _dec(raw)
        elif key == "balance":
            if raw in ("", "unread"):
                unread = True
            else:
                cash = _dec(raw)
    if unread or cash is None:
        return _balance_deny_reason(venue, None, cost)
    return _balance_deny_reason(venue, cash, cost)


def _is_unread_balance_reason(reason: str) -> bool:
    return "balance unreadable" in str(reason or "").lower()


def _unread_alert_due(kind: str) -> bool:
    """Shared first + every 5 minutes across poller children. kind is log or ntfy."""
    now = time.time()
    RAW.mkdir(parents=True, exist_ok=True)
    try:
        with venue_pace.FileLock(_UNREAD_ALERT.with_suffix(".lock")):
            try:
                data = json.loads(_UNREAD_ALERT.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            last = float(data.get(kind) or 0)
            if last and (now - last) < _UNREAD_ALERT_SEC:
                return False
            data[kind] = now
            _UNREAD_ALERT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            return True
    except Exception:
        return False


def _phone_unread_balance(reason: str, title: str = "") -> None:
    """Ping at most first + every 5 minutes when cash is missing at send time."""
    if not _unread_alert_due("ntfy"):
        return
    game = str(title or "").strip()
    message = reason if not game else f"{reason} — {game}"
    _phone_watch_note("Kalshi balance unreadable", message[:400])


def _record_unread_balance_skip(reason: str, title: str = "", key: str = "") -> bool:
    """Skip send only. Do not flood opportunities. Log/ntfy first + every 5 minutes."""
    if not _unread_alert_due("log"):
        return False
    record_send_skip(reason, title, key)
    _phone_unread_balance(reason, title)
    return True


def _record_balance_skip(reason: str, title: str = "", key: str = "") -> None:
    """Last skip always. One orders.jsonl row per bet+reason so scans do not flood the ledger."""
    if _is_unread_balance_reason(reason):
        _record_unread_balance_skip(reason, title, key)
        return
    fp = f"{key}\t{reason}"
    if fp not in _balance_skip_keys:
        _balance_skip_keys.add(fp)
        record_send_skip(reason, title, key)
        return
    row = {
        "event": "skip",
        "reason": str(reason or "").strip()[:400],
        "game": title,
        "bet_key": key,
        "at": _iso_now(),
    }
    try:
        LAST_SKIP.parent.mkdir(parents=True, exist_ok=True)
        LAST_SKIP.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
    except Exception:
        pass


def _preview(spec: dict) -> tuple[bool, str]:
    if orders_halted():
        return False, "orders stopped"
    if not ORDERS_ENABLED:
        return False, "placing orders is off"
    if spec["venue"] != "polymarket":
        return True, "no preview endpoint"
    status, body = polymarket_us_live.signed_json("POST", "/v1/order/preview", {"request": spec["body"]})
    if status == 200:
        return True, "preview 200"
    return False, f"preview http {status} {_public_note(body)}"


def _is_gtc_spec(spec: dict | None) -> bool:
    """True when this post is a resting good-til-canceled limit, not IOC/FOK."""
    spec = spec if isinstance(spec, dict) else {}
    if str(spec.get("_tif") or "").strip().lower() == "gtc":
        return True
    body = spec.get("body") if isinstance(spec.get("body"), dict) else {}
    raw = str(
        body.get("tif")
        or body.get("time_in_force")
        or body.get("timeInForce")
        or ""
    ).strip().lower()
    compact = raw.replace("_", "").replace("-", "").replace(" ", "")
    return compact in {
        "gtc",
        "goodtillcancel",
        "goodtillcanceled",
        "timeinforcegoodtillcancel",
    }


def _send_blocked(spec: dict) -> str:
    """Empty when this post may leave.

    Strategy B / C / D / E use their own state files and must not be gated by
    lock.on, orders_stopped.json, or this process copy of ORDERS_ENABLED.
    One-leg miss turns Lock gap (A) off only. Leftover flatten/hedge still
    posts while A is off.
    """
    if spec.get("_strategy_b"):
        return ""
    if str(spec.get("_system") or "") in _DIRECTIONAL_SYSTEMS:
        return ""
    if spec.get("_watch_recovery"):
        return ""
    if not lock_system_on():
        return "lock gap is off"
    if not ORDERS_ENABLED:
        return "placing orders is off"
    return ""


def _send(spec: dict) -> tuple[int, dict | None, str]:
    """Post one order. Ledger jsonl is written on send and on result.

    Drive HTML rebuilds on those events unless a hard-then-easy pair is holding
    them until both attempts finish.
    """
    blocked = _send_blocked(spec)
    if blocked:
        return 0, None, blocked
    if spec.get("venue") not in _ORDER_VENUES:
        return 0, None, "unknown venue"
    if spec.get("venue") == "novig" and not novig_live.orders_live():
        return 0, None, "novig orders off or trading key missing"
    if spec.get("venue") == "polymarket" and not _is_gtc_spec(spec):
        skip = poly_size_lt_qty_skip(spec)
        if skip:
            record_send_skip(skip, str(spec.get("game") or ""), str(spec.get("_bet_key") or ""), spec=spec)
            return 0, None, skip
    sent_at = _iso_now()
    spec["sent_at"] = sent_at
    spec["lag_seconds"] = _lag_seconds(spec.get("quote_seen_at"), sent_at)
    _begin_order_post(spec)
    recorded: dict = {}
    try:
        if spec["venue"] == "kalshi":
            status, body = kalshi_private.signed_call("POST", "/trade-api/v2/portfolio/events/orders", spec["body"])
            request = spec["body"]
            payload = None
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
        elif spec["venue"] == "gemini":
            status, body = gemini_private.private_call("/v1/prediction-markets/order", spec["body"], "POST", record=recorded)
            request = recorded.get("request") or spec["body"]
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
        elif spec["venue"] == "polymarket":
            status, body = polymarket_us_live.signed_json("POST", "/v1/orders", spec["body"])
            request = spec["body"]
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
        else:
            # Novig: 201 means queued. Poll until the order is terminal so fill state is known.
            request = spec["body"]
            status, accepted, note = novig_live.place_order(spec["body"])
            body = json.dumps(accepted if accepted is not None else {"note": note}, default=str)
            payload = accepted
            if (
                status in (200, 201)
                and isinstance(accepted, dict)
                and accepted.get("orderId")
                and not _is_gtc_spec(spec)
            ):
                terminal = novig_live.wait_order_terminal(str(accepted.get("orderId")))
                if isinstance(terminal, dict):
                    payload = terminal
                    body = json.dumps(terminal, default=str)
                    note = str(terminal.get("status") or note)
            else:
                note = note or f"http {status}"
            _phone_order_placed(spec)
            try:
                record_order_io(
                    spec["venue"], "order", request, status, body,
                    attempt=int(spec.get("_attempt") or 1),
                    quote=_quote_envelope(spec),
                )
            except Exception:
                pass
            payload = payload if isinstance(payload, (dict, list)) else None
            payload = _with_venue_confirm(spec, status, payload)
            try:
                _complete_order_post(spec, status, payload, note)
            except Exception:
                pass
            _after_send_hooks(spec, payload, status)
            return status, payload, note
    except Exception:
        _complete_order_post(spec, 0, None, "request failed")
        raise
    _phone_order_placed(spec)
    try:
        record_order_io(
            spec["venue"], "order", request, status, body,
            attempt=int(spec.get("_attempt") or 1),
            quote=_quote_envelope(spec),
        )
    except Exception:
        pass
    payload = payload if isinstance(payload, (dict, list)) else None
    if isinstance(payload, dict) and isinstance(payload.get("order"), dict):
        inner = payload["order"]
        if payload.get("fill_count") is None and inner.get("fill_count") is not None:
            payload = inner
    note = _public_note(body)
    payload = _with_venue_confirm(spec, status, payload)
    # Ledger/page writes must not hide a venue fill. Confirm GET is truth, not the
    # order tape. 2026-10-21 Wawrinka/Landaluce: Kalshi HTTP 201 fill_count 1, then
    # Drive replace PermissionError aborted the pair before one-leg latch.
    try:
        _complete_order_post(spec, status, payload, note)
    except Exception:
        pass
    _after_send_hooks(spec, payload, status)
    return status, payload, note


def _with_venue_confirm(spec: dict, status: int, payload):
    """After an order HTTP return, overlay venue fill/history. Status 0 skips."""
    if status == 0:
        return payload
    try:
        confirm = confirm_venue_after_order(spec, status, payload)
    except Exception as exc:
        confirm = venue_fill_confirm.unknown_result(
            str((spec or {}).get("venue") or ""),
            f"confirm {type(exc).__name__}",
            venue_fill_confirm.tape_filled_qty(payload),
            venue_fill_confirm.ids_from(payload, spec),
        )
    return venue_fill_confirm.attach(payload, confirm)


def _order_id(payload) -> str:
    if not isinstance(payload, (dict, list)):
        return ""
    for node in _walk(payload):
        for key in ("order_id", "orderId", "id"):
            value = node.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _cancel(spec: dict, payload) -> tuple[int, str]:
    order_id = _order_id(payload)
    if not order_id:
        return 0, "no order id"
    recorded: dict = {}
    request = None
    if spec["venue"] == "kalshi":
        request = {"order_id": order_id, "market_ticker": spec["instrument"]}
        status, body = kalshi_private.signed_call(
            "DELETE",
            f"/trade-api/v2/portfolio/events/orders/{order_id}",
            query={"market_ticker": spec["instrument"]},
        )
    elif spec["venue"] == "gemini":
        try:
            gid = int(order_id)
        except ValueError:
            return 0, "gemini order id was not an integer"
        status, body = gemini_private.private_call(
            "/v1/prediction-markets/order/cancel", {"orderId": gid}, "POST", record=recorded
        )
        request = recorded.get("request") or {"orderId": gid}
    elif spec["venue"] == "polymarket":
        request = {"marketSlug": spec["instrument"], "order_id": order_id}
        status, body = polymarket_us_live.signed_json(
            "POST",
            f"/v1/order/{order_id}/cancel",
            {"marketSlug": spec["instrument"]},
        )
    elif spec["venue"] == "novig":
        request = {"orderId": order_id}
        status, body = novig_live.cancel_order(order_id)
    else:
        return 0, "unknown venue"
    try:
        record_order_io(spec["venue"], "cancel", request, status, body)
    except Exception:
        pass
    return status, _public_note(body)


def _book_side(spec: dict) -> str:
    """Venue side. A Polymarket short is No even when this leg is the pair's Yes column."""
    intent = str(spec.get("intent") or "")
    body = spec.get("body")
    if not intent and isinstance(body, dict):
        intent = str(body.get("intent") or "")
    if "SHORT" in intent:
        return "no"
    if "LONG" in intent:
        return "yes"
    return str(spec.get("outcome") or "")


def _log_sent(log, spec: dict, status: int) -> None:
    extra = _trigger_log_bits(spec)
    lag = spec.get("lag_seconds") or ""
    sent = _hhmmss(spec.get("sent_at"))
    tail = ""
    if extra:
        tail = f" {extra}"
    if sent:
        tail = f"{tail}; orders {sent}" if extra else f" orders {sent}"
    if lag != "":
        tail = f"{tail} lag={lag}s"
    book_sz = spec.get("quote_size") or ""
    if book_sz != "":
        tail = f"{tail} book_size={book_sz}"
    log(
        f"order sent venue={spec['venue']} instrument={spec['instrument']} side={_book_side(spec)} "
        f"limit={spec['limit']} size=1 http={status}{tail}"
    )


def _log_one_leg(log, spec: dict, payload=None) -> None:
    price = _execution_price(payload, str(spec.get("outcome") or "")) or spec.get("pay")
    log(
        f"ONE LEG venue={spec['venue']} contract={spec['instrument']} side={_book_side(spec)} "
        f"size=1 price={price}"
    )


def _execution_price(payload, outcome: str) -> str:
    """Fill price from the venue response, when it sent one. Empty when it did not.

    Gemini's fill is avgExecutionPrice. A limit on the order is not the fill.
    A known venue-confirm house_cash / avg_price wins over the order tape.
    """
    confirm = venue_confirm_of(payload)
    if confirm and confirm.get("known"):
        house = confirm.get("house_cash") or confirm.get("avg_price")
        if house not in (None, ""):
            return str(house)
    if not isinstance(payload, (dict, list)):
        return ""
    preferred = "yes_price_dollars" if outcome == "yes" else "no_price_dollars"
    preferred_fold = preferred.replace("_", "")
    fill = ""
    side = ""
    for node in _walk(payload):
        for key, value in node.items():
            if value in (None, ""):
                continue
            folded = str(key).replace("_", "").lower()
            if folded in ("avgexecutionprice", "avgpx"):
                raw = value.get("value") if isinstance(value, dict) else value
                text = str(raw)
                if text not in {"0", "0.0", "0.00", "0.000", "0.0000"}:
                    fill = text
            elif folded == preferred_fold:
                side = str(value)
            elif not side and folded in ("avgprice", "averageprice", "averagefillprice", "filledprice"):
                side = str(value)
    return fill or side


def one_leg_message(title: str, first: dict, first_payload, second: dict, status2: int, note2: str, second_payload) -> str:
    """Phone and log text. Separate from the under-$1 opportunity ping."""
    fill = _execution_price(first_payload, str(first.get("outcome") or ""))
    price = f"fill {fill}" if fill else f"limit {first.get('pay')}"
    order_id = _order_id(first_payload)
    order_bit = f" order {order_id}" if order_id else ""
    other_id = _order_id(second_payload)
    other_bit = f" order {other_id}" if other_id else ""
    return (
        "one leg filled, other leg did not. "
        f"{title}. Filled {first.get('venue')} {_book_side(first)} {first.get('instrument')} "
        f"{price} size 1{order_bit}. "
        f"Other leg {second.get('venue')} {_book_side(second)} {second.get('instrument')} "
        f"http {status2} {note2}{other_bit}. Recovery did not fill; orders stop."
    )


def alert_one_leg(log, title: str, first: dict, first_payload, second: dict, status2: int, note2: str, second_payload) -> None:
    """Supervisor log and a durable HTML note. Does not send an order. The phone ping is once per pair."""
    message = one_leg_message(title, first, first_payload, second, status2, note2, second_payload)
    log(message)
    row = {
        "seen_at": "",
        "game": title,
        "filled_venue": first.get("venue"),
        "contract": first.get("instrument"),
        "side": first.get("outcome"),
        "price": _execution_price(first_payload, str(first.get("outcome") or "")) or str(first.get("pay") or ""),
        "order_id": _order_id(first_payload),
        "other_venue": second.get("venue"),
        "other_contract": second.get("instrument"),
        "other_side": second.get("outcome"),
        "other_result": f"http {status2} {note2}",
        "other_order_id": _order_id(second_payload),
        "note": "one leg filled, other leg did not. No further order was sent.",
    }
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        row["seen_at"] = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    except Exception:
        row["seen_at"] = ""
    try:
        import stream_health

        stream_health.append_one_leg_alert(row)
    except Exception as exc:
        log(f"one leg note failed {type(exc).__name__}")


def _order_was_sent(outcome: dict | None) -> bool:
    """True when this leg result came from an immediate-or-cancel that was actually posted."""
    outcome = outcome or {}
    if "posted" in outcome:
        return bool(outcome.get("posted"))
    return str(outcome.get("step") or "") in {"websocket", "book", "midway", "simultaneous", "hard", "easy", "watch"}


def _fill_bit(spec: dict, outcome: dict) -> str:
    price = outcome.get("pay") or spec.get("pay") or ""
    return f"{spec.get('venue')} {spec.get('outcome')} {spec.get('instrument')} at {price}"


def format_posted_leg_return(outcome: dict | None) -> str:
    """One posted IOC: HTTP tape and venue-confirm qty. Empty if not posted."""
    if not isinstance(outcome, dict):
        return ""
    status = int(outcome.get("status") or 0)
    if not _order_was_sent(outcome) and status == 0:
        return ""
    spec = outcome.get("spec") if isinstance(outcome.get("spec"), dict) else {}
    venue = str(spec.get("venue") or outcome.get("venue") or "")
    payload = outcome.get("payload")
    qty = outcome_fill_qty(outcome)
    if qty == qty.to_integral_value():
        qty_txt = format(qty.quantize(Decimal("1")), "f")
    else:
        qty_txt = format(qty, "f")
    note = public_venue_note(payload, str(outcome.get("note") or ""))
    flatten = str(outcome.get("step") or "") == "flatten" or bool(spec.get("_flatten"))
    confirm = venue_confirm_of(payload)
    tape_qty = None
    if confirm is not None:
        tape_qty = _dec(confirm.get("tape_qty"))
    if tape_qty is None:
        tape_qty = venue_fill_confirm.tape_filled_qty(payload)
    if tape_qty == tape_qty.to_integral_value():
        tape_txt = format(tape_qty.quantize(Decimal("1")), "f")
    else:
        tape_txt = format(tape_qty, "f")
    head = f"{'flatten ' if flatten else ''}{venue or 'venue'} HTTP {status} fill {tape_txt}"
    line = f"{head} {note}".strip() if note else head
    if confirm is not None:
        if confirm.get("known"):
            confirm_bit = f"confirm {confirm.get('note') or ('qty ' + qty_txt)}"
        else:
            confirm_bit = f"confirm unknown {confirm.get('note') or ''}".strip()
        line = f"{line}; {confirm_bit}".strip()
        if confirm.get("mismatch"):
            line = f"{line} (using confirm qty {qty_txt})"
    return _scrub_public_text(line)


def posted_leg_returns(*outcomes) -> str:
    """Public venue returns for each posted leg, including flatten HTTP. No secrets."""
    parts = []
    seen: set[str] = set()
    for outcome in outcomes:
        line = format_posted_leg_return(outcome)
        if not line:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(line.rstrip(".") + ".")
    return " ".join(parts)


def sent_reason_with_venue_returns(summary: str, *outcomes) -> str:
    """Decision sentence plus each posted venue return. Empty outcomes leave the summary."""
    extra = posted_leg_returns(*outcomes)
    summary = (summary or "").strip()
    if not extra:
        return summary
    if not summary:
        return extra
    return summary.rstrip(".") + ". " + extra


def _leg_stop_bits(spec: dict, outcome: dict | None) -> dict:
    """Venue, contract, side, and price for the orders-off ping. No secrets."""
    outcome = outcome or {}
    price = _execution_price(outcome.get("payload"), str(spec.get("outcome") or ""))
    if not price:
        price = str(outcome.get("pay") or spec.get("pay") or "")
    return {
        "venue": str(spec.get("venue") or ""),
        "contract": str(spec.get("instrument") or ""),
        "side": str(spec.get("outcome") or ""),
        "price": price,
    }


def _phone_orders_off(filled: dict, missed: dict) -> None:
    """Ping once when the stop latch is first written. Does not wait on ntfy.

    The helper is a detached process so a slow notify cannot stall the game loop.
    """
    script = ROOT / "tools" / "ntfy_job_done.py"
    route = STAMP / "progress.html"

    def _bit(label: str, row: dict) -> str:
        venue = str(row.get("venue") or "")
        side = str(row.get("side") or "")
        contract = str(row.get("contract") or "")
        price = str(row.get("price") or "")
        price_bit = f" at {price}" if price else ""
        return f"{label} {venue} {side} {contract}{price_bit}".strip()

    title = "Lock gap off"
    message = (
        "Lock gap (A) is off after a one-leg fill. B–E stay on. "
        f"{_bit('Filled', filled)}. {_bit('Missed', missed)}. "
        "Turn A back: python tools/prediction_job_control.py systems --lock on"
    )
    try:
        import subprocess
        import sys
        import win_hidden

        win_hidden.popen(
            [sys.executable, "-u", str(script), "--path", str(route), "-t", title, "-m", message],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            new_group=True,
        )
    except Exception:
        pass


def _phone_order_placed(spec: dict) -> None:
    """Ping once when this order's HTTP request has been sent. Does not wait on ntfy.

    Skips never reach here. The helper is a detached process: its own retries can
    take longer than a minute, and that wait must not sit on the game loop.
    """
    script = ROOT / "tools" / "ntfy_job_done.py"
    route = STAMP / "progress.html"
    venue = str(spec.get("venue") or "")
    contract = str(spec.get("instrument") or "")
    side = str(spec.get("outcome") or "")
    limit = str(spec.get("limit") or "")
    title = f"Order placed {venue} {contract} {side} limit {limit}"
    message = f"Order placed. venue={venue} contract={contract} side={side} limit={limit}"
    try:
        import subprocess
        import sys
        import win_hidden

        win_hidden.popen(
            [sys.executable, "-u", str(script), "--path", str(route), "-t", title, "-m", message],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            new_group=True,
        )
    except Exception:
        pass


def _phone_trade_result(log, message: str, success: bool) -> None:
    """One phone ping via tools/ntfy_job_done.py. The Drive path routes it to Paul's topic.

    Does not place an order. A network failure still leaves the helper's exit code at 0.
    """
    script = ROOT / "tools" / "ntfy_job_done.py"
    route = STAMP / "progress.html"
    title = "Gap lock success" if success else "Gap lock failure"
    try:
        import subprocess
        import sys

        import win_hidden

        win_hidden.run(
            [sys.executable, "-u", str(script), "--path", str(route), "-t", title, "-m", message],
            cwd=str(ROOT),
            timeout=120,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        log(f"trade phone alert failed {type(exc).__name__}")


_orders_off_logged: set[str] = set()
_halt_logged = False
_consider = threading.local()


def pair_labels_conflict(game: str, side: str) -> bool:
    """True when the game title and the side name different events.

    26 Oct 2026: opportunities logged Tampa Bay vs Carolina with side
    New Mexico St. over 9.5. That is a leftover consider slot, not a ticket.
    """
    game_l = (game or "").lower()
    side_l = (side or "").lower()
    if not game_l or not side_l:
        return False
    nfl = ("tampa bay", "carolina")
    nms = ("new mexico",)
    game_nfl = any(mark in game_l for mark in nfl)
    side_nms = any(mark in side_l for mark in nms)
    game_nms = any(mark in game_l for mark in nms)
    side_nfl = any(mark in side_l for mark in nfl)
    return (game_nfl and side_nms) or (game_nms and side_nfl)


def _consider_from_legs(legs: list[dict]) -> dict:
    yes = next((leg for leg in legs if str(leg.get("outcome") or "").lower() == "yes"), None)
    no = next((leg for leg in legs if str(leg.get("outcome") or "").lower() == "no"), None)
    yes = yes if isinstance(yes, dict) else {}
    no = no if isinstance(no, dict) else {}
    return {
        "yes_venue": str(yes.get("venue") or ""),
        "no_venue": str(no.get("venue") or ""),
        "yes_price": str(yes.get("pay") or ""),
        "no_price": str(no.get("pay") or ""),
        "yes_size": str(yes.get("quote_size") or ""),
        "no_size": str(no.get("quote_size") or ""),
        "side": "",
        "number": "",
        "market_type": "",
    }


def _clear_consider() -> None:
    for name in ("sport", "title", "cand", "net"):
        if hasattr(_consider, name):
            delattr(_consider, name)


def _bind_consider_to_pair(title: str, legs: list[dict]) -> None:
    """Opportunities row must name THIS pair. Leftover thread-local cand cannot mix games."""
    sport = str(getattr(_consider, "sport", "") or "")
    cand = getattr(_consider, "cand", None)
    prior_title = str(getattr(_consider, "title", "") or "")
    stale = not isinstance(cand, dict)
    if isinstance(cand, dict) and pair_labels_conflict(title, str(cand.get("side") or "")):
        stale = True
    if prior_title and title and prior_title != title:
        stale = True
    if stale:
        _set_consider(sport, title, _consider_from_legs(legs), None)
        return
    _consider.title = title


def _set_consider(sport: str, title: str, cand: dict, net: Decimal | None) -> None:
    _consider.sport = sport
    _consider.title = title
    _consider.cand = cand
    _consider.net = net


def _log_consider(decision: str, reason: str, net: Decimal | None = None, cand_patch: dict | None = None) -> None:
    """One opportunities-log row. Skips when no pair is in context, or the after-fee cost is above 0.99."""
    cand = getattr(_consider, "cand", None)
    if not isinstance(cand, dict):
        return
    use = dict(cand)
    if cand_patch:
        use.update(cand_patch)
    amount = net if net is not None else getattr(_consider, "net", None)
    try:
        import opportunity_considerations

        opportunity_considerations.record(
            getattr(_consider, "sport", "") or "",
            getattr(_consider, "title", "") or "",
            use,
            decision,
            reason,
            amount if isinstance(amount, Decimal) else None,
        )
    except Exception:
        return


def _note_orders_off(log, key: str) -> None:
    """One skip line per bet. Does not call a venue."""
    if key in _orders_off_logged:
        return
    with venue_pace.FileLock(ORDER_LOCK):
        already = any(
            row.get("bet_key") == key and row.get("event") == "orders_off"
            for row in _read_orders()
        )
        if already:
            _orders_off_logged.add(key)
            return
        _append_unlocked({
            "event": "orders_off",
            "bet_key": key,
            "note": "placing orders is off",
        })
    _orders_off_logged.add(key)
    log("order skipped; placing orders is off")


def execute_locks(
    scan,
    sport: str,
    title: str,
    game: dict,
    result: dict,
    fresh: list[dict],
    log,
    gemini_events=None,
    kalshi_events=None,
    polymarket=None,
    novig=None,
    skip_book_recheck=False,
) -> None:
    """Send qualifying pairs. Pairs under $1 but above NET_MAX stay alerts only.

    skip_book_recheck: REST books are already in the candidate prices/sizes
    (catalog verify). Do not GET the books again. Still hard-first, 1 contract.
    Local cash only — no hourly wallet GET.
    """
    if result.get("closed"):
        try:
            _maybe_performance_after_game("closed", title=str(title or ""), we_touched=None)
        except Exception:
            pass
        return
    import opportunity_considerations

    candidates = [row for row in (result.get("candidates") or []) if isinstance(row, dict)]
    ready = []
    game_row = game if isinstance(game, dict) else {}
    for cand in candidates:
        net = pair_net(scan, cand)
        ok, reason = qualifies(scan, cand, title, game_row)
        if ok:
            ready.append((cand, reason, net))
            continue
        plain = opportunity_considerations.reason_from_qualifies(reason, cand, net)
        if plain:
            _set_consider(sport, title, cand, net)
            _log_consider("denied", plain, net)
    if not ready:
        return
    if strategy_b_blocks_lock(sport, title):
        log(f"order skip {title}; Tennis crossover has this tennis match open")
        for cand, _reason, net in ready:
            _set_consider(sport, title, cand, net)
            _log_consider("denied", "Tennis crossover has this match open.", net)
        return
    if directional_blocks_lock(sport, title):
        log(f"order skip {title}; CFB favorite or T0 spread ticket is open")
        for cand, _reason, net in ready:
            _set_consider(sport, title, cand, net)
            _log_consider("denied", "CFB favorite or T0 spread ticket is open.", net)
        return
    if not lock_system_on():
        for cand, _reason, net in ready:
            _set_consider(sport, title, cand, net)
            _log_consider("denied", "Lock gap system is off.", net)
        return
    global ORDERS_ENABLED, _halt_logged
    ORDERS_ENABLED = True
    if watch_is_active():
        if not _halt_logged:
            _halt_logged = True
            log("order skipped; leftover watch still open")
        for cand, _reason, net in ready:
            _set_consider(sport, title, cand, net)
            _log_consider("denied", "Leftover watch still open after a one-leg fill.", net)
        return
    open_now = open_lock_keys()
    if lock_slots_full(open_now):
        why = lock_open_denial(len(open_now))
        log(f"order skip {title}; {why}")
        for cand, _reason, net in ready:
            _set_consider(sport, title, cand, net)
            _log_consider("denied", why, net)
        return
    import time
    now = time.time()
    for cand, reason, net in ready:
        _set_consider(sport, title, cand, net)
        if pair_labels_conflict(title, str(cand.get("side") or "")):
            log(f"order skip {title}; game title and side name different events")
            _log_consider("denied", "Game title and side name different events; not sent.", net)
            continue
        key = scan._trade_bet_key(sport, game, cand)
        outcomes = ordered_outcomes(cand, fresh)
        legs = []
        for outcome in outcomes:
            spec = _leg_spec(cand, outcome)
            if spec is None:
                why = _leg_deny_reason(cand, outcome)
                log(f"order skip {title} {reason} {why}")
                _log_consider("denied", why, net)
                legs = []
                break
            _attach_quote_size(spec, cand.get(f"{outcome}_size"))
            legs.append(spec)
        if len(legs) != 2:
            continue
        venues = [leg["venue"] for leg in legs]
        blocked_reason = ""
        blocked_venue = ""
        for venue in venues:
            ok, why = _capability_ok(venue, now)
            if not ok:
                blocked_reason = why
                blocked_venue = venue
                break
        if blocked_reason:
            if "balance" in blocked_reason.lower():
                why = _balance_deny_from_probe(blocked_reason, blocked_venue)
                if _is_unread_balance_reason(why):
                    if _record_unread_balance_skip(why, title, key):
                        log(f"order skip both legs {title} {blocked_reason}")
                    continue
                log(f"order skip both legs {title} {blocked_reason}")
                _log_consider("denied", why, net)
                _record_balance_skip(why, title, key)
            else:
                log(f"order skip both legs {title} {blocked_reason}")
                _log_consider("denied", "The venue could not take the order.", net)
            continue
        if not skip_book_recheck:
            for venue in venues:
                ensure_venue_balance(venue)
        balances = _read_balances()
        balance_note = " ".join(
            f"{name}={_money(amount)}" for name, amount in sorted(balances.items()) if name in venues
        )
        log(f"balances before send {balance_note or 'none stored'}")
        blocked_notes = []
        for leg in legs:
            if leg["venue"] in balances and _affordable(leg, balances):
                continue
            cost = contract_cost(leg, _leg_cash_price(leg))
            cash = balances.get(leg["venue"])
            log(
                f"order skip venue={leg['venue']} cost={_money(cost) if cost is not None else 'unknown'} "
                f"balance={'unread' if cash is None else _money(cash)}"
            )
            blocked_notes.append(_balance_deny_reason(leg["venue"], cash, cost))
        if blocked_notes:
            why = "; ".join(dict.fromkeys(blocked_notes))
            if all(_is_unread_balance_reason(note) for note in blocked_notes):
                _record_unread_balance_skip(why, title, key)
                continue
            _log_consider("denied", why, net)
            _record_balance_skip(why, title, key)
            continue
        preview_reason = ""
        for leg in legs:
            ok, why = _preview(leg)
            if not ok:
                preview_reason = why
                break
        if preview_reason:
            log(f"order skip both legs {title} {preview_reason}")
            if "stopped" in preview_reason.lower():
                _log_consider("denied", "Orders stopped after a one-leg fill.", net)
            else:
                _log_consider("denied", "The venue refused the order before it was sent.", net)
            continue
        compared_at = _iso_now()
        quote_metas = [_leg_quote_meta(leg, fresh, compared_at, "websocket") for leg in legs]
        trigger = _pick_trigger(quote_metas, fresh)
        for leg, meta in zip(legs, quote_metas):
            _attach_quote(leg, meta, trigger, "websocket")
        with venue_pace.FileLock(ORDER_LOCK):
            rows_now = _read_orders()
            if bet_blocked(rows_now, key, _pid_alive):
                log(f"order skip duplicate {title} {cand.get('market_type')} {cand.get('side')} {cand.get('number')}")
                _log_consider("denied", "Duplicate.", net)
                continue
            live_open = open_lock_keys(rows_now, include_watches=False)
            if lock_slots_full(live_open, this_key=key):
                why = lock_open_denial(len(live_open))
                log(f"order skip {title}; {why}")
                _log_consider("denied", why, net)
                continue
            claim = {
                "event": "claim",
                "bet_key": key,
                "sport": sport,
                "game": title,
                "market_type": cand.get("market_type"),
                "side": cand.get("side"),
                "number": cand.get("number"),
                "net": reason,
                "pid": os.getpid(),
                "compared_at": compared_at,
            }
            if trigger:
                claim["trigger_venue"] = trigger.get("venue") or ""
                claim["trigger_side"] = trigger.get("side") or ""
                claim["trigger_price"] = trigger.get("price") or ""
                claim["trigger_seen_at"] = trigger.get("seen_at") or ""
                claim["trigger_source"] = trigger.get("source") or "websocket"
            claim["legs"] = [
                {
                    "venue": meta.get("venue"),
                    "side": meta.get("side"),
                    "quote_source": "websocket",
                    "quote_price": meta.get("price"),
                    "quote_seen_at": meta.get("seen_at"),
                }
                for meta in quote_metas
            ]
            _append_unlocked(claim)
        _send_pair(
            log,
            key,
            title,
            legs,
            gemini_events,
            kalshi_events,
            polymarket,
            novig,
            fresh=fresh,
            skip_book_recheck=skip_book_recheck,
        )


def _spec_at_price(spec: dict, pay: Decimal) -> dict | None:
    """One-contract take body at this outcome price. Poly FOK; others IOC."""
    snapped = snap_pay(str(spec.get("venue") or ""), pay)
    if snapped is None:
        return None
    venue = spec["venue"]
    outcome = str(spec["outcome"])
    instrument = str(spec["instrument"])
    if venue == "kalshi":
        body = kalshi_order_body(instrument, outcome, snapped, str(uuid.uuid4()))
        limit = body["price"]
    elif venue == "gemini":
        body = gemini_order_payload(instrument, outcome, snapped)
        limit = body["price"]
    elif venue == "polymarket":
        intent = str(spec.get("intent") or "")
        try:
            api_price = polymarket_api_price(intent, snapped)
        except ValueError:
            return None
        if api_price < Decimal("0.01") or api_price > Decimal("0.99"):
            return None
        body = polymarket_order_body(instrument, intent, api_price)
        limit = body["price"]["value"]
    elif venue == "novig":
        if not novig_live.orders_live():
            return None
        outcome_id = str(spec.get("outcome_id") or "")
        body = novig_live.order_body(outcome_id, snapped, str(uuid.uuid4()))
        if body is None:
            return None
        limit = body["price"]
    else:
        return None
    built = {
        "venue": venue,
        "instrument": instrument,
        "outcome": outcome,
        "pay": format(snapped, "f"),
        "limit": limit,
        "body": body,
        "intent": spec.get("intent") or "",
        "fee_coefficient": spec.get("fee_coefficient"),
        "fee_charged": spec.get("fee_charged"),
        "event_status": spec.get("event_status"),
    }
    if venue == "novig":
        built["outcome_id"] = str(spec.get("outcome_id") or "")
    if spec.get("_watch_recovery"):
        built["_watch_recovery"] = True
    if spec.get("_flatten"):
        built["_flatten"] = True
        built["_watch_recovery"] = True
    if spec.get("_strategy_b"):
        built["_strategy_b"] = True
    if spec.get("_system"):
        built["_system"] = spec.get("_system")
    if spec.get("game"):
        built["game"] = spec.get("game")
    if spec.get("sport"):
        built["sport"] = spec.get("sport")
    if spec.get("player"):
        built["player"] = spec.get("player")
    return built


def _post_same_limit(log, key: str, built: dict, step: str, send, limit: Decimal | None, other_price: Decimal | None, other_fee: Decimal | None):
    """Post this exact one-contract limit. Repeat only the shard-user 404.

    Up to two more posts, two seconds apart. Profit and balance are checked
    again before each repeat. The body, including client order id, stays the
    same. A 201, a cancel, or any other reject returns immediately.
    """
    attempt = 1
    status, payload, note = 0, None, ""
    while attempt <= 1 + SHARD_USER_EXTRA_TRIES:
        built["_attempt"] = attempt
        built["_bet_key"] = key
        built["_step"] = step
        status, payload, note = send(built)
        _log_sent(log, built, status)
        if send is not _send:
            _append(_sent_row(built, status, payload, note))
        if not shard_user_missing(status, payload, note) or attempt >= 1 + SHARD_USER_EXTRA_TRIES:
            return status, payload, note
        log(
            f"order retry shard user missing attempt={attempt} "
            f"venue={built['venue']} instrument={built['instrument']} "
            f"waiting {SHARD_USER_WAIT_SEC}s"
        )
        time.sleep(SHARD_USER_WAIT_SEC)
        if (
            not built.get("_watch_recovery")
            and not built.get("_strategy_b")
            and (orders_halted() or not ORDERS_ENABLED)
        ):
            return status, payload, note
        if built.get("_strategy_b") or built.get("_flatten"):
            blocked = ""
        else:
            blocked = _profit_block(built, limit, other_price, other_fee)
        if blocked:
            log(
                f"order retry skipped {step} not profitable venue={built['venue']} "
                f"instrument={built['instrument']} {blocked}"
            )
            return status, payload, note
        funds = _funds_block(built)
        if funds:
            log(f"order retry skipped {step} {funds}")
            return status, payload, note
        attempt += 1
    return status, payload, note


def _one_ioc(log, key: str, spec: dict, pay: Decimal, step: str, send, other_price: Decimal | None = None, other_fee: Decimal | None = None) -> dict:
    """Send one immediate-or-cancel. advance is true only when it cancelled with nothing filled, or this limit was over the cap so a later try may still be sent."""
    built = _spec_at_price(spec, pay)
    blank = {"filled": False, "advance": False, "payload": None, "status": 0, "note": "price not sendable", "pay": spec.get("pay"), "spec": spec, "step": step, "posted": False}
    if built is None:
        return blank
    if spec.get("_watch_recovery"):
        built["_watch_recovery"] = True
    if spec.get("_flatten"):
        built["_flatten"] = True
        built["_watch_recovery"] = True
    _carry_quote_fields(spec, built)
    if not built.get("quote_source"):
        built["quote_source"] = quote_source_for_step(step)
    if not built.get("quote_price"):
        built["quote_price"] = built.get("pay") or spec.get("pay") or ""
    if not built.get("quote_seen_at") and spec.get("quote_seen_at"):
        built["quote_seen_at"] = spec.get("quote_seen_at")
    if orders_halted() and not built.get("_watch_recovery"):
        blank["note"] = "orders stopped"
        _log_consider("denied", "Orders stopped after a one-leg fill.")
        return blank
    limit = _dec(built.get("pay"))
    fee = leg_fee(built, limit) if limit is not None else None
    gross = limit + other_price if limit is not None and other_price is not None else None
    net_now = gross + fee + other_fee if gross is not None and fee is not None and other_fee is not None else None
    if built.get("_flatten"):
        blocked = ""
    else:
        blocked = _profit_block(built, limit, other_price, other_fee)
    if blocked:
        log(
            f"order skip {step} not profitable venue={built['venue']} instrument={built['instrument']} "
            f"{blocked}"
        )
        if net_now is not None and gross is not None and net_now <= Decimal("0.99"):
            patch = {}
            if str(built.get("outcome") or "") == "yes":
                patch["yes_price"] = built.get("pay") or ""
                if other_price is not None:
                    patch["no_price"] = format(other_price, "f")
            elif str(built.get("outcome") or "") == "no":
                patch["no_price"] = built.get("pay") or ""
                if other_price is not None:
                    patch["yes_price"] = format(other_price, "f")
            if gross >= ONE:
                moved = "Price moved so the send was no longer under $1."
            else:
                moved = (
                    f"Price moved. After-fee cost {_net_text(net_now)} "
                    f"is above the {send_line()} send line but still at or under 0.99."
                )
            _log_consider("denied", moved, net_now, patch)
        blank["note"] = blocked
        blank["pay"] = built["pay"]
        blank["spec"] = built
        blank["advance"] = blocked.startswith("limit=")
        return blank
    funds = _funds_block(built)
    if funds:
        named = _balance_deny_from_funds(funds)
        if _is_unread_balance_reason(named):
            if _record_unread_balance_skip(named, str(built.get("game") or ""), key):
                log(f"order skip {step} {funds}")
        else:
            log(f"order skip {step} {funds}")
            _log_consider("denied", named)
        blank["note"] = funds
        blank["pay"] = built["pay"]
        blank["spec"] = built
        blank["advance"] = True
        return blank
    status, payload, note = _post_same_limit(log, key, built, step, send, limit, other_price, other_fee)
    filled = filled_contracts(payload) if payload is not None else Decimal("0")
    if status not in (200, 201) and not venue_confirm_known(payload):
        filled = Decimal("0")
    if poly_partial_unexpected(built, filled):
        note_poly_fok_partial(built, filled, log)
    if status in (200, 201) and order_still_open(payload) and filled < SIZE:
        cancel_status, cancel_note = _cancel(built, payload)
        log(f"order cancel venue={built['venue']} instrument={built['instrument']} http={cancel_status} {cancel_note}")
        # Keep filled qty. Cancelling the unfilled remainder is not a miss that retries.
        return {
            "filled": filled >= SIZE,
            "advance": False,
            "payload": payload,
            "status": status,
            "note": note,
            "pay": built["pay"],
            "spec": built,
            "step": step,
            "posted": status != 0,
            "fill_qty": format(filled, "f"),
        }
    return {
        "filled": filled >= SIZE,
        "advance": ioc_nothing_filled(status, payload),
        "payload": payload,
        "status": status,
        "note": note,
        "pay": built["pay"],
        "spec": built,
        "step": step,
        "posted": status != 0,
        "fill_qty": format(filled, "f"),
    }


def place_leg(log, key: str, spec: dict, books, other_price: Decimal | None, other_fee: Decimal | None, send=None, read_ws=None, fetch_book=None) -> dict:
    """One leg, one contract, immediate-or-cancel only.

    1. Send at the websocket price.
    2. If that read times out, or the order comes back cancelled with nothing filled, send at the book ask.
    3. If the book order comes back the same way, send at the midway price between that quote and the most we can pay.
    """
    send = send or _send
    read_ws = read_ws or read_websocket_price
    fetch_book = fetch_book or fetch_book_ask
    missed = {"filled": False, "payload": None, "status": 0, "note": "", "pay": spec.get("pay"), "spec": spec, "step": ""}
    if orders_halted():
        missed["note"] = "orders stopped"
        _log_consider("denied", "Orders stopped after a one-leg fill.")
        return missed
    if not ORDERS_ENABLED:
        missed["note"] = "placing orders is off"
        return missed
    ws_price, ws_why = read_ws(spec, books)
    if ws_why != "timeout" and ws_price is not None:
        snapped = snap_pay(spec["venue"], ws_price)
        if snapped is not None:
            live = dict(spec)
            live["quote_source"] = "websocket"
            live["quote_price"] = format(snapped, "f")
            if not live.get("quote_seen_at"):
                live["quote_seen_at"] = _iso_now()
            outcome = _one_ioc(log, key, live, snapped, "websocket", send, other_price, other_fee)
            if outcome["filled"] or not outcome["advance"]:
                return outcome
        else:
            log(f"order websocket price not sendable venue={spec['venue']} instrument={spec['instrument']}")
    else:
        log(f"order websocket price timed out venue={spec['venue']} instrument={spec['instrument']}")
    book_price, book_note = fetch_book(spec)
    if book_price is None:
        missed["note"] = book_note or "book ask missing"
        log(f"order book ask missing venue={spec['venue']} instrument={spec['instrument']} {missed['note']}")
        return missed
    book_pay = snap_pay(spec["venue"], book_price)
    if book_pay is None:
        missed["note"] = "book ask not sendable"
        return missed
    book_spec = dict(spec)
    book_spec["quote_source"] = "book"
    book_spec["quote_price"] = format(book_pay, "f")
    book_spec["quote_seen_at"] = _iso_now()
    outcome = _one_ioc(log, key, book_spec, book_pay, "book", send, other_price, other_fee)
    if outcome["filled"] or not outcome["advance"]:
        return outcome
    maximum = max_leg_price(
        spec["venue"],
        other_price,
        other_fee,
        spec.get("fee_coefficient"),
        spec.get("fee_charged"),
        spec.get("event_status"),
    )
    mid = midway_limit(book_pay, maximum, venue_tick(spec["venue"]))
    if mid is None:
        log(
            f"order midway not sent venue={spec['venue']} instrument={spec['instrument']} "
            f"quote={format(book_pay, 'f')} max={format(maximum, 'f') if maximum is not None else 'none'}"
        )
        outcome["note"] = f"{outcome['note']}; midway not sent"
        return outcome
    mid_spec = dict(spec)
    mid_spec["quote_source"] = "recovery-cap"
    mid_spec["quote_price"] = format(mid, "f")
    if not mid_spec.get("quote_seen_at"):
        mid_spec["quote_seen_at"] = _iso_now()
    return _one_ioc(log, key, mid_spec, mid, "midway", send, other_price, other_fee)


def leg_filled_at_least_one(outcome: dict | None) -> bool:
    """True when this leg filled at least one contract. A miss is false.

    Qty >= 1 is the only yes. HTTP 201, status cancelled, fill_count 0, or a
    weak filled flag without contracts is not a fill (21 Oct 2026 SHSU 9.5).
    """
    if not outcome:
        return False
    return outcome_fill_qty(outcome) >= ONE


def exactly_one_leg_filled(first_out: dict | None, second_out: dict | None) -> bool:
    """True when one venue filled at least one contract and the other filled none.

    The two results are the two legs of the pair. Which venue filled does not
    matter. Nothing filled is false. Both filled is false.
    """
    return leg_filled_at_least_one(first_out) != leg_filled_at_least_one(second_out)


def _pair_legs_ok(legs: list[dict]) -> bool:
    """True when both legs are distinct order venues (Kalshi/Gemini/Polymarket/Novig-when-live)."""
    if len(legs) != 2:
        return False
    venues = [str(leg.get("venue") or "") for leg in legs]
    if venues[0] == venues[1]:
        return False
    for venue in venues:
        if venue not in _ORDER_VENUES:
            return False
        if venue == "novig" and not novig_live.orders_live():
            return False
    return True


def _sort_legs_for_log(legs: list[dict]) -> list[dict]:
    """Deterministic listing only. Alphabetical venue name. Not a send preference."""
    return sorted(legs, key=lambda leg: (str(leg.get("venue") or ""), str(leg.get("outcome") or "")))


def _kalshi_no_house_cash(payload) -> Decimal | None:
    """Kalshi No debit. Confirm / no_price_dollars are already house cash.

    Osborne 26 Oct 2026: fills GET no_price_dollars 0.89, POST average_fill_price
    0.11 Yes-wire. Inverting the confirm price again debited 0.11 instead of 0.89.
    """
    confirm = venue_confirm_of(payload)
    if confirm and confirm.get("known") and confirm.get("avg_price"):
        px = _dec(confirm.get("avg_price"))
        if px is not None and Decimal("0") < px < ONE:
            return px
    no_px = None
    yes_px = None
    avg_fill = None
    for node in _walk(payload):
        if no_px is None:
            no_px = _dec(node.get("no_price_dollars") if node.get("no_price_dollars") not in (None, "") else node.get("no_price"))
        if yes_px is None:
            yes_px = _dec(node.get("yes_price_dollars") if node.get("yes_price_dollars") not in (None, "") else node.get("yes_price"))
        if avg_fill is None:
            avg_fill = _dec(node.get("average_fill_price"))
    if no_px is not None and Decimal("0") < no_px < ONE:
        return no_px
    yes_wire = yes_px if yes_px is not None else avg_fill
    if yes_wire is not None and Decimal("0") < yes_wire < ONE:
        cash = ONE - yes_wire
        if Decimal("0") < cash < ONE:
            return cash
    return None


def _actual_fill_cash(spec: dict, payload) -> Decimal | None:
    """Pay-side cash of a fill. Kalshi No uses 1 − Yes-wire average_fill_price.

    Venue-confirm avg_price and no_price_dollars are already No cash. Do not
    invert them again.
    """
    side = _book_side(spec) or str(spec.get("outcome") or "")
    exec_px = _dec(_execution_price(payload, str(spec.get("outcome") or "")))
    pay = _dec(spec.get("pay"))
    venue = str(spec.get("venue") or "")
    if venue == "kalshi" and side == "no":
        cash = _kalshi_no_house_cash(payload)
        if cash is not None:
            return cash
        if exec_px is not None and Decimal("0") < exec_px < ONE:
            cash = ONE - exec_px
            if Decimal("0") < cash < ONE:
                return cash
    if venue == "polymarket":
        prices = venue_fill_confirm.poly_prices_from_payload(payload)
        confirm = venue_confirm_of(payload)
        quote = spec.get("quote_price") or spec.get("pay")
        if confirm and confirm.get("house_cash"):
            house = _dec(confirm.get("house_cash"))
            if house is not None and Decimal("0") < house < ONE:
                return house
        cash = _polymarket_fill_cash(
            side,
            prices.get("avg") if prices.get("avg") is not None else exec_px,
            pay,
            spread=prices.get("spread"),
            quote=quote,
            intent=str(spec.get("intent") or prices.get("intent") or ""),
        )
        if cash is not None:
            return cash
    if exec_px is not None and Decimal("0") < exec_px < ONE:
        return exec_px
    return pay


def _partner_spec_from_consider(filled_spec: dict) -> dict | None:
    cand = getattr(_consider, "cand", None)
    if not isinstance(cand, dict):
        return None
    filled_outcome = str(filled_spec.get("outcome") or "")
    other = "no" if filled_outcome == "yes" else "yes" if filled_outcome == "no" else ""
    if not other:
        return None
    return _leg_spec(cand, other)


def _register_send_fill_watch(spec: dict, payload) -> None:
    """Open a leftover watch as soon as a venue fill is known. Does not send.

    Venue confirm qty >= 1 counts even when the ledger replace failed.
    Leftover recovery posts are skipped. Latch is not written here.
    Do not leftover-watch a directional dog (E) or C/D one-way T0.
    """
    if spec.get("_watch_recovery") or spec.get("_flatten") or spec.get("_strategy_b"):
        return
    if leftover_watch_skipped(spec):
        return
    if str(spec.get("_step") or "") in {"watch", "simultaneous", "hard", "easy", "flatten", "recovery"}:
        return
    if filled_contracts(payload) < ONE:
        return
    key = str(spec.get("_bet_key") or "")
    if not key:
        return
    fill_px = _actual_fill_cash(spec, payload)
    fill_fee = leg_fee(spec, fill_px, payload) if fill_px is not None else None
    if fill_px is None or fill_fee is None:
        return
    missed = _partner_spec_from_consider(spec)
    if missed is None:
        opp = opposite_side_of(_book_side(spec) or spec.get("outcome") or "")
        missed = {"venue": "", "instrument": "", "outcome": opp, "side": opp}
    title = str(getattr(_consider, "title", "") or "")
    persist_one_leg_watch(key, title, spec, missed, fill_px, fill_fee)


def _fill_price_of(spec: dict, outcome: dict | None) -> Decimal | None:
    outcome = outcome or {}
    payload = outcome.get("payload")
    cash = _actual_fill_cash(spec, payload) if payload is not None else None
    if cash is not None:
        return cash
    fill_px = _dec(outcome.get("pay")) or _dec(spec.get("pay"))
    if fill_px is None:
        fill_px = _dec(_execution_price(payload, str(spec.get("outcome") or "")))
    return fill_px


def _record_filled(key: str, spec: dict, outcome: dict) -> None:
    _append({
        "event": "filled",
        "bet_key": key,
        "venue": spec["venue"],
        "instrument": spec["instrument"],
        "side": _book_side(spec),
        "size": "1",
        "price": _execution_price(outcome.get("payload"), str(spec.get("outcome") or "")) or outcome.get("pay") or spec.get("pay"),
    })


def _recovery_leg(log, key: str, missed: dict, books, filled_price: Decimal, filled_fee: Decimal, send=None) -> dict:
    """One recovery after the parallel first attempt left exactly one fill.

    Uses the existing three-step walk (websocket → book → midway), capped so
    the limit never exceeds the max profitable price given the actual fill.
    """
    maximum = max_leg_price(
        missed["venue"],
        filled_price,
        filled_fee,
        missed.get("fee_coefficient"),
        missed.get("fee_charged"),
        missed.get("event_status"),
    )
    if maximum is None:
        return {
            "filled": False,
            "advance": False,
            "payload": None,
            "status": 0,
            "note": "no profitable recovery limit",
            "pay": missed.get("pay"),
            "spec": missed,
            "step": "recovery",
            "posted": False,
        }
    log(
        f"order recovery max={format(maximum, 'f')} venue={missed['venue']} "
        f"instrument={missed['instrument']} after fill={format(filled_price, 'f')}"
    )
    return place_leg(log, key, missed, books, filled_price, filled_fee, send=send)


def _send_pair(
    log,
    key: str,
    title: str,
    legs: list[dict],
    gemini_events=None,
    kalshi_events=None,
    polymarket=None,
    novig=None,
    fresh=None,
    skip_book_recheck=False,
) -> None:
    """Sequential hard-first IOC after a live book recheck. Flatten if the easy leg is skipped or misses.

    orders.html / opportunities.html / orders_performance.html wait until both
    IOCs finish (or flatten / hard-miss abort). Do not rebuild them between the
    hard confirm and the easy send.
    """
    books = {"gemini": gemini_events, "kalshi": kalshi_events, "polymarket": polymarket, "novig": novig}
    phone: tuple[bool, str] | None = None
    filled_any = False
    stop_filled: dict | None = None
    stop_missed: dict | None = None
    first_out = None
    second_out = None
    flatten = None
    first = None
    second = None
    result_reason = ""
    sent_order = False
    flattened_ok = False
    try:
        _hold_send_html()
        if not _pair_legs_ok(legs):
            names = ",".join(str(leg.get("venue") or "") for leg in legs)
            log(f"order skip {title}; pair needs two distinct order venues ({names})")
            record_send_skip(f"pair needs two distinct order venues ({names})", title, key)
            _log_consider("denied", "This pair is not two live order venues, so it was not sent.")
            return
        ordered = _sort_legs_for_log(legs)
        first, second = ordered[0], ordered[1]
        _bind_consider_to_pair(title, ordered)
        if orders_halted():
            log("order skipped; orders stopped")
            _log_consider("denied", "Orders stopped after a one-leg fill.")
            return
        if watch_is_active():
            log("order skipped; one-leg watch is open")
            _log_consider("denied", "Orders stopped after a one-leg fill.")
            return
        price_a = _dec(first.get("pay"))
        price_b = _dec(second.get("pay"))
        fee_a = leg_fee(first, price_a) if price_a is not None else None
        fee_b = leg_fee(second, price_b) if price_b is not None else None
        # Recheck the pair at the prices about to be sent before the hard IOC leaves.
        block_a = _profit_block(first, price_a, price_b, fee_b)
        block_b = _profit_block(second, price_b, price_a, fee_a)
        if block_a or block_b:
            why = block_a or block_b
            log(f"order skip hard-first not profitable {title} {why}")
            record_send_skip(f"over cap {why}", title, key)
            _log_consider("denied", f"Price moved; hard-first send no longer under the {send_line()} cap.")
            return
        funds_a = _funds_block(first if first.get("body") else {**first, "limit": first.get("pay")})
        funds_b = _funds_block(second if second.get("body") else {**second, "limit": second.get("pay")})
        # Build sendable bodies at the quoted pays, then recheck funds on those bodies.
        built_a = _spec_at_price(first, price_a) if price_a is not None else None
        built_b = _spec_at_price(second, price_b) if price_b is not None else None
        if built_a is None or built_b is None:
            log(f"order skip hard-first price not sendable {title}")
            _log_consider("denied", "A hard-first limit was not sendable.")
            return
        compared_at = first.get("quote_seen_at") or second.get("quote_seen_at") or _iso_now()
        quote_src = "book" if skip_book_recheck else "websocket"
        meta_a = _leg_quote_meta(first, fresh, compared_at, quote_src)
        meta_b = _leg_quote_meta(second, fresh, compared_at, quote_src)
        trigger = _pick_trigger([meta_a, meta_b], fresh)
        if first.get("trigger_venue"):
            trigger = {
                "venue": first.get("trigger_venue"),
                "side": first.get("trigger_side"),
                "price": first.get("trigger_price"),
                "seen_at": first.get("trigger_seen_at"),
                "source": first.get("trigger_source") or quote_src,
            }
        _attach_quote(built_a, meta_a, trigger, quote_src)
        _attach_quote(built_b, meta_b, trigger, quote_src)
        _carry_quote_fields(first, built_a)
        _carry_quote_fields(second, built_b)
        funds_a = _funds_block(built_a)
        funds_b = _funds_block(built_b)
        if funds_a or funds_b:
            reasons = []
            if funds_a:
                reasons.append(_balance_deny_from_funds(funds_a))
            if funds_b:
                reasons.append(_balance_deny_from_funds(funds_b))
            why = "; ".join(dict.fromkeys(reasons))
            if all(_is_unread_balance_reason(item) for item in reasons):
                if _record_unread_balance_skip(why, title, key):
                    log(f"order skip hard-first funds {funds_a or funds_b}")
                return
            log(f"order skip hard-first funds {funds_a or funds_b}")
            _record_balance_skip(why, title, key)
            _log_consider("denied", why)
            return
        if skip_book_recheck:
            live_a, live_b = built_a, built_b
            gate = ""
        else:
            gate, live_a, live_b = _recheck_pair_books(built_a, built_b)
        if gate or live_a is None or live_b is None:
            log(f"order skip send gate {title} {gate}")
            record_send_skip(gate or "book recheck failed", title, key, spec=live_a or built_a)
            _log_consider("denied", gate or "Book recheck failed; neither leg sent.")
            return
        rebuilt_a = _spec_at_price(live_a, _dec(live_a.get("pay")))
        rebuilt_b = _spec_at_price(live_b, _dec(live_b.get("pay")))
        if rebuilt_a is None or rebuilt_b is None:
            log(f"order skip send gate not sendable {title}")
            record_send_skip("rechecked ask not sendable", title, key, spec=live_a)
            _log_consider("denied", "Rechecked ask was not sendable; neither leg sent.")
            return
        _carry_quote_fields(live_a, rebuilt_a)
        _carry_quote_fields(live_b, rebuilt_b)
        built_a, built_b = rebuilt_a, rebuilt_b
        hard_built, easy_built = _pick_hard_leg(built_a, built_b)
        if hard_built is built_a:
            hard_spec, easy_spec = first, second
        else:
            hard_spec, easy_spec = second, first
        first, second = hard_spec, easy_spec
        first["pay"] = hard_built.get("pay")
        second["pay"] = easy_built.get("pay")
        price_hard = _dec(hard_built.get("pay"))
        price_easy = _dec(easy_built.get("pay"))
        fee_hard = leg_fee(hard_built, price_hard) if price_hard is not None else None
        fee_easy = leg_fee(easy_built, price_easy) if price_easy is not None else None
        hard_sz = hard_built.get("quote_size") or ""
        easy_sz = easy_built.get("quote_size") or ""
        log(
            f"order hard-first send {title} hard {hard_built.get('venue')}/{hard_built.get('outcome')}"
            f"@{hard_built.get('pay')} size={hard_sz} then easy {easy_built.get('venue')}/"
            f"{easy_built.get('outcome')}@{easy_built.get('pay')} size={easy_sz}; "
            f"trigger {trigger.get('venue') or ''} {trigger.get('side') or ''} {trigger.get('price') or ''} "
            f"seen {_hhmmss(trigger.get('seen_at'))} {_short_source(str(trigger.get('source') or 'websocket'))} + "
            f"{hard_built.get('venue')} {hard_built.get('outcome')} {hard_built.get('quote_price') or hard_built.get('pay')} "
            f"seen {_hhmmss(hard_built.get('quote_seen_at'))} {_short_source(str(hard_built.get('quote_source') or 'book'))} + "
            f"{easy_built.get('venue')} {easy_built.get('outcome')} {easy_built.get('quote_price') or easy_built.get('pay')} "
            f"seen {_hhmmss(easy_built.get('quote_seen_at'))} {_short_source(str(easy_built.get('quote_source') or 'book'))}; "
            f"orders {_hhmmss(_iso_now())}"
        )

        def _unsent(spec: dict, note: str) -> dict:
            return {
                "filled": False,
                "payload": None,
                "status": 0,
                "note": note,
                "pay": spec.get("pay"),
                "spec": spec,
                "step": "easy",
                "posted": False,
            }

        def _finish_one_leg(filled_spec: dict, filled_out: dict, missed_spec: dict, missed_out: dict) -> None:
            nonlocal flatten, flattened_ok, filled_any, sent_order, result_reason, phone, stop_filled, stop_missed
            filled_any = True
            _record_filled(key, filled_spec, filled_out)
            fill_px = _fill_price_of(filled_spec, filled_out)
            fill_fee = leg_fee(filled_spec, fill_px, filled_out.get("payload")) if fill_px is not None else None
            flatten = flatten_filled_leg(log, key, title, filled_spec)
            sent_order = sent_order or _order_was_sent(flatten)
            if leg_filled_at_least_one(flatten):
                flattened_ok = True
                filled_any = True
                flat_spec = flatten.get("spec") if isinstance(flatten.get("spec"), dict) else _flatten_spec(filled_spec)
                if isinstance(flat_spec, dict):
                    _record_filled(key, flat_spec, flatten)
                log(f"order flattened one-leg {title}")
                result_reason = "One leg filled; flatten filled. Not holding directional."
                if sent_order:
                    phone = (
                        True,
                        "success. flattened the filled leg. "
                        f"{title}. {_fill_bit(filled_spec, filled_out)}.",
                    )
                return
            note2 = str(flatten.get("note") or "flatten missed")
            status2 = int(flatten.get("status") or 0)
            result_reason = (
                "Sent. One leg filled and flatten missed. "
                f"{filled_spec.get('venue')} flatten HTTP {status2} {note2}."
            )
            _log_one_leg(log, filled_spec, filled_out.get("payload"))
            _append({
                "event": "one_leg",
                "bet_key": key,
                "venue": filled_spec["venue"],
                "instrument": filled_spec["instrument"],
                "side": _book_side(filled_spec),
                "size": "1",
                "price": _execution_price(filled_out.get("payload"), str(filled_spec.get("outcome") or "")) or filled_out.get("pay") or filled_spec.get("pay"),
                "second_venue": missed_spec["venue"],
                "second_http": int((missed_out or {}).get("status") or 0),
                "note": note2,
            })
            alert_one_leg(log, title, filled_spec, filled_out.get("payload"), missed_spec, status2, note2, flatten.get("payload"))
            if sent_order:
                detail = one_leg_message(title, filled_spec, filled_out.get("payload"), missed_spec, status2, note2, flatten.get("payload"))
                phone = (False, f"failure. {detail}")
            stop_filled = _leg_stop_bits(filled_spec, filled_out)
            stop_missed = _leg_stop_bits(missed_spec, missed_out or {})
            watch_px = fill_px if fill_px is not None else _dec(filled_spec.get("pay"))
            watch_fee = fill_fee if fill_fee is not None else (
                leg_fee(filled_spec, watch_px, filled_out.get("payload")) if watch_px is not None else None
            )
            if watch_px is not None and watch_fee is not None:
                try:
                    persist_one_leg_watch(key, title, filled_spec, missed_spec, watch_px, watch_fee, books=books)
                except Exception as exc:
                    log(f"order watch persist {type(exc).__name__}")

        first_out = _one_ioc(
            log, key, hard_built, price_hard, "hard", _send, price_easy, fee_easy,
        )
        sent_order = _order_was_sent(first_out)
        hard_filled = outcome_fill_qty(first_out) >= ONE
        if outcome_fill_qty(first_out) > 0:
            filled_any = True
        if not hard_filled:
            gap_gate, live_easy = _live_from_book(easy_built)
            gap_closed = bool(gap_gate) or live_easy is None
            if not gap_closed and live_easy is not None:
                pe = _dec(live_easy.get("pay"))
                fe = leg_fee(live_easy, pe) if pe is not None else None
                ph = price_hard
                fh = fee_hard
                if _profit_block(live_easy, pe, ph, fh):
                    gap_closed = True
            log(
                f"order hard_miss_abort {title} venue={hard_built.get('venue')} "
                f"gap_closed={gap_closed}; easy not sent"
            )
            _append({
                "event": "hard_miss_abort",
                "bet_key": key,
                "venue": hard_built.get("venue"),
                "http_status": first_out.get("status"),
                "note": first_out.get("note"),
                "other_venue": easy_built.get("venue"),
                "gap_closed": gap_closed,
                "hard_size": hard_sz,
                "easy_size": easy_sz,
            })
            if sent_order:
                gap_bit = "Gap closed after the miss." if gap_closed else "Gap still open; still did not send the easier leg."
                result_reason = f"Hard miss abort. Did not send the easier leg. {gap_bit}"
                phone = (
                    False,
                    "failure. hard miss abort. did not send easier leg. "
                    f"{title}. {_fill_bit(first, first_out)}.",
                )
            return
        fill_px = _fill_price_of(first, first_out)
        fill_fee = leg_fee(first, fill_px, first_out.get("payload")) if fill_px is not None else None
        if fill_px is None:
            fill_px = price_hard
            fill_fee = fee_hard
        easy_gate, live_easy = _live_from_book(easy_built)
        if easy_gate or live_easy is None:
            log(f"order hard filled gap closed {title} {easy_gate}; flatten hard, easy not sent")
            second_out = _unsent(easy_built, easy_gate or "easy book recheck failed")
            _finish_one_leg(first, first_out, second, second_out)
            return
        rebuilt_easy = _spec_at_price(live_easy, _dec(live_easy.get("pay")))
        if rebuilt_easy is None:
            log(f"order hard filled easy not sendable {title}; flatten hard, easy not sent")
            second_out = _unsent(easy_built, "rechecked easy ask not sendable")
            _finish_one_leg(first, first_out, second, second_out)
            return
        _carry_quote_fields(live_easy, rebuilt_easy)
        easy_pay = _dec(rebuilt_easy.get("pay"))
        easy_fee_now = leg_fee(rebuilt_easy, easy_pay) if easy_pay is not None else None
        blocked = _profit_block(rebuilt_easy, easy_pay, fill_px, fill_fee)
        easy_size = _takeable_size(rebuilt_easy)
        if blocked or easy_size is None or easy_size < SIZE:
            why = blocked or f"easy no takeable size (saw {easy_size})"
            log(f"order hard filled gap closed {title} {why}; flatten hard, easy not sent")
            second_out = _unsent(rebuilt_easy, why)
            _finish_one_leg(first, first_out, second, second_out)
            return
        second["pay"] = rebuilt_easy.get("pay")
        second_out = _one_ioc(
            log, key, rebuilt_easy, easy_pay, "easy", _send, fill_px, fill_fee,
        )
        sent_order = sent_order or _order_was_sent(second_out)
        easy_filled = outcome_fill_qty(second_out) >= ONE
        if outcome_fill_qty(second_out) > 0:
            filled_any = True
        if hard_filled and easy_filled:
            filled_any = True
            _record_filled(key, first, first_out)
            _record_filled(key, second, second_out)
            try:
                _drop_watch({"bet_key": key})
            except Exception:
                pass
            log(f"order both legs filled {title}")
            result_reason = "Both legs filled."
            if sent_order:
                phone = (
                    True,
                    "success. both legs filled. "
                    f"{title}. {_fill_bit(first, first_out)}. {_fill_bit(second, second_out)}.",
                )
            return
        _finish_one_leg(first, first_out, second, second_out)
    finally:
        if result_reason:
            patch = {}
            for outcome in (first_out, second_out):
                if not isinstance(outcome, dict):
                    continue
                spec = outcome.get("spec") if isinstance(outcome.get("spec"), dict) else {}
                side = str(spec.get("outcome") or "")
                pay = outcome.get("pay") or spec.get("pay")
                if side in ("yes", "no") and pay:
                    patch[f"{side}_price"] = str(pay)
            source = first or second or {}
            for key in QUOTE_KEYS:
                if key.startswith("trigger_") and source.get(key) not in (None, ""):
                    patch[key] = source.get(key)
            returns = posted_leg_returns(first_out, second_out, flatten)
            if returns:
                patch["venue_return"] = returns
            filled_shops: list[str] = []
            for outcome in (first_out, second_out, flatten):
                if not isinstance(outcome, dict):
                    continue
                if outcome_fill_qty(outcome) <= 0:
                    continue
                spec = outcome.get("spec") if isinstance(outcome.get("spec"), dict) else {}
                shop = str(spec.get("venue") or "").lower()
                if shop and shop not in filled_shops:
                    filled_shops.append(shop)
            if filled_shops:
                patch["filled_venues"] = ",".join(filled_shops)
            if flattened_ok:
                patch["hold_now"] = "none"
            result_reason = sent_reason_with_venue_returns(
                result_reason, first_out, second_out, flatten
            )
            _log_consider("sent", result_reason, None, patch or None)
        if filled_any:
            refresh_balances(log)
        if exactly_one_leg_filled(first_out, second_out) and not flattened_ok:
            if stop_filled is None or stop_missed is None:
                if first is not None and second is not None:
                    if leg_filled_at_least_one(first_out):
                        stop_filled = _leg_stop_bits(first, first_out)
                        stop_missed = _leg_stop_bits(second, second_out)
                    else:
                        stop_filled = _leg_stop_bits(second, second_out)
                        stop_missed = _leg_stop_bits(first, first_out)
            if stop_filled is not None and stop_missed is not None:
                stop_orders("one leg filled and the other missed", stop_filled, stop_missed)
        if phone is not None:
            _phone_trade_result(log, phone[1], phone[0])
        if sent_order or result_reason:
            _refresh_order_pages()
        _release_send_html()


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def smoke() -> dict:
    """Balance reads and Gemini terms. Does not place an order."""
    report = {}
    try:
        status, usd = kalshi_private.balance_usd()
        report["kalshi_http"] = status
        report["kalshi_usd"] = usd
    except Exception as exc:
        report["kalshi_http"] = type(exc).__name__
    try:
        status, body = gemini_private.private_call("/v1/balances", None, "POST")
        report["gemini_balance_http"] = status
        if status == 200:
            data = json.loads(body)
            usd = None
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, dict) and str(row.get("currency") or "").upper() == "USD":
                        usd = row.get("available")
            report["gemini_usd"] = usd
        else:
            report["gemini_balance_note"] = _public_note(body)
    except Exception as exc:
        report["gemini_balance_http"] = type(exc).__name__
    try:
        status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "GET")
        if status != 200:
            status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "POST")
        report["gemini_terms_http"] = status
        if status == 200:
            data = json.loads(body)
            report["gemini_terms_accepted"] = bool(data.get("hasAcceptedLatest"))
        else:
            report["gemini_terms_note"] = _public_note(body)
    except Exception as exc:
        report["gemini_terms_http"] = type(exc).__name__
    try:
        status, body = polymarket_us_live.signed_json("GET", "/v1/account/balances")
        report["polymarket_http"] = status
        if status == 200:
            data = json.loads(body)
            power = None
            for row in data.get("balances") or []:
                if isinstance(row, dict):
                    power = row.get("buyingPower")
            report["polymarket_buying_power"] = power
        else:
            report["polymarket_note"] = _public_note(body)
    except Exception as exc:
        report["polymarket_http"] = type(exc).__name__
    report["orders_sent"] = 0
    return report


def _public_book(symbol: str) -> tuple[int, dict | None]:
    if not venue_pace.wait_turn("gemini", priority=venue_pace.PRIORITY_BACKGROUND):
        return 0, None
    try:
        url = "https://api.gemini.com/v1/book/" + urllib.parse.quote(symbol, safe="")
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "stockresearch-gemini-probe"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        venue_pace.release_turn("gemini")


def _book_best_ask(book: dict) -> Decimal | None:
    best = None
    for level in book.get("asks") or []:
        if isinstance(level, dict):
            price = _dec(level.get("price"))
        elif isinstance(level, (list, tuple)) and level:
            price = _dec(level[0])
        else:
            price = None
        if price is None:
            continue
        if best is None or price < best:
            best = price
    return best


def _nfl_probe_symbols() -> list[tuple[str, str]]:
    path = RAW / "nfl_lackc_gemini.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        for raw in event.get("contracts") or []:
            if not isinstance(raw, dict):
                continue
            symbol = str(raw.get("instrumentSymbol") or "")
            prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
            ask = _dec(prices.get("bestAsk"))
            if not symbol.startswith("GEMI-NFL-"):
                continue
            if str(raw.get("status") or "") != "active" or str(raw.get("marketState") or "") != "open":
                continue
            if ask is None or ask < Decimal("0.20") or ask > Decimal("0.80"):
                continue
            rows.append((abs(ask - Decimal("0.50")), symbol, str(raw.get("label") or "")))
    rows.sort(key=lambda item: item[0])
    return [(symbol, label) for _score, symbol, label in rows[:8]]


def probe_gemini_once() -> dict:
    """One non-marketable Gemini prediction-market limit. Does not flip ORDERS_ENABLED."""
    if ORDERS_ENABLED:
        raise RuntimeError("probe refuses to run while ORDERS_ENABLED is true")
    symbol = ""
    label = ""
    book_ask = None
    for candidate, candidate_label in _nfl_probe_symbols():
        status, book = _public_book(candidate)
        ask = _book_best_ask(book) if status == 200 and isinstance(book, dict) else None
        if ask is not None and Decimal("0.04") <= ask <= Decimal("0.96"):
            symbol = candidate
            label = candidate_label
            book_ask = ask
            break
    if not symbol or book_ask is None:
        return {"error": "no live nfl ask", "orders_enabled": ORDERS_ENABLED}
    limit = (book_ask - Decimal("0.03")).quantize(CENT, rounding=ROUND_DOWN)
    if limit < CENT or limit >= book_ask:
        return {"error": "limit would not sit below the ask", "book_ask": format(book_ask, "f"), "orders_enabled": ORDERS_ENABLED}
    body = {
        "symbol": symbol,
        "orderType": "limit",
        "side": "buy",
        "quantity": "1",
        "price": format(limit, "f"),
        "outcome": "yes",
        "timeInForce": "good-til-cancel",
        "makerOrCancel": True,
    }
    recorded: dict = {}
    status, text = gemini_private.private_call("/v1/prediction-markets/order", body, "POST", record=recorded)
    request = recorded.get("request") or body
    record_order_io("gemini", "order", request, status, text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    cancel_status = None
    cancelled = False
    if status in (200, 201) and order_still_open(payload):
        cancel_status, _note = _cancel({"venue": "gemini", "instrument": symbol, "outcome": "yes"}, payload)
        cancelled = True
    fields = payload if isinstance(payload, dict) else {}
    return {
        "symbol": symbol,
        "label": label,
        "side": "buy",
        "outcome": "yes",
        "limit": format(limit, "f"),
        "size": "1",
        "time_in_force": "good-til-cancel",
        "maker_or_cancel": True,
        "book_ask": format(book_ask, "f"),
        "http_status": status,
        "order_id": _order_id(payload) if payload is not None else "",
        "order_status": fields.get("status"),
        "filled_quantity": fields.get("filledQuantity"),
        "remaining_quantity": fields.get("remainingQuantity"),
        "reason": fields.get("reason") or fields.get("message") or fields.get("error"),
        "cancelled": cancelled,
        "cancel_http": cancel_status,
        "orders_enabled": ORDERS_ENABLED,
    }


if __name__ == "__main__":
    import sys
    if "--probe-gemini" in sys.argv:
        summary = probe_gemini_once()
        print(json.dumps(summary, default=str))
    elif "--smoke" in sys.argv:
        print(json.dumps(smoke(), default=str))
    else:
        print("Pass --smoke to read balances. This command does not place an order.")
