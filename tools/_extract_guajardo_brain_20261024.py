"""Extract Guajardo vs Brain tape + Polymarket US fills. Read-only. No orders. No secrets."""
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
OUT = RAW / "guajardo_brain_extract_20261024.json"
SLUG = "aec-utr-guaale-bralac-2026-10-24"
OIDS = {"D9ZCAFZ011KJ", "D9ZCDDRG11M3", "D9ZCT3CG11KJ"}
NEEDLES = (
    "guajardo",
    "lachlan brain",
    "guajarbrain",
    "guaale",
    "bralac",
    "d9zcafz011kj",
    "d9zcddrg11m3",
    "d9zct3cg11kj",
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
    leftover = [row for row in _jsonl(RAW / "leftover_watch_stats.jsonl") if _hit(row)]
    watch = {}
    watch_path = RAW / "strategy_b_watch.json"
    if watch_path.exists():
        data = json.loads(watch_path.read_text(encoding="utf-8"))
        matches = data.get("matches") if isinstance(data, dict) else data
        if isinstance(matches, list):
            for item in matches:
                if isinstance(item, dict) and _hit(item):
                    watch = item
                    break
        elif isinstance(data, dict) and _hit(data):
            watch = data
    one_leg = {}
    one_path = RAW / "one_leg_watch.json"
    if one_path.exists():
        try:
            blob = json.loads(one_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            blob = {}
        if _hit(blob):
            one_leg = blob
        elif isinstance(blob, dict):
            for key, value in blob.items():
                if _hit({key: value}):
                    one_leg[key] = value
    lock_skip = {}
    skip_path = RAW / "lock_last_skip.json"
    if skip_path.exists():
        try:
            lock_skip = json.loads(skip_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            lock_skip = {}
    ticks = []
    tick_path = RAW / "price_memory" / "2026-10-24" / "tennis.jsonl"
    for row in _jsonl(tick_path) or []:
        if not _hit(row):
            continue
        seen = str(row.get("seen_at") or "")
        if seen >= "2026-10-24T13:39:00" and seen <= "2026-10-24T13:50:00":
            ticks.append(
                {
                    "seen_at": row.get("seen_at"),
                    "side": row.get("side"),
                    "pay": row.get("pay"),
                    "price": row.get("price"),
                    "venue": row.get("venue"),
                    "phase": row.get("phase"),
                }
            )
    last = {}
    last_path = RAW / "price_last.json"
    if last_path.exists():
        data = json.loads(last_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key, value in data.items():
                if _hit(key) or _hit(value):
                    last[key] = value
    pid = ""
    pid_path = RAW / "strategy_b.pid"
    if pid_path.exists():
        pid = pid_path.read_text(encoding="utf-8").strip()
    cfb = RAW / "cfb_favorite_watch.json"
    spread = RAW / "spread_t0_watch.json"
    cfb_hit = False
    spread_hit = False
    if cfb.exists():
        cfb_hit = _hit(cfb.read_text(encoding="utf-8"))
    if spread.exists():
        spread_hit = _hit(spread.read_text(encoding="utf-8"))
    live_state = []
    for path in (RAW / "live_state").glob("tennis_*2026_10_24.json"):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _hit(blob) or _hit(path.name):
            live_state.append({"file": path.name, "keys": sorted(blob.keys())[:20] if isinstance(blob, dict) else []})
    return {
        "orders": orders,
        "order_io": order_io,
        "leftover_watch": leftover,
        "strategy_b_watch": watch,
        "one_leg": one_leg,
        "lock_skip_hit": _hit(lock_skip),
        "ticks_n": len(ticks),
        "ticks": ticks,
        "price_last": last,
        "pid_file": pid,
        "cfb_watch_hit": cfb_hit,
        "spread_watch_hit": spread_hit,
        "live_state": live_state,
    }


def _poly_amount(value):
    if isinstance(value, dict):
        return value.get("value")
    return value


def _poly_trade_row(item: dict) -> dict:
    trade = item.get("trade") if isinstance(item.get("trade"), dict) else {}
    stamp = _parse(trade.get("createTime") or trade.get("updateTime") or item.get("timestamp"))
    ours = venue_fill_confirm._poly_our_order_id(item) if trade else ""
    return {
        "time_et": _et(stamp),
        "slug": str(trade.get("marketSlug") or ""),
        "qty": str(trade.get("qtyDecimal") or trade.get("qty") or ""),
        "price": str(_poly_amount(trade.get("price")) or ""),
        "cost": str(_poly_amount(trade.get("costBasis")) or ""),
        "fee": str(_poly_amount(trade.get("fee") or trade.get("fees")) or ""),
        "intent": str(trade.get("intent") or item.get("intent") or ""),
        "side": str(trade.get("side") or item.get("side") or ""),
        "isAggressor": trade.get("isAggressor"),
        "aggressor_id": ours,
        "aggressor_raw": venue_fill_confirm._poly_nested_order_id(trade.get("aggressor")),
        "passive_raw": venue_fill_confirm._poly_nested_order_id(trade.get("passive")),
        "trade_id": str(trade.get("id") or item.get("id") or ""),
        "state": str(trade.get("state") or ""),
        "title": str((trade.get("marketMetadata") or {}).get("title") or item.get("title") or ""),
        "outcome": str(trade.get("outcome") or item.get("outcome") or ""),
        "keys": sorted(trade.keys()),
    }


def pull_venues():
    out = {}
    poly_rows = []
    poly_pages = []
    cursor = ""
    try:
        for _ in range(10):
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

    # Unfiltered recent trades, then match order ids (in case slug filter misses).
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
        rows = []
        positions = data.get("positions") or data.get("items") or []
        if isinstance(positions, dict):
            positions = positions.get("positions") or []
        if not isinstance(positions, list):
            positions = []
        for item in positions:
            if not isinstance(item, dict):
                continue
            blob = json.dumps(item, default=str)
            if SLUG not in blob and "Guajardo" not in blob and "Lachlan Brain" not in blob:
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
                | {"keys": sorted(item.keys())[:40]}
            )
        out["polymarket_positions"] = {
            "http": status,
            "n_all": len(positions) if isinstance(positions, list) else 0,
            "n_match": len(rows),
            "rows": rows,
            "endpoint": "GET /v1/portfolio/positions",
        }
    except Exception as exc:
        out["polymarket_positions"] = {"error": type(exc).__name__}

    kalshi_rows = []
    kalshi_pages = []
    try:
        cursor = ""
        for _ in range(4):
            query = {"limit": "200", "min_ts": str(int(datetime(2026, 10, 24, 13, 0, tzinfo=ET).timestamp()))}
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
                if not isinstance(item, dict):
                    continue
                blob = json.dumps(item, default=str).lower()
                if "guaj" in blob or "guaale" in blob or ("brain" in blob and "lachlan" in blob):
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
            {"status": "filled", "timestamp": int(datetime(2026, 10, 24, 13, 0, tzinfo=ET).timestamp() * 1000)},
            timeout=20,
        )
        data = json.loads(text) if text and status == 200 else {}
        orders = data.get("orders") if isinstance(data, dict) else []
        if not isinstance(orders, list):
            orders = []
        rows = []
        for item in orders:
            blob = json.dumps(item, default=str).lower()
            if "guaj" in blob or "brain" in blob:
                rows.append({"symbol": item.get("symbol") or item.get("ticker")})
        out["gemini"] = {
            "http": status,
            "n_hist": len(orders),
            "n_match": len(rows),
            "rows": rows,
            "endpoint": "POST /v1/prediction-markets/orders/history",
        }
    except Exception as exc:
        out["gemini"] = {"error": type(exc).__name__}

    novig_rows = []
    try:
        status, text = novig_live.list_fills(
            {
                "limit": "200",
                "startsAfter": str(int(datetime(2026, 10, 24, 13, 0, tzinfo=ET).timestamp() * 1000) - 1),
                "startsBefore": str(int(datetime(2026, 10, 24, 14, 30, tzinfo=ET).timestamp() * 1000)),
            },
            timeout=20,
        )
        data = json.loads(text) if text and status == 200 else {}
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            blob = json.dumps(item, default=str).lower()
            if "guaj" in blob or "brain" in blob or "guaale" in blob:
                novig_rows.append({"orderId": item.get("orderId"), "qty": item.get("qty")})
        out["novig"] = {
            "http": status,
            "n": len(novig_rows),
            "rows": novig_rows,
            "endpoint": "GET /v3/portfolio/fills",
        }
    except Exception as exc:
        out["novig"] = {"error": type(exc).__name__}
    return out


def main() -> int:
    local = extract_local()
    venues = pull_venues()
    payload = {
        "pulled_at": datetime.now(ET).isoformat(timespec="seconds"),
        "timezone": "America/New_York",
        "slug": SLUG,
        "order_ids": sorted(OIDS),
        "local": local,
        "venues": venues,
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("orders", len(local["orders"]), "order_io", len(local["order_io"]), "ticks", local["ticks_n"])
    poly = venues.get("polymarket") or {}
    print("poly", poly.get("n"), "pages", poly.get("http_pages"))
    print("poly_pos", (venues.get("polymarket_positions") or {}).get("n_match"))
    print("kalshi", (venues.get("kalshi") or {}).get("n"), "gemini", (venues.get("gemini") or {}).get("n_match"))
    watch = local.get("strategy_b_watch") or {}
    print("b_stage", watch.get("stage"), "note", watch.get("note"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
