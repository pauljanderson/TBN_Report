"""Extract Moreno vs Herrera Polymarket US fills. Read-only. No orders. No secrets."""
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

import polymarket_us_live  # noqa: E402
import venue_fill_confirm  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = RAW / "moreno_herrera_poly_extract_20261029.json"
FIXTURE = ROOT / "tools" / "fixtures" / "moreno_herrera_poly_20261028.json"
SLUG = "aec-utr-morale-cartho-2026-10-28"
OIDS = {"DCFF2ZM011N2", "DCFF326G11R3", "DCFGAH0011N2"}
NEEDLES = (
    "moreno",
    "herrera",
    "morale-cartho",
    "dcff2zm011n2",
    "dcff326g11r3",
    "dcfgah0011n2",
    "alejandro moreno",
    "cardona herrera",
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
                "commissionSpreadPx": order.get("commissionSpreadPx") or item.get("commissionSpreadPx"),
                "commissionNotionalCollected": order.get("commissionNotionalCollected")
                or item.get("commissionNotionalCollected"),
                "lastPx": item.get("lastPx") or order.get("lastPx"),
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
                "house_cash",
                "fee",
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
    res = item.get("positionResolution") if isinstance(item.get("positionResolution"), dict) else {}
    meta = trade.get("marketMetadata") if isinstance(trade.get("marketMetadata"), dict) else {}
    cash = trade.get("cash") if isinstance(trade.get("cash"), dict) else {}
    return {
        "type": item.get("type") or trade.get("type"),
        "slug": str(trade.get("marketSlug") or res.get("marketSlug") or ""),
        "title": str(meta.get("title") or ""),
        "outcome": str(meta.get("outcome") or ""),
        "intent": str(aggressor.get("intent") or trade.get("intent") or ""),
        "side": str(aggressor.get("side") or trade.get("side") or ""),
        "price": trade.get("price") or aggressor.get("price"),
        "qty": trade.get("qtyDecimal") if trade.get("qtyDecimal") not in (None, "") else trade.get("qty"),
        "fee": trade.get("fee") or agg_ex.get("fee"),
        "cash": cash,
        "create_time": _et(_parse(trade.get("createTime") or item.get("createTime") or res.get("updateTime"))),
        "aggressor_id": str(aggressor.get("id") or ""),
        "our_order_id": venue_fill_confirm._poly_our_order_id(item) if isinstance(item, dict) else "",
        "settlementPx": res.get("settlementPx") or item.get("settlementPx"),
        "before": res.get("beforePosition") or item.get("beforePosition"),
        "after": res.get("afterPosition") or item.get("afterPosition"),
    }


def _page_activities(types: str, slug: str | None = None, pages: int = 8) -> dict:
    poly_pages = []
    poly_rows = []
    cursor = ""
    for _ in range(pages):
        query = {
            "limit": "100",
            "types": types,
            "sortOrder": "SORT_ORDER_DESCENDING",
        }
        if slug:
            query["marketSlug"] = slug
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
            if slug and row["slug"] and row["slug"] != slug:
                continue
            poly_rows.append(row)
        cursor = str((data or {}).get("nextCursor") or "")
        if bool((data or {}).get("eof")) or not cursor or not batch:
            break
    return {"http_pages": poly_pages, "n": len(poly_rows), "rows": poly_rows}


def extract_local():
    orders = [row for row in _jsonl(RAW / "orders.jsonl") if _hit(row)]
    order_io = []
    for row in _jsonl(RAW / "order_io.jsonl"):
        if not _hit(row):
            continue
        request = row.get("request") if isinstance(row.get("request"), dict) else {}
        response = row.get("response") if isinstance(row.get("response"), dict) else {}
        oid = str(response.get("id") or request.get("id") or row.get("order_id") or "")
        order_io.append(
            {
                "timestamp": row.get("timestamp"),
                "venue": row.get("venue"),
                "kind": row.get("kind"),
                "http_status": row.get("http_status"),
                "order_id": oid,
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
                watch = {
                    k: item.get(k)
                    for k in (
                        "key",
                        "game",
                        "stage",
                        "venue",
                        "t0_when",
                        "listed_start",
                        "postponed_reason",
                        "postponed_at",
                        "note",
                        "t0_yes",
                        "last_order",
                    )
                }
                break
    return {"orders": orders, "order_io": order_io, "strategy_b_watch": watch}


def extract_venues():
    out = {}
    quoted = __import__("urllib.parse").parse.quote(SLUG, safe="")
    try:
        market = polymarket_us_live._get(f"{polymarket_us_live.GATEWAY}/v1/markets/{quoted}") or {}
        out["market"] = {
            "slug": SLUG,
            "state": (market.get("marketData") or {}).get("state") if isinstance(market.get("marketData"), dict) else market.get("state"),
            "settlementPx": ((market.get("marketData") or {}).get("stats") or {}).get("settlementPx")
            if isinstance(market.get("marketData"), dict)
            else market.get("settlementPx"),
            "title": (market.get("marketData") or {}).get("title") if isinstance(market.get("marketData"), dict) else market.get("title"),
            "yes_outcome": ((market.get("marketData") or {}).get("outcomes") or [{}])[0].get("name")
            if isinstance((market.get("marketData") or {}).get("outcomes"), list)
            else None,
            "raw_keys": sorted(market.keys())[:40] if isinstance(market, dict) else [],
            "marketData_keys": sorted((market.get("marketData") or {}).keys())[:40]
            if isinstance(market.get("marketData"), dict)
            else [],
        }
        md = market.get("marketData") if isinstance(market.get("marketData"), dict) else {}
        out["market"]["event_title"] = (md.get("event") or {}).get("title") if isinstance(md.get("event"), dict) else md.get("eventTitle")
        out["market"]["outcome"] = md.get("outcome") or (md.get("team") or {}).get("name")
        out["market_trim"] = {
            "marketData": {
                k: md.get(k)
                for k in ("marketSlug", "state", "title", "outcome", "eventTitle", "stats", "closed")
                if k in md
            }
        }
    except Exception as exc:
        out["market"] = {"error": type(exc).__name__}

    out["trades"] = _page_activities("ACTIVITY_TYPE_TRADE", SLUG)
    out["resolutions"] = _page_activities("ACTIVITY_TYPE_POSITION_RESOLUTION", SLUG, pages=3)
    try:
        status, text = polymarket_us_live.signed_json("GET", "/v1/portfolio/positions")
        data = json.loads(text) if text and status == 200 else {}
        hits = []
        for item in data.get("positions") or data.get("items") or []:
            if isinstance(item, dict) and _hit(item):
                hits.append(
                    {
                        "slug": item.get("marketSlug") or item.get("slug"),
                        "title": item.get("title") or item.get("eventTitle"),
                        "outcome": item.get("outcome") or item.get("outcomeName"),
                        "qty": item.get("qty") or item.get("quantity") or item.get("net"),
                        "net": item.get("net"),
                        "cost": item.get("cost") or item.get("cash"),
                    }
                )
        out["positions"] = {"http": status, "n_hit": len(hits), "rows": hits}
    except Exception as exc:
        out["positions"] = {"error": type(exc).__name__}

    try:
        recent = _page_activities("ACTIVITY_TYPE_TRADE", None, pages=4)
        moreno_rows = [row for row in recent.get("rows") or [] if _hit(row)]
        out["recent_moreno"] = {"http_pages": recent.get("http_pages"), "n": len(moreno_rows), "rows": moreno_rows}
    except Exception as exc:
        out["recent_moreno"] = {"error": type(exc).__name__}
    return out


def _fixture_from(local: dict, venues: dict) -> dict:
    fills = []
    for row in local.get("order_io") or []:
        oid = str(row.get("order_id") or "")
        if oid not in OIDS:
            continue
        fills.append(
            {
                "order_id": oid,
                "http_status": row.get("http_status"),
                "request": row.get("request"),
                "response": row.get("response"),
            }
        )
    market = venues.get("market_trim") or venues.get("market") or {}
    return {
        "slug": SLUG,
        "game": "Alejandro Moreno vs. Thomas Cardona Herrera",
        "kitchen_rows": [
            "2026-10-28 11:03:19 ET B flatten (close initial lock) Alejandro Moreno vs Thomas Cardona Herrera Poly Yes Moreno, Alejandro 0.86 fee 0.01 cash 0.87 HTTP 200 fill 1 postponed",
            "2026-10-28 10:59:51 ET B initial low Yes Cardona Herrera, Thomas 0.16 fee 0.01 cash 0.17 HTTP 200 fill 1 postponed",
            "2026-10-28 10:59:51 ET B initial Hi Yes Moreno, Alejandro 0.85 fee 0 fill 0.3 HTTP 200 confirm 0 missed send",
        ],
        "poly_book": market if "marketData" in market else {"marketData": market},
        "fills": fills,
        "trades": venues.get("trades", {}).get("rows") or [],
        "resolutions": venues.get("resolutions", {}).get("rows") or [],
        "positions": venues.get("positions", {}).get("rows") or [],
        "watch": local.get("strategy_b_watch") or {},
        "orders": [
            {
                k: row.get(k)
                for k in (
                    "event",
                    "order_id",
                    "step",
                    "side",
                    "side_label",
                    "limit_price",
                    "quote_price",
                    "confirm_qty",
                    "confirm_note",
                    "tape_qty",
                    "http_status",
                    "sent_at",
                    "instrument",
                )
            }
            for row in local.get("orders") or []
            if row.get("event") in {"sent", "flatten_filled", "skip"}
        ],
    }


def main() -> int:
    print("extract local", flush=True)
    local = extract_local()
    print(f"orders {len(local['orders'])} io {len(local['order_io'])}", flush=True)
    print("extract venues", flush=True)
    venues = extract_venues()
    payload = {
        "written_at": datetime.now(ET).isoformat(timespec="seconds"),
        "slug": SLUG,
        "local": {
            "n_orders": len(local["orders"]),
            "n_io": len(local["order_io"]),
            "watch_stage": (local.get("strategy_b_watch") or {}).get("stage"),
            "watch_reason": (local.get("strategy_b_watch") or {}).get("postponed_reason"),
            "io_ids": [row.get("order_id") for row in local["order_io"]],
        },
        "venues": {
            "market": venues.get("market"),
            "trades_n": (venues.get("trades") or {}).get("n"),
            "resolutions_n": (venues.get("resolutions") or {}).get("n"),
            "positions": venues.get("positions"),
            "recent_moreno_n": (venues.get("recent_moreno") or {}).get("n"),
        },
        "trades": venues.get("trades"),
        "resolutions": venues.get("resolutions"),
        "recent_moreno": venues.get("recent_moreno"),
        "order_io": local["order_io"],
        "orders": [
            {
                k: row.get(k)
                for k in (
                    "event",
                    "order_id",
                    "step",
                    "side",
                    "side_label",
                    "limit_price",
                    "quote_price",
                    "confirm_qty",
                    "confirm_note",
                    "tape_qty",
                    "http_status",
                    "sent_at",
                    "reason",
                    "instrument",
                )
            }
            for row in local["orders"]
        ],
        "watch": local.get("strategy_b_watch"),
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    fixture = _fixture_from(local, venues)
    FIXTURE.write_text(json.dumps(fixture, indent=2, default=str), encoding="utf-8")
    print(f"wrote {FIXTURE}", flush=True)
    print("market", json.dumps(venues.get("market"), default=str)[:800], flush=True)
    print("trades", (venues.get("trades") or {}).get("n"), flush=True)
    for row in (venues.get("trades") or {}).get("rows") or []:
        print(
            "TRADE",
            row.get("create_time"),
            row.get("our_order_id"),
            row.get("intent"),
            row.get("outcome"),
            "qty",
            row.get("qty"),
            "px",
            row.get("price"),
            "fee",
            row.get("fee"),
            flush=True,
        )
    for row in (venues.get("resolutions") or {}).get("rows") or []:
        print(
            "RES",
            row.get("create_time"),
            row.get("outcome"),
            "px",
            row.get("settlementPx"),
            "qty",
            row.get("qty"),
            "after",
            row.get("after"),
            flush=True,
        )
    print("positions", venues.get("positions"), flush=True)
    print("recent_moreno", (venues.get("recent_moreno") or {}).get("n"), flush=True)
    for row in (venues.get("recent_moreno") or {}).get("rows") or []:
        print(
            "RECENT",
            row.get("create_time"),
            row.get("slug"),
            row.get("outcome"),
            row.get("qty"),
            row.get("price"),
            row.get("our_order_id"),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
