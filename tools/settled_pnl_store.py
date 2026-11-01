"""Persist with-fee P&L for settled prediction-market fills.

Local file only (not Drive). Keyed by venue order_id. Does not place, cancel,
or sell. Does not invent Novig fees. Postponed is not settled.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from prediction_paths import RAW_DIR as RAW, ensure_dirs

ET = ZoneInfo("America/New_York")
STORE_PATH = RAW / "settled_pnl.json"
FOUR = Decimal("0.0001")
FINAL_RESULTS = {"yes", "no", "void", "n/a"}
FLATTEN_STATUS = "flatten"
_CACHE: dict | None = None
_POLY_ORDER: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _qty_fill(qty) -> bool:
    number = _dec(qty)
    return number is not None and number > 0


def order_key(leg: dict) -> str:
    oid = str((leg or {}).get("order_id") or "").strip()
    if oid:
        return oid
    return "|".join(
        str((leg or {}).get(field) or "")
        for field in ("venue", "instrument", "sent_at", "side", "qty", "cash")
    )


def load(path: Path | None = None) -> dict:
    global _CACHE
    target = path or STORE_PATH
    if path is None and _CACHE is not None:
        return _CACHE
    if not target.is_file():
        blob = {}
        if path is None:
            _CACHE = blob
        return blob
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        blob = {}
        if path is None:
            _CACHE = blob
        return blob
    if isinstance(raw, dict) and isinstance(raw.get("orders"), dict):
        raw = raw["orders"]
    if not isinstance(raw, dict):
        blob = {}
        if path is None:
            _CACHE = blob
        return blob
    blob = {str(key): dict(row) for key, row in raw.items() if isinstance(row, dict)}
    if path is None:
        _CACHE = blob
    return blob


def save(rows: dict, path: Path | None = None) -> Path:
    global _CACHE
    target = path or STORE_PATH
    if path is None:
        _CACHE = rows
    ensure_dirs()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "written_at": _now(),
        "n": len(rows),
        "orders": rows,
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def money4(value) -> str:
    number = _dec(value)
    if number is None:
        return ""
    return format(number.quantize(FOUR, rounding=ROUND_HALF_UP), "f")


def documented_fee(leg: dict) -> Decimal | None:
    """Venue fee already on the tape, or the documented formula. Novig missing stays None."""
    if not isinstance(leg, dict):
        return None
    if leg.get("fee") not in (None, ""):
        found = _dec(leg.get("fee"))
        if found is not None:
            return found
    venue = str(leg.get("venue") or "").lower()
    cash = _dec(leg.get("cash") or leg.get("wire") or leg.get("limit"))
    if cash is None:
        return None
    try:
        import live_lock_orders

        spec = {
            "venue": venue,
            "outcome": str(leg.get("side") or ""),
            "pay": cash,
            "intent": str(leg.get("io_intent") or ""),
            "fee_coefficient": leg.get("fee_coefficient"),
            "fee_charged": leg.get("fee_charged"),
            "event_status": leg.get("event_status"),
        }
        return live_lock_orders.leg_fee(spec, cash, None)
    except Exception:
        return None


def _money_node(value) -> Decimal | None:
    if isinstance(value, dict):
        return _dec(value.get("value"))
    return _dec(value)


def poly_fee_from_order(payload) -> Decimal | None:
    """commissionNotional* from GET /v1/order. 0.0000 is a real $0, not missing."""
    if not isinstance(payload, dict):
        return None
    found = None

    def walk(node) -> None:
        nonlocal found
        if isinstance(node, dict):
            for key in ("commissionNotionalCollected", "commissionNotionalTotalCollected"):
                if key not in node or node.get(key) in (None, ""):
                    continue
                number = _money_node(node.get(key))
                if number is None:
                    continue
                if found is None or number > found:
                    found = number
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(payload)
    return found


def poly_theta_from_payload(payload) -> Decimal | None:
    if not isinstance(payload, dict):
        return None
    found = None

    def walk(node) -> None:
        nonlocal found
        if found is not None:
            return
        if isinstance(node, dict):
            if node.get("feeCoefficient") not in (None, ""):
                found = _dec(node.get("feeCoefficient"))
                return
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(payload)
    return found


def fetch_poly_order(order_id: str) -> dict:
    """Signed GET /v1/order/{id}. Empty on failure. Does not trade."""
    oid = str(order_id or "").strip()
    if not oid:
        return {}
    cached = _POLY_ORDER.get(oid)
    if isinstance(cached, dict):
        return cached
    try:
        import polymarket_us_live
        import venue_pace

        held = False
        try:
            if not venue_pace.wait_turn("polymarket"):
                return {}
            held = True
        except Exception:
            pass
        try:
            status, text = polymarket_us_live.signed_json("GET", f"/v1/order/{oid}")
        finally:
            if held:
                venue_pace.release_turn("polymarket")
    except Exception:
        _POLY_ORDER[oid] = {}
        return {}
    if status != 200 or not text:
        _POLY_ORDER[oid] = {}
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        _POLY_ORDER[oid] = {}
        return {}
    if not isinstance(payload, dict):
        _POLY_ORDER[oid] = {}
        return {}
    _POLY_ORDER[oid] = payload
    return payload


def enrich_poly_leg_fee(leg: dict) -> Decimal | None:
    """GET this-order commission (0 included). Do not invent theta when both are missing."""
    if not isinstance(leg, dict):
        return None
    existing = documented_fee(leg)
    if existing is not None:
        return existing
    if str(leg.get("venue") or "").lower() != "polymarket":
        return None
    payload = fetch_poly_order(str(leg.get("order_id") or ""))
    fee = poly_fee_from_order(payload)
    theta = poly_theta_from_payload(payload)
    if theta is not None and leg.get("fee_coefficient") in (None, ""):
        leg["fee_coefficient"] = str(theta)
    if fee is None and theta is not None:
        cash = _dec(leg.get("cash") or leg.get("wire") or leg.get("limit"))
        if cash is not None:
            try:
                import polymarket_us_live

                fee = polymarket_us_live.taker_fee(cash, theta)
            except Exception:
                fee = None
    if fee is not None:
        leg["fee"] = money4(fee)
    return fee


def enrich_fill_fees(clusters: list[dict]) -> int:
    """Venue GET for filled legs whose fee is still missing. Novig stays unlabeled if omitted."""
    n = 0
    seen: set[int] = set()
    for cluster in clusters or []:
        for bucket in ("fill_legs", "legs"):
            for leg in cluster.get(bucket) or []:
                if not isinstance(leg, dict) or id(leg) in seen:
                    continue
                seen.add(id(leg))
                if not _qty_fill(leg.get("qty")):
                    continue
                if documented_fee(leg) is not None:
                    continue
                venue = str(leg.get("venue") or "").lower()
                if venue == "polymarket":
                    if enrich_poly_leg_fee(leg) is not None:
                        n += 1
                elif venue == "novig":
                    continue
    return n


def all_in_cost(leg: dict) -> Decimal | None:
    """Wire times qty plus fee. Fee is not already inside wire."""
    cash = _dec(leg.get("cash") or leg.get("wire"))
    qty = _dec(leg.get("qty")) or Decimal("1")
    fee = documented_fee(leg)
    if cash is None or fee is None:
        return None
    return (cash * qty) + fee


def flatten_net_from_legs(legs: list[dict]) -> Decimal | None:
    """Yes+No same ticker is a $1 closed set. Net = 1 − sum(all-in). Independent of winner."""
    filled = [leg for leg in (legs or []) if isinstance(leg, dict) and (_dec(leg.get("qty")) or Decimal("0")) > 0]
    if len(filled) < 2:
        return None
    costs = []
    qtys = []
    for leg in filled:
        cost = all_in_cost(leg)
        if cost is None:
            return None
        costs.append(cost)
        qtys.append(_dec(leg.get("qty")) or Decimal("0"))
    qty = min(qtys)
    if qty <= 0:
        return None
    return qty - sum(costs, Decimal("0"))


def upsert_flatten_pair(
    legs: list[dict],
    *,
    source: str,
    store: dict | None = None,
    game: str = "",
    persist: bool = False,
) -> Decimal | None:
    """Book venue flatten net on the close ticket. Origin is paired at $0. Do not directional-settle."""
    filled = [dict(leg) for leg in (legs or []) if isinstance(leg, dict) and (_dec(leg.get("qty")) or Decimal("0")) > 0]
    net = flatten_net_from_legs(filled)
    if net is None:
        return None
    close = None
    for leg in filled:
        if str(leg.get("step") or "").lower() in {"flatten", "extra-flatten"}:
            close = leg
            break
    if close is None:
        close = filled[-1]
    blob = store if store is not None else load()
    for leg in filled:
        key = order_key(leg)
        if not key:
            continue
        cash = _dec(leg.get("cash") or leg.get("wire"))
        fee = documented_fee(leg)
        after = None if cash is None or fee is None else cash + fee
        is_close = order_key(leg) == order_key(close)
        pnl = net if is_close else Decimal("0")
        row = {
            "order_id": str(leg.get("order_id") or key),
            "venue": str(leg.get("venue") or ""),
            "instrument": str(leg.get("instrument") or ""),
            "side": str(leg.get("side") or ""),
            "game": game or str(leg.get("game") or ""),
            "qty": money4(_dec(leg.get("qty"))),
            "wire": money4(cash),
            "fee": money4(fee) if fee is not None else None,
            "after_fee": money4(after) if after is not None else None,
            "result": FLATTEN_STATUS,
            "settlementPx": leg.get("settlementPx") or "",
            "payout": money4(Decimal("1") if is_close else Decimal("0")),
            "pnl": money4(pnl),
            "status": FLATTEN_STATUS,
            "settled_ts": _now(),
            "source": source,
            "house_cash": money4(cash) if cash is not None else None,
            "flatten_pair": True,
            "flatten_net": money4(net),
            "flatten_close": is_close,
        }
        blob[key] = row
    if persist:
        save(blob)
    return net


def compute_pnl(leg: dict, result: str) -> tuple[str, Decimal | None, Decimal | None]:
    """Return (status, pnl, payout). status open means not priced."""
    result = str(result or "").lower()
    qty = _dec(leg.get("qty")) or Decimal("0")
    cash = _dec(leg.get("cash") or leg.get("wire")) or Decimal("0")
    venue = str(leg.get("venue") or "").lower()
    fee = documented_fee(leg)
    if result in {"void", "n/a"}:
        return "void", Decimal("0"), Decimal("0")
    if result not in {"yes", "no"}:
        return "open", None, None
    if fee is None and venue == "novig":
        return "open", None, None
    if fee is None:
        return "open", None, None
    book = str(leg.get("side") or "").lower()
    cost = (cash * qty) + fee
    won = (book == "yes" and result == "yes") or (book == "no" and result == "no")
    payout = qty if won else Decimal("0")
    pnl = payout - cost
    return ("win" if won else "lose"), pnl, payout


def row_for(leg: dict, store: dict | None = None) -> dict | None:
    key = order_key(leg)
    if not key:
        return None
    blob = store if store is not None else load()
    row = blob.get(key)
    return dict(row) if isinstance(row, dict) else None


def settlement_rows(store: dict | None = None) -> list[dict]:
    """Ticker results already priced, so the tape rebuild does not forget them."""
    rows = []
    for oid, item in (store if store is not None else load()).items():
        ticker = str(item.get("instrument") or "").strip()
        result = str(item.get("result") or "").lower()
        if not ticker or result not in FINAL_RESULTS:
            continue
        rows.append({
            "source": "settled_pnl",
            "venue": item.get("venue") or "",
            "ticker": ticker,
            "result": result,
            "status": "void" if result in {"void", "n/a"} else "settled",
            "order_id": oid,
            "game": item.get("game") or "",
            "settlementPx": item.get("settlementPx") or item.get("settlementPrice"),
        })
    return rows


def upsert_leg(
    leg: dict,
    *,
    result: str,
    source: str,
    store: dict | None = None,
    game: str = "",
    settled_ts: str = "",
    persist: bool = False,
) -> dict | None:
    if not isinstance(leg, dict) or not _qty_fill(leg.get("qty")):
        return None
    key = order_key(leg)
    if not key:
        return None
    status, pnl, payout = compute_pnl(leg, result)
    if str(result or "").lower() not in FINAL_RESULTS and status == "open":
        return None
    cash = _dec(leg.get("cash") or leg.get("wire"))
    fee = documented_fee(leg)
    after = None if cash is None or fee is None else cash + fee
    qty = _dec(leg.get("qty"))
    row = {
        "order_id": str(leg.get("order_id") or key),
        "venue": str(leg.get("venue") or ""),
        "instrument": str(leg.get("instrument") or ""),
        "side": str(leg.get("side") or ""),
        "game": game or str(leg.get("game") or ""),
        "qty": money4(qty),
        "wire": money4(cash),
        "fee": money4(fee) if fee is not None else None,
        "after_fee": money4(after) if after is not None else ("fee unknown" if fee is None else None),
        "result": str(result or "").lower(),
        "settlementPx": leg.get("settlementPx") or leg.get("settlement_px") or "",
        "payout": money4(payout) if payout is not None else None,
        "pnl": money4(pnl) if pnl is not None else None,
        "status": status,
        "settled_ts": settled_ts or _now(),
        "source": source,
        "house_cash": money4(cash) if cash is not None else None,
    }
    blob = store if store is not None else load()
    prev = blob.get(key) if isinstance(blob.get(key), dict) else {}
    if prev.get("flatten_pair") and str(result or "").lower() in {"yes", "no"}:
        return dict(prev)
    if prev and not row.get("pnl") and prev.get("pnl") not in (None, ""):
        row["pnl"] = prev.get("pnl")
        row["payout"] = row.get("payout") or prev.get("payout")
        row["status"] = prev.get("status") or row["status"]
    blob[key] = row
    if persist:
        save(blob)
    return row


def persist_from_clusters(clusters: list[dict], *, source: str = "tape_rebuild") -> dict:
    """Upsert every filled settled ticket we can price. Postponed is skipped."""
    blob = load()
    n = 0
    for cluster in clusters or []:
        if not isinstance(cluster, dict):
            continue
        if cluster.get("postponed") and not cluster.get("venue_paid") and not cluster.get("void"):
            continue
        game = str(cluster.get("game") or "")
        for bucket in ("fill_legs", "legs"):
            for leg in cluster.get(bucket) or []:
                if not isinstance(leg, dict) or not _qty_fill(leg.get("qty")):
                    continue
                result = str(leg.get("settle_result") or "").lower()
                if result not in FINAL_RESULTS:
                    continue
                row = upsert_leg(
                    leg,
                    result=result,
                    source=source,
                    store=blob,
                    game=game,
                    settled_ts=str(cluster.get("settled_at") or ""),
                )
                if row:
                    n += 1
    save(blob)
    _ = n
    return blob


def apply_to_leg(leg: dict, store: dict | None = None) -> tuple[str, Decimal | None]:
    row = row_for(leg, store)
    if not row:
        return "open", None
    result = str(row.get("result") or "").lower()
    if result in {"void", "n/a"}:
        return "void", Decimal("0")
    pnl = _dec(row.get("pnl"))
    status = str(row.get("status") or "")
    if row.get("flatten_pair") or status == FLATTEN_STATUS or result == FLATTEN_STATUS:
        return FLATTEN_STATUS, Decimal("0") if pnl is None else pnl
    if status in {"win", "lose", "void"} and (pnl is not None or status == "void"):
        return status, Decimal("0") if status == "void" else pnl
    if pnl is None:
        return "open", None
    if pnl > 0:
        return "win", pnl
    if pnl < 0:
        return "lose", pnl
    return "void" if result in {"void", "n/a"} else "win", pnl


def result_from_market(info: dict | None) -> str:
    """Winner from venue settlementPx (0 or 1). Ignore ticker result=yes / POSITION_RESOLUTION."""
    if not isinstance(info, dict):
        return ""
    px = info.get("settlementPx") or info.get("settlementPrice") or info.get("settlement_px")
    px_result = ""
    number = _money_node(px)
    if number is not None:
        if number >= 1:
            px_result = "yes"
        elif number <= 0:
            px_result = "no"
        else:
            return ""
    if px_result:
        return px_result
    venue = str(info.get("venue") or "").lower()
    source = str(info.get("source") or "").lower()
    if venue in {"polymarket", "poly"} or "position_resolution" in source:
        return ""
    result = str(info.get("result") or "").lower()
    if result in FINAL_RESULTS:
        return result
    return ""


def fetch_market_result(venue: str, ident: str) -> dict:
    """Public market GET. Empty on failure. Does not trade."""
    venue = str(venue or "").lower()
    ident = str(ident or "").strip()
    if not ident:
        return {}
    try:
        import open_count_sync
    except Exception:
        return {}
    info = {}
    if venue == "kalshi":
        info = open_count_sync._fetch_kalshi_market(ident) or {}
    elif venue == "polymarket":
        info = open_count_sync._fetch_poly_market(ident) or {}
    else:
        return {}
    if not isinstance(info, dict):
        return {}
    result = result_from_market(info)
    if result:
        info["result"] = result
    return info


def note_game_settled(
    *,
    kind: str = "",
    title: str = "",
    game_key: str = "",
    instruments: list[tuple[str, str]] | None = None,
) -> int:
    """Fetch venue results for this close and upsert. Does not rebuild. Does not sell."""
    kind = str(kind or "").strip().lower()
    if kind in {"postponed", "delayed"}:
        return 0
    found = list(instruments or [])
    if not found:
        found = _instruments_from_watches(title, game_key)
    if not found:
        return 0
    blob = load()
    n = 0
    for venue, ident in found:
        info = fetch_market_result(venue, ident)
        result = result_from_market(info)
        if result not in FINAL_RESULTS:
            continue
        stub = {
            "order_id": "",
            "venue": venue,
            "instrument": ident,
            "side": "",
            "qty": "1",
            "cash": None,
            "fee": None,
        }
        # Ticker-only row so load_settlements sees the result before the full rebuild.
        key = f"ticker|{venue}|{ident.lower()}"
        prev = blob.get(key) if isinstance(blob.get(key), dict) else {}
        px = info.get("settlementPx") or info.get("settlementPrice") or info.get("settlement_px")
        if isinstance(px, dict):
            px = px.get("value")
        blob[key] = {
            "order_id": key,
            "venue": venue,
            "instrument": ident,
            "side": prev.get("side") or "",
            "game": title or prev.get("game") or "",
            "qty": prev.get("qty") or "",
            "wire": prev.get("wire"),
            "fee": prev.get("fee"),
            "after_fee": prev.get("after_fee"),
            "result": result,
            "settlementPx": prev.get("settlementPx") or px,
            "payout": prev.get("payout"),
            "pnl": prev.get("pnl"),
            "status": "void" if result in {"void", "n/a"} else (prev.get("status") or "settled"),
            "settled_ts": _now(),
            "source": f"close_hook:{kind or 'settled'}",
        }
        n += 1
        _ = stub
    if n:
        save(blob)
    return n


def _instruments_from_watches(title: str, game_key: str) -> list[tuple[str, str]]:
    needles = [
        " ".join(str(text or "").lower().replace("_", " ").split())
        for text in (title, game_key)
        if str(text or "").strip()
    ]
    if not needles:
        return []
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _hit(blob: str) -> bool:
        text = " ".join(str(blob or "").lower().replace("_", " ").split())
        if not text:
            return False
        return any(n in text or text in n for n in needles)

    def _add(venue, ident):
        venue = str(venue or "").lower()
        ident = str(ident or "").strip()
        if not venue or not ident:
            return
        key = (venue, ident.lower())
        if key in seen:
            return
        seen.add(key)
        found.append((venue, ident))

    try:
        import open_count_sync

        for sid in open_count_sync.WATCH:
            status = open_count_sync.load_watch(sid) or {}
            for match in status.get("matches") or []:
                if not isinstance(match, dict):
                    continue
                blob = " ".join(str(match.get(k) or "") for k in ("game", "key", "title"))
                if not _hit(blob):
                    continue
                _add(match.get("venue"), match.get("instrument"))
                last = match.get("last_order") if isinstance(match.get("last_order"), dict) else {}
                _add(last.get("venue") or match.get("venue"), last.get("instrument") or last.get("ticker"))
                t0 = match.get("t0_yes") if isinstance(match.get("t0_yes"), dict) else {}
                for which in ("a", "b"):
                    node = t0.get(which) if isinstance(t0.get(which), dict) else {}
                    _add(node.get("venue") or match.get("venue"), node.get("instrument"))
    except Exception:
        pass
    return found
