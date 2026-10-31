"""Extract Moutet vs Paul T0 tape + venue fills. Read-only. No orders. No secrets."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
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
OUT = RAW / "moutet_paul_t0_extract_20261023.json"
SLUG = "aec-atp-cormou-tompau-2026-10-23"
KALSHI_EVENT = "KXATPMATCH-26OCT23MOUPAU"
KALSHI_MOU = "KXATPMATCH-26OCT23MOUPAU-MOU"
KALSHI_PAU = "KXATPMATCH-26OCT23MOUPAU-PAU"
T0 = datetime(2026, 10, 23, 7, 59, 52, tzinfo=ET)
WINDOW_LO = datetime(2026, 10, 23, 7, 40, tzinfo=ET)
WINDOW_HI = datetime(2026, 10, 23, 12, 30, tzinfo=ET)
ONE = Decimal("1")
CENT = Decimal("0.01")
THETA = Decimal("0.0695")


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
        "moutet" in low
        or "moupau" in low
        or "cormou" in low
        or "tompau" in low
        or KALSHI_EVENT.lower() in low
        or SLUG in low
    )


def _poly_fee(price):
    px = _dec(price)
    if px is None:
        return None
    exact = THETA * ONE * px * (ONE - px)
    return exact.quantize(CENT, rounding=ROUND_HALF_EVEN)


def extract_local():
    orders = []
    for row in _jsonl(RAW / "orders.jsonl"):
        blob = json.dumps(row, default=str)
        if _hit_game(blob):
            stamp = _parse(row.get("ts") or row.get("time") or row.get("timestamp"))
            if stamp is None or stamp >= WINDOW_LO:
                orders.append(row)

    io_rows = []
    for row in _jsonl(RAW / "order_io.jsonl"):
        req = row.get("request") if isinstance(row.get("request"), dict) else {}
        resp = row.get("response") if isinstance(row.get("response"), dict) else {}
        blob = json.dumps(row, default=str)
        if not _hit_game(blob):
            continue
        stamp = _parse(row.get("timestamp"))
        if stamp is not None and stamp < WINDOW_LO - timedelta(hours=1):
            continue
        kind = str(row.get("kind") or "")
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
                    "marketSlug",
                    "intent",
                    "quantity",
                    "type",
                    "tif",
                    "url",
                    "client_order_id",
                )
                if k in req
            },
        }
        if kind == "order":
            trimmed["response"] = {
                k: resp.get(k)
                for k in (
                    "order_id",
                    "client_order_id",
                    "fill_count",
                    "average_fill_price",
                    "average_fee_paid",
                    "remaining_count",
                    "ts_ms",
                    "id",
                    "state",
                    "status",
                    "cumQuantity",
                    "avgPx",
                    "fee",
                    "intent",
                )
                if k in resp
            }
            trimmed["order_id"] = resp.get("order_id") or resp.get("id") or ""
        elif kind == "book":
            book = resp.get("orderbook_fp") if isinstance(resp.get("orderbook_fp"), dict) else {}
            yes = book.get("yes_dollars") or []
            no = book.get("no_dollars") or []
            trimmed["best_yes"] = yes[0] if yes else None
            trimmed["best_no"] = no[0] if no else None
            trimmed["url"] = req.get("url")
        io_rows.append(trimmed)

    log_lines = []
    starts = []
    if (RAW / "strategy_b.log").exists():
        for line in (RAW / "strategy_b.log").read_text(encoding="utf-8").splitlines():
            if "strategy b start" in line or "strategy b exit" in line:
                starts.append(line)
            if _hit_game(line):
                log_lines.append(line)

    watch = {}
    status = json.loads((RAW / "strategy_b_watch.json").read_text(encoding="utf-8"))
    skipped = []
    for row in status.get("matches") or []:
        game = str(row.get("game") or "")
        key = str(row.get("key") or "")
        if "Moutet" in game or "moupau" in key or "Paul" in game and "Moutet" in game:
            watch = row
            break
    for row in status.get("skipped") or []:
        game = str(row.get("game") or "")
        if "Moutet" in game or "Paul @" in game and "Moutet" in game:
            skipped.append(row)

    ticks = []
    t0_books = []
    max_moutet_yes = {}
    jsonl_path = RAW / "price_memory" / "2026-10-23" / "tennis.jsonl"
    if jsonl_path.exists():
        for rec in _jsonl(jsonl_path):
            game = str(rec.get("game") or "")
            if "Moutet" not in game and "moupau" not in game.lower():
                continue
            seen = _parse(rec.get("seen_at") or rec.get("ts") or rec.get("time"))
            slim = {
                "seen_at": rec.get("seen_at") or rec.get("ts"),
                "seen_et": _et(seen),
                "game": game,
                "venue": rec.get("venue"),
                "side": rec.get("side"),
                "pay": rec.get("pay") or rec.get("outcome"),
                "price": rec.get("price"),
                "phase": rec.get("phase"),
            }
            if seen is not None and WINDOW_LO - timedelta(minutes=10) <= seen <= WINDOW_HI:
                ticks.append(slim)
            if seen is not None and abs((seen - T0).total_seconds()) <= 20:
                t0_books.append(slim)
            if (
                str(rec.get("pay") or "").lower() == "yes"
                and "moutet" in str(rec.get("side") or "").lower()
                and seen is not None
                and seen >= T0
            ):
                venue = str(rec.get("venue") or "")
                px = _dec(rec.get("price"))
                if px is None:
                    continue
                prev = max_moutet_yes.get(venue)
                if prev is None or px > _dec(prev.get("price")):
                    max_moutet_yes[venue] = slim

    last_before_t0 = {}
    for rec in ticks:
        seen = _parse(rec.get("seen_at"))
        if seen is None or seen > T0 + timedelta(seconds=2):
            continue
        if seen < T0 - timedelta(minutes=8):
            continue
        key = "|".join(
            [
                str(rec.get("game") or ""),
                str(rec.get("venue") or ""),
                str(rec.get("side") or ""),
                str(rec.get("pay") or ""),
            ]
        )
        prev = last_before_t0.get(key)
        prev_seen = _parse((prev or {}).get("seen_at"))
        if prev is None or (prev_seen is not None and seen >= prev_seen):
            last_before_t0[key] = rec

    pid = {}
    if (RAW / "strategy_b.pid").exists():
        pid = json.loads((RAW / "strategy_b.pid").read_text(encoding="utf-8"))

    job = {}
    jp = RAW / "live_jobs" / "tennis_moupau_2026_10_23.json"
    if jp.exists():
        job = json.loads(jp.read_text(encoding="utf-8"))

    health = {}
    hp = RAW / "live_health" / "tennis_moupau_2026_10_23.json"
    if hp.exists():
        health = json.loads(hp.read_text(encoding="utf-8"))

    last = {}
    price_last = json.loads((RAW / "price_last.json").read_text(encoding="utf-8")) if (RAW / "price_last.json").exists() else {}
    for key, rec in price_last.items():
        if not isinstance(rec, dict):
            continue
        game = str(rec.get("game") or "")
        if "Moutet" in game:
            last[key] = rec

    qf_slug = ""
    for path in (RAW / "live_jobs").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = str(data.get("title") or "")
        if "Tommy Paul @ Corentin Moutet" in title or "Corentin Moutet Quarterfinals" in title:
            game = data.get("game") if isinstance(data.get("game"), dict) else {}
            markets = game.get("polymarket_markets") or []
            if markets and isinstance(markets[0], dict):
                qf_slug = str(markets[0].get("slug") or "")
            break

    return {
        "orders": orders,
        "order_io": io_rows,
        "log_lines": log_lines,
        "starts": starts[-20:],
        "watch": watch,
        "skipped": skipped,
        "t0_books": t0_books,
        "last_before_t0": last_before_t0,
        "ticks_n": len(ticks),
        "ticks": ticks,
        "max_moutet_yes_after_t0": max_moutet_yes,
        "price_last": last,
        "pid_file": pid,
        "novig_orders_live_now": bool(novig_live.orders_live()),
        "watch_open_n": status.get("currently_open"),
        "watch_pid": status.get("pid"),
        "watch_updated": status.get("updated_at"),
        "health": {
            "transport": health.get("transport"),
            "last_poll": health.get("last_poll"),
            "pid": health.get("pid"),
        },
        "job": {
            "key": job.get("key"),
            "title": job.get("title"),
            "start": job.get("start"),
            "kalshi": ((job.get("game") or {}).get("kalshi") if isinstance(job.get("game"), dict) else None),
            "gemini": ((job.get("game") or {}).get("gemini") if isinstance(job.get("game"), dict) else None),
            "listed_start": (job.get("game") or {}).get("listed_start") if isinstance(job.get("game"), dict) else None,
            "polymarket_markets": (job.get("game") or {}).get("polymarket_markets") if isinstance(job.get("game"), dict) else None,
        },
        "qf_slug": qf_slug,
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


def pull_venues(qf_slug: str):
    out = {}
    out["polymarket_cormou"] = _poly_fills(SLUG)
    if qf_slug and qf_slug != SLUG:
        out["polymarket_qf"] = _poly_fills(qf_slug)
    else:
        out["polymarket_qf"] = {"n": 0, "rows": [], "note": "no separate quarterfinals slug in live_jobs"}

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
        for ticker in (KALSHI_MOU, KALSHI_PAU, KALSHI_EVENT):
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
                    kalshi_pages[-1]["body_prefix"] = (text or "")[:160]
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
                    kalshi_rows.append(
                        {
                            "ticker": found,
                            "order_id": item.get("order_id"),
                            "trade_id": item.get("trade_id"),
                            "count": item.get("count_fp") or item.get("count"),
                            "yes_price": item.get("yes_price_dollars") or item.get("yes_price"),
                            "no_price": item.get("no_price_dollars") or item.get("no_price"),
                            "side": item.get("side") or item.get("action") or item.get("outcome_side"),
                            "is_taker": item.get("is_taker"),
                            "fee_cost": item.get("fee_cost") or item.get("taker_fees") or item.get("fee"),
                            "created": item.get("created_time") or item.get("ts"),
                            "keys": sorted(item.keys())[:40],
                        }
                    )
                cursor = str(data.get("cursor") or "")
                if not cursor or not batch:
                    break
        seen_ids = set()
        unique = []
        for row in kalshi_rows:
            key = (row.get("order_id"), row.get("trade_id"), row.get("ticker"), row.get("created"))
            if key in seen_ids:
                continue
            seen_ids.add(key)
            unique.append(row)
        out["kalshi"] = {
            "http_pages": kalshi_pages,
            "n": len(unique),
            "rows": unique,
            "endpoint": "GET /trade-api/v2/portfolio/fills",
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
                | {"keys": sorted(item.keys())[:40]}
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
            if "moutet" in blob or "moupau" in blob or "cormou" in blob:
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
                if "moutet" not in blob and "moupau" not in blob and "cormou" not in blob:
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
    venues = pull_venues(str(local.get("qf_slug") or ""))
    payload = {
        "pulled_at": datetime.now(ET).isoformat(timespec="seconds"),
        "timezone": "America/New_York",
        "slug": SLUG,
        "kalshi_event": KALSHI_EVENT,
        "t0_quote": T0.isoformat(),
        "poly_fee_theta": str(THETA),
        "local": local,
        "venues": venues,
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("orders", len(local["orders"]), "order_io", len(local["order_io"]), "ticks", local["ticks_n"])
    print("t0_books", len(local["t0_books"]), "last_before", len(local["last_before_t0"]))
    print("kalshi fills", (venues.get("kalshi") or {}).get("n"), "poly", (venues.get("polymarket_cormou") or {}).get("n"))
    print("gemini match", (venues.get("gemini") or {}).get("n_match"), "novig", (venues.get("novig") or {}).get("n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
