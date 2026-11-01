"""Read-only extract of tape vs venue-return fills. Does not place, cancel, or sell.

Writes a local JSON summary under RAW. No secrets. No Drive HTML.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
from order_ledger import ORDERS, ORDER_IO, _io_instrument, _load_jsonl, _order_id_of, polymarket_fill  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
WINDOW_START = datetime(2026, 10, 18, 0, 0, tzinfo=ET)
WINDOW_END = datetime(2026, 10, 23, 0, 0, tzinfo=ET)
ONE = Decimal("1")
OUT = RAW / "_venue_fill_audit_extract_20261022.json"


def parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def in_window(stamp):
    return stamp is not None and WINDOW_START <= stamp < WINDOW_END


def ddec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def qty_ge_1(qty) -> bool:
    try:
        return Decimal(str(qty or 0)) >= 1
    except Exception:
        return False


def public_note(payload) -> str:
    try:
        return live_lock_orders._scrub_public_text(live_lock_orders.public_venue_note(payload, ""))
    except Exception:
        return ""


def kalshi_book_side(req: dict) -> str:
    req_side = str(req.get("side") or req.get("action") or "").lower()
    if req_side in {"ask", "sell", "no"}:
        return "no"
    if req_side in {"bid", "buy", "yes"}:
        return "yes"
    return ""


def io_row_summary(row: dict) -> dict:
    payload = row.get("response") if isinstance(row.get("response"), dict) else {}
    qty = live_lock_orders.filled_contracts(payload) if payload else Decimal("0")
    inner = payload.get("order") if isinstance(payload.get("order"), dict) else payload
    req = row.get("request") if isinstance(row.get("request"), dict) else {}
    venue = str(row.get("venue") or "").lower()
    poly = polymarket_fill(payload) if venue == "polymarket" and payload else {}
    avg = inner.get("average_fill_price") if isinstance(inner, dict) else None
    http = row.get("http_status") if row.get("http_status") is not None else row.get("status")
    book = kalshi_book_side(req) if venue == "kalshi" else (poly.get("side") or "")
    yes_wire = ddec(avg)
    cash = None
    if venue == "kalshi" and book == "no" and yes_wire is not None:
        cash = ONE - yes_wire
    elif venue == "polymarket":
        cash = ddec(poly.get("cash")) or ddec(poly.get("avg"))
        yes_wire = ddec(poly.get("avg"))
    elif yes_wire is not None:
        cash = yes_wire
    empty_201 = False
    try:
        empty_201 = int(http or 0) in {200, 201} and not qty_ge_1(qty)
    except (TypeError, ValueError):
        empty_201 = False
    return {
        "ts": row.get("timestamp"),
        "venue": venue,
        "kind": row.get("kind"),
        "http": http,
        "instrument": _io_instrument(row),
        "order_id": _order_id_of(payload),
        "qty": str(qty),
        "qty_ge_1": qty_ge_1(qty),
        "empty_201": empty_201,
        "req_side": str(req.get("side") or req.get("action") or req.get("intent") or ""),
        "book_side": book,
        "yes_wire": str(yes_wire) if yes_wire is not None else "",
        "no_cash": str(cash) if cash is not None else "",
        "poly_avg": poly.get("avg") or "",
        "poly_cash": poly.get("cash") or "",
        "poly_fee": poly.get("fee") or "",
        "poly_outcome": poly.get("outcome_name") or "",
        "fill_count": inner.get("fill_count") if isinstance(inner, dict) else None,
        "note": public_note(payload),
        "gemini_symbol": req.get("symbol") or (inner.get("symbol") if isinstance(inner, dict) else "") or "",
        "gemini_price": req.get("price") or "",
        "gemini_side": req.get("side") or "",
    }


def main() -> None:
    io_list = _load_jsonl(ORDER_IO)
    orders = _load_jsonl(ORDERS)
    consider = {}
    cpath = RAW / "considerations.json"
    if cpath.is_file():
        try:
            consider = json.loads(cpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            consider = {}
    consider_rows = consider.get("rows") if isinstance(consider.get("rows"), list) else []
    b_watch = {}
    bpath = RAW / "strategy_b_watch.json"
    if bpath.is_file():
        try:
            b_watch = json.loads(bpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            b_watch = {}

    io_orders = []
    for row in io_list:
        if str(row.get("kind") or "") != "order":
            continue
        stamp = parse_dt(row.get("timestamp"))
        if not in_window(stamp):
            continue
        io_orders.append(io_row_summary(row))

    fills = [r for r in io_orders if r["qty_ge_1"]]
    empty_201 = [r for r in io_orders if r["empty_201"]]
    by_venue = Counter(r["venue"] for r in fills)
    empty_by_venue = Counter(r["venue"] for r in empty_201)

    order_events = Counter()
    filled_events = []
    one_leg_events = []
    for row in orders:
        stamp = parse_dt(row.get("ts") or row.get("at") or row.get("timestamp") or row.get("compared_at"))
        if not in_window(stamp) and not in_window(parse_dt(row.get("compared_at"))):
            # still count if event time missing but keep a sample
            pass
        event = str(row.get("event") or "")
        order_events[event] += 1
        if event == "filled":
            filled_events.append({
                "ts": row.get("ts") or row.get("timestamp") or row.get("compared_at"),
                "venue": row.get("venue"),
                "instrument": row.get("instrument"),
                "side": row.get("side"),
                "price": row.get("price") or row.get("fill_price") or row.get("limit"),
                "size": row.get("size") or row.get("qty"),
                "game": row.get("game"),
                "bet_key": row.get("bet_key"),
                "order_id": row.get("order_id"),
                "http": row.get("http") or row.get("http_status"),
            })
        if event == "one_leg":
            one_leg_events.append({
                "ts": row.get("ts") or row.get("timestamp") or row.get("compared_at"),
                "game": row.get("game"),
                "bet_key": row.get("bet_key"),
                "venue": row.get("venue"),
                "instrument": row.get("instrument"),
                "reason": str(row.get("reason") or row.get("note") or "")[:200],
            })

    sent_rows = []
    both_filled_no_io = []
    shsu = []
    rewrite_rows = []
    catalog_denied_sendish = []
    for row in consider_rows:
        if not isinstance(row, dict):
            continue
        stamp = parse_dt(row.get("at"))
        decision = str(row.get("decision") or "")
        reason = str(row.get("reason") or "")
        game = str(row.get("game") or "")
        if "0.98399" in reason or ("above the 0.984" in reason and "0.983" in reason):
            rewrite_rows.append({"at": row.get("at"), "game": game, "decision": decision, "reason": reason[:240]})
        if "catalog" in reason.lower() and decision == "denied":
            if "at or under" in reason.lower() or "does not send" in reason.lower():
                catalog_denied_sendish.append({"at": row.get("at"), "game": game, "reason": reason[:240]})
        if "sam houston" in game.lower() or "shsu" in game.lower():
            if stamp and stamp.strftime("%Y-%m-%dT%H:%M") in ("2026-10-21T22:42", "2026-10-21T22:58"):
                shsu.append({
                    "at": row.get("at"),
                    "game": game,
                    "number": row.get("number"),
                    "decision": decision,
                    "reason": reason[:240],
                    "yes_px": row.get("yes_price") or row.get("yes"),
                    "no_px": row.get("no_price") or row.get("no"),
                })
        if decision != "sent" or not in_window(stamp):
            continue
        sent_rows.append({
            "at": row.get("at"),
            "game": game,
            "number": row.get("number"),
            "reason": reason[:240],
            "yes_venue": row.get("yes_venue"),
            "no_venue": row.get("no_venue"),
            "venue_return": str(row.get("venue_return") or "")[:200],
        })
        both = "both legs filled" in reason.lower()
        if both:
            # later matched vs io
            pass

    needles_named = {
        "ribecai": ("ribhou", "micrib", "ribecai", "houkes"),
        "urso": ("ursaur", "pobane", "urso", "poborilova"),
        "danilova": ("olgdanyuhliu", "avabecjizsib", "danilova", "sibai"),
        "funk": ("aarfun", "serpet", "funk", "petrov"),
        "wolff": ("vivwol", "steweb", "wolff"),
        "machac": ("mackha", "machac", "khachanov"),
        "mtn_fiu": ("mtnfiu", "mtn", "middle tennessee", "fiu"),
        "car_cgy": ("carcgy", "calgary", "carolina"),
        "tb_cle": ("tbcle", "tampa", "cleveland"),
        "shsu": ("nmsushsu", "shsu", "sam houston"),
        "cui": ("cuiyib", "jiecui", "yibwu"),
    }
    named_io = {}
    for label, needles in needles_named.items():
        hits = []
        for row in io_orders:
            blob = " ".join(str(row.get(k) or "") for k in ("instrument", "poly_outcome", "note", "gemini_symbol")).lower()
            if any(n in blob for n in needles):
                hits.append(row)
        named_io[label] = hits

    # Gemini io fills (qty>=1) plus any gemini posts
    gemini_io = [r for r in io_orders if r["venue"] == "gemini"]
    gemini_fills = [r for r in gemini_io if r["qty_ge_1"]]
    novig_io = [r for r in io_orders if r["venue"] == "novig"]

    # orders.jsonl filled vs io fills by venue+instrument
    io_keys = {(r["venue"], r["instrument"]) for r in fills if r["instrument"]}
    tape_keys = {(str(r.get("venue") or "").lower(), str(r.get("instrument") or "")) for r in filled_events if r.get("instrument")}

    b_open = b_watch.get("open") or b_watch.get("matches") or b_watch.get("open_matches") or []
    if isinstance(b_watch.get("state"), dict):
        b_open = b_watch["state"].get("open") or b_open
    b_keys = list(b_watch.keys()) if isinstance(b_watch, dict) else []

    summary = {
        "pulled_at": datetime.now(ET).isoformat(),
        "window": "2026-10-18 inclusive through 2026-10-22 ET",
        "io_order_posts": len(io_orders),
        "io_fills_qty_ge_1": len(fills),
        "io_fills_by_venue": dict(by_venue),
        "empty_201": len(empty_201),
        "empty_201_by_venue": dict(empty_by_venue),
        "orders_jsonl_events": dict(order_events),
        "orders_filled_n": len(filled_events),
        "orders_one_leg_n": len(one_leg_events),
        "consider_sent_n": len(sent_rows),
        "consider_both_filled_n": sum(1 for r in sent_rows if "both legs filled" in str(r.get("reason") or "").lower()),
        "rewrite_n": len(rewrite_rows),
        "catalog_denied_sendish_n": len(catalog_denied_sendish),
        "gemini_io_n": len(gemini_io),
        "gemini_fills_n": len(gemini_fills),
        "novig_io_n": len(novig_io),
        "io_key_n": len(io_keys),
        "tape_key_n": len(tape_keys),
        "tape_not_io": sorted(tape_keys - io_keys)[:80],
        "io_not_tape": sorted(io_keys - tape_keys)[:80],
        "b_watch_keys": b_keys[:40],
        "b_open_type": type(b_open).__name__,
        "named_io_counts": {k: len(v) for k, v in named_io.items()},
        "named_io_fills": {k: [r for r in v if r["qty_ge_1"]] for k, v in named_io.items()},
        "named_io_all": {k: v for k, v in named_io.items()},
        "shsu_consider": shsu,
        "rewrite_sample": rewrite_rows[:15],
        "catalog_sample": catalog_denied_sendish[:10],
        "gemini_io": gemini_io,
        "novig_io": novig_io,
        "fills": fills,
        "empty_201_sample": empty_201[:40],
        "filled_events": filled_events,
        "one_leg_events": one_leg_events[:40],
        "sent_both_filled": [r for r in sent_rows if "both legs filled" in str(r.get("reason") or "").lower()],
        "sent_rows_sample": sent_rows[:30],
    }
    OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}")
    print("io_fills", len(fills), dict(by_venue))
    print("empty_201", len(empty_201), dict(empty_by_venue))
    print("orders filled", len(filled_events), "one_leg", len(one_leg_events))
    print("consider sent", len(sent_rows), "both_filled", summary["consider_both_filled_n"])
    print("named", summary["named_io_counts"])
    print("gemini fills", len(gemini_fills), "novig io", len(novig_io))
    print("tape_not_io", len(tape_keys - io_keys), "io_not_tape", len(io_keys - tape_keys))


if __name__ == "__main__":
    main()
