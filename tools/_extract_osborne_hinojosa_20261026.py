"""Osborne vs Hinojosa Gomez tape + venue fill-history. Read-only. No orders. No secrets."""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import gemini_private  # noqa: E402
import kalshi_private  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = RAW / "osborne_hinojosa_extract_20261026.json"
SLUG = "aec-wta-aleosb-jeshin-2026-10-25"
KALSHI_EVENT = "KXWTACHALLENGERMATCH-26OCT25OSBHIN"
KALSHI_OSB = "KXWTACHALLENGERMATCH-26OCT25OSBHIN-OSB"
KALSHI_HIN = "KXWTACHALLENGERMATCH-26OCT25OSBHIN-HIN"
KALSHI_OID = "01a179a7-e628-7aef-9600-afe97ae29d38"
POLY_OID = "DB9ZWXWG11MV"
NEEDLES = (
    "osborne",
    "hinojosa",
    "osbhin",
    "aleosb",
    "jeshin",
    KALSHI_EVENT.lower(),
    SLUG,
    KALSHI_OID.lower(),
    POLY_OID.lower(),
)
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


def _hit(blob: str) -> bool:
    low = str(blob or "").lower()
    return any(n in low for n in NEEDLES)


def _is_other_match(game: str) -> bool:
    low = str(game or "").lower()
    if "rodriguez" in low:
        return True
    if "urhobo" in low or "mcdonald" in low:
        return True
    return False


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


def _parse(text):
    text = str(text or "").strip()
    if not text:
        return None
    if text.isdigit():
        raw = int(text)
        if raw > 10**12:
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        if "." not in text:
            return None
        head, rest = text.split(".", 1)
        digits = "".join(ch for ch in rest if ch.isdigit())
        tail = rest[len(digits) :] if digits else rest
        try:
            stamp = datetime.fromisoformat(f"{head}.{digits[:6]}{tail}".replace("Z", "+00:00"))
        except ValueError:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def _et(stamp):
    if stamp is None:
        return ""
    return stamp.astimezone(ET).isoformat(timespec="milliseconds")


def _kalshi_fill_row(item: dict) -> dict:
    keep = {}
    for key in (
        "ticker",
        "order_id",
        "trade_id",
        "count",
        "count_fp",
        "yes_price",
        "yes_price_dollars",
        "no_price",
        "no_price_dollars",
        "side",
        "action",
        "outcome_side",
        "is_taker",
        "fee_cost",
        "taker_fees",
        "taker_fee_dollars",
        "fees",
        "fee",
        "created_time",
        "ts",
        "settled",
        "revenue",
        "book_side",
    ):
        if key in item:
            keep[key] = item[key]
    keep["keys"] = sorted(item.keys())
    keep["created_et"] = _et(_parse(item.get("created_time") or item.get("ts")))
    return keep


def _poly_trade_row(item: dict) -> dict:
    trade = item.get("trade") if isinstance(item.get("trade"), dict) else item
    aggressor = trade.get("aggressor") if isinstance(trade.get("aggressor"), dict) else {}
    order = aggressor.get("order") if isinstance(aggressor.get("order"), dict) else aggressor
    return {
        "type": item.get("type") or trade.get("type"),
        "marketSlug": trade.get("marketSlug"),
        "qty": trade.get("qtyDecimal") or trade.get("qty"),
        "price": trade.get("price"),
        "isAggressor": trade.get("isAggressor"),
        "aggressor_id": order.get("id") or aggressor.get("id"),
        "createTime": trade.get("createTime") or item.get("createTime"),
        "title": (trade.get("marketMetadata") or {}).get("title") if isinstance(trade.get("marketMetadata"), dict) else "",
        "outcome": (trade.get("marketMetadata") or {}).get("outcome") if isinstance(trade.get("marketMetadata"), dict) else "",
    }


def slim_io(row: dict) -> dict:
    req = row.get("request") if isinstance(row.get("request"), dict) else {}
    resp = row.get("response") if isinstance(row.get("response"), dict) else {}
    out = {
        "kind": row.get("kind"),
        "venue": row.get("venue"),
        "http_status": row.get("http_status"),
        "timestamp": row.get("timestamp"),
        "sent_at": row.get("sent_at"),
        "attempt": row.get("attempt"),
        "quote": row.get("quote"),
        "request": req,
    }
    if row.get("venue") == "kalshi":
        keep = [
            "average_fee_paid",
            "average_fill_price",
            "client_order_id",
            "fill_count",
            "order_id",
            "remaining_count",
            "ts_ms",
            "status",
            "yes_price",
            "no_price",
            "taker_fees",
            "fee_cost",
        ]
        out["response"] = {k: resp.get(k) for k in keep if k in resp}
        out["ts_et"] = _et(_parse(resp.get("ts_ms")))
    elif row.get("venue") == "polymarket":
        execs = []
        for e in resp.get("executions") or []:
            if not isinstance(e, dict):
                continue
            o = e.get("order") if isinstance(e.get("order"), dict) else {}
            md = o.get("marketMetadata") if isinstance(o.get("marketMetadata"), dict) else {}
            execs.append(
                {
                    "id": e.get("id"),
                    "type": e.get("type"),
                    "aggressor": e.get("aggressor"),
                    "lastShares": e.get("lastShares"),
                    "lastPx": e.get("lastPx"),
                    "tradeId": e.get("tradeId"),
                    "commissionNotionalCollected": e.get("commissionNotionalCollected"),
                    "cumQuantity": o.get("cumQuantity"),
                    "leavesQuantity": o.get("leavesQuantity"),
                    "state": o.get("state"),
                    "avgPx": o.get("avgPx"),
                    "commissionNotionalTotalCollected": o.get("commissionNotionalTotalCollected"),
                    "outcome": md.get("outcome"),
                    "slug": md.get("slug") or o.get("marketSlug"),
                    "createTime": o.get("createTime"),
                    "intent": o.get("intent"),
                    "outcomeSide": o.get("outcomeSide"),
                }
            )
        out["poly_id"] = resp.get("id")
        out["executions"] = execs
    return out


def extract_local():
    orders = []
    for row in _jsonl(RAW / "orders.jsonl"):
        blob = json.dumps(row, default=str)
        if not _hit(blob):
            continue
        if _is_other_match(str(row.get("game") or "")):
            continue
        ev = row.get("event")
        if ev == "t0" and row.get("action") == "skip":
            continue
        orders.append(row)

    io_rows = []
    for row in _jsonl(RAW / "order_io.jsonl"):
        if str(row.get("kind") or "") != "order":
            continue
        blob = json.dumps(row, default=str)
        if not _hit(blob):
            continue
        io_rows.append(slim_io(row))

    cash = []
    for row in _jsonl(RAW / "venue_cash_drift.jsonl"):
        blob = json.dumps(row, default=str)
        if _hit(blob):
            cash.append(row)

    ledger_hits = []
    ledger = (
        ROOT
        / "drive"
        / "paul_experiments"
        / "prediction_market_arb_exhaustive_20261017"
        / "orders_performance_20261022"
        / "ledger.csv"
    )
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if "Osborne vs Hinojosa Gomez" in line:
                ledger_hits.append(line)

    return {"orders": orders, "order_io": io_rows, "cash": cash, "ledger_rows": ledger_hits}


def pull_venues():
    out = {}

    poly_rows = []
    poly_pages = []
    try:
        cursor = ""
        for _ in range(6):
            query = {
                "limit": "100",
                "types": "ACTIVITY_TYPE_TRADE",
                "sortOrder": "SORT_ORDER_DESCENDING",
                "marketSlug": SLUG,
            }
            if cursor:
                query["cursor"] = cursor
            status, text = polymarket_us_live.get_activities(query, timeout=20)
            poly_pages.append({"http": status, "bytes": len(text or "")})
            data = json.loads(text) if text and status == 200 else {}
            batch = data.get("activities") if isinstance(data, dict) else []
            if not isinstance(batch, list):
                batch = []
            for item in batch:
                if isinstance(item, dict):
                    poly_rows.append(_poly_trade_row(item))
            cursor = str(data.get("nextCursor") or "")
            if bool(data.get("eof")) or not cursor or not batch:
                out["polymarket_eof"] = bool(data.get("eof")) if isinstance(data, dict) else None
                break
        out["polymarket"] = {
            "http_pages": poly_pages,
            "n": len(poly_rows),
            "rows": poly_rows,
            "endpoint": "GET /v1/portfolio/activities",
            "slug": SLUG,
        }
    except Exception as exc:
        out["polymarket"] = {"error": type(exc).__name__, "http_pages": poly_pages, "slug": SLUG}

    try:
        status, text = polymarket_us_live.signed_json("GET", "/v1/portfolio/positions", timeout=20)
        data = json.loads(text) if text and status == 200 else {}
        positions = data.get("positions") or data.get("items") or data.get("availablePositions") or []
        n_all = 0
        rows = []
        if isinstance(positions, dict):
            n_all = len(positions)
            for slug, item in positions.items():
                blob = json.dumps(item, default=str) if isinstance(item, dict) else str(slug)
                if slug == SLUG or _hit(blob):
                    meta = item.get("marketMetadata") if isinstance(item, dict) and isinstance(item.get("marketMetadata"), dict) else {}
                    rows.append(
                        {
                            "slug": str(slug),
                            "title": meta.get("title"),
                            "outcome": meta.get("outcome"),
                            "net": item.get("netPositionDecimal") or item.get("netPosition") if isinstance(item, dict) else None,
                            "expired": item.get("expired") if isinstance(item, dict) else None,
                            "market_state": item.get("marketState") if isinstance(item, dict) else None,
                            "keys": sorted(item.keys())[:40] if isinstance(item, dict) else [],
                        }
                    )
        elif isinstance(positions, list):
            n_all = len(positions)
            for item in positions:
                if not isinstance(item, dict):
                    continue
                blob = json.dumps(item, default=str)
                if SLUG in blob or _hit(blob):
                    meta = item.get("marketMetadata") if isinstance(item.get("marketMetadata"), dict) else {}
                    rows.append(
                        {
                            "slug": item.get("marketSlug") or item.get("slug"),
                            "title": meta.get("title"),
                            "outcome": meta.get("outcome"),
                            "net": item.get("netPositionDecimal") or item.get("netPosition"),
                            "expired": item.get("expired"),
                            "market_state": item.get("marketState") or meta.get("state"),
                            "keys": sorted(item.keys())[:40],
                        }
                    )
        out["polymarket_positions"] = {
            "http": status,
            "n_all": n_all,
            "n_match": len(rows),
            "rows": rows,
            "eof": data.get("eof") if isinstance(data, dict) else None,
            "endpoint": "GET /v1/portfolio/positions",
        }
    except Exception as exc:
        out["polymarket_positions"] = {"error": type(exc).__name__}

    try:
        book = polymarket_us_live.fetch_book(SLUG) or {}
        out["polymarket_book"] = {
            "slug": SLUG,
            "title": book.get("title") or book.get("question"),
            "keys": sorted(book.keys())[:50] if isinstance(book, dict) else [],
            "market_state": book.get("marketState") or book.get("state") or book.get("status"),
            "settlementPx": book.get("settlementPx") or book.get("settlementPrice"),
            "expired": book.get("expired"),
            "endDate": book.get("endDate") or book.get("end_date"),
        }
    except Exception as exc:
        out["polymarket_book"] = {"error": type(exc).__name__, "slug": SLUG}

    kalshi_rows = []
    kalshi_pages = []
    try:
        for query in (
            {"order_id": KALSHI_OID, "limit": "100"},
            {"ticker": KALSHI_OSB, "limit": "200"},
            {"ticker": KALSHI_HIN, "limit": "200"},
        ):
            cursor = ""
            for _ in range(4):
                q = dict(query)
                if cursor:
                    q["cursor"] = cursor
                status, text = kalshi_private.get_fills(q, timeout=20)
                kalshi_pages.append({"http": status, "bytes": len(text or ""), "query": {k: q[k] for k in q if k != "cursor"}})
                if status != 200:
                    kalshi_pages[-1]["body_prefix"] = (text or "")[:200]
                    break
                data = json.loads(text) if text else {}
                batch = data.get("fills") or []
                if not isinstance(batch, list):
                    break
                for item in batch:
                    if not isinstance(item, dict):
                        continue
                    blob = json.dumps(item, default=str)
                    if KALSHI_EVENT not in blob and KALSHI_OID not in blob:
                        continue
                    kalshi_rows.append(_kalshi_fill_row(item))
                cursor = str(data.get("cursor") or "")
                if not cursor or not batch:
                    break
        seen = set()
        unique = []
        for row in kalshi_rows:
            key = (row.get("order_id"), row.get("trade_id"), row.get("ticker"), row.get("created_time") or row.get("ts"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        out["kalshi"] = {
            "http_pages": kalshi_pages,
            "n": len(unique),
            "rows": unique,
            "endpoint": "GET /trade-api/v2/portfolio/fills",
        }
    except Exception as extra:
        out["kalshi"] = {"error": type(extra).__name__, "http_pages": kalshi_pages}

    try:
        status, text = kalshi_private.signed_call(
            "GET",
            "/trade-api/v2/portfolio/positions",
            query={"count_filter": "position", "limit": "200", "ticker": KALSHI_EVENT},
            timeout=20,
        )
        data = json.loads(text) if text and status == 200 else {}
        market_rows = data.get("market_positions") or data.get("event_positions") or []
        if isinstance(market_rows, dict):
            market_rows = [market_rows]
        hits = []
        for item in market_rows if isinstance(market_rows, list) else []:
            blob = json.dumps(item, default=str)
            if KALSHI_EVENT not in blob:
                continue
            hits.append(
                {
                    k: item.get(k)
                    for k in (
                        "ticker",
                        "position_fp",
                        "position",
                        "market_exposure_dollars",
                        "realized_pnl_dollars",
                        "unrealized_pnl_dollars",
                        "average_price_dollars",
                        "result",
                    )
                    if k in item
                }
                | {"keys": sorted(item.keys())[:50]}
            )
        out["kalshi_positions"] = {
            "http": status,
            "n_match": len(hits),
            "n_raw": len(market_rows) if isinstance(market_rows, list) else 0,
            "rows": hits,
            "endpoint": "GET /trade-api/v2/portfolio/positions",
            "body_prefix": (text or "")[:180] if status != 200 else "",
        }
    except Exception as extra:
        out["kalshi_positions"] = {"error": type(extra).__name__}

    try:
        status, text = kalshi_private.signed_call(
            "GET",
            "/trade-api/v2/portfolio/settlements",
            query={"ticker": KALSHI_EVENT, "limit": "200"},
            timeout=20,
        )
        data = json.loads(text) if text and status == 200 else {}
        rows = data.get("settlements") or []
        if isinstance(rows, dict):
            rows = [rows]
        hits = []
        for item in rows if isinstance(rows, list) else []:
            blob = json.dumps(item, default=str)
            if KALSHI_EVENT not in blob:
                continue
            hits.append(redact(item))
        out["kalshi_settlements"] = {
            "http": status,
            "n": len(hits),
            "rows": hits,
            "endpoint": "GET /trade-api/v2/portfolio/settlements",
            "body_prefix": (text or "")[:180] if status != 200 else "",
        }
    except Exception as extra:
        out["kalshi_settlements"] = {"error": type(extra).__name__}

    markets = []
    for ticker in (KALSHI_OSB, KALSHI_HIN):
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                status = response.status
                text = response.read().decode("utf-8")
        except Exception as extra:
            markets.append({"ticker": ticker, "error": type(extra).__name__})
            continue
        data = json.loads(text) if text else {}
        market = data.get("market") if isinstance(data.get("market"), dict) else data
        markets.append(
            {
                "ticker": ticker,
                "http": status,
                "status": market.get("status"),
                "result": market.get("result"),
                "yes_bid": market.get("yes_bid_dollars") or market.get("yes_bid"),
                "yes_ask": market.get("yes_ask_dollars") or market.get("yes_ask"),
                "last_price": market.get("last_price_dollars") or market.get("last_price"),
                "title": market.get("title") or market.get("subtitle"),
                "expiration_time": market.get("expiration_time") or market.get("close_time"),
            }
        )
    out["kalshi_markets"] = {"endpoint": "GET /trade-api/v2/markets/{ticker}", "rows": markets}

    try:
        status, text = gemini_private.get_order_history(
            {"status": "filled", "limit": 50, "from": int(datetime(2026, 10, 26, 14, 0, tzinfo=ET).timestamp() * 1000)},
            timeout=20,
        )
        data = json.loads(text) if text and status == 200 else {}
        orders = data.get("orders") if isinstance(data, dict) else []
        if not isinstance(orders, list):
            orders = []
        rows = []
        for item in orders:
            blob = json.dumps(item, default=str).lower()
            if _hit(blob):
                rows.append(
                    {
                        "symbol": item.get("symbol") or item.get("ticker"),
                        "qty": item.get("filledQuantity") or item.get("originalQuantity"),
                        "avg": item.get("avgExecutionPrice") or item.get("avgFillPrice"),
                        "id": item.get("orderId") or item.get("id"),
                        "status": item.get("status"),
                    }
                )
        out["gemini"] = {
            "http": status,
            "n_page": len(orders),
            "n_match": len(rows),
            "rows": rows,
            "endpoint": "POST /v1/prediction-markets/orders/history",
            "body_prefix": (text or "")[:180] if status != 200 else "",
        }
    except Exception as extra:
        out["gemini"] = {"error": type(extra).__name__}

    try:
        status, text = novig_live.list_fills({"limit": "100"}, timeout=20)
        data = json.loads(text) if text and status == 200 else {}
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []
        rows = []
        for item in items:
            blob = json.dumps(item, default=str)
            if _hit(blob):
                rows.append(redact(item))
        out["novig"] = {
            "http": status,
            "n_page": len(items),
            "n_match": len(rows),
            "rows": rows,
            "endpoint": "GET /v3/portfolio/fills",
            "body_prefix": (text or "")[:180] if status != 200 else "",
        }
    except Exception as extra:
        out["novig"] = {"error": type(extra).__name__}

    return out


def main() -> None:
    payload = {
        "pulled_at": datetime.now(ET).isoformat(timespec="seconds"),
        "local": extract_local(),
        "venues": pull_venues(),
    }
    OUT.write_text(json.dumps(redact(payload), indent=2, default=str), encoding="utf-8")
    local = payload["local"]
    venues = payload["venues"]
    print(
        f"wrote {OUT} orders={len(local['orders'])} io={len(local['order_io'])} "
        f"kalshi_fills={(venues.get('kalshi') or {}).get('n')} "
        f"poly_acts={(venues.get('polymarket') or {}).get('n')}"
    )


if __name__ == "__main__":
    main()
