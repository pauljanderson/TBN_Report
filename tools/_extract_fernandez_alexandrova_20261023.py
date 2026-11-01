"""Extract Fernandez vs Alexandrova Strategy B tape + venue fills. Read-only. No orders. No secrets."""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
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
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = RAW / "fernandez_alexandrova_extract_20261023.json"
SLUG = "aec-wta-leyfer-ekaale-2026-10-23"
KALSHI_EVENT = "KXWTAMATCH-26OCT23FERALE"
KALSHI_FER = "KXWTAMATCH-26OCT23FERALE-FER"
KALSHI_ALE = "KXWTAMATCH-26OCT23FERALE-ALE"
T0 = datetime(2026, 10, 23, 4, 1, 23, tzinfo=ET)
CROSS = datetime(2026, 10, 23, 4, 40, 45, tzinfo=ET)
DIP = datetime(2026, 10, 23, 4, 51, 24, tzinfo=ET)
WINDOW_LO = datetime(2026, 10, 23, 3, 50, tzinfo=ET)
WINDOW_HI = datetime(2026, 10, 23, 6, 0, tzinfo=ET)
OIDS = {
    "01a167c7-73d8-7880-85c5-c8bfe0390cfe",
    "01a167c7-8760-7288-9d02-bbcd2a99a148",
    "01a167eb-7e68-7317-99a5-e3fb2a317ea4",
    "01a167f5-3e80-7a9e-b93d-a95e45e35612",
}


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


def _hit_game(blob: str) -> bool:
    low = blob.lower()
    return (
        "fernandez" in low
        or "alexandrova" in low
        or "ferale" in low
        or "leyfer" in low
        or "ekaale" in low
        or KALSHI_EVENT.lower() in low
        or SLUG in low
    )


def extract_local():
    orders = []
    for row in _jsonl(RAW / "orders.jsonl"):
        blob = json.dumps(row, default=str)
        if _hit_game(blob):
            orders.append(row)

    io_rows = []
    for row in _jsonl(RAW / "order_io.jsonl"):
        req = row.get("request") if isinstance(row.get("request"), dict) else {}
        resp = row.get("response") if isinstance(row.get("response"), dict) else {}
        blob = json.dumps(row, default=str)
        if not _hit_game(blob):
            continue
        kind = str(row.get("kind") or "")
        if kind != "order":
            continue
        trimmed = {
            "timestamp": row.get("timestamp"),
            "venue": row.get("venue"),
            "kind": kind,
            "http_status": row.get("http_status"),
            "request": {
                k: req.get(k)
                for k in (
                    "ticker",
                    "side",
                    "count",
                    "price",
                    "time_in_force",
                    "client_order_id",
                )
                if k in req
            },
            "response": {
                k: resp.get(k)
                for k in (
                    "order_id",
                    "client_order_id",
                    "fill_count",
                    "average_fill_price",
                    "average_fee_paid",
                    "remaining_count",
                    "ts_ms",
                )
                if k in resp
            },
            "quote_price": row.get("quote_price"),
            "quote_seen_at": row.get("quote_seen_at"),
            "sent_at": row.get("sent_at"),
            "lag_seconds": row.get("lag_seconds"),
        }
        trimmed["order_id"] = resp.get("order_id") or ""
        io_rows.append(trimmed)

    log_lines = []
    if (RAW / "strategy_b.log").exists():
        for line in (RAW / "strategy_b.log").read_text(encoding="utf-8").splitlines():
            if _hit_game(line):
                log_lines.append(line)

    watch = {}
    status = json.loads((RAW / "strategy_b_watch.json").read_text(encoding="utf-8"))
    for row in status.get("matches") or []:
        game = str(row.get("game") or "")
        key = str(row.get("key") or "")
        if "Fernandez" in game or "ferale" in key:
            watch = row
            break

    snapshots = []
    jsonl_path = RAW / "price_memory" / "2026-10-23" / "tennis.jsonl"
    marks = [
        ("t0", T0),
        ("cross", CROSS),
        ("dip", DIP),
    ]
    last_by_key = {}
    if jsonl_path.exists():
        for rec in _jsonl(jsonl_path):
            game = str(rec.get("game") or "")
            if "Fernandez" not in game and "Alexandrova" not in game:
                continue
            seen = _parse(rec.get("seen_at") or rec.get("ts") or rec.get("time"))
            if seen is None:
                continue
            if seen < WINDOW_LO or seen > WINDOW_HI:
                continue
            if str(rec.get("pay") or "").lower() != "yes":
                continue
            slim = {
                "seen_at": rec.get("seen_at"),
                "seen_et": _et(seen),
                "game": game,
                "venue": rec.get("venue"),
                "side": rec.get("side"),
                "pay": rec.get("pay"),
                "price": rec.get("price"),
                "phase": rec.get("phase"),
            }
            key = "|".join([str(rec.get("venue") or ""), str(rec.get("side") or "")])
            last_by_key[key] = slim
            for name, mark in marks:
                if abs((seen - mark).total_seconds()) <= 8:
                    snapshots.append({"mark": name, **slim})

    nearest = {}
    if jsonl_path.exists():
        for rec in _jsonl(jsonl_path):
            game = str(rec.get("game") or "")
            if "Fernandez" not in game and "Alexandrova" not in game:
                continue
            if str(rec.get("pay") or "").lower() != "yes":
                continue
            seen = _parse(rec.get("seen_at"))
            if seen is None:
                continue
            key = "|".join([str(rec.get("venue") or ""), str(rec.get("side") or "")])
            for name, mark in marks:
                if seen > mark + timedelta(seconds=2):
                    continue
                if seen < mark - timedelta(minutes=3):
                    continue
                slot = f"{name}|{key}"
                prev = nearest.get(slot)
                prev_seen = _parse((prev or {}).get("seen_at"))
                if prev is None or (prev_seen is not None and seen >= prev_seen):
                    nearest[slot] = {
                        "mark": name,
                        "seen_at": rec.get("seen_at"),
                        "seen_et": _et(seen),
                        "venue": rec.get("venue"),
                        "side": rec.get("side"),
                        "price": rec.get("price"),
                        "lag_sec": round((mark - seen).total_seconds(), 3),
                    }

    pid = {}
    if (RAW / "strategy_b.pid").exists():
        pid = json.loads((RAW / "strategy_b.pid").read_text(encoding="utf-8"))

    job = {}
    jp = RAW / "live_jobs" / "tennis_ferale_2026_10_23.json"
    if jp.exists():
        job = json.loads(jp.read_text(encoding="utf-8"))

    return {
        "orders": orders,
        "order_io": io_rows,
        "log_lines": log_lines,
        "watch": watch,
        "snapshots_near_marks": snapshots,
        "nearest_yes_before_marks": nearest,
        "pid_file": pid,
        "watch_open_n": status.get("currently_open"),
        "watch_pid": status.get("pid"),
        "watch_updated": status.get("updated_at"),
        "novig_orders_live_now": bool(novig_live.orders_live()),
        "job": {
            "key": job.get("key"),
            "title": job.get("title"),
            "start": job.get("start"),
            "kalshi": ((job.get("game") or {}).get("kalshi") if isinstance(job.get("game"), dict) else None),
            "gemini": ((job.get("game") or {}).get("gemini") if isinstance(job.get("game"), dict) else None),
            "listed_start": (job.get("game") or {}).get("listed_start") if isinstance(job.get("game"), dict) else None,
            "polymarket_markets": (job.get("game") or {}).get("polymarket_markets") if isinstance(job.get("game"), dict) else None,
        },
    }


def _poly_amount(value):
    if isinstance(value, dict):
        return value.get("value")
    return value


def _poly_fills(slug: str) -> dict:
    poly_rows = []
    poly_pages = []
    cursor = ""
    try:
        for _ in range(8):
            query = {
                "limit": "100",
                "types": "ACTIVITY_TYPE_TRADE",
                "sortOrder": "SORT_ORDER_DESCENDING",
                "marketSlug": slug,
            }
            if cursor:
                query["cursor"] = cursor
            status, text = polymarket_us_live.get_activities(query, timeout=20)
            poly_pages.append({"http": status, "bytes": len(text or ""), "slug": slug})
            if status != 200:
                poly_pages[-1]["body_prefix"] = (text or "")[:120]
                break
            data = json.loads(text) if text else {}
            batch = data.get("activities") if isinstance(data, dict) else []
            if not isinstance(batch, list):
                break
            for item in batch:
                if not isinstance(item, dict):
                    continue
                trade = item.get("trade") if isinstance(item.get("trade"), dict) else {}
                stamp = _parse(trade.get("createTime") or trade.get("updateTime"))
                found_slug = str(trade.get("marketSlug") or "")
                if found_slug and found_slug != slug:
                    continue
                poly_rows.append(
                    {
                        "time_et": _et(stamp),
                        "slug": found_slug,
                        "qty": str(trade.get("qtyDecimal") or trade.get("qty") or ""),
                        "price": str(_poly_amount(trade.get("price")) or ""),
                        "cost": str(_poly_amount(trade.get("costBasis")) or ""),
                        "intent": str(trade.get("intent") or item.get("intent") or ""),
                        "side": str(trade.get("side") or item.get("side") or ""),
                        "orderId": str(
                            trade.get("orderId")
                            or trade.get("order_id")
                            or item.get("orderId")
                            or ""
                        ),
                        "trade_id": str(trade.get("id") or item.get("id") or ""),
                    }
                )
            cursor = str((data or {}).get("nextCursor") or "")
            if bool((data or {}).get("eof")) or not cursor or not batch:
                break
        return {
            "http_pages": poly_pages,
            "n": len(poly_rows),
            "rows": poly_rows,
            "endpoint": "GET /v1/portfolio/activities",
            "slug": slug,
        }
    except Exception as exc:
        return {"error": type(exc).__name__, "http_pages": poly_pages, "slug": slug}


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
        "yes_price_fixed",
    ):
        if key in item:
            keep[key] = item[key]
    keep["keys"] = sorted(item.keys())
    keep["created_et"] = _et(_parse(item.get("created_time") or item.get("ts")))
    return keep


def pull_venues():
    out = {}
    out["polymarket"] = _poly_fills(SLUG)

    try:
        status, text = polymarket_us_live.signed_json("GET", "/v1/portfolio/positions", timeout=20)
        data = json.loads(text) if text and status == 200 else {}
        rows = []
        positions = data.get("positions") or data.get("items") or data.get("availablePositions") or []
        if isinstance(positions, dict):
            positions = positions.get("positions") or positions.get("availablePositions") or []
        if not isinstance(positions, list):
            positions = []
        for item in positions:
            if not isinstance(item, dict):
                continue
            blob = json.dumps(item, default=str)
            if not _hit_game(blob):
                continue
            rows.append(
                {
                    k: item.get(k)
                    for k in (
                        "marketSlug",
                        "title",
                        "outcome",
                        "netPosition",
                        "quantity",
                        "avgPx",
                        "realizedPnl",
                        "unrealizedPnl",
                        "status",
                        "result",
                    )
                    if k in item
                }
            )
        out["polymarket_positions"] = {
            "http": status,
            "n_match": len(rows),
            "rows": rows,
            "endpoint": "GET /v1/portfolio/positions",
        }
    except Exception as exc:
        out["polymarket_positions"] = {"error": type(exc).__name__}

    kalshi_rows = []
    kalshi_pages = []
    try:
        for ticker in (KALSHI_FER, KALSHI_ALE, KALSHI_EVENT):
            cursor = ""
            for _ in range(4):
                query = {
                    "ticker": ticker,
                    "min_ts": str(int(WINDOW_LO.timestamp()) - 3600),
                    "limit": "200",
                }
                if cursor:
                    query["cursor"] = cursor
                status, text = kalshi_private.get_fills(query, timeout=20)
                kalshi_pages.append({"http": status, "bytes": len(text or ""), "ticker": ticker})
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
                    found = str(item.get("ticker") or "")
                    if KALSHI_EVENT not in found:
                        continue
                    kalshi_rows.append(_kalshi_fill_row(item))
                cursor = str(data.get("cursor") or "")
                if not cursor or not batch:
                    break
        seen_ids = set()
        unique = []
        for row in kalshi_rows:
            key = (row.get("order_id"), row.get("trade_id"), row.get("ticker"), row.get("created_time") or row.get("ts"))
            if key in seen_ids:
                continue
            seen_ids.add(key)
            unique.append(row)
        out["kalshi"] = {
            "http_pages": kalshi_pages,
            "n": len(unique),
            "rows": unique,
            "endpoint": "GET /trade-api/v2/portfolio/fills",
            "oid_hits": [row for row in unique if str(row.get("order_id") or "") in OIDS],
        }
    except Exception as exc:
        out["kalshi"] = {"error": type(exc).__name__, "http_pages": kalshi_pages}

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
            "rows": hits,
            "endpoint": "GET /trade-api/v2/portfolio/positions",
            "body_prefix": (text or "")[:180] if status != 200 else "",
        }
    except Exception as exc:
        out["kalshi_positions"] = {"error": type(exc).__name__}

    markets = []
    for ticker in (KALSHI_FER, KALSHI_ALE):
        url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                status = response.status
                text = response.read().decode("utf-8")
        except Exception as exc:
            markets.append({"ticker": ticker, "error": type(exc).__name__})
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
            {"status": "filled", "timestamp": int(WINDOW_LO.timestamp() * 1000)},
            timeout=20,
        )
        data = json.loads(text) if text and status == 200 else {}
        orders = data.get("orders") if isinstance(data, dict) else []
        if not isinstance(orders, list):
            orders = []
        rows = []
        for item in orders:
            blob = json.dumps(item, default=str).lower()
            if "fernandez" in blob or "alexandrova" in blob or "ferale" in blob or "leyfer" in blob:
                rows.append(
                    {
                        "symbol": item.get("symbol") or item.get("ticker"),
                        "qty": item.get("originalQuantity") or item.get("quantity"),
                        "avg": item.get("avgFillPrice") or item.get("price"),
                        "id": item.get("orderId") or item.get("id"),
                    }
                )
        out["gemini"] = {
            "http": status,
            "n_hist": len(orders) if isinstance(orders, list) else 0,
            "n_match": len(rows),
            "rows": rows,
            "endpoint": "POST /v1/prediction-markets/orders/history",
        }
    except Exception as exc:
        out["gemini"] = {"error": type(exc).__name__}

    novig_rows = []
    novig_pages = []
    try:
        cursor = ""
        query_base = {
            "limit": "200",
            "startsAfter": str(int(WINDOW_LO.timestamp() * 1000) - 1),
            "startsBefore": str(int(WINDOW_HI.timestamp() * 1000)),
        }
        for _ in range(6):
            query = dict(query_base)
            if cursor:
                query["after"] = cursor
            status, text = novig_live.list_fills(query, timeout=20)
            novig_pages.append({"http": status, "bytes": len(text or "")})
            if status != 200:
                novig_pages[-1]["body_prefix"] = (text or "")[:160]
                break
            data = json.loads(text) if text else {}
            items = data.get("items") if isinstance(data, dict) else None
            next_cursor = str(data.get("next") or "") if isinstance(data, dict) else ""
            if not isinstance(items, list):
                items = []
                if isinstance(data, dict):
                    for value in data.values():
                        if isinstance(value, dict) and isinstance(value.get("items"), list):
                            items.extend(value["items"])
                            next_cursor = str(value.get("next") or next_cursor)
            for item in items:
                if not isinstance(item, dict):
                    continue
                blob = json.dumps(item, default=str).lower()
                if "fernandez" not in blob and "alexandrova" not in blob and "ferale" not in blob:
                    continue
                novig_rows.append(
                    {
                        "orderId": item.get("orderId"),
                        "qty": item.get("qty"),
                        "cost": item.get("cost"),
                        "price": item.get("price"),
                        "marketId": item.get("marketId"),
                        "outcomeId": item.get("outcomeId"),
                        "ts": item.get("ts"),
                    }
                )
            cursor = next_cursor
            if not cursor or not items:
                break
        out["novig"] = {
            "http_pages": novig_pages,
            "n": len(novig_rows),
            "rows": novig_rows,
            "endpoint": "GET /v3/portfolio/fills",
            "orders_live_now": bool(novig_live.orders_live()),
        }
    except Exception as exc:
        out["novig"] = {"error": type(exc).__name__, "http_pages": novig_pages}
    return out


def main() -> int:
    local = extract_local()
    venues = pull_venues()
    payload = {
        "pulled_at": datetime.now(ET).isoformat(timespec="seconds"),
        "timezone": "America/New_York",
        "slug": SLUG,
        "kalshi_event": KALSHI_EVENT,
        "t0": T0.isoformat(),
        "cross": CROSS.isoformat(),
        "dip": DIP.isoformat(),
        "local": local,
        "venues": venues,
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("orders", len(local["orders"]), "order_io", len(local["order_io"]))
    print("kalshi fills", (venues.get("kalshi") or {}).get("n"), "oid_hits", len((venues.get("kalshi") or {}).get("oid_hits") or []))
    print("poly", (venues.get("polymarket") or {}).get("n"), "gemini", (venues.get("gemini") or {}).get("n_match"), "novig", (venues.get("novig") or {}).get("n"))
    print("markets", venues.get("kalshi_markets"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
