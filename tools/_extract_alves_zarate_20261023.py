"""Extract Meligeni Alves vs Zarate B + lock tape + venue fills. Read-only. No orders. No secrets."""
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
OUT = RAW / "alves_zarate_extract_20261023.json"
SLUG = "aec-atp-felalv-carzar-2026-10-23"
KALSHI_EVENT = "KXATPCHALLENGERMATCH-26OCT23MELZAR"
KALSHI_MEL = "KXATPCHALLENGERMATCH-26OCT23MELZAR-MEL"
KALSHI_ZAR = "KXATPCHALLENGERMATCH-26OCT23MELZAR-ZAR"
LISTED = datetime(2026, 10, 23, 11, 0, tzinfo=ET)
WINDOW_LO = datetime(2026, 10, 23, 10, 30, tzinfo=ET)
WINDOW_HI = datetime(2026, 10, 23, 15, 30, tzinfo=ET)
CROSS = Decimal("0.50")


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
        "meligeni" in low
        or "zarate" in low
        or "melzar" in low
        or "felalv" in low
        or "carzar" in low
        or KALSHI_EVENT.lower() in low
        or SLUG in low
    )


def _is_zarate(side: str) -> bool:
    low = str(side or "").lower()
    return "zarate" in low


def _is_alves(side: str) -> bool:
    low = str(side or "").lower()
    return "alves" in low or "meligeni" in low


def extract_local():
    orders = []
    for row in _jsonl(RAW / "orders.jsonl"):
        blob = json.dumps(row, default=str)
        if _hit_game(blob):
            orders.append(row)

    io_rows = []
    for row in _jsonl(RAW / "order_io.jsonl"):
        blob = json.dumps(row, default=str)
        if not _hit_game(blob):
            continue
        req = row.get("request") if isinstance(row.get("request"), dict) else {}
        resp = row.get("response") if isinstance(row.get("response"), dict) else {}
        confirm = row.get("confirm") if isinstance(row.get("confirm"), dict) else {}
        kind = str(row.get("kind") or "")
        trimmed = {
            "timestamp": row.get("timestamp"),
            "venue": row.get("venue"),
            "kind": kind,
            "http_status": row.get("http_status"),
            "quote_price": row.get("quote_price"),
            "quote_seen_at": row.get("quote_seen_at"),
            "sent_at": row.get("sent_at"),
            "lag_seconds": row.get("lag_seconds"),
            "intent": row.get("intent") or req.get("intent") or resp.get("intent"),
            "outcome": row.get("outcome") or req.get("outcome") or resp.get("outcome"),
            "side": row.get("side") or req.get("side"),
            "player": row.get("player") or req.get("player") or row.get("outcome_name"),
            "game": row.get("game"),
            "strategy": row.get("strategy") or row.get("_strategy_b"),
            "flatten": row.get("flatten") or row.get("is_flatten"),
            "request": {
                k: req.get(k)
                for k in (
                    "ticker",
                    "side",
                    "action",
                    "count",
                    "price",
                    "yes_price",
                    "no_price",
                    "time_in_force",
                    "client_order_id",
                    "type",
                    "orderType",
                    "intent",
                    "outcome",
                    "qty",
                    "limitPrice",
                    "symbol",
                    "marketSlug",
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
                    "status",
                    "state",
                    "cumQuantity",
                    "avgPx",
                    "fee",
                    "message",
                    "error",
                    "ts_ms",
                    "id",
                )
                if k in resp
            },
            "confirm": {
                k: confirm.get(k)
                for k in (
                    "qty",
                    "fill_qty",
                    "price",
                    "fee",
                    "order_id",
                    "status",
                    "http_status",
                )
                if k in confirm
            },
        }
        trimmed["order_id"] = (
            resp.get("order_id")
            or resp.get("id")
            or req.get("client_order_id")
            or ""
        )
        io_rows.append(trimmed)

    log_lines = []
    if (RAW / "strategy_b.log").exists():
        for line in (RAW / "strategy_b.log").read_text(encoding="utf-8").splitlines():
            if _hit_game(line):
                log_lines.append(line)

    supervisor_hits = []
    if (RAW / "live_supervisor.log").exists():
        for line in (RAW / "live_supervisor.log").read_text(encoding="utf-8").splitlines():
            if _hit_game(line):
                supervisor_hits.append(line)

    watch = {}
    watch_all_keys = []
    watch_open = []
    status = {}
    if (RAW / "strategy_b_watch.json").exists():
        status = json.loads((RAW / "strategy_b_watch.json").read_text(encoding="utf-8"))
        for row in status.get("matches") or []:
            game = str(row.get("game") or "")
            key = str(row.get("key") or "")
            watch_all_keys.append(
                {
                    "key": key,
                    "game": game,
                    "stage": row.get("stage"),
                    "stopped": row.get("stopped"),
                    "t0_dog_player": row.get("t0_dog_player") or row.get("dog_player"),
                    "t0_fav_player": row.get("t0_fav_player") or row.get("fav_player"),
                    "note": row.get("note"),
                    "updated_at": row.get("updated_at") or row.get("last_seen"),
                }
            )
            if str(row.get("stage") or "") not in {"", "done", "abandoned", "absorbed"} and not row.get("stopped"):
                watch_open.append(watch_all_keys[-1])
            if "Zarate" in game or "Meligeni" in game or "melzar" in key.lower():
                watch = row

    considerations = []
    cons_path = RAW / "considerations.json"
    if cons_path.exists():
        try:
            data = json.loads(cons_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        rows = data.get("rows") if isinstance(data, dict) else data
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                blob = json.dumps(row, default=str)
                if _hit_game(blob):
                    considerations.append(row)

    opportunities = []
    for path in (
        RAW / "opportunities.jsonl",
        RAW / "live_opportunities.jsonl",
        RAW / "opportunity.jsonl",
    ):
        if not path.exists():
            continue
        for row in _jsonl(path):
            blob = json.dumps(row, default=str)
            if _hit_game(blob):
                opportunities.append({"_src": path.name, **row})

    zarate_over_50 = []
    zarate_yes_series = []
    alves_yes_series = []
    last_by_key = {}
    first_over = []
    jsonl_path = RAW / "price_memory" / "2026-10-23" / "tennis.jsonl"
    if jsonl_path.exists():
        last_zarate = {}
        for rec in _jsonl(jsonl_path):
            game = str(rec.get("game") or "")
            if "Zarate" not in game and "Meligeni" not in game:
                continue
            seen = _parse(rec.get("seen_at") or rec.get("ts") or rec.get("time"))
            if seen is None:
                continue
            pay = str(rec.get("pay") or rec.get("side_pay") or "").lower()
            side = str(rec.get("side") or rec.get("player") or rec.get("outcome") or "")
            venue = str(rec.get("venue") or "")
            px = _dec(rec.get("price") or rec.get("last") or rec.get("ask") or rec.get("yes_ask"))
            slim = {
                "seen_at": rec.get("seen_at"),
                "seen_et": _et(seen),
                "venue": venue,
                "side": side,
                "pay": pay or rec.get("pay"),
                "price": str(px) if px is not None else rec.get("price"),
                "last": rec.get("last") or rec.get("last_price"),
                "ask": rec.get("ask") or rec.get("yes_ask") or rec.get("price"),
                "bid": rec.get("bid") or rec.get("yes_bid"),
                "phase": rec.get("phase"),
                "keys": sorted(k for k in rec.keys() if k not in {"ticks", "history"}),
            }
            key = "|".join([venue.lower(), side.lower(), (pay or "yes")])
            last_by_key[key] = slim
            if pay not in ("", "yes"):
                continue
            if _is_zarate(side):
                zarate_yes_series.append(slim)
                if px is not None and px > CROSS:
                    prev = last_zarate.get(venue.lower())
                    from_below = prev is None or prev <= CROSS
                    episode = {
                        **slim,
                        "from_below": from_below,
                        "prev_px": str(prev) if prev is not None else "",
                    }
                    zarate_over_50.append(episode)
                    if from_below:
                        first_over.append(episode)
                    last_zarate[venue.lower()] = px
                elif px is not None:
                    last_zarate[venue.lower()] = px
            elif _is_alves(side):
                alves_yes_series.append(slim)

    pid = {}
    if (RAW / "strategy_b.pid").exists():
        try:
            pid = json.loads((RAW / "strategy_b.pid").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pid = {"raw": (RAW / "strategy_b.pid").read_text(encoding="utf-8")[:200]}

    job = {}
    jp = RAW / "live_jobs" / "tennis_melzar_2026_10_23.json"
    if jp.exists():
        job = json.loads(jp.read_text(encoding="utf-8"))

    lock_skip = {}
    if (RAW / "lock_last_skip.json").exists():
        try:
            skip_data = json.loads((RAW / "lock_last_skip.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skip_data = {}
        if isinstance(skip_data, dict):
            blob = json.dumps(skip_data, default=str)
            if _hit_game(blob):
                lock_skip = skip_data
            else:
                for key, val in skip_data.items():
                    if _hit_game(str(key)) or _hit_game(json.dumps(val, default=str)):
                        lock_skip[key] = val

    return {
        "orders": orders,
        "order_io": io_rows,
        "log_lines": log_lines,
        "supervisor_hits": supervisor_hits[-400:],
        "supervisor_n": len(supervisor_hits),
        "watch": watch,
        "watch_all_keys": watch_all_keys,
        "watch_open": watch_open,
        "watch_open_n": status.get("currently_open"),
        "watch_pid": status.get("pid"),
        "watch_updated": status.get("updated_at"),
        "considerations": considerations,
        "opportunities": opportunities,
        "zarate_over_50": zarate_over_50,
        "zarate_over_50_first_from_below": first_over,
        "zarate_yes_n": len(zarate_yes_series),
        "alves_yes_n": len(alves_yes_series),
        "zarate_yes_head": zarate_yes_series[:8],
        "zarate_yes_tail": zarate_yes_series[-12:],
        "alves_yes_head": alves_yes_series[:8],
        "alves_yes_tail": alves_yes_series[-12:],
        "last_by_key": last_by_key,
        "pid_file": pid,
        "lock_skip": lock_skip,
        "novig_orders_live_now": bool(novig_live.orders_live()),
        "job": {
            "key": job.get("key"),
            "title": job.get("title"),
            "start": job.get("start"),
            "kalshi": ((job.get("game") or {}).get("kalshi") if isinstance(job.get("game"), dict) else None),
            "listed_start": (job.get("game") or {}).get("listed_start") if isinstance(job.get("game"), dict) else None,
            "period": (job.get("game") or {}).get("period") if isinstance(job.get("game"), dict) else None,
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
                        "fee": str(_poly_amount(trade.get("fee") or trade.get("fees")) or ""),
                        "intent": str(trade.get("intent") or item.get("intent") or ""),
                        "side": str(trade.get("side") or item.get("side") or ""),
                        "outcome": str(trade.get("outcome") or item.get("outcome") or ""),
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
        "book_side",
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
        for ticker in (KALSHI_MEL, KALSHI_ZAR, KALSHI_EVENT):
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

    settlements = []
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
        for item in rows if isinstance(rows, list) else []:
            blob = json.dumps(item, default=str)
            if KALSHI_EVENT not in blob:
                continue
            settlements.append(item)
        out["kalshi_settlements"] = {
            "http": status,
            "n": len(settlements),
            "rows": settlements,
            "endpoint": "GET /trade-api/v2/portfolio/settlements",
            "body_prefix": (text or "")[:180] if status != 200 else "",
        }
    except Exception as exc:
        out["kalshi_settlements"] = {"error": type(exc).__name__}

    markets = []
    for ticker in (KALSHI_MEL, KALSHI_ZAR):
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
            if "zarate" in blob or "meligeni" in blob or "melzar" in blob or "felalv" in blob:
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
                if "zarate" not in blob and "meligeni" not in blob and "melzar" not in blob:
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
        "listed_start": LISTED.isoformat(),
        "local": local,
        "venues": venues,
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("orders", len(local["orders"]), "order_io", len(local["order_io"]))
    print("b_log", len(local["log_lines"]), "watch_game", (local.get("watch") or {}).get("game"))
    print("considerations", len(local["considerations"]), "opps", len(local["opportunities"]))
    print("zarate>50", len(local["zarate_over_50"]), "from_below", len(local["zarate_over_50_first_from_below"]))
    print("kalshi fills", (venues.get("kalshi") or {}).get("n"))
    print("poly", (venues.get("polymarket") or {}).get("n"), "gemini", (venues.get("gemini") or {}).get("n_match"), "novig", (venues.get("novig") or {}).get("n"))
    print("markets", venues.get("kalshi_markets"))
    print("watch_open_n", local.get("watch_open_n"), "pid", local.get("watch_pid"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
