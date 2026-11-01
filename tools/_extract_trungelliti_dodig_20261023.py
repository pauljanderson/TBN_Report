"""Extract Trungelliti vs Dodig tape + venue fills. Read-only. No orders. No secrets."""
from __future__ import annotations

import json
import sys
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
OUT = RAW / "trungelliti_dodig_extract_20261023.json"
SLUG = "aec-atp-martru-matdod-2026-10-23"
KALSHI = "KXATPCHALLENGERMATCH-26OCT23TRUDOD"
T0 = datetime(2026, 10, 23, 5, 3, 24, tzinfo=ET)
WINDOW_LO = datetime(2026, 10, 23, 4, 50, tzinfo=ET)
WINDOW_HI = datetime(2026, 10, 23, 7, 0, tzinfo=ET)
OIDS = {"D93BC89011N2", "D93BDNCG11TB", "D93BJMM091KJ"}


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


def _trim_poly_payload(payload):
    if not isinstance(payload, dict):
        return payload
    keep = {}
    for key in (
        "id", "state", "status", "cumQuantity", "leavesQuantity", "quantity",
        "avgPx", "price", "intent", "tif", "marketSlug", "side", "type",
        "lastShares", "fee", "executions", "_venue_confirm",
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
                "price": (order.get("price") or item.get("price")),
                "quantity": order.get("quantity") or item.get("quantity"),
            }
        )
    if execs:
        keep["executions_trim"] = execs
    confirm = payload.get("_venue_confirm")
    if isinstance(confirm, dict):
        keep["_venue_confirm"] = {
            k: confirm.get(k)
            for k in (
                "known", "qty", "avg_price", "note", "mismatch", "tape_qty",
                "order_id", "http", "house_fill",
            )
        }
    return keep


def extract_local():
    orders = []
    for row in _jsonl(RAW / "orders.jsonl"):
        blob = json.dumps(row, default=str)
        if SLUG in blob or any(oid in blob for oid in OIDS) or "Trungelliti" in blob or "trudod" in blob.lower() or "matdod" in blob:
            if "2026-10-23" in blob or any(oid in blob for oid in OIDS):
                orders.append(row)
    io_rows = []
    activity_keys = set()
    for row in _jsonl(RAW / "order_io.jsonl"):
        req = row.get("request") if isinstance(row.get("request"), dict) else {}
        resp = row.get("response") if isinstance(row.get("response"), dict) else {}
        slug = str(req.get("marketSlug") or "")
        oid = str(resp.get("id") or "")
        url = str((req.get("url") if isinstance(req, dict) else "") or "")
        hit = SLUG in slug or oid in OIDS or SLUG in url or any(oid in json.dumps(row, default=str) for oid in OIDS)
        if not hit:
            continue
        stamp = _parse(row.get("timestamp"))
        if stamp is not None and stamp < WINDOW_LO - timedelta(hours=2):
            continue
        kind = str(row.get("kind") or "")
        trimmed = {
            "timestamp": row.get("timestamp"),
            "venue": row.get("venue"),
            "kind": kind,
            "http_status": row.get("http_status"),
            "request": {
                k: req.get(k)
                for k in ("marketSlug", "type", "price", "quantity", "tif", "intent", "url")
                if k in req
            } if isinstance(req, dict) else {},
        }
        if kind == "order":
            trimmed["response"] = _trim_poly_payload(resp)
            trimmed["order_id"] = oid
        elif kind == "book":
            md = resp.get("marketData") if isinstance(resp.get("marketData"), dict) else {}
            bids = md.get("bids") or []
            asks = md.get("asks") or []
            trimmed["best_bid"] = bids[0] if bids else None
            trimmed["best_ask"] = asks[0] if asks else None
            trimmed["n_bids"] = len(bids)
            trimmed["n_asks"] = len(asks)
        else:
            trimmed["response_keys"] = sorted(resp.keys()) if isinstance(resp, dict) else type(resp).__name__
            if isinstance(resp, dict) and "activities" in resp:
                acts = resp.get("activities") or []
                trimmed["n_activities"] = len(acts)
                sample = acts[0] if acts else {}
                if isinstance(sample, dict):
                    activity_keys |= set(sample.keys())
                    trade = sample.get("trade") if isinstance(sample.get("trade"), dict) else {}
                    activity_keys |= {f"trade.{k}" for k in trade.keys()}
                slim = []
                for item in acts[:12]:
                    if not isinstance(item, dict):
                        continue
                    trade = item.get("trade") if isinstance(item.get("trade"), dict) else {}
                    slim.append(
                        {
                            "type": item.get("type"),
                            "keys": sorted(item.keys()),
                            "trade_keys": sorted(trade.keys()),
                            "id": trade.get("id") or item.get("id"),
                            "orderId": trade.get("orderId") or trade.get("order_id") or item.get("orderId"),
                            "marketSlug": trade.get("marketSlug"),
                            "qty": trade.get("qtyDecimal") or trade.get("qty"),
                            "price": trade.get("price"),
                            "intent": trade.get("intent") or item.get("intent"),
                            "side": trade.get("side") or item.get("side"),
                            "createTime": trade.get("createTime") or trade.get("updateTime"),
                        }
                    )
                trimmed["activities_slim"] = slim
        io_rows.append(trimmed)

    log_lines = []
    starts = []
    if (RAW / "strategy_b.log").exists():
        for line in (RAW / "strategy_b.log").read_text(encoding="utf-8").splitlines():
            if "strategy b start" in line or "strategy b exit" in line:
                starts.append(line)
            if "martru-matdod" in line or "Trungelliti" in line or "Dodig" in line or "trudod" in line:
                log_lines.append(line)

    watch = {}
    status = json.loads((RAW / "strategy_b_watch.json").read_text(encoding="utf-8"))
    for row in status.get("matches") or []:
        game = str(row.get("game") or "")
        key = str(row.get("key") or "")
        if "Trungelliti" in game or "Dodig" in game or "trudod" in key or "01a1602ead877e239640734d" in key:
            watch = row
            break

    ticks = []
    t0_books = []
    csv_path = RAW / "price_memory" / "csv" / "2026-10-23_tennis.csv"
    jsonl_path = RAW / "price_memory" / "2026-10-23" / "tennis.jsonl"
    sources = [jsonl_path]
    for path in sources:
        if not path.exists():
            continue
        for rec in _jsonl(path):
            game = str(rec.get("game") or "")
            if "Trungelliti" not in game and "Dodig" not in game and "trudod" not in game.lower():
                continue
            seen = _parse(rec.get("seen_at") or rec.get("ts") or rec.get("time"))
            ticks.append(
                {
                    "seen_at": rec.get("seen_at") or rec.get("ts"),
                    "seen_et": _et(seen),
                    "game": game,
                    "venue": rec.get("venue"),
                    "side": rec.get("side"),
                    "pay": rec.get("pay") or rec.get("outcome"),
                    "price": rec.get("price"),
                    "size": rec.get("size") or rec.get("qty"),
                    "source": rec.get("source"),
                }
            )
            if seen is not None and abs((seen - T0).total_seconds()) <= 8:
                t0_books.append(ticks[-1])

    checks = []
    for rec in _jsonl(RAW / "live_checks.jsonl"):
        blob = json.dumps(rec, default=str)
        if "Trungelliti" not in blob and "Dodig" not in blob and "trudod" not in blob.lower() and "matdod" not in blob:
            continue
        stamp = _parse(rec.get("compared_at") or rec.get("ts") or rec.get("time"))
        if stamp is None or stamp < WINDOW_LO or stamp > WINDOW_HI:
            continue
        checks.append(
            {
                "compared_at": rec.get("compared_at") or rec.get("ts"),
                "game": rec.get("game") or rec.get("title"),
                "net": rec.get("net"),
                "gross": rec.get("gross"),
                "yes_venue": rec.get("yes_venue"),
                "no_venue": rec.get("no_venue"),
                "side": rec.get("side"),
                "yes_price": rec.get("yes_price") or rec.get("yes"),
                "no_price": rec.get("no_price") or rec.get("no"),
            }
        )

    last = {}
    price_last = json.loads((RAW / "price_last.json").read_text(encoding="utf-8")) if (RAW / "price_last.json").exists() else {}
    for key, rec in price_last.items():
        if not isinstance(rec, dict):
            continue
        game = str(rec.get("game") or "")
        if "Trungelliti" in game or "Dodig" in game:
            last[key] = rec

    pid = {}
    if (RAW / "strategy_b.pid").exists():
        pid = json.loads((RAW / "strategy_b.pid").read_text(encoding="utf-8"))

    health = {}
    hp = RAW / "live_health" / "tennis_trudod_2026_10_23.json"
    if hp.exists():
        health = json.loads(hp.read_text(encoding="utf-8"))
    job = {}
    jp = RAW / "live_jobs" / "tennis_trudod_2026_10_23.json"
    if jp.exists():
        job = json.loads(jp.read_text(encoding="utf-8"))

    return {
        "orders": orders,
        "order_io": io_rows,
        "activity_keys": sorted(activity_keys),
        "log_lines": log_lines,
        "starts": starts[-12:],
        "watch": watch,
        "t0_books": t0_books,
        "ticks_n": len(ticks),
        "ticks": ticks,
        "checks": checks[:80],
        "price_last": last,
        "pid_file": pid,
        "health": {
            "expected": health.get("expected"),
            "transport": health.get("transport"),
            "updated_at": health.get("updated_at"),
            "pid": health.get("pid"),
        },
        "job": {
            "key": job.get("key"),
            "title": job.get("title"),
            "start": job.get("start"),
            "kalshi": ((job.get("game") or {}).get("kalshi") if isinstance(job.get("game"), dict) else None),
            "listed_start": (job.get("game") or {}).get("listed_start") if isinstance(job.get("game"), dict) else None,
        },
    }


def _poly_amount(value):
    if isinstance(value, dict):
        return value.get("value")
    return value


def pull_venues():
    out = {}
    # Polymarket activities for this slug, recent pages.
    poly_rows = []
    poly_pages = []
    sample_keys = set()
    cursor = ""
    try:
        for _ in range(8):
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
                sample_keys |= set(item.keys())
                sample_keys |= {f"trade.{k}" for k in trade.keys()}
                stamp = _parse(trade.get("createTime") or trade.get("updateTime"))
                slug = str(trade.get("marketSlug") or "")
                if slug and slug != SLUG:
                    continue
                poly_rows.append(
                    {
                        "time_et": _et(stamp),
                        "slug": slug,
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
                        "state": str(trade.get("state") or ""),
                        "keys": sorted(trade.keys()),
                    }
                )
            cursor = str((data or {}).get("nextCursor") or "")
            if bool((data or {}).get("eof")) or not cursor or not batch:
                break
        out["polymarket"] = {
            "http_pages": poly_pages,
            "n": len(poly_rows),
            "rows": poly_rows,
            "sample_keys": sorted(sample_keys),
            "endpoint": "GET /v1/portfolio/activities",
        }
    except Exception as exc:
        out["polymarket"] = {"error": type(exc).__name__, "http_pages": poly_pages}

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
            if SLUG not in blob and "Trungelliti" not in blob and "Dodig" not in blob:
                continue
            rows.append(
                {
                    k: item.get(k)
                    for k in (
                        "marketSlug", "title", "outcome", "netPosition", "quantity",
                        "avgPx", "realizedPnl", "unrealizedPnl", "status", "result",
                    )
                    if k in item
                } | {"keys": sorted(item.keys())[:40]}
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
        cursor = ""
        for _ in range(6):
            query = {
                "ticker": KALSHI,
                "min_ts": str(int(WINDOW_LO.timestamp()) - 3600),
                "limit": "200",
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
                if not isinstance(item, dict):
                    continue
                ticker = str(item.get("ticker") or "")
                if KALSHI not in ticker and "TRUDOD" not in ticker:
                    continue
                kalshi_rows.append(
                    {
                        "ticker": ticker,
                        "order_id": item.get("order_id"),
                        "count": item.get("count_fp") or item.get("count"),
                        "yes_price": item.get("yes_price_dollars"),
                        "no_price": item.get("no_price_dollars"),
                        "side": item.get("side") or item.get("outcome_side"),
                        "created": item.get("created_time") or item.get("ts"),
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
            if "trung" in blob or "dodig" in blob or "trudod" in blob:
                rows.append({"keys": sorted(item.keys())[:30], "symbol": item.get("symbol") or item.get("ticker")})
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
                novig_pages[-1]["body_prefix"] = (text or "")[:120]
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
                blob = json.dumps(item, default=str)
                if "trung" not in blob.lower() and "dodig" not in blob.lower() and "01a1602ead877e239640734d" not in blob:
                    continue
                novig_rows.append(
                    {
                        "orderId": item.get("orderId"),
                        "qty": item.get("qty"),
                        "cost": item.get("cost"),
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
        "kalshi_ticker": KALSHI,
        "local": local,
        "venues": venues,
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("orders", len(local["orders"]), "order_io", len(local["order_io"]), "ticks", local["ticks_n"])
    print("poly", (venues.get("polymarket") or {}).get("n"), "kalshi", (venues.get("kalshi") or {}).get("n"))
    print("activity_keys", local.get("activity_keys"))
    print("poly_keys", (venues.get("polymarket") or {}).get("sample_keys"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
