"""Periodic venue-true reconcile of kitchen prediction-market tickets.

One process. Lists kitchen rows that are open, postponed, unreconciled, or
missed-send. REST-pulls venue trades + settlement. Updates settled_pnl_store
to venue qty / cash / settle.

Does not place, cancel, or sell. Does not start Strategy B. Does not leftover-GTC.
Does not print secrets. Does not bump stake.

Rules:
- confirm qty 0 is never a won/lost ticket
- venue qty 0.02 is a real 0.02 fill (not house 1, not a ghost missed-send)
- After settlement (or a closed Yes+No flatten), pull Kalshi fills / Poly
  activities / Gemini history / Novig fills and overwrite kitchen to venue truth
- A Kalshi flatten round-trip books venue net P&L, not two directional settles
- Kalshi 19.04 all-in is wire 18 + fee 1.04. Do not double-count fees
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from prediction_paths import RAW_DIR as RAW, ROOT, ensure_dirs

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import settled_pnl_store  # noqa: E402
import venue_fill_confirm  # noqa: E402

ET = ZoneInfo("America/New_York")
INTERVAL_SEC = 90.0
SLUGS_PER_TICK = 8
STATE_PATH = RAW / "pm_settle_reconcile.json"
LOG = RAW / "pm_settle_reconcile.log"
PID_FILE = RAW / "pm_settle_reconcile.pid"
ORDERS = RAW / "orders.jsonl"
ONE = Decimal("1")
FOUR = Decimal("0.0001")


def _now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        value = value.get("value")
        if value is None or value == "":
            return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _money(value) -> str:
    number = _dec(value)
    if number is None:
        return ""
    return format(number.quantize(FOUR, rounding=ROUND_HALF_UP), "f")


def log(msg: str) -> None:
    line = f"{_now()} {msg}"
    print(line, flush=True)
    try:
        ensure_dirs()
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _jsonl(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def sent_qty(row: dict) -> Decimal:
    for key in ("confirm_qty", "tape_qty", "fill_qty", "qty"):
        number = _dec(row.get(key))
        if number is not None:
            return number
    return Decimal("0")


def is_missed_send(row: dict) -> bool:
    try:
        status = int(row.get("http_status") or 0)
    except (TypeError, ValueError):
        return False
    return status in {200, 201} and sent_qty(row) <= 0


def is_tiny_fill(row: dict) -> bool:
    qty = sent_qty(row)
    return Decimal("0") < qty < ONE


def load_sent_rows(path: Path | None = None) -> list[dict]:
    rows = []
    for row in _jsonl(path or ORDERS) or []:
        if str(row.get("event") or "") != "sent":
            continue
        if not str(row.get("order_id") or "").strip():
            continue
        rows.append(row)
    return rows


def candidate_reasons(row: dict, store: dict | None = None, watches=None) -> list[str]:
    reasons = []
    oid = str(row.get("order_id") or "").strip()
    qty = sent_qty(row)
    if is_missed_send(row):
        reasons.append("missed_send")
    if is_tiny_fill(row):
        reasons.append("tiny_fill")
    blob = store if store is not None else {}
    saved = blob.get(oid) if isinstance(blob.get(oid), dict) else {}
    booked = str(saved.get("status") or "").lower() in {"win", "lose", "void", "flatten"} or saved.get("flatten_pair")
    if qty > 0 and not saved:
        reasons.append("unreconciled")
    elif qty > 0 and not booked:
        if str(saved.get("result") or "").lower() not in settled_pnl_store.FINAL_RESULTS:
            reasons.append("unreconciled")
    game = str(row.get("game") or row.get("bet_key") or "")
    if watches:
        for match in watches:
            if not isinstance(match, dict):
                continue
            blob = " ".join(str(match.get(k) or "") for k in ("game", "key"))
            if game and game[:24].lower() not in blob.lower() and str(match.get("game") or "") not in game:
                if str(row.get("instrument") or "") not in str(match.get("t0_yes") or ""):
                    continue
            stage = str(match.get("stage") or "")
            if stage in {"waiting_t0", "t0_filled_waiting_50_cross", "waiting_cross", "waiting_fav_dip", "fav_gtc_resting", "one_leg_miss", "absorbed"}:
                reasons.append("open")
            if stage == "postponed" or match.get("postponed_reason"):
                reasons.append("postponed")
            break
    return list(dict.fromkeys(reasons))


def debit_hint(quote, limit) -> Decimal | None:
    """BUY_SHORT house debit: the cheaper of quote, limit, and their $1 complements."""
    found = []
    for raw in (quote, limit):
        px = _dec(raw)
        if px is None or px <= 0 or px >= ONE:
            continue
        found.append(px)
        found.append(ONE - px)
    ok = [px for px in found if Decimal("0") < px < ONE]
    return min(ok) if ok else _dec(quote) or _dec(limit)


def kalshi_statement_cash(*, trade_px, fee, limit=None, quote=None) -> tuple[Decimal | None, Decimal]:
    """Wire is the contract price. After-fee matches Kalshi all-in (19.04 = 18 + 1.04)."""
    px = _dec(trade_px)
    fee_n = _dec(fee) or Decimal("0")
    posted = _dec(limit) if _dec(limit) not in (None,) and (_dec(limit) or Decimal("0")) > 0 else _dec(quote)
    if px is None:
        return posted, fee_n
    if posted is not None and fee_n > 0 and abs(px - (posted + fee_n)) <= Decimal("0.0002"):
        return posted, fee_n
    return px, fee_n


def house_cash_from_venue(*, intent: str, trade_px, quote, limit, venue: str = "", fee=None) -> Decimal | None:
    if str(venue or "").lower() == "kalshi":
        cash, _fee = kalshi_statement_cash(trade_px=trade_px, fee=fee, limit=limit, quote=quote)
        return cash
    hint = debit_hint(quote, limit)
    return venue_fill_confirm.poly_house_cash(
        avg=trade_px,
        quote=hint,
        pay=hint,
        api_limit=limit,
        intent=str(intent or ""),
    ) or _dec(trade_px) or hint


def fills_by_order(trades: list[dict]) -> dict[str, dict]:
    """Sum execution TRADE rows per our order id. Partials are distinct fills, not cum snapshots."""
    out: dict[str, dict] = {}
    for row in trades or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("our_order_id") or row.get("aggressor_id") or row.get("order_id") or "").strip()
        if not oid:
            continue
        qty = _dec(row.get("qty")) or Decimal("0")
        px = _dec(row.get("price"))
        cur = out.setdefault(
            oid,
            {"qty": Decimal("0"), "price": None, "intent": "", "side": "", "fee": None, "n": 0},
        )
        cur["qty"] += qty
        if px is not None:
            cur["price"] = px
        cur["intent"] = str(row.get("intent") or cur["intent"])
        cur["side"] = str(row.get("side") or cur["side"])
        fee = _dec(row.get("fee"))
        if fee is not None:
            cur["fee"] = (cur["fee"] or Decimal("0")) + fee
        cur["n"] += 1
    return out


def never_won_if_unfilled(qty) -> bool:
    number = _dec(qty) or Decimal("0")
    return number <= 0


def _kalshi_trade_row(fill: dict) -> dict:
    side = str(fill.get("outcome_side") or fill.get("side") or "").lower()
    yes_px = _dec(fill.get("yes_price_dollars"))
    no_px = _dec(fill.get("no_price_dollars"))
    if side == "no":
        px = no_px if no_px is not None else ((ONE - yes_px) if yes_px is not None else None)
    else:
        px = yes_px if yes_px is not None else no_px
    qty = _dec(fill.get("count_fp") if fill.get("count_fp") not in (None, "") else fill.get("count"))
    fee = _dec(fill.get("fee_cost") if fill.get("fee_cost") not in (None, "") else fill.get("fee"))
    return {
        "our_order_id": str(fill.get("order_id") or "").strip(),
        "qty": qty,
        "price": px,
        "fee": fee,
        "side": side,
        "action": str(fill.get("action") or "").lower(),
        "intent": "",
        "slug": str(fill.get("ticker") or fill.get("market_ticker") or ""),
        "ticker": str(fill.get("ticker") or fill.get("market_ticker") or ""),
        "venue": "kalshi",
    }


def fetch_kalshi_fills(ticker: str, pages: int = 4) -> list[dict]:
    """GET fills for this ticker. No short min_ts — post-settlement hours later is the point."""
    import kalshi_private

    rows = []
    cursor = ""
    ident = str(ticker or "").strip()
    if not ident:
        return rows
    for _ in range(pages):
        query = {"limit": "100", "ticker": ident}
        if cursor:
            query["cursor"] = cursor
        status, text = kalshi_private.get_fills(query, timeout=20)
        if status != 200:
            break
        data = json.loads(text) if text else {}
        batch = data.get("fills") if isinstance(data, dict) else []
        if not isinstance(batch, list):
            break
        for item in batch:
            if isinstance(item, dict):
                rows.append(_kalshi_trade_row(item))
        cursor = str((data or {}).get("cursor") or "")
        if not cursor or not batch:
            break
    return rows


def fetch_gemini_fills(*, days: int = 7) -> list[dict]:
    try:
        import gemini_private
    except Exception:
        return []
    end = datetime.now(ET)
    start = end.timestamp() - (days * 86400)
    extra = {
        "status": "filled",
        "from": int(start * 1000),
        "to": int(end.timestamp() * 1000) + 5000,
        "limit": 200,
    }
    try:
        status, text = gemini_private.get_order_history(extra, timeout=20)
    except Exception:
        return []
    if status != 200:
        return []
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return []
    orders = data.get("orders") if isinstance(data, dict) else data
    if not isinstance(orders, list):
        return []
    rows = []
    for item in orders:
        if not isinstance(item, dict):
            continue
        rows.append({
            "our_order_id": str(item.get("order_id") or item.get("orderId") or "").strip(),
            "qty": item.get("qty") or item.get("quantity") or item.get("filled_qty"),
            "price": item.get("avg_price") or item.get("price"),
            "fee": item.get("fee"),
            "side": str(item.get("side") or "").lower(),
            "slug": str(item.get("symbol") or item.get("ticker") or ""),
            "venue": "gemini",
        })
    return rows


def fetch_novig_fills() -> list[dict]:
    try:
        import novig_live
    except Exception:
        return []
    try:
        status, text = novig_live.list_fills({"limit": "100"}, timeout=20)
    except Exception:
        return []
    if status != 200:
        return []
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return []
    batch = data.get("fills") if isinstance(data, dict) else data
    if not isinstance(batch, list):
        return []
    rows = []
    for item in batch:
        if not isinstance(item, dict):
            continue
        rows.append({
            "our_order_id": str(item.get("orderId") or item.get("order_id") or "").strip(),
            "qty": item.get("qty") or item.get("quantity") or item.get("size"),
            "price": item.get("price") or item.get("avgPrice"),
            "fee": item.get("fee"),
            "side": str(item.get("side") or item.get("outcome") or "").lower(),
            "slug": str(item.get("marketId") or item.get("instrument") or ""),
            "venue": "novig",
        })
    return rows


def is_venue_flatten(sents: list[dict], fills: list[dict]) -> bool:
    if any(str(row.get("step") or "").lower() in {"flatten", "extra-flatten"} for row in sents or []):
        return True
    actions = {str(row.get("action") or "").lower() for row in fills or []}
    return "buy" in actions and "sell" in actions


def flatten_groups(sent_rows: list[dict], fills: dict[str, dict]) -> list[list[dict]]:
    """Pair a kitchen flatten close with its origin on the same bet/ticker. Not a held Yes+No lock."""
    by_key: dict[tuple[str, str, str], list[dict]] = {}
    for sent in sent_rows or []:
        oid = str(sent.get("order_id") or "").strip()
        fill = fills.get(oid) if oid else None
        qty = (_dec(fill.get("qty")) if fill else None) or sent_qty(sent)
        if qty is None or qty <= 0:
            continue
        venue = str(sent.get("venue") or (fill or {}).get("venue") or "").lower()
        ident = str(sent.get("instrument") or (fill or {}).get("ticker") or (fill or {}).get("slug") or "")
        if not venue or not ident:
            continue
        side = str(sent.get("side") or (fill or {}).get("side") or "").lower()
        bet = str(sent.get("bet_key") or sent.get("game") or ident)
        by_key.setdefault((venue, ident.lower(), bet), []).append(
            {"sent": sent, "fill": fill or {}, "qty": qty, "side": side}
        )
    groups = []
    for (_venue, _ident, _bet), legs in by_key.items():
        closes = [
            leg
            for leg in legs
            if str(leg["sent"].get("step") or "").lower() in {"flatten", "extra-flatten"}
        ]
        if not closes:
            continue
        origins = [
            leg
            for leg in legs
            if str(leg["sent"].get("step") or "").lower() not in {"flatten", "extra-flatten"}
        ]
        for close in closes:
            close_side = str(close.get("side") or "").lower()
            want = "no" if close_side == "yes" else "yes"
            origin = next((leg for leg in origins if str(leg.get("side") or "").lower() == want), None)
            if origin is None:
                continue
            pair = [origin, close]
            if not is_venue_flatten([origin["sent"], close["sent"]], [origin.get("fill") or {}, close.get("fill") or {}]):
                continue
            groups.append(pair)
    return groups


def apply_flatten_group(legs: list[dict], store: dict) -> list[dict]:
    """Overwrite kitchen to venue flatten net. Poly fill 0 is not in the group."""
    book = []
    for leg in legs:
        sent = leg["sent"]
        fill = leg["fill"] or {}
        venue = str(sent.get("venue") or "kalshi")
        intent = str(fill.get("intent") or sent.get("io_intent") or "")
        cash = house_cash_from_venue(
            intent=intent,
            trade_px=fill.get("price"),
            quote=sent.get("quote_price") or sent.get("house_cash") or sent.get("wire"),
            limit=sent.get("limit_price"),
            venue=venue,
            fee=fill.get("fee") if fill.get("fee") is not None else sent.get("fee"),
        )
        fee = _dec(fill.get("fee"))
        if fee is None:
            fee = _dec(sent.get("fee"))
        if fee is None:
            fee = Decimal("0")
        if venue == "kalshi":
            cash, fee = kalshi_statement_cash(
                trade_px=cash,
                fee=fee,
                limit=sent.get("limit_price") if str(sent.get("side") or "").lower() == "yes" else None,
                quote=sent.get("quote_price") or cash,
            )
        book.append({
            "order_id": str(sent.get("order_id") or ""),
            "venue": venue,
            "instrument": str(sent.get("instrument") or ""),
            "side": str(leg.get("side") or sent.get("side") or ""),
            "qty": str(leg.get("qty") or fill.get("qty") or "1"),
            "cash": cash,
            "fee": fee,
            "step": str(sent.get("step") or ""),
            "game": str(sent.get("game") or ""),
            "io_intent": intent,
        })
    net = settled_pnl_store.upsert_flatten_pair(
        book,
        source="pm_settle_reconcile",
        store=store,
        game=str((legs[0]["sent"] if legs else {}).get("game") or ""),
    )
    patches = []
    for row in book:
        oid = str(row.get("order_id") or "")
        saved = store.get(oid) or {}
        patches.append({
            "order_id": oid,
            "instrument": row.get("instrument"),
            "game": row.get("game"),
            "kitchen_qty": _money(row.get("qty")),
            "venue_qty": _money(row.get("qty")),
            "action": "flatten_settled",
            "status": saved.get("status"),
            "pnl": saved.get("pnl"),
            "cash": saved.get("wire"),
            "fee": saved.get("fee"),
            "after_fee": saved.get("after_fee"),
            "flatten_net": saved.get("flatten_net") or _money(net),
            "note": "venue flatten net; not two directional settles",
        })
    return patches


def apply_row(
    sent: dict,
    *,
    venue_fill: dict | None,
    market: dict | None,
    store: dict,
) -> dict:
    """Patch one kitchen send to venue qty/cash/settle. Never stamps confirm-0 as a win."""
    oid = str(sent.get("order_id") or "").strip()
    fill = venue_fill if isinstance(venue_fill, dict) else {}
    qty = _dec(fill.get("qty"))
    if qty is None:
        qty = Decimal("0")
    action = {
        "order_id": oid,
        "instrument": str(sent.get("instrument") or ""),
        "game": str(sent.get("game") or sent.get("side_label") or ""),
        "kitchen_qty": _money(sent_qty(sent)),
        "venue_qty": _money(qty),
        "action": "",
    }
    prev = store.get(oid) if isinstance(store.get(oid), dict) else {}
    if never_won_if_unfilled(qty):
        if prev and str(prev.get("status") or "").lower() in {"win", "lose"}:
            store.pop(oid, None)
            action["action"] = "clear_false_win"
            action["note"] = "confirm 0 is not a won ticket"
            return action
        action["action"] = "missed_send"
        action["note"] = "venue has no fill; keep missed send"
        return action
    if prev.get("flatten_pair"):
        action["action"] = "keep_flatten"
        action["pnl"] = prev.get("pnl")
        action["note"] = "flatten net already booked; skip directional settle"
        return action
    if qty >= 1:
        house = "house"
    else:
        house = "tiny"
    intent = str(fill.get("intent") or sent.get("io_intent") or "")
    if not intent:
        side = str(sent.get("side") or "").lower()
        intent = "ORDER_INTENT_BUY_SHORT" if side in {"no", "short"} else "ORDER_INTENT_BUY_LONG"
    venue = str(sent.get("venue") or fill.get("venue") or "polymarket")
    cash = house_cash_from_venue(
        intent=intent,
        trade_px=fill.get("price"),
        quote=sent.get("quote_price"),
        limit=sent.get("limit_price"),
        venue=venue,
        fee=fill.get("fee"),
    )
    side = str(sent.get("side") or "").lower()
    fee = _dec(fill.get("fee"))
    if fee is None:
        fee = _dec(sent.get("fee"))
    if fee is None:
        fee = settled_pnl_store.documented_fee(
            {
                "venue": str(sent.get("venue") or "polymarket"),
                "side": side,
                "cash": cash,
                "io_intent": intent,
                "fee_coefficient": sent.get("fee_coefficient"),
            }
        )
    if fee is None:
        fee = Decimal("0")
    if "SHORT" in intent.upper() or str(fill.get("side") or "").upper() in {"ORDER_SIDE_SELL", "OUTCOME_SIDE_NO"}:
        side = "no"
    elif "LONG" in intent.upper():
        side = side or "yes"
    result = settled_pnl_store.result_from_market(market or {})
    px = (market or {}).get("settlementPx") or (market or {}).get("settlementPrice")
    leg = {
        "order_id": oid,
        "venue": venue,
        "instrument": str(sent.get("instrument") or ""),
        "side": side,
        "qty": str(qty),
        "cash": cash,
        "fee": fee,
        "io_intent": intent,
        "settlementPx": px,
        "game": str(sent.get("game") or ""),
    }
    if result in settled_pnl_store.FINAL_RESULTS:
        settled_pnl_store.upsert_leg(
            leg,
            result=result,
            source="pm_settle_reconcile",
            store=store,
            game=str(sent.get("game") or ""),
        )
        row = store.get(oid) or {}
        action["action"] = "settled"
        action["status"] = row.get("status")
        action["pnl"] = row.get("pnl")
        action["cash"] = row.get("wire")
        action["house"] = house
        return action
    store[oid] = {
        "order_id": oid,
        "venue": leg["venue"],
        "instrument": leg["instrument"],
        "side": side,
        "game": leg["game"],
        "qty": _money(qty),
        "wire": _money(cash),
        "fee": _money(fee),
        "status": "open",
        "source": "pm_settle_reconcile",
        "house_cash": _money(cash),
    }
    action["action"] = "qty_updated"
    action["house"] = house
    action["cash"] = _money(cash)
    action["note"] = "venue fill kept; market not binary-settled yet"
    return action


def reconcile_rows(
    sent_rows: list[dict],
    *,
    trades: list[dict],
    markets: dict[str, dict],
    store: dict,
    watches=None,
    fetched_slugs=None,
) -> dict:
    fills = fills_by_order(trades)
    fetched = {str(s or "").strip().lower() for s in (fetched_slugs or []) if str(s or "").strip()}
    for row in trades or []:
        slug = str((row or {}).get("slug") or (row or {}).get("ticker") or "").strip().lower()
        if slug:
            fetched.add(slug)
    for sent in sent_rows or []:
        oid = str(sent.get("order_id") or "")
        if oid in fills:
            fetched.add(str(sent.get("instrument") or "").strip().lower())
    patches = []
    scanned = []
    flatten_oids: set[str] = set()
    for group in flatten_groups(sent_rows, fills):
        for patch in apply_flatten_group(group, store):
            oid = str(patch.get("order_id") or "")
            flatten_oids.add(oid)
            patch["reasons"] = ["flatten_pair"]
            patches.append(patch)
            scanned.append({"order_id": oid, "reasons": ["flatten_pair"]})
    batch_oids = {str(row.get("order_id") or "") for row in (sent_rows or [])}
    for oid, row in list(store.items()):
        if not isinstance(row, dict) or not row.get("flatten_pair"):
            continue
        if oid in flatten_oids or oid not in batch_oids:
            continue
        store.pop(oid, None)
    for sent in sent_rows or []:
        oid = str(sent.get("order_id") or "")
        if oid in flatten_oids:
            continue
        reasons = candidate_reasons(sent, store, watches)
        slug = str(sent.get("instrument") or "")
        if not reasons and oid not in fills:
            continue
        if not reasons and oid in fills:
            reasons = ["venue_fill"]
        scanned.append({"order_id": oid, "reasons": reasons})
        market = markets.get(slug.lower()) or markets.get(slug) or {}
        slug_fetched = slug.lower() in fetched
        fill = fills.get(oid)
        if fill is None and not slug_fetched:
            continue
        patch = apply_row(
            sent,
            venue_fill=fill if fill is not None else {"qty": "0"},
            market=market,
            store=store,
        )
        patch["reasons"] = reasons
        patches.append(patch)
    changed = [
        row
        for row in patches
        if row.get("action") in {"settled", "qty_updated", "clear_false_win", "flatten_settled"}
    ]
    return {
        "n_sent": len(sent_rows or []),
        "n_scanned": len(scanned),
        "n_changed": len(changed),
        "patches": patches,
        "changed": changed,
        "scanned": scanned,
    }


def _poly_trade_row(item: dict) -> dict:
    trade = item.get("trade") if isinstance(item.get("trade"), dict) else item
    if not isinstance(trade, dict):
        trade = {}
    aggressor = trade.get("aggressor") if isinstance(trade.get("aggressor"), dict) else {}
    return {
        "our_order_id": venue_fill_confirm._poly_our_order_id(item) if isinstance(item, dict) else "",
        "aggressor_id": str(aggressor.get("id") or ""),
        "intent": str(aggressor.get("intent") or trade.get("intent") or ""),
        "side": str(aggressor.get("side") or trade.get("side") or ""),
        "price": trade.get("price") or aggressor.get("price"),
        "qty": trade.get("qtyDecimal") if trade.get("qtyDecimal") not in (None, "") else trade.get("qty"),
        "fee": trade.get("fee"),
        "slug": str(trade.get("marketSlug") or ""),
        "state": str(aggressor.get("state") or trade.get("state") or ""),
    }


def fetch_poly_trades(slug: str, pages: int = 4) -> list[dict]:
    import polymarket_us_live

    rows = []
    cursor = ""
    for _ in range(pages):
        query = {
            "limit": "100",
            "types": "ACTIVITY_TYPE_TRADE",
            "sortOrder": "SORT_ORDER_DESCENDING",
            "marketSlug": slug,
        }
        if cursor:
            query["cursor"] = cursor
        status, text = polymarket_us_live.get_activities(query, timeout=20)
        if status != 200:
            break
        data = json.loads(text) if text else {}
        batch = data.get("activities") if isinstance(data, dict) else []
        if not isinstance(batch, list):
            break
        for item in batch:
            if isinstance(item, dict):
                rows.append(_poly_trade_row(item))
        cursor = str((data or {}).get("nextCursor") or "")
        if bool((data or {}).get("eof")) or not cursor or not batch:
            break
    return rows


def fetch_markets_for(idents: list[tuple[str, str]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for venue, ident in idents:
        info = settled_pnl_store.fetch_market_result(venue, ident)
        if info:
            out[ident] = info
            out[ident.lower()] = info
    return out


def _watch_matches() -> list[dict]:
    rows = []
    try:
        import open_count_sync

        for sid in open_count_sync.WATCH:
            status = open_count_sync.load_watch(sid) or {}
            for match in status.get("matches") or []:
                if isinstance(match, dict):
                    rows.append(match)
    except Exception:
        pass
    return rows


def _ident_of(row: dict) -> tuple[str, str]:
    venue = str(row.get("venue") or "").lower()
    ident = str(row.get("instrument") or "").strip()
    return venue, ident


def pick_idents(sent_rows: list[dict], store: dict, watches=None) -> list[tuple[str, str]]:
    """Recent unreconciled / flatten / missed-send first, then older Poly leftover."""
    ranked = []
    for row in sent_rows or []:
        reasons = candidate_reasons(row, store, watches)
        venue, ident = _ident_of(row)
        if not ident:
            continue
        if not reasons:
            continue
        sent_at = str(row.get("sent_at") or row.get("at") or "")
        recent = 0 if sent_at >= "2026-10-29" else 1
        flatten = 0 if str(row.get("step") or "") in {"flatten", "extra-flatten"} or "flatten" in reasons else 1
        tiny = 0 if is_tiny_fill(row) else 1
        ranked.append((recent, flatten, tiny, sent_at, venue, ident))
    ranked.sort()
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    extra = 0
    for recent, _flatten, _tiny, _at, venue, ident in ranked:
        key = (venue, ident.lower())
        if key in seen:
            continue
        if recent != 0:
            extra += 1
            if extra > SLUGS_PER_TICK:
                continue
        seen.add(key)
        out.append((venue, ident))
    return out


def warn_same_direction_kalshi(rows: list[dict]) -> list[dict]:
    """Loud log for Yes-A + No-B complementary Kalshi stacks (GIMPEN class). Fail-soft."""
    try:
        import kalshi_same_direction as ksd
    except Exception as exc:
        log(f"same-direction import {type(exc).__name__}")
        return []
    try:
        stacks = ksd.find_same_direction_stacks(rows)
    except Exception as exc:
        log(f"same-direction scan {type(exc).__name__}")
        return []
    seen: set[str] = set()
    unique: list[dict] = []
    for row in stacks:
        event = str(row.get("event") or "")
        if not event or event in seen:
            continue
        seen.add(event)
        unique.append(row)
        log(f"DANGER {row.get('reason')}")
    if unique:
        log(
            f"DANGER same-direction count={len(unique)} — run "
            "run_pm_venue_kitchen_check.bat (all platforms); send gate is kalshi_same_direction"
        )
    return unique


def reconcile_once(*, persist: bool = True, fetch: bool = True) -> dict:
    """One pass. Read-only REST. Updates settled_pnl.json. Does not trade."""
    ensure_dirs()
    sent = load_sent_rows()
    store = settled_pnl_store.load()
    watches = _watch_matches()
    idents = pick_idents(sent, store, watches)
    slugs = [ident for venue, ident in idents if venue == "polymarket"]
    tickers = [ident for venue, ident in idents if venue == "kalshi"]
    need_gemini = any(venue == "gemini" for venue, _ident in idents)
    need_novig = any(venue == "novig" for venue, _ident in idents)
    trades: list[dict] = []
    markets: dict[str, dict] = {}
    if fetch:
        for slug in slugs:
            try:
                trades.extend(fetch_poly_trades(slug))
            except Exception as exc:
                log(f"poly trades {slug} {type(exc).__name__}")
        for ticker in tickers:
            try:
                trades.extend(fetch_kalshi_fills(ticker))
            except Exception as exc:
                log(f"kalshi fills {ticker} {type(exc).__name__}")
        if need_gemini:
            try:
                trades.extend(fetch_gemini_fills())
            except Exception as exc:
                log(f"gemini fills {type(exc).__name__}")
        if need_novig:
            try:
                trades.extend(fetch_novig_fills())
            except Exception as exc:
                log(f"novig fills {type(exc).__name__}")
        try:
            markets = fetch_markets_for(idents)
        except Exception as exc:
            log(f"markets {type(exc).__name__}")
    for row in store.values():
        if not isinstance(row, dict):
            continue
        inst = str(row.get("instrument") or "")
        if not inst or inst in markets or inst.lower() in markets:
            continue
        info = {
            "venue": row.get("venue") or "",
            "settlementPx": row.get("settlementPx"),
            "result": row.get("result"),
        }
        if settled_pnl_store.result_from_market(info):
            markets[inst] = info
            markets[inst.lower()] = info
    ident_set = {ident.lower() for _venue, ident in idents}
    report = reconcile_rows(
        [row for row in sent if str(row.get("instrument") or "").lower() in ident_set],
        trades=trades,
        markets=markets,
        store=store,
        watches=watches,
        fetched_slugs=[ident for _venue, ident in idents],
    )
    # Venue → tape: bank settlements the kitchen never booked (both_unfilled ghosts).
    miss = {"added": 0, "skipped": 0, "same_direction_n": 0}
    if fetch:
        try:
            import pm_venue_miss_ingest

            sett_rows: list[dict] = []
            # Prefer settlements already on disk from dump_kalshi_recon / pm dump.
            for path_name in (
                "kalshi_recon_dump/kalshi_recon_dump_latest.json",
                "pm_recon_dump/pm_recon_dump_latest.json",
            ):
                path = RAW / path_name
                if not path.is_file():
                    continue
                try:
                    blob = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if path_name.startswith("pm_"):
                    block = ((blob.get("venues") or {}).get("kalshi") or {})
                else:
                    block = blob
                batch = (block.get("settlements") or {}).get("settlements") or []
                if isinstance(batch, list):
                    sett_rows.extend(r for r in batch if isinstance(r, dict))
                if sett_rows:
                    break
            if sett_rows:
                before = len(store)
                miss = pm_venue_miss_ingest.ingest_kalshi_settlements(
                    store,
                    sett_rows,
                    fills=[t for t in trades if str(t.get("venue") or "").lower() == "kalshi"],
                    persist=False,
                )
                if len(store) > before or miss.get("added"):
                    report["n_changed"] = int(report.get("n_changed") or 0) + int(miss.get("added") or 0)
                    report["venue_miss_ingest"] = miss
                    log(
                        f"venue→tape miss ingest added={miss.get('added')} "
                        f"skipped={miss.get('skipped')} same_dir={miss.get('same_direction_n')}"
                    )
        except Exception as exc:
            log(f"venue miss ingest {type(exc).__name__}")
    if persist and report.get("n_changed"):
        settled_pnl_store.save(store)
        try:
            import orders_performance_refresh

            orders_performance_refresh.schedule_rebuild("pm_settle_reconcile")
        except Exception:
            pass
    state = {
        "written_at": _now(),
        "n_slugs": len(idents),
        "slugs": slugs,
        "kalshi": tickers,
        "n_changed": report.get("n_changed"),
        "changed": report.get("changed"),
    }
    # Open + tape Kalshi legs: catch Yes-A/No-B doubles even when kitchen missed them.
    scan_rows: list[dict] = []
    for venue, ident in idents:
        if venue == "kalshi":
            scan_rows.append({"venue": "kalshi", "instrument": ident, "ticker": ident})
    for row in sent:
        if str(row.get("venue") or "").lower() == "kalshi":
            scan_rows.append(row)
    for row in trades:
        if str(row.get("venue") or "").lower() == "kalshi":
            scan_rows.append(row)
    for row in store.values():
        if isinstance(row, dict) and str(row.get("venue") or "").lower() == "kalshi":
            scan_rows.append(row)
    stacks = warn_same_direction_kalshi(scan_rows)
    report["same_direction_stacks"] = stacks
    state["same_direction_n"] = len(stacks)
    if persist:
        STATE_PATH.write_text(json.dumps(state, indent=2, default=str) + "\n", encoding="utf-8")
    log(
        f"reconcile idents={len(idents)} poly={len(slugs)} kalshi={len(tickers)} "
        f"scanned={report.get('n_scanned')} changed={report.get('n_changed')} "
        f"same_direction={len(stacks)}"
    )
    return report


def loop() -> None:
    ensure_dirs()
    PID_FILE.write_text(json.dumps({"pid": os.getpid(), "started_at": _now()}), encoding="utf-8")
    log(f"pm settle reconcile start pid {os.getpid()} interval={INTERVAL_SEC:.0f}s")
    while True:
        try:
            reconcile_once()
        except KeyboardInterrupt:
            log("interrupted; continuing")
        except Exception as exc:
            log(f"loop {type(exc).__name__}")
        time.sleep(INTERVAL_SEC)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--once" in args:
        report = reconcile_once()
        print(json.dumps({"n_changed": report.get("n_changed"), "changed": report.get("changed")}, default=str))
        return 0
    loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
