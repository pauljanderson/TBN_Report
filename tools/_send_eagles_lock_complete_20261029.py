"""Paul: complete A lock-gap 2nd leg. 1 Poly FOK Yes Eagles. Do not GTC.

REST-confirm Kalshi No PHI still held. REST Poly Yes Eagles ML book.
Abort if pair > 0.99 unrounded after-fee. Do not sell Kalshi. Do not start B.
Do not leftover-GTC. Do not bump stake. Do not print secrets.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_private  # noqa: E402
import kalshi_ticker_decode as ktd  # noqa: E402
import live_lock_orders  # noqa: E402
import polymarket_us_live  # noqa: E402

TICKER = "KXNFLGAME-26NOV01PHIWAS-PHI"
WAS_TICKER = "KXNFLGAME-26NOV01PHIWAS-WAS"
HELD_SIDE = "no"
CASH = Decimal("0.6660")
NET_MAX = Decimal("0.99")
# This NFL book is 0.0025 (offers 0.3025 / 0.3050). House POLY_TICK 0.001
# snapped 0.3025 → 0.302 and venue 400'd "price isn't valid".
NFL_POLY_TICK = Decimal("0.0025")
GAME = "Philadelphia Eagles vs Washington Commanders"
DATE = "2026-11-01"
KEY = "pro football\tphiwas\t2026-11-01\tmoneyline\tcode:PHI\t\tpolymarket\tkalshi"


def _fp(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _abort(why: str, extra: dict | None = None) -> int:
    row = {"result": "aborted", "why": why, "kalshi_ticker": TICKER}
    if extra:
        row.update(extra)
    print(json.dumps(row, default=str))
    return 1


def _name_hit(want: str, *names: str) -> bool:
    w = str(want or "").casefold().strip()
    if not w:
        return False
    for raw in names:
        n = str(raw or "").casefold().strip()
        if not n:
            continue
        if w == n or w in n or n in w:
            return True
        wt, nt = w.split()[-1], n.split()[-1]
        if wt == nt and len(wt) > 3:
            return True
    return False


def kalshi_seat() -> tuple[dict | None, str]:
    status, body = kalshi_private.signed_call(
        "GET",
        "/trade-api/v2/portfolio/positions",
        query={"limit": "200", "count_filter": "position", "ticker": TICKER},
    )
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None, f"kalshi positions not json http={status}"
    if status not in (200, 201) or not isinstance(data, dict):
        return None, f"kalshi positions http={status}"
    markets = data.get("market_positions") or []
    want = None
    was_row = None
    for row in markets:
        if not isinstance(row, dict):
            continue
        tick = str(row.get("ticker") or "")
        if tick == TICKER:
            want = row
        elif tick == WAS_TICKER:
            was_row = row
    if want is None:
        status2, body2 = kalshi_private.signed_call(
            "GET",
            "/trade-api/v2/portfolio/positions",
            query={"limit": "1000", "count_filter": "position"},
        )
        try:
            data2 = json.loads(body2)
        except json.JSONDecodeError:
            data2 = {}
        if status2 in (200, 201) and isinstance(data2, dict):
            for row in data2.get("market_positions") or []:
                if not isinstance(row, dict):
                    continue
                tick = str(row.get("ticker") or "")
                if tick == TICKER:
                    want = row
                elif tick == WAS_TICKER:
                    was_row = row
        if want is None:
            extra = {}
            if was_row is not None:
                extra["was_ticker_held"] = True
                extra["was_position_fp"] = str(was_row.get("position_fp") or "")
            return None, "kalshi seat gone"
    signed = _fp(want.get("position_fp"))
    if signed is None or signed == 0:
        return None, "kalshi seat gone (position_fp 0)"
    side = "yes" if signed > 0 else "no"
    qty = abs(signed)
    if side != HELD_SIDE:
        return None, f"kalshi seat is {side} on {TICKER}, not No Eagles"
    if qty < 1:
        return None, f"kalshi No Eagles qty {format(qty, 'f')} < 1"
    if was_row is not None:
        was_signed = _fp(was_row.get("position_fp"))
        if was_signed is not None and was_signed < 0:
            return None, "kalshi also holds No Commanders (-WAS); not this ticket"
    return {
        "ticker": TICKER,
        "side": side,
        "qty": qty,
        "position_fp": signed,
        "seat": "No Philadelphia Eagles",
        "pays": "Washington Commanders win",
    }, ""


def poly_yes_eagles() -> tuple[dict | None, str]:
    row = {"title_kalshi": GAME, "title_gemini": GAME, "date": DATE}
    markets = polymarket_us_live.markets_from_search(row, None)
    if not markets:
        import urllib.parse

        payload = polymarket_us_live._get(
            polymarket_us_live.GATEWAY
            + "/v1/search?"
            + urllib.parse.urlencode({"query": GAME, "limit": "10"})
        )
        events = payload.get("events") if isinstance(payload, dict) else []
        markets = []
        for event in events or []:
            if not isinstance(event, dict):
                continue
            title = str(event.get("title") or "")
            if not _name_hit("eagles", title) or not (
                _name_hit("commanders", title) or _name_hit("washington", title)
            ):
                continue
            start = str(event.get("startTime") or event.get("startDate") or "")
            if DATE not in start and DATE not in str(event.get("slug") or ""):
                if not polymarket_us_live._event_on_date(event, DATE):
                    continue
            for market in event.get("markets") or []:
                parsed = polymarket_us_live.two_way_moneyline(market)
                if not parsed:
                    continue
                parsed["event_title"] = title
                parsed["startTime"] = start
                parsed["date"] = DATE
                markets.append(parsed)
    if not markets:
        return None, "no Polymarket moneyline for PHI vs WAS"
    who = "Philadelphia Eagles"
    picked = None
    for market in markets:
        kind = str(market.get("kind") or "moneyline")
        if kind not in {"", "moneyline", "ml"}:
            continue
        slug = str(market.get("slug") or "")
        blob = " ".join(
            str(market.get(k) or "")
            for k in ("slug", "event_title", "kind", "number", "long_name", "short_name")
        ).lower()
        if any(tok in blob for tok in ("spread", "total", "over", "under")):
            continue
        long_name = str(market.get("long_name") or "")
        short_name = str(market.get("short_name") or "")
        title = str(market.get("event_title") or "")
        if not (
            _name_hit("eagles", title, long_name, short_name)
            and (_name_hit("commanders", title, long_name, short_name) or _name_hit("washington", title, long_name, short_name))
        ):
            continue
        if _name_hit(who, long_name):
            picked = {
                "venue": "polymarket",
                "instrument": slug,
                "outcome": "yes",
                "intent": "ORDER_INTENT_BUY_LONG",
                "fee_coefficient": market.get("fee_coefficient"),
                "label": f"Polymarket Yes {long_name}",
                "long_name": long_name,
                "short_name": short_name,
                "event_title": title,
                "kind": "moneyline",
            }
            break
        if _name_hit(who, short_name):
            picked = {
                "venue": "polymarket",
                "instrument": slug,
                "outcome": "no",
                "intent": "ORDER_INTENT_BUY_SHORT",
                "fee_coefficient": market.get("fee_coefficient"),
                "label": f"Polymarket Yes {short_name} (short)",
                "long_name": long_name,
                "short_name": short_name,
                "event_title": title,
                "kind": "moneyline",
            }
            break
    if picked is None:
        return None, "Polymarket moneyline found but not Yes Eagles / PHI vs WAS ML"
    return picked, ""


def main() -> int:
    live_lock_orders.ORDERS_ENABLED = True
    live_lock_orders.NET_MAX = NET_MAX
    live_lock_orders.POLY_TICK = NFL_POLY_TICK
    seat, why = kalshi_seat()
    if seat is None:
        return _abort(why)
    spec, why = poly_yes_eagles()
    if spec is None:
        return _abort(why, {"kalshi_held": seat})
    ask, note = live_lock_orders.fetch_book_ask(spec, pace=False, priority=True)
    if ask is None:
        return _abort(f"poly book miss: {note}", {"kalshi_held": seat, "poly": spec})
    fee = live_lock_orders.leg_fee(spec, ask)
    if fee is None:
        return _abort("poly fee unknown", {"kalshi_held": seat, "ask": format(ask, "f")})
    after = ask + fee
    pair = CASH + after
    extra = {
        "kalshi_held": seat,
        "poly_slug": spec["instrument"],
        "poly_label": spec["label"],
        "poly_kind": spec["kind"],
        "ask": format(ask, "f"),
        "fee": format(fee, "f"),
        "after_fee": format(after, "f"),
        "pair": format(pair, "f"),
        "quote_size": spec.get("quote_size") or "",
    }
    if pair > NET_MAX:
        return _abort(f"pair {format(pair, 'f')} > {format(NET_MAX, 'f')}", extra)
    skip = live_lock_orders.poly_size_lt_qty_skip(spec, rest=False)
    if skip:
        return _abort(skip, extra)
    spec["game"] = GAME
    spec["sport"] = "pro football"
    spec["player"] = "Philadelphia Eagles"
    spec["quote_source"] = "book"
    spec["quote_price"] = format(ask, "f")
    spec["quote_seen_at"] = live_lock_orders._iso_now()
    spec["_watch_recovery"] = True
    spec["_system"] = "lock"

    def _log(msg: str) -> None:
        print(msg, flush=True)

    outcome = live_lock_orders._one_ioc(
        _log,
        KEY,
        spec,
        ask,
        "book",
        live_lock_orders._send,
        CASH,
        Decimal("0"),
    )
    qty = live_lock_orders.outcome_fill_qty(outcome)
    posted = bool(outcome.get("posted"))
    fill_px = live_lock_orders._fill_price_of(spec, outcome) if posted else None
    if qty >= live_lock_orders.SIZE or live_lock_orders.leg_filled_at_least_one(outcome):
        live_lock_orders._record_filled(KEY, outcome.get("spec") or spec, outcome)
        fill_fee = live_lock_orders.leg_fee(spec, fill_px) if fill_px is not None else fee
        fill_after = (fill_px + fill_fee) if fill_px is not None and fill_fee is not None else after
        fill_pair = CASH + fill_after
        print(
            json.dumps(
                {
                    "result": "sent",
                    "filled": True,
                    "fill_qty": format(qty, "f"),
                    "fill_price": format(fill_px, "f") if fill_px is not None else outcome.get("pay"),
                    "pair_after_fee": format(fill_pair, "f"),
                    "http_status": outcome.get("status"),
                    "note": outcome.get("note") or "",
                    "tif": "FOK",
                    **extra,
                },
                default=str,
            )
        )
        return 0
    print(
        json.dumps(
            {
                "result": "sent" if posted else "aborted",
                "why": "FOK miss" if posted else (outcome.get("note") or "not posted"),
                "filled": False,
                "fill_qty": format(qty, "f"),
                "fill_price": None,
                "pair_after_fee": format(pair, "f"),
                "http_status": outcome.get("status"),
                "note": outcome.get("note") or "",
                "tif": "FOK",
                "retried": False,
                **extra,
            },
            default=str,
        )
    )
    return 0 if posted else 1


if __name__ == "__main__":
    raise SystemExit(main())
