"""Extract Namigata vs Yoshimoto tape + Polymarket US fills. Read-only. No orders. No secrets."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
import venue_fill_confirm  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = RAW / "namigata_poly_extract_20261024.json"
SLUG = "aec-utr-namjun-yosnat-2026-10-24"
OIDS = {"DA4V3W5011KJ", "DA4V6VTG31MQ", "DA4VGMG011TB"}
NEEDLES = (
    "namigata",
    "yoshimoto",
    "namigayoshim",
    "namjun",
    "yosnat",
    "da4v3w5011kj",
    "da4v6vtg31mq",
    "da4vgmg011tb",
)


def _dec(value):
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return Decimal(str(value))
    except Exception:
        return None


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
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def _et(stamp):
    if stamp is None:
        return ""
    return stamp.astimezone(ET).isoformat(timespec="milliseconds")


def _hit(blob) -> bool:
    text = json.dumps(blob, default=str).lower() if not isinstance(blob, str) else blob.lower()
    return any(needle in text for needle in NEEDLES)


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


def _qty_nodes(payload):
    rows = []
    if not isinstance(payload, (dict, list)):
        return rows
    for node in venue_fill_confirm._walk(payload):
        if not isinstance(node, dict):
            continue
        found = {}
        for key in (
            "cumQuantity",
            "leavesQuantity",
            "quantity",
            "lastShares",
            "qtyDecimal",
            "qty",
            "filledQuantity",
            "fill_count",
            "size",
        ):
            if key in node and node.get(key) not in (None, ""):
                found[key] = node.get(key)
        if found:
            rows.append({"path_keys": sorted(node.keys())[:24], "qtys": found})
    return rows[:40]


def _trim_poly_payload(payload):
    if not isinstance(payload, dict):
        return payload
    keep = {}
    for key in (
        "id",
        "state",
        "status",
        "cumQuantity",
        "leavesQuantity",
        "quantity",
        "avgPx",
        "price",
        "intent",
        "tif",
        "marketSlug",
        "side",
        "type",
        "lastShares",
        "fee",
        "executions",
        "_venue_confirm",
    ):
        if key in payload:
            keep[key] = payload[key]
    execs = []
    for item in payload.get("executions") or []:
        if not isinstance(item, dict):
            continue
        order = item.get("order") if isinstance(item.get("order"), dict) else {}
        execs.append(
            {
                "id": item.get("id"),
                "cumQuantity": order.get("cumQuantity") or item.get("cumQuantity"),
                "leavesQuantity": order.get("leavesQuantity") or item.get("leavesQuantity"),
                "state": order.get("state") or item.get("state"),
                "avgPx": order.get("avgPx") or item.get("avgPx"),
                "intent": order.get("intent") or item.get("intent"),
                "price": order.get("price") or item.get("price"),
                "quantity": order.get("quantity") or item.get("quantity"),
                "lastShares": order.get("lastShares") or item.get("lastShares"),
                "qtyDecimal": order.get("qtyDecimal") or item.get("qtyDecimal"),
                "fee": order.get("fee") or item.get("fee"),
            }
        )
    if execs:
        keep["executions_trim"] = execs
    confirm = payload.get("_venue_confirm")
    if isinstance(confirm, dict):
        keep["_venue_confirm"] = {
            k: confirm.get(k)
            for k in (
                "known",
                "qty",
                "avg_price",
                "note",
                "mismatch",
                "tape_qty",
                "order_id",
                "http",
                "house_fill",
            )
        }
    keep["qty_nodes"] = _qty_nodes(payload)
    keep["tape_filled_qty"] = str(venue_fill_confirm.tape_filled_qty(payload))
    return keep


def _poly_trade_row(item: dict) -> dict:
    trade = item.get("trade") if isinstance(item.get("trade"), dict) else item
    if not isinstance(trade, dict):
        trade = {}
    aggressor = trade.get("aggressor") if isinstance(trade.get("aggressor"), dict) else {}
    agg_ex = trade.get("aggressorExecution") if isinstance(trade.get("aggressorExecution"), dict) else {}
    return {
        "type": item.get("type") or trade.get("type"),
        "slug": str(trade.get("marketSlug") or ""),
        "title": str((trade.get("marketMetadata") or {}).get("title") or "")
        if isinstance(trade.get("marketMetadata"), dict)
        else "",
        "outcome": str((trade.get("marketMetadata") or {}).get("outcome") or "")
        if isinstance(trade.get("marketMetadata"), dict)
        else "",
        "intent": str(aggressor.get("intent") or trade.get("intent") or ""),
        "side": str(aggressor.get("side") or trade.get("side") or ""),
        "price": trade.get("price") or aggressor.get("price"),
        "qty": trade.get("qtyDecimal") if trade.get("qtyDecimal") not in (None, "") else trade.get("qty"),
        "fee": trade.get("fee") or agg_ex.get("fee"),
        "create_time": _et(_parse(trade.get("createTime") or item.get("createTime"))),
        "aggressor_id": str(aggressor.get("id") or ""),
        "aggressor_exec_id": str(agg_ex.get("id") or ""),
        "is_aggressor": trade.get("isAggressor"),
        "our_order_id": venue_fill_confirm._poly_our_order_id(item) if isinstance(item, dict) else "",
    }


def extract_local():
    orders = [row for row in _jsonl(RAW / "orders.jsonl") if _hit(row)]
    order_io = []
    for row in _jsonl(RAW / "order_io.jsonl"):
        if not _hit(row):
            continue
        request = row.get("request") if isinstance(row.get("request"), dict) else {}
        response = row.get("response") if isinstance(row.get("response"), dict) else {}
        order_io.append(
            {
                "timestamp": row.get("timestamp"),
                "venue": row.get("venue"),
                "kind": row.get("kind"),
                "http_status": row.get("http_status"),
                "request": {
                    k: request.get(k)
                    for k in (
                        "marketSlug",
                        "type",
                        "price",
                        "quantity",
                        "tif",
                        "intent",
                    )
                    if k in request
                },
                "response": _trim_poly_payload(response),
            }
        )
    watch = {}
    watch_path = RAW / "strategy_b_watch.json"
    if watch_path.exists():
        data = json.loads(watch_path.read_text(encoding="utf-8"))
        for item in (data.get("matches") or []) if isinstance(data, dict) else []:
            if isinstance(item, dict) and _hit(item):
                watch = item
                break
    other = {}
    for name in ("cfb_favorite_watch.json", "spread_t0_watch.json", "one_leg_watch.json"):
        path = RAW / name
        if not path.exists():
            other[name] = "missing"
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            other[name] = "bad json"
            continue
        hits = []
        for item in blob.get("matches") or blob.get("games") or []:
            if isinstance(item, dict) and _hit(item):
                hits.append(
                    {
                        "key": item.get("key"),
                        "game": item.get("game"),
                        "stage": item.get("stage"),
                    }
                )
        other[name] = hits
    return {
        "orders": orders,
        "order_io": order_io,
        "strategy_b_watch": watch,
        "other_watches": other,
        "currently_open_b": (
            json.loads((RAW / "strategy_b_watch.json").read_text(encoding="utf-8")).get("currently_open")
            if (RAW / "strategy_b_watch.json").exists()
            else None
        ),
    }


def extract_venues():
    out = {}
    poly_pages = []
    poly_rows = []
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
            if status != 200:
                poly_pages[-1]["body_prefix"] = (text or "")[:160]
                break
            data = json.loads(text) if text else {}
            batch = data.get("activities") if isinstance(data, dict) else []
            if not isinstance(batch, list):
                break
            for item in batch:
                if not isinstance(item, dict):
                    continue
                row = _poly_trade_row(item)
                if row["slug"] and row["slug"] != SLUG:
                    continue
                poly_rows.append(row)
            cursor = str((data or {}).get("nextCursor") or "")
            if bool((data or {}).get("eof")) or not cursor or not batch:
                break
        out["polymarket"] = {
            "http_pages": poly_pages,
            "n": len(poly_rows),
            "rows": poly_rows,
            "endpoint": "GET /v1/portfolio/activities",
        }
    except Exception as exc:
        out["polymarket"] = {"error": type(exc).__name__, "http_pages": poly_pages}

    oid_rows = []
    try:
        status, text = polymarket_us_live.get_activities(
            {
                "limit": "100",
                "types": "ACTIVITY_TYPE_TRADE",
                "sortOrder": "SORT_ORDER_DESCENDING",
            },
            timeout=20,
        )
        data = json.loads(text) if text and status == 200 else {}
        batch = data.get("activities") if isinstance(data, dict) else []
        if not isinstance(batch, list):
            batch = []
        for item in batch:
            if not isinstance(item, dict):
                continue
            row = _poly_trade_row(item)
            blob = json.dumps(item, default=str)
            if any(oid in blob for oid in OIDS) or _hit(blob):
                oid_rows.append(row)
        out["polymarket_recent_match"] = {
            "http": status,
            "n_page": len(batch),
            "n_match": len(oid_rows),
            "rows": oid_rows,
            "eof": bool(data.get("eof")) if isinstance(data, dict) else None,
        }
    except Exception as exc:
        out["polymarket_recent_match"] = {"error": type(exc).__name__}

    try:
        status, text = polymarket_us_live.signed_json("GET", "/v1/portfolio/positions", timeout=20)
        data = json.loads(text) if text and status == 200 else {}
        positions = data.get("positions")
        rows = []
        n_all = 0
        namigata = None
        if isinstance(positions, dict):
            n_all = len(positions)
            for slug, item in positions.items():
                if not isinstance(item, dict):
                    continue
                blob = json.dumps(item, default=str)
                meta = item.get("marketMetadata") if isinstance(item.get("marketMetadata"), dict) else {}
                row = {
                    "slug": str(slug),
                    "title": str(meta.get("title") or ""),
                    "outcome": str(meta.get("outcome") or ""),
                    "net": item.get("netPositionDecimal") or item.get("netPosition"),
                    "expired": item.get("expired"),
                    "market_state": item.get("marketState") or meta.get("state"),
                }
                if slug == SLUG or _hit(blob):
                    namigata = row
                    rows.append(row)
        elif isinstance(positions, list):
            n_all = len(positions)
            for item in positions:
                if not isinstance(item, dict):
                    continue
                blob = json.dumps(item, default=str)
                if SLUG in blob or _hit(blob):
                    rows.append(
                        {
                            "slug": item.get("marketSlug") or item.get("slug"),
                            "title": str((item.get("marketMetadata") or {}).get("title") or ""),
                            "net": item.get("netPositionDecimal") or item.get("netPosition"),
                            "expired": item.get("expired"),
                        }
                    )
        out["polymarket_positions"] = {
            "http": status,
            "n_all": n_all,
            "n_match": len(rows),
            "namigata": namigata,
            "rows": rows,
            "endpoint": "GET /v1/portfolio/positions",
        }
    except Exception as exc:
        out["polymarket_positions"] = {"error": type(exc).__name__}

    try:
        book = polymarket_us_live.fetch_book(SLUG) or {}
        out["polymarket_book"] = {
            "slug": SLUG,
            "title": book.get("title") or book.get("question"),
            "keys": sorted(book.keys())[:40] if isinstance(book, dict) else [],
            "yes_ask": book.get("yes_ask") or book.get("bestAsk") or book.get("ask"),
            "no_ask": book.get("no_ask"),
            "last": book.get("last") or book.get("lastPrice"),
            "state": book.get("state") or book.get("marketState") or book.get("status"),
            "settlementPx": book.get("settlementPx") or book.get("settlementPrice"),
            "outcomes": book.get("outcomes") or book.get("outcomePrices"),
        }
        raw_book = {k: book.get(k) for k in list(book)[:30]} if isinstance(book, dict) else {}
        # Drop bulky nested books; keep quotes.
        slim = {}
        for key, value in (book or {}).items():
            if key in {"asks", "bids", "raw", "book"}:
                continue
            if isinstance(value, (dict, list)) and key not in {"outcomes", "tokens"}:
                continue
            slim[key] = value
        out["polymarket_book"]["slim"] = slim
        out["polymarket_book"]["raw_prefix_keys"] = list(raw_book.keys())
    except Exception as exc:
        out["polymarket_book"] = {"error": type(exc).__name__}

    kalshi_rows = []
    kalshi_pages = []
    try:
        cursor = ""
        for _ in range(4):
            query = {
                "limit": "200",
                "min_ts": str(int(datetime(2026, 10, 24, 19, 50, tzinfo=ET).timestamp())),
            }
            if cursor:
                query["cursor"] = cursor
            status, text = kalshi_private.get_fills(query, timeout=20)
            kalshi_pages.append({"http": status, "bytes": len(text or "")})
            if status != 200:
                kalshi_pages[-1]["body_prefix"] = (text or "")[:120]
                break
            data = json.loads(text) if text else {}
            batch = data.get("fills") or []
            if not isinstance(batch, list):
                break
            for item in batch:
                if isinstance(item, dict) and _hit(item):
                    kalshi_rows.append(
                        {
                            "ticker": item.get("ticker"),
                            "order_id": item.get("order_id"),
                            "count": item.get("count_fp") or item.get("count"),
                            "side": item.get("side") or item.get("outcome_side"),
                        }
                    )
            cursor = str(data.get("cursor") or "")
            if not cursor or not batch:
                break
        out["kalshi"] = {
            "http_pages": kalshi_pages,
            "n": len(kalshi_rows),
            "rows": kalshi_rows,
            "endpoint": "GET /trade-api/v2/portfolio/fills",
        }
    except Exception as exc:
        out["kalshi"] = {"error": type(exc).__name__, "http_pages": kalshi_pages}

    try:
        status, text = gemini_private.get_order_history(
            {
                "status": "filled",
                "timestamp": int(datetime(2026, 10, 24, 19, 50, tzinfo=ET).timestamp() * 1000),
            },
            timeout=20,
        )
        data = json.loads(text) if text and status == 200 else {}
        orders = data.get("orders") if isinstance(data, dict) else []
        n_match = 0
        if isinstance(orders, list):
            n_match = sum(1 for item in orders if isinstance(item, dict) and _hit(item))
        out["gemini"] = {"http": status, "n_match": n_match}
    except Exception as exc:
        out["gemini"] = {"error": type(exc).__name__}

    try:
        status, text = novig_live.list_fills({"limit": "50"}, timeout=15)
        n_match = 1 if text and _hit(text) else 0
        out["novig"] = {"http": status, "n_match": n_match}
    except Exception as exc:
        out["novig"] = {"error": type(exc).__name__}

    return out


def main() -> int:
    local = extract_local()
    venues = extract_venues()
    bundle = {
        "pulled_at": datetime.now(ET).isoformat(timespec="milliseconds"),
        "slug": SLUG,
        "order_ids": sorted(OIDS),
        "local": local,
        "venues": venues,
    }
    OUT.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
    print(str(OUT))
    poly = venues.get("polymarket") or {}
    pos = venues.get("polymarket_positions") or {}
    print(f"activities n={poly.get('n')} http={poly.get('http_pages')}")
    print(f"positions n_all={pos.get('n_all')} n_match={pos.get('n_match')} namigata={pos.get('namigata')}")
    print(f"local orders={len(local.get('orders') or [])} order_io={len(local.get('order_io') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
