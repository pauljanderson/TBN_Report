"""Read-only Oct 18-22 2026 ET fill-history pull. Does not place, cancel, or sell.

Calls only documented endpoints through existing venue auth helpers.
Saves amounts/tickers/sides/prices/qty/times. Redacts keys. No secrets printed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import gemini_private  # noqa: E402
import kalshi_private  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402
from order_ledger import ORDERS, ORDER_IO, _io_instrument, _load_jsonl, _order_id_of, polymarket_fill  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402
import live_lock_orders  # noqa: E402

ET = ZoneInfo("America/New_York")
WINDOW_START = datetime(2026, 10, 18, 0, 0, tzinfo=ET)
WINDOW_END = datetime(2026, 10, 23, 0, 0, tzinfo=ET)
OUT = RAW / "_venue_fill_history_pull_20261022.json"
MAX_PAGES = 40
ONE = Decimal("1")
SECRET_NEEDLES = (
    "api_key",
    "apikey",
    "secret",
    "signature",
    "passphrase",
    "private_key",
    "authorization",
    "access_key",
    "token",
)


def parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        raw = int(text)
        if raw > 10**12:
            stamp = datetime.fromtimestamp(raw / 1000, tz=ET)
        else:
            stamp = datetime.fromtimestamp(raw, tz=ET)
        return stamp.astimezone(ET)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def in_window(stamp):
    return stamp is not None and WINDOW_START <= stamp < WINDOW_END


def ddec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def qty_ge_1(qty) -> bool:
    number = ddec(qty)
    return number is not None and number >= 1


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            lowered = str(key).lower().replace("-", "_")
            if any(needle in lowered for needle in SECRET_NEEDLES):
                out[key] = "[redacted]"
            else:
                out[key] = redact(value)
        return out
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    return obj


def amount_value(node):
    if isinstance(node, dict):
        return node.get("value")
    return node


def kalshi_row(fill: dict) -> dict:
    yes_px = ddec(fill.get("yes_price_dollars"))
    no_px = ddec(fill.get("no_price_dollars"))
    outcome = str(fill.get("outcome_side") or fill.get("side") or "").lower()
    action = str(fill.get("action") or "").lower()
    book = str(fill.get("book_side") or "").lower()
    house_cash = no_px if outcome == "no" else yes_px
    if house_cash is None and yes_px is not None and outcome == "no":
        house_cash = ONE - yes_px
    qty = fill.get("count_fp") or fill.get("count")
    stamp = parse_dt(fill.get("created_time")) or parse_dt(fill.get("ts"))
    return {
        "venue": "kalshi",
        "time_et": stamp.strftime("%Y-%m-%d %H:%M:%S ET") if stamp else "",
        "ticker": fill.get("ticker") or fill.get("market_ticker") or "",
        "side": outcome or action or book,
        "book_side": book,
        "qty": str(qty) if qty is not None else "",
        "house_fill": qty_ge_1(qty),
        "yes_wire": str(yes_px) if yes_px is not None else "",
        "no_price": str(no_px) if no_px is not None else "",
        "house_cash": str(house_cash) if house_cash is not None else "",
        "order_id": fill.get("order_id") or "",
        "fill_id": fill.get("fill_id") or fill.get("trade_id") or "",
        "second_yes_ticket": False,
    }


def gemini_row(order: dict) -> dict:
    qty = order.get("filledQuantity") or order.get("filled_quantity")
    stamp = parse_dt(order.get("updatedAt") or order.get("createdAt"))
    meta = order.get("contractMetadata") if isinstance(order.get("contractMetadata"), dict) else {}
    return {
        "venue": "gemini",
        "time_et": stamp.strftime("%Y-%m-%d %H:%M:%S ET") if stamp else "",
        "ticker": order.get("symbol") or "",
        "side": str(order.get("side") or ""),
        "outcome": str(order.get("outcome") or ""),
        "qty": str(qty) if qty is not None else "",
        "house_fill": qty_ge_1(qty) and str(order.get("status") or "").lower() == "filled",
        "price": str(order.get("avgExecutionPrice") or order.get("price") or ""),
        "limit": str(order.get("price") or ""),
        "status": str(order.get("status") or ""),
        "order_id": str(order.get("orderId") or order.get("clientOrderId") or ""),
        "event": meta.get("eventName") or meta.get("eventTicker") or "",
        "resolution": meta.get("resolutionSide") or "",
    }


def poly_row(activity: dict) -> dict:
    trade = activity.get("trade") if isinstance(activity.get("trade"), dict) else {}
    qty = trade.get("qtyDecimal") or trade.get("qty")
    stamp = parse_dt(trade.get("createTime") or trade.get("updateTime"))
    price = amount_value(trade.get("price"))
    cost = amount_value(trade.get("costBasis"))
    return {
        "venue": "polymarket",
        "time_et": stamp.strftime("%Y-%m-%d %H:%M:%S ET") if stamp else "",
        "ticker": trade.get("marketSlug") or "",
        "type": str(activity.get("type") or ""),
        "side": "",
        "qty": str(qty) if qty is not None else "",
        "house_fill": qty_ge_1(qty),
        "price": str(price) if price is not None else "",
        "cost": str(cost) if cost is not None else "",
        "aggressor": trade.get("isAggressor"),
        "state": str(trade.get("state") or ""),
        "trade_id": str(trade.get("id") or ""),
        "title": "",
    }


def novig_row(fill: dict) -> dict:
    qty = fill.get("qty")
    cost = ddec(fill.get("cost"))
    qty_n = ddec(qty)
    price = None
    if cost is not None and qty_n not in (None, Decimal("0")):
        # Docs: price = 100 * cost / qty (native 1-cent contracts).
        price = (Decimal("100") * cost) / qty_n
    stamp = parse_dt(fill.get("ts"))
    return {
        "venue": "novig",
        "time_et": stamp.strftime("%Y-%m-%d %H:%M:%S ET") if stamp else "",
        "ticker": str(fill.get("marketId") or ""),
        "outcome_id": str(fill.get("outcomeId") or ""),
        "qty": str(qty) if qty is not None else "",
        "house_fill": qty_ge_1(qty),
        "cost": str(cost) if cost is not None else "",
        "price": str(price) if price is not None else "",
        "fee": str(fill.get("fee") or ""),
        "order_id": str(fill.get("orderId") or ""),
        "fill_id": str(fill.get("fillId") or ""),
        "taker": fill.get("taker"),
    }


def pull_kalshi() -> dict:
    fills = []
    pages = []
    cursor = ""
    query_base = {
        "min_ts": str(int(WINDOW_START.timestamp())),
        "max_ts": str(int(WINDOW_END.timestamp())),
        "limit": "1000",
    }
    try:
        for _ in range(MAX_PAGES):
            query = dict(query_base)
            if cursor:
                query["cursor"] = cursor
            status, text = kalshi_private.get_fills(query)
            page = {"http": status, "bytes": len(text or "")}
            if status != 200:
                pages.append(page | {"error": "http"})
                break
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                pages.append(page | {"error": "not_json"})
                break
            batch = data.get("fills") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                pages.append(page | {"error": "shape"})
                break
            rows = [kalshi_row(item) for item in batch if isinstance(item, dict)]
            fills.extend(rows)
            cursor = str((data or {}).get("cursor") or "")
            pages.append(page | {"n": len(rows), "cursor_next": bool(cursor)})
            if not cursor or not batch:
                break
        called = True
        note = ""
    except FileNotFoundError:
        called = False
        note = "FileNotFoundError"
        pages.append({"http": 0, "error": "missing_secrets"})
    except Exception as exc:
        called = False
        note = type(exc).__name__
        pages.append({"http": 0, "error": type(exc).__name__})
    house = [row for row in fills if row.get("house_fill")]
    return {
        "called": called,
        "endpoint": "GET /trade-api/v2/portfolio/fills",
        "doc": "https://docs.kalshi.com/api-reference/portfolio/get-fills",
        "http_pages": pages,
        "n": len(fills),
        "n_house": len(house),
        "note": note,
        "fills": house,
        "all_rows": fills,
    }


def pull_gemini() -> dict:
    extra = {
        "status": "filled",
        "from": int(WINDOW_START.timestamp() * 1000),
        "to": int(WINDOW_END.timestamp() * 1000),
        "limit": 1000,
    }
    try:
        status, text = gemini_private.get_order_history(extra)
        called = True
        note = ""
    except Exception as exc:
        return {
            "called": False,
            "endpoint": "POST /v1/prediction-markets/orders/history",
            "doc": "https://developer.gemini.com/rest-api/prediction-markets/order-management/get-order-history",
            "http_pages": [{"http": 0, "error": type(exc).__name__}],
            "n": 0,
            "n_house": 0,
            "note": type(exc).__name__,
            "fills": [],
            "all_rows": [],
        }
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {}
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        orders = []
    rows = [gemini_row(item) for item in orders if isinstance(item, dict)]
    house = [row for row in rows if row.get("house_fill")]
    return {
        "called": called,
        "endpoint": "POST /v1/prediction-markets/orders/history",
        "doc": "https://developer.gemini.com/rest-api/prediction-markets/order-management/get-order-history",
        "http_pages": [{"http": status, "n": len(rows), "bytes": len(text or "")}],
        "n": len(rows),
        "n_house": len(house),
        "note": note,
        "fills": house,
        "all_rows": rows,
    }


def pull_polymarket() -> dict:
    fills = []
    pages = []
    cursor = ""
    try:
        for _ in range(MAX_PAGES):
            query = {
                "limit": "100",
                "types": "ACTIVITY_TYPE_TRADE",
                "sortOrder": "SORT_ORDER_DESCENDING",
            }
            if cursor:
                query["cursor"] = cursor
            status, text = polymarket_us_live.get_activities(query)
            page = {"http": status, "bytes": len(text or "")}
            if status != 200:
                pages.append(page | {"error": "http"})
                break
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                pages.append(page | {"error": "not_json"})
                break
            batch = data.get("activities") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                pages.append(page | {"error": "shape"})
                break
            stop = False
            kept = 0
            for item in batch:
                if not isinstance(item, dict):
                    continue
                trade = item.get("trade") if isinstance(item.get("trade"), dict) else {}
                stamp = parse_dt(trade.get("createTime") or trade.get("updateTime"))
                if stamp is not None and stamp < WINDOW_START:
                    stop = True
                    continue
                if stamp is not None and stamp >= WINDOW_END:
                    continue
                if stamp is None and not in_window(stamp):
                    # Keep undated trades from this page; they may still be in-window.
                    pass
                row = poly_row(item)
                fills.append(row)
                kept += 1
            cursor = str((data or {}).get("nextCursor") or "")
            eof = bool((data or {}).get("eof"))
            pages.append(page | {"n": kept, "eof": eof, "cursor_next": bool(cursor)})
            if eof or not cursor or stop or not batch:
                break
        called = True
        note = ""
    except Exception as exc:
        called = False
        note = type(exc).__name__
        pages.append({"http": 0, "error": type(exc).__name__})
    house = [row for row in fills if row.get("house_fill")]
    return {
        "called": called,
        "endpoint": "GET /v1/portfolio/activities",
        "doc": "https://docs.polymarket.us/api-reference/portfolio/get-activities",
        "host": "https://api.polymarket.us",
        "http_pages": pages,
        "n": len(fills),
        "n_house": len(house),
        "note": note,
        "fills": house,
        "all_rows": fills,
        "skipped_hosts": [
            "https://clob.polymarket.com (global CLOB, different product)",
            "https://api.prod.polymarketexchange.com (institutional Report API, Bearer JWT, different host)",
        ],
    }


def _novig_items(payload):
    if not isinstance(payload, dict):
        return [], ""
    if isinstance(payload.get("items"), list):
        return payload.get("items"), str(payload.get("next") or "")
    items = []
    next_cursor = ""
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            items.extend(row for row in value["items"] if isinstance(row, dict))
            next_cursor = str(value.get("next") or next_cursor)
    return items, next_cursor


def pull_novig() -> dict:
    fills = []
    pages = []
    cursor = ""
    query_base = {
        "limit": "500",
        "startsAfter": str(int(WINDOW_START.timestamp() * 1000) - 1),
        "startsBefore": str(int(WINDOW_END.timestamp() * 1000)),
    }
    try:
        for _ in range(MAX_PAGES):
            query = dict(query_base)
            if cursor:
                query["after"] = cursor
            status, text = novig_live.list_fills(query)
            page = {"http": status, "bytes": len(text or "")}
            if status != 200:
                pages.append(page | {"error": "http", "body_prefix": (text or "")[:80]})
                break
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                pages.append(page | {"error": "not_json"})
                break
            batch, next_cursor = _novig_items(data)
            rows = [novig_row(item) for item in batch if isinstance(item, dict)]
            fills.extend(rows)
            pages.append(page | {"n": len(rows), "cursor_next": bool(next_cursor)})
            cursor = next_cursor
            if not cursor or not batch:
                break
        called = True
        note = ""
    except Exception as exc:
        called = False
        note = type(exc).__name__
        pages.append({"http": 0, "error": type(exc).__name__})
    house = [row for row in fills if row.get("house_fill")]
    return {
        "called": called,
        "endpoint": "GET /v3/portfolio/fills",
        "doc": "https://docs.novig.com/api-reference/execution/list-fills",
        "http_pages": pages,
        "n": len(fills),
        "n_house": len(house),
        "note": note,
        "fills": house,
        "all_rows": fills,
    }


def io_summary(row: dict) -> dict:
    payload = row.get("response") if isinstance(row.get("response"), dict) else {}
    qty = live_lock_orders.filled_contracts(payload) if payload else Decimal("0")
    req = row.get("request") if isinstance(row.get("request"), dict) else {}
    venue = str(row.get("venue") or "").lower()
    poly = polymarket_fill(payload) if venue == "polymarket" and payload else {}
    return {
        "ts": row.get("timestamp"),
        "venue": venue,
        "instrument": _io_instrument(row),
        "order_id": _order_id_of(payload),
        "qty": str(qty),
        "qty_ge_1": qty_ge_1(qty),
        "gemini_symbol": req.get("symbol") or "",
        "poly_outcome": poly.get("outcome_name") or "",
        "req_side": str(req.get("side") or req.get("action") or req.get("intent") or ""),
    }


def named_hits(rows: list[dict], needles: tuple[str, ...]) -> list[dict]:
    hits = []
    for row in rows:
        blob = " ".join(str(row.get(k) or "") for k in row).lower()
        if any(n in blob for n in needles):
            hits.append(row)
    return hits


def diff_tables(venues: dict) -> dict:
    io_list = _load_jsonl(ORDER_IO)
    orders = _load_jsonl(ORDERS)
    io_fills = []
    for row in io_list:
        if str(row.get("kind") or "") != "order":
            continue
        stamp = parse_dt(row.get("timestamp"))
        if not in_window(stamp):
            continue
        summary = io_summary(row)
        if summary["qty_ge_1"]:
            io_fills.append(summary)
    tape = []
    for row in orders:
        if str(row.get("event") or "") != "filled":
            continue
        stamp = parse_dt(row.get("ts") or row.get("timestamp") or row.get("compared_at"))
        if not in_window(stamp):
            continue
        tape.append({
            "ts": row.get("ts") or row.get("timestamp") or row.get("compared_at"),
            "venue": str(row.get("venue") or "").lower(),
            "instrument": str(row.get("instrument") or ""),
            "order_id": str(row.get("order_id") or ""),
            "price": row.get("price") or row.get("fill_price") or row.get("limit"),
            "size": row.get("size") or row.get("qty"),
        })

    def instr(row):
        return str(row.get("ticker") or row.get("instrument") or row.get("gemini_symbol") or "").lower()

    history = []
    for venue, payload in venues.items():
        for row in payload.get("fills") or []:
            history.append(row | {"venue": venue if venue != "polymarket" else "polymarket"})

    io_keys = {(r["venue"], instr(r)) for r in io_fills if instr(r)}
    hist_keys = {(r["venue"], instr(r)) for r in history if instr(r)}
    tape_keys = {(r["venue"], r["instrument"].lower()) for r in tape if r.get("instrument")}

    hist_not_io = sorted(hist_keys - io_keys)
    io_not_hist = sorted(io_keys - hist_keys)
    tape_not_hist = sorted(tape_keys - hist_keys)
    hist_not_tape = sorted(hist_keys - tape_keys)

    needles = {
        "ribecai": ("ribhou", "micrib", "ribecai", "houkes"),
        "urso": ("ursaur", "pobane", "urso", "poborilova"),
        "danilova": ("olgdanyuhliu", "avabecjizsib", "danilova", "sibai"),
        "funk": ("aarfun", "serpet", "funk", "petrov"),
        "wolff": ("vivwol", "steweb", "wolff"),
        "machac": ("mackha", "machac", "khachanov"),
        "tb_cle": ("tbcle", "tampa", "gemi-mlb-261018"),
        "car_cgy": ("carcgy", "calgary", "gemi-nhl-261019"),
        "mtn_fiu": ("mtnfiu", "gemi-ncaaf-261020"),
    }
    named = {}
    for label, needle in needles.items():
        named[label] = {
            "history": named_hits(history, needle),
            "history_all": named_hits(
                [row for payload in venues.values() for row in (payload.get("all_rows") or payload.get("fills") or [])],
                needle,
            ),
            "order_io": named_hits(io_fills, needle),
            "tape": named_hits(tape, needle),
        }
    return {
        "io_fills_n": len(io_fills),
        "tape_filled_n": len(tape),
        "history_n": len(history),
        "hist_not_io": hist_not_io[:80],
        "io_not_hist": io_not_hist[:80],
        "tape_not_hist": tape_not_hist[:80],
        "hist_not_tape": hist_not_tape[:80],
        "named": named,
        "io_fills": io_fills,
        "tape": tape,
    }


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    venues = {
        "kalshi": pull_kalshi(),
        "gemini": pull_gemini(),
        "polymarket": pull_polymarket(),
        "novig": pull_novig(),
    }
    summary = {
        "pulled_at": datetime.now(ET).isoformat(),
        "window": "2026-10-18 00:00 ET through 2026-10-22 24:00 ET",
        "venues": redact(venues),
        "diff": redact(diff_tables(venues)),
        "no_gtc": True,
        "no_sell": True,
    }
    OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}")
    for name, payload in venues.items():
        pages = payload.get("http_pages") or []
        https = [p.get("http") for p in pages]
        print(name, "called", payload.get("called"), "http", https, "n", payload.get("n"), "house", payload.get("n_house"))


if __name__ == "__main__":
    main()
