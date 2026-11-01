"""Extract Chin vs Kuhar Polymarket US fills. Read-only. No orders. No secrets."""
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
OUT = RAW / "chin_kuhar_poly_extract_20261029.json"
FIXTURE = ROOT / "tools" / "fixtures" / "chin_kuhar_poly_20261028.json"
SLUG = "aec-itfme-johchi-matkuh-2026-10-28"
OIDS = {"DCCWHAK011MM", "DCCWHE2G11M3"}
NEEDLES = (
    "kuhar",
    "johchi-matkuh",
    "john chin",
    "matt kuhar",
    "dccwhak011mm",
    "dccwhe2g11m3",
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
        "state": str(aggressor.get("state") or trade.get("state") or item.get("state") or ""),
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
        md = market.get("marketData") if isinstance(market.get("marketData"), dict) else {}
        stats = md.get("stats") if isinstance(md.get("stats"), dict) else {}
        outcomes = md.get("outcomes") if isinstance(md.get("outcomes"), list) else []
        out["market"] = {
            "slug": SLUG,
            "state": md.get("state") or market.get("state"),
            "settlementPx": stats.get("settlementPx") or md.get("settlementPx") or market.get("settlementPx"),
            "title": md.get("title") or market.get("title"),
            "yes_outcome": (outcomes[0] or {}).get("name") if outcomes else None,
            "event_title": (md.get("event") or {}).get("title") if isinstance(md.get("event"), dict) else md.get("eventTitle"),
            "outcome": md.get("outcome") or ((md.get("team") or {}).get("name") if isinstance(md.get("team"), dict) else None),
        }
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

    order_gets = []
    for oid in sorted(OIDS):
        try:
            status, text = polymarket_us_live.signed_json("GET", f"/v1/orders/{oid}", timeout=15)
            parsed = None
            try:
                parsed = json.loads(text) if text and status == 200 else None
            except json.JSONDecodeError:
                parsed = None
            trim = _trim_poly_payload(parsed) if isinstance(parsed, dict) else None
            order_gets.append(
                {
                    "order_id": oid,
                    "http": status,
                    "body_prefix": (text or "")[:180] if status != 200 else "",
                    "trim": trim,
                }
            )
        except Exception as exc:
            order_gets.append({"order_id": oid, "error": type(exc).__name__})
    out["order_gets"] = order_gets
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
    market = venues.get("market") or {}
    px = market.get("settlementPx")
    px_s = ""
    if isinstance(px, dict):
        px_s = str(px.get("value") or "")
    elif px not in (None, ""):
        px_s = str(px)
    result = ""
    try:
        number = Decimal(px_s)
        if number >= 1:
            result = "yes"
        elif number <= 0:
            result = "no"
    except Exception:
        result = ""
    winner = "Matt Kuhar" if result == "no" else ("John Chin" if result == "yes" else "")
    return {
        "slug": SLUG,
        "game": "John Chin vs. Matt Kuhar",
        "official_winner": winner or "Matt Kuhar",
        "official_score": "4-6 6-1 6-1",
        "official_event": "ITF M15 Pembroke R32, 28 Oct 2026",
        "poly_settlement": {
            "settlementPx": px_s,
            "result": result,
            "state": market.get("state"),
            "yes_outcome": market.get("yes_outcome") or "John Chin",
        },
        "poly_book": venues.get("market_trim") or {"marketData": market},
        "kitchen_rows": [
            "2026-10-28 07:59:58 ET B initial Hi Poly Yes Matt Kuhar 0.74 fee 0.01 cash 0.75 HTTP 200 fill 1 settled win +$0.25",
            "2026-10-28 07:59:58 ET B initial low Poly Yes John Chin 0.27 fee 0.01 cash 0.28 HTTP 200 fill 1 settled loss -$0.28",
        ],
        "fills": fills,
        "trades": venues.get("trades", {}).get("rows") or [],
        "resolutions": venues.get("resolutions", {}).get("rows") or [],
        "positions": venues.get("positions", {}).get("rows") or [],
        "order_gets": venues.get("order_gets") or [],
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
            if row.get("event") in {"sent", "flatten_filled", "skip", "t0"}
        ],
    }


def main() -> int:
    print("extract local", flush=True)
    local = extract_local()
    print(f"orders {len(local['orders'])} io {len(local['order_io'])}", flush=True)
    print("extract venues", flush=True)
    venues = extract_venues()
    fixture = _fixture_from(local, venues)
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
            "order_gets": [
                {"order_id": row.get("order_id"), "http": row.get("http"), "error": row.get("error")}
                for row in (venues.get("order_gets") or [])
            ],
        },
        "trades": venues.get("trades"),
        "resolutions": venues.get("resolutions"),
        "order_io": local["order_io"],
        "orders": fixture["orders"],
        "watch": local.get("strategy_b_watch"),
        "official_winner": fixture.get("official_winner"),
        "poly_settlement": fixture.get("poly_settlement"),
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    FIXTURE.write_text(json.dumps(fixture, indent=2, default=str), encoding="utf-8")
    print(f"wrote {FIXTURE}", flush=True)
    print("market", json.dumps(venues.get("market"), default=str)[:800], flush=True)
    print("winner", fixture.get("official_winner"), fixture.get("poly_settlement"), flush=True)
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
    for row in venues.get("order_gets") or []:
        print("ORDER_GET", row.get("order_id"), row.get("http") or row.get("error"), flush=True)
    print("watch", json.dumps(local.get("strategy_b_watch"), default=str)[:500], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
