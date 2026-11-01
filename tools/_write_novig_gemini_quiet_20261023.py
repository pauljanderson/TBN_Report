"""Read-only Novig zero / Gemini quiet investigation. Does not place, cancel, or sell."""
from __future__ import annotations

import html as html_lib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import gemini_private  # noqa: E402
import live_lock_orders  # noqa: E402
import live_strategy_b  # noqa: E402
import novig_live  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "novig_gemini_quiet_20261023.html"
DUMP = RAW / "_novig_gemini_quiet_20261023.json"
CONSIDER = RAW / "considerations.json"
ORDERS = RAW / "orders.jsonl"
ORDER_IO = RAW / "order_io.jsonl"
SUPERVISOR = RAW / "live_supervisor.log"
B_WATCH = RAW / "strategy_b_watch.json"
LOCK_SKIP = RAW / "lock_last_skip.json"
ORDERS_STOP = RAW / "orders_stopped.json"
RESTART_HINT = datetime(2026, 10, 22, 23, 51, tzinfo=ET)
FALLBACK_START = datetime(2026, 10, 22, 8, 17, tzinfo=ET)
NOW = datetime.now(ET)
ONE = Decimal("1")
NET_MAX = live_lock_orders.NET_MAX
SECRET_NEEDLES = (
    "api_key",
    "apikey",
    "secret",
    "signature",
    "passphrase",
    "private_key",
    "authorization",
    "access_key",
    "token",
    "novig-key",
    "x-gemini",
)

ASKED = (
    "why do we still have 0 orders on Novig? and why haven't we had any orders on Gemini in a while?"
)
PLAIN = (
    "A prediction market is a ticket that costs between 0 and $1 and pays $1 if that named result happens. "
    "Kalshi, Gemini, Polymarket US, and Novig are the four shops. The lock bot only buys both sides of the same "
    "result when the two prices plus the documented fees add up to at most 0.984 (the live send cap, NET_MAX). "
    "It always picks the cheaper legal Yes shop and the cheaper legal No shop. Strategy B never sends Novig; it "
    "only uses Kalshi, Gemini, and Polymarket on tennis Yes tickets. Immediate-or-cancel (IOC) means fill now or "
    "cancel. This page pulled Novig and Gemini history from the shops themselves and counted looks, sends, and "
    "denials from the live log. It does not place, cancel, sell, or start a second Strategy B."
)


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, kind: str = "text") -> str:
    extra = ' class="num"' if kind == "num" else ""
    return f"<td{extra}>{esc('' if value is None else value)}</td>"


def table(headers: list[tuple[str, str]], rows: list[list], total: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(td(cell, headers[i][1] if i < len(headers) else "text") for i, cell in enumerate(row))
        body.append(f"<tr>{cells}</tr>")
    if total is not None:
        cells = "".join(td(cell, headers[i][1] if i < len(headers) else "text") for i, cell in enumerate(total))
        body.append(f'<tr class="total-row">{cells}</tr>')
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        raw = int(text)
        if raw > 10**12:
            stamp = datetime.fromtimestamp(raw / 1000, tz=ET)
        else:
            stamp = datetime.fromtimestamp(raw, tz=ET)
        return stamp.astimezone(ET)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def ddec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def qty_ge_1(qty) -> bool:
    number = ddec(qty)
    return number is not None and number >= 1


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            lowered = str(key).lower().replace("-", "_")
            if any(needle in lowered for needle in SECRET_NEEDLES):
                out[key] = "[redacted]"
            else:
                out[key] = redact(value)
        return out
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    return obj


def public_note(text: str, limit: int = 120) -> str:
    blob = str(text or "")
    low = blob.lower()
    if any(needle in low for needle in SECRET_NEEDLES):
        return "(redacted note)"
    return blob[:limit]


def fmt_et(stamp) -> str:
    if stamp is None:
        return ""
    return stamp.strftime("%Y-%m-%d %H:%M:%S ET")


def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
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


def _novig_items(payload):
    if not isinstance(payload, dict):
        return [], ""
    if isinstance(payload.get("items"), list):
        return payload.get("items"), str(payload.get("next") or "")
    items = []
    next_cursor = ""
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            items.extend(row for row in value["items"] if isinstance(row, dict))
            next_cursor = str(value.get("next") or next_cursor)
    return items, next_cursor


def novig_fill_row(fill: dict) -> dict:
    qty = fill.get("qty")
    cost = ddec(fill.get("cost"))
    qty_n = ddec(qty)
    price = None
    if cost is not None and qty_n not in (None, Decimal("0")):
        price = (Decimal("100") * cost) / qty_n
    stamp = parse_dt(fill.get("ts"))
    return {
        "time_et": fmt_et(stamp),
        "ts": stamp.isoformat() if stamp else "",
        "ticker": str(fill.get("marketId") or ""),
        "outcome_id": str(fill.get("outcomeId") or ""),
        "qty": str(qty) if qty is not None else "",
        "house_fill": qty_ge_1(qty),
        "cost": str(cost) if cost is not None else "",
        "price": str(price) if price is not None else "",
        "order_id": str(fill.get("orderId") or ""),
        "fill_id": str(fill.get("fillId") or ""),
    }


def pull_novig_fills() -> dict:
    fills = []
    pages = []
    cursor = ""
    query_base = {"limit": "500"}
    try:
        for _ in range(20):
            query = dict(query_base)
            if cursor:
                query["after"] = cursor
            status, text = novig_live.list_fills(query)
            page = {"http": status, "bytes": len(text or "")}
            if status != 200:
                pages.append(page | {"error": "http", "body_prefix": public_note(text, 80)})
                break
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                pages.append(page | {"error": "not_json"})
                break
            batch, next_cursor = _novig_items(data)
            rows = [novig_fill_row(item) for item in batch if isinstance(item, dict)]
            fills.extend(rows)
            pages.append(page | {"n": len(rows), "cursor_next": bool(next_cursor)})
            cursor = next_cursor
            if not cursor or not batch:
                break
        called = True
        note = ""
    except Exception as exc:
        called = False
        note = type(exc).__name__
        pages.append({"http": 0, "error": type(exc).__name__})
    house = [row for row in fills if row.get("house_fill")]
    return {
        "called": called,
        "endpoint": "GET /v3/portfolio/fills",
        "http_pages": pages,
        "n": len(fills),
        "n_house": len(house),
        "note": note,
        "fills": house,
        "all_n": len(fills),
    }


def pull_novig_account() -> dict:
    flag = bool(novig_live.NOVIG_ORDERS_ENABLED)
    live = bool(novig_live.orders_live())
    try:
        ready, ready_note = novig_live.trading_key_ready()
    except Exception as exc:
        ready, ready_note = False, type(exc).__name__
    try:
        bal_http, bal = novig_live.balance_usd()
    except Exception as exc:
        bal_http, bal = 0, None
        ready_note = ready_note or type(exc).__name__
    return {
        "NOVIG_ORDERS_ENABLED": flag,
        "orders_live": live,
        "trading_key_ready": bool(ready),
        "trading_key_note": public_note(str(ready_note or ""), 160),
        "balance_http": bal_http,
        "balance_usd": str(bal) if bal is not None else None,
        "keys_present": bool(novig_live.keys_present()),
    }


def gemini_row(order: dict) -> dict:
    qty = order.get("filledQuantity") or order.get("filled_quantity") or order.get("quantity")
    stamp = parse_dt(order.get("updatedAt") or order.get("createdAt"))
    created = parse_dt(order.get("createdAt"))
    meta = order.get("contractMetadata") if isinstance(order.get("contractMetadata"), dict) else {}
    return {
        "time_et": fmt_et(stamp),
        "created_et": fmt_et(created),
        "ts": stamp.isoformat() if stamp else "",
        "ticker": str(order.get("symbol") or ""),
        "side": str(order.get("side") or ""),
        "outcome": str(order.get("outcome") or ""),
        "qty": str(qty) if qty is not None else "",
        "house_fill": qty_ge_1(qty) and str(order.get("status") or "").lower() == "filled",
        "price": str(order.get("avgExecutionPrice") or order.get("price") or ""),
        "limit": str(order.get("price") or ""),
        "status": str(order.get("status") or ""),
        "order_id": str(order.get("orderId") or order.get("clientOrderId") or ""),
        "event": str(meta.get("eventName") or meta.get("eventTicker") or ""),
        "resolution": str(meta.get("resolutionSide") or ""),
    }


def pull_gemini(status: str | None, start: datetime, end: datetime) -> dict:
    extra = {
        "from": int(start.timestamp() * 1000),
        "to": int(end.timestamp() * 1000),
        "limit": 1000,
    }
    if status:
        extra["status"] = status
    try:
        http, text = gemini_private.get_order_history(extra)
        called = True
        note = ""
    except Exception as exc:
        return {
            "called": False,
            "status_filter": status or "(all)",
            "endpoint": "POST /v1/prediction-markets/orders/history",
            "http": 0,
            "n": 0,
            "n_house": 0,
            "note": type(exc).__name__,
            "fills": [],
            "all_rows": [],
        }
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {}
        note = "not_json"
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        orders = []
        if http != 200:
            note = public_note(text, 80)
    rows = [gemini_row(item) for item in orders if isinstance(item, dict)]
    house = [row for row in rows if row.get("house_fill")]
    return {
        "called": called,
        "status_filter": status or "(all)",
        "endpoint": "POST /v1/prediction-markets/orders/history",
        "http": http,
        "bytes": len(text or ""),
        "n": len(rows),
        "n_house": len(house),
        "note": note,
        "fills": house,
        "all_rows": rows,
    }


def find_restart() -> dict:
    hits = []
    if SUPERVISOR.is_file():
        with SUPERVISOR.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "supervisor start" not in line:
                    continue
                stamp = parse_dt(line.split(" ", 1)[0])
                if stamp is None:
                    continue
                hits.append({"ts": stamp.isoformat(), "time_et": fmt_et(stamp), "line": line.strip()[:180]})
    last = hits[-1] if hits else None
    window_start = RESTART_HINT
    source = "hint 23:51 ET Oct 22"
    if last:
        last_dt = parse_dt(last["ts"])
        if last_dt is not None:
            if abs((last_dt - RESTART_HINT).total_seconds()) <= 30 * 60:
                window_start = last_dt
                source = "supervisor start nearest 23:51 ET Oct 22"
            elif last_dt >= RESTART_HINT - timedelta(hours=2):
                window_start = last_dt
                source = "latest supervisor start"
    if window_start < FALLBACK_START:
        # keep hint if supervisor log has no recent start
        pass
    return {
        "hits_n": len(hits),
        "last": last,
        "recent": hits[-8:],
        "window_start": window_start.isoformat(),
        "window_start_et": fmt_et(window_start),
        "source": source,
        "fallback_24h": fmt_et(NOW - timedelta(hours=24)),
    }


def reason_bucket(reason: str) -> str:
    text = str(reason or "").strip()
    low = text.lower()
    if "already have" in low and "open lock" in low:
        return "lock slots full"
    if "strategy b has this match open" in low:
        return "Strategy B has this match open"
    if "orders stopped" in low or "one-leg" in low:
        return "orders stopped"
    if "placing orders is off" in low:
        return "placing orders is off"
    if "balance too low" in low:
        return "balance too low"
    if "balance unreadable" in low:
        return "balance unreadable"
    if "recheck" in low or "over $1" in low or "not profitable" in low:
        return "recheck / not profitable"
    if "not selected" in low or "cheaper" in low:
        return "not the cheaper leg"
    if "novig quote only" in low or "quote only" in low:
        return "Novig quote only"
    if "orders off" in low or "novig orders" in low or "trading key" in low:
        return "Novig orders off / key"
    if "gemini no" in low and "not a" in low:
        return "Gemini No not a real offer"
    if "missing order fields" in low:
        return "missing order fields"
    if "net " in low and "above" in low:
        return "above send cap"
    if "after-fee cost" in low and "above" in low:
        return "above send cap"
    if "both books need" in low:
        return "size < 1"
    if "fee unknown" in low:
        return "fee unknown"
    if "contract is closed" in low:
        return "closed"
    if "catalog pass" in low:
        return "catalog pass (no send)"
    if "both legs filled" in low or "neither leg" in low or "one leg" in low:
        return "send result"
    if "venue" in low and ("http" in low or "error" in low or "reject" in low):
        return "venue HTTP / reject"
    if not text:
        return "(empty)"
    return "other"


def venue_in_row(row: dict, venue: str) -> bool:
    yes = str(row.get("yes_venue") or "").lower()
    no = str(row.get("no_venue") or "").lower()
    return venue in (yes, no)


def pair_label(row: dict) -> str:
    yes = str(row.get("yes_venue") or "").lower() or "?"
    no = str(row.get("no_venue") or "").lower() or "?"
    return f"{yes} Yes / {no} No"


def consider_stats(rows: list[dict], start: datetime) -> dict:
    window = []
    undated = 0
    for row in rows:
        stamp = parse_dt(row.get("at"))
        if stamp is None:
            undated += 1
            continue
        if stamp >= start:
            window.append(row)
    by_venue = {}
    for venue in ("kalshi", "polymarket", "gemini", "novig"):
        looks = [r for r in window if venue_in_row(r, venue)]
        sent = [r for r in looks if str(r.get("decision") or "") == "sent"]
        denied = [r for r in looks if str(r.get("decision") or "") != "sent"]
        reasons = Counter(reason_bucket(str(r.get("reason") or "")) for r in denied)
        sports = Counter(str(r.get("sport") or "") or "(blank)" for r in looks)
        partners = Counter()
        for r in looks:
            yes = str(r.get("yes_venue") or "").lower()
            no = str(r.get("no_venue") or "").lower()
            if venue == yes:
                partners[f"Yes; No on {no or '?'}"] += 1
            if venue == no:
                partners[f"No; Yes on {yes or '?'}"] += 1
        nets = []
        under_cap = 0
        for r in looks:
            net = ddec(r.get("net"))
            if net is None:
                continue
            nets.append(net)
            if net <= NET_MAX:
                under_cap += 1
        by_venue[venue] = {
            "looks": len(looks),
            "sent": len(sent),
            "denied": len(denied),
            "under_net_max": under_cap,
            "reasons": reasons.most_common(),
            "sports": sports.most_common(),
            "partners": partners.most_common(),
            "min_net": str(min(nets)) if nets else "",
            "max_net": str(max(nets)) if nets else "",
            "sent_rows": [
                {
                    "at": r.get("at"),
                    "game": r.get("game"),
                    "sport": r.get("sport"),
                    "pair": pair_label(r),
                    "net": r.get("net"),
                    "reason": (r.get("reason") or "")[:160],
                    "venue_return": (r.get("venue_return") or "")[:160],
                }
                for r in sent[:20]
            ],
        }
    pairs = Counter(pair_label(r) for r in window)
    sports = Counter(str(r.get("sport") or "") or "(blank)" for r in window)
    decisions = Counter(str(r.get("decision") or "") or "(blank)" for r in window)
    reasons = Counter(reason_bucket(str(r.get("reason") or "")) for r in window)
    novig_under = []
    gemini_under = []
    for r in window:
        net = ddec(r.get("net"))
        if net is None or net > NET_MAX:
            continue
        item = {
            "at": r.get("at"),
            "game": r.get("game"),
            "sport": r.get("sport"),
            "pair": pair_label(r),
            "net": r.get("net"),
            "decision": r.get("decision"),
            "reason": (r.get("reason") or "")[:180],
        }
        if venue_in_row(r, "novig"):
            novig_under.append(item)
        if venue_in_row(r, "gemini"):
            gemini_under.append(item)
    return {
        "n_file": len(rows),
        "n_window": len(window),
        "undated": undated,
        "keep_cap": 500,
        "by_venue": {k: {**v, "reasons": v["reasons"], "sports": v["sports"], "partners": v["partners"]} for k, v in by_venue.items()},
        "pairs": pairs.most_common(),
        "sports": sports.most_common(),
        "decisions": decisions.most_common(),
        "reasons": reasons.most_common(),
        "novig_under_cap": novig_under,
        "gemini_under_cap": gemini_under[:40],
        "gemini_under_cap_n": len(gemini_under),
        "first_at": window[0].get("at") if window else "",
        "last_at": window[-1].get("at") if window else "",
    }


def io_stats(start: datetime) -> dict:
    counts = Counter()
    kinds = Counter()
    http_by = Counter()
    filled = Counter()
    errors = []
    posts = []
    first = None
    last = None
    n_window = 0
    n_file = 0
    for row in iter_jsonl(ORDER_IO):
        n_file += 1
        stamp = parse_dt(row.get("timestamp") or row.get("ts") or row.get("at"))
        if stamp is None or stamp < start:
            continue
        n_window += 1
        if first is None:
            first = stamp
        last = stamp
        venue = str(row.get("venue") or "").lower()
        kind = str(row.get("kind") or row.get("path") or "")
        counts[venue] += 1
        kinds[f"{venue}:{kind}"] += 1
        http = row.get("http") or row.get("http_status") or row.get("status")
        http_by[f"{venue} {http}"] += 1
        payload = row.get("response") if isinstance(row.get("response"), dict) else {}
        qty = live_lock_orders.filled_contracts(payload) if payload else Decimal("0")
        if qty_ge_1(qty):
            filled[venue] += 1
        if venue in ("novig", "gemini") and str(kind).lower() in ("order", "place", "post"):
            posts.append({
                "at": fmt_et(stamp),
                "venue": venue,
                "kind": kind,
                "http": http,
                "instrument": str((row.get("request") or {}).get("symbol") or (row.get("request") or {}).get("outcomeId") or row.get("instrument") or "")[:80],
                "qty": str(qty),
                "note": public_note(str(row.get("note") or ""), 80),
            })
        if venue in ("novig", "gemini"):
            http_n = 0
            try:
                http_n = int(http)
            except (TypeError, ValueError):
                http_n = 0
            if http_n and http_n >= 400:
                errors.append({
                    "at": fmt_et(stamp),
                    "venue": venue,
                    "kind": kind,
                    "http": http,
                    "note": public_note(str(row.get("note") or "")[:80], 80),
                })
    return {
        "n_file": n_file,
        "n_window": n_window,
        "first": fmt_et(first),
        "last": fmt_et(last),
        "counts": counts.most_common(),
        "kinds": kinds.most_common(),
        "http": http_by.most_common(40),
        "filled_ge_1": filled.most_common(),
        "novig_gemini_order_posts": posts,
        "http_errors": errors[:40],
        "n_http_errors": len(errors),
    }


def order_stats(start: datetime) -> dict:
    events = Counter()
    venues = Counter()
    sent_venues = Counter()
    filled_venues = Counter()
    samples = defaultdict(list)
    n_window = 0
    first = None
    last = None
    for row in iter_jsonl(ORDERS):
        stamp = parse_dt(row.get("ts") or row.get("timestamp") or row.get("compared_at") or row.get("at"))
        if stamp is None or stamp < start:
            continue
        n_window += 1
        if first is None:
            first = stamp
        last = stamp
        event = str(row.get("event") or "")
        events[event] += 1
        venue = str(row.get("venue") or "").lower()
        if venue:
            venues[venue] += 1
        if event in ("sent", "order", "posted"):
            sent_venues[venue or pair_from_bet(row)] += 1
        if event == "filled":
            filled_venues[venue] += 1
        if venue in ("novig", "gemini") or "novig" in str(row.get("bet_key") or "").lower() or "gemini" in str(row.get("bet_key") or "").lower():
            if len(samples[venue or event]) < 12:
                samples[venue or event].append({
                    "at": fmt_et(stamp),
                    "event": event,
                    "venue": venue,
                    "game": str(row.get("game") or "")[:80],
                    "instrument": str(row.get("instrument") or "")[:80],
                    "note": public_note(str(row.get("note") or row.get("reason") or "")[:120], 120),
                })
    return {
        "n_window": n_window,
        "first": fmt_et(first),
        "last": fmt_et(last),
        "events": events.most_common(),
        "venues": venues.most_common(),
        "sent_venues": sent_venues.most_common(),
        "filled_venues": filled_venues.most_common(),
        "novig_gemini_samples": {k: v for k, v in samples.items()},
    }


def pair_from_bet(row: dict) -> str:
    key = str(row.get("bet_key") or "")
    parts = key.split("\t")
    if len(parts) >= 8:
        return f"{parts[6]} / {parts[7]}"
    return key[-40:]


def live_slots() -> dict:
    try:
        keys = live_lock_orders.open_lock_keys()
    except Exception as exc:
        keys = []
        lock_err = type(exc).__name__
    else:
        lock_err = ""
    b = load_json(B_WATCH) or {}
    open_b = []
    try:
        open_b = live_strategy_b.open_matches(b if isinstance(b, dict) else {})
    except Exception:
        open_b = []
    stages = Counter(str(r.get("stage") or "") for r in (b.get("matches") or []) if isinstance(r, dict))
    return {
        "lock_open": [str(k)[:120] for k in keys],
        "lock_open_n": len(keys),
        "lock_max": int(live_lock_orders.MAX_OPEN_LOCKS),
        "lock_err": lock_err,
        "b_currently_open_field": b.get("currently_open") if isinstance(b, dict) else None,
        "b_open_n": len(open_b),
        "b_max": int(live_strategy_b.MAX_OPEN_B_MATCHES),
        "b_open": [
            {
                "game": r.get("game"),
                "stage": r.get("stage"),
                "venue": r.get("venue"),
                "opened_at": r.get("opened_at"),
            }
            for r in open_b
        ],
        "b_stage_counts": stages.most_common(),
        "b_updated_at": b.get("updated_at") if isinstance(b, dict) else "",
        "orders_stopped_exists": ORDERS_STOP.is_file(),
        "lock_last_skip": load_json(LOCK_SKIP) or {},
        "net_max": str(NET_MAX),
        "b_novig_orders": b.get("novig_orders") if isinstance(b, dict) else "",
    }


def collect() -> dict:
    restart = find_restart()
    start = parse_dt(restart["window_start"]) or RESTART_HINT
    consider_raw = load_json(CONSIDER)
    consider_rows = []
    if isinstance(consider_raw, dict):
        consider_rows = [r for r in (consider_raw.get("rows") or []) if isinstance(r, dict)]
    elif isinstance(consider_raw, list):
        consider_rows = [r for r in consider_raw if isinstance(r, dict)]
    gemini_from = datetime(2026, 10, 1, tzinfo=ET)
    return {
        "written_at": fmt_et(NOW),
        "restart": restart,
        "window_start_et": fmt_et(start),
        "novig_account": pull_novig_account(),
        "novig_fills": pull_novig_fills(),
        "gemini_filled": pull_gemini("filled", gemini_from, NOW + timedelta(minutes=5)),
        "gemini_cancelled": pull_gemini("cancelled", start, NOW + timedelta(minutes=5)),
        "gemini_all_window": pull_gemini(None, start, NOW + timedelta(minutes=5)),
        "consider": consider_stats(consider_rows, start),
        "order_io": io_stats(start),
        "orders": order_stats(start),
        "slots": live_slots(),
        "code": {
            "lock_includes_novig": True,
            "lock_novig_via": "live_game_pollers._compared -> novig_live.novig_candidates (Kalshi/Gemini/Polymarket vs Novig)",
            "strategy_b_venues": list(live_strategy_b.VENUE_ORDER),
            "strategy_b_novig": "never sent by Strategy B",
            "NOVIG_ORDERS_ENABLED": bool(novig_live.NOVIG_ORDERS_ENABLED),
            "NET_MAX": str(NET_MAX),
            "lock_max": int(live_lock_orders.MAX_OPEN_LOCKS),
            "b_max": int(live_strategy_b.MAX_OPEN_B_MATCHES),
            "gemini_no_rejection": "qualifies() denies when Gemini No is not a buyable offer (size missing/zero)",
        },
    }


def last_gemini_fill(data: dict) -> dict | None:
    rows = list((data.get("gemini_filled") or {}).get("fills") or [])
    rows.sort(key=lambda r: r.get("ts") or "")
    return rows[-1] if rows else None


def html_page(data: dict) -> str:
    stamp = data.get("written_at") or fmt_et(NOW)
    acc = data.get("novig_account") or {}
    nf = data.get("novig_fills") or {}
    gf = data.get("gemini_filled") or {}
    gc = data.get("gemini_cancelled") or {}
    ga = data.get("gemini_all_window") or {}
    con = data.get("consider") or {}
    io = data.get("order_io") or {}
    orders = data.get("orders") or {}
    slots = data.get("slots") or {}
    restart = data.get("restart") or {}
    last_g = last_gemini_fill(data)
    byv = con.get("by_venue") or {}
    novig_v = byv.get("novig") or {}
    gemini_v = byv.get("gemini") or {}
    kalshi_v = byv.get("kalshi") or {}
    poly_v = byv.get("polymarket") or {}
    novig_under = con.get("novig_under_cap") or []
    gemini_under = con.get("gemini_under_cap") or []
    posts = io.get("novig_gemini_order_posts") or []
    lock_n = slots.get("lock_open_n")
    b_n = slots.get("b_open_n")
    b_field = slots.get("b_currently_open_field")
    broken = []
    if acc.get("NOVIG_ORDERS_ENABLED") is not True:
        broken.append("NOVIG_ORDERS_ENABLED is not True")
    if acc.get("orders_live") is not True:
        broken.append("novig orders_live() is False (" + str(acc.get("trading_key_note") or "") + ")")
    if acc.get("balance_usd") is None:
        broken.append("Novig balance unreadable (HTTP " + str(acc.get("balance_http")) + ")")
    if slots.get("orders_stopped_exists"):
        broken.append("orders_stopped.json is present (latch on)")
    if nf.get("called") is False:
        broken.append("Novig fills GET failed")
    if gf.get("called") is False or gf.get("http") not in (200, None):
        if gf.get("http") not in (200,):
            broken.append("Gemini filled-history HTTP " + str(gf.get("http")))

    novig_why = []
    if acc.get("orders_live") is not True:
        novig_why.append(
            f"The lock bot will not POST Novig: orders_live() is False. Flag NOVIG_ORDERS_ENABLED={acc.get('NOVIG_ORDERS_ENABLED')}, "
            f"trading_key_ready={acc.get('trading_key_ready')} ({esc(acc.get('trading_key_note'))})."
        )
    else:
        novig_why.append(
            "Novig orders are live in code (NOVIG_ORDERS_ENABLED True and trading_key_ready True). Strategy B never sends Novig. Only the lock bot can."
        )
    if novig_v.get("looks", 0) == 0:
        novig_why.append(
            f"In the opportunities window ({esc(con.get('first_at') or restart.get('window_start_et'))} → now, {con.get('n_window')} looks kept; file cap 500), "
            "Novig was in 0 Yes/No pairs. The lock bot does build Kalshi/Gemini/Polymarket vs Novig pairs in code, but none of those pairs made the 0.99 log band this window."
        )
    else:
        novig_why.append(
            f"Novig was in {novig_v.get('looks')} look(s), {novig_v.get('sent')} sent, {novig_v.get('denied')} denied, "
            f"{novig_v.get('under_net_max')} at or under NET_MAX {esc(str(NET_MAX))}."
        )
    if not novig_under:
        novig_why.append(
            f"No Novig look in this window had after-fee cost at or under the send cap {esc(str(NET_MAX))}. "
            "That is cheaper-leg / price, not a missing wire, unless orders_live is False."
        )
    if (nf.get("n_house") or 0) == 0:
        novig_why.append(
            f"Venue GET /v3/portfolio/fills HTTP pages {[p.get('http') for p in (nf.get('http_pages') or [])]}: "
            f"{nf.get('n')} row(s), {nf.get('n_house')} with qty >= 1. Still empty."
        )
    io_novig = dict(io.get("counts") or [])
    # counts is list of tuples
    io_map = {k: v for k, v in (io.get("counts") or [])}
    if io_map.get("novig", 0) == 0:
        novig_why.append("order_io.jsonl has 0 Novig rows in this window (no book GET and no POST logged).")

    gemini_why = []
    if last_g:
        gemini_why.append(
            f"Last Gemini house fill on the venue: {esc(last_g.get('time_et'))} {esc(last_g.get('ticker'))} "
            f"{esc(last_g.get('outcome'))} {esc(last_g.get('side'))} qty {esc(last_g.get('qty'))} @ {esc(last_g.get('price'))} "
            f"({esc(last_g.get('event'))})."
        )
    else:
        gemini_why.append("Gemini filled-history returned 0 house fills in the Oct 1–now pull.")
    gemini_why.append(
        f"Since the live window start ({esc(restart.get('window_start_et'))}): Gemini HTTP order posts in order_io = "
        f"{len([p for p in posts if p.get('venue')=='gemini'])}. Gemini looks in opportunities = {gemini_v.get('looks')}, "
        f"sent = {gemini_v.get('sent')}, denied = {gemini_v.get('denied')}, under NET_MAX = {gemini_v.get('under_net_max')}."
    )
    gemini_why.append(
        f"Venue history this window: filled HTTP {gf.get('http')} n={gf.get('n')}; cancelled HTTP {gc.get('http')} n={gc.get('n')}; "
        f"unfiltered HTTP {ga.get('http')} n={ga.get('n')}."
    )
    if gemini_v.get("looks", 0) == 0:
        gemini_why.append("Gemini never appeared as a Yes or No venue in the opportunities window, so it was not the cheaper legal leg of any logged pair.")
    elif gemini_v.get("sent", 0) == 0:
        gemini_why.append("Gemini was in some looks but none were sent. See the deny-reason table.")
    sports_g = gemini_v.get("sports") or []
    sports_all = con.get("sports") or []
    if sports_all:
        gemini_why.append("Lock flow sports this window: " + ", ".join(f"{s} {n}" for s, n in sports_all) + ".")
    if sports_g:
        gemini_why.append("Looks that included Gemini: " + ", ".join(f"{s} {n}" for s, n in sports_g) + ".")

    slots_note = (
        f"Lock bot open slots now: {lock_n} / {slots.get('lock_max')}. "
        f"Strategy B open now: {b_n} / {slots.get('b_max')} (watch file currently_open field={b_field}). "
        f"orders_stopped.json exists: {slots.get('orders_stopped_exists')}. "
        "Strategy B 2/2 only blocks NEW lock-bot pairs on those same tennis matches, not Gemini/Novig as venues. "
        "Lock 0/3 would not by itself explain zero Novig or a quiet Gemini."
    )

    look_rows = []
    for venue in ("kalshi", "polymarket", "gemini", "novig"):
        v = byv.get(venue) or {}
        look_rows.append([
            venue,
            v.get("looks"),
            v.get("sent"),
            v.get("denied"),
            v.get("under_net_max"),
            v.get("min_net"),
            v.get("max_net"),
            ", ".join(f"{a} {b}" for a, b in (v.get("sports") or [])[:4]),
        ])
    pair_rows = [[p, n] for p, n in (con.get("pairs") or [])]
    reason_rows = []
    for venue in ("kalshi", "polymarket", "gemini", "novig"):
        for reason, n in ((byv.get(venue) or {}).get("reasons") or []):
            reason_rows.append([venue, reason, n])
    partner_rows = []
    for venue in ("gemini", "novig"):
        for partner, n in ((byv.get(venue) or {}).get("partners") or []):
            partner_rows.append([venue, partner, n])
    fill_rows = []
    for row in (gf.get("fills") or []):
        fill_rows.append([
            row.get("time_et"),
            row.get("ticker"),
            row.get("event"),
            row.get("outcome"),
            row.get("side"),
            row.get("qty"),
            row.get("price"),
            row.get("status"),
        ])
    under_rows = []
    for row in novig_under[:40]:
        under_rows.append([row.get("at"), "novig", row.get("sport"), row.get("game"), row.get("pair"), row.get("net"), row.get("decision"), row.get("reason")])
    for row in gemini_under[:40]:
        under_rows.append([row.get("at"), "gemini", row.get("sport"), row.get("game"), row.get("pair"), row.get("net"), row.get("decision"), row.get("reason")])
    io_rows = [[v, n] for v, n in (io.get("counts") or [])]
    io_kind_rows = [[k, n] for k, n in (io.get("kinds") or [])[:30]]
    post_rows = [[p.get("at"), p.get("venue"), p.get("kind"), p.get("http"), p.get("instrument"), p.get("qty"), p.get("note")] for p in posts]
    err_rows = [[e.get("at"), e.get("venue"), e.get("kind"), e.get("http"), e.get("note")] for e in (io.get("http_errors") or [])]
    b_rows = [[r.get("game"), r.get("stage"), r.get("venue"), r.get("opened_at")] for r in (slots.get("b_open") or [])]
    lock_rows = [[k] for k in (slots.get("lock_open") or [])]
    skip = slots.get("lock_last_skip") or {}
    gemini_window_rows = []
    for row in (ga.get("all_rows") or gc.get("all_rows") or [])[:30]:
        gemini_window_rows.append([
            row.get("time_et") or row.get("created_et"),
            row.get("ticker"),
            row.get("status"),
            row.get("outcome"),
            row.get("qty"),
            row.get("price"),
        ])

    broken_html = (
        "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in broken) + "</ul>"
        if broken
        else "<p>No broken-wire flag from this read: Novig fills GET ran, Gemini history ran, latch file absent unless noted above.</p>"
    )

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Novig zero and Gemini quiet — 23 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
ul, ol {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Why Novig is still 0, and why Gemini has been quiet</h1>
<p class="note">America/New_York. Written {esc(stamp)}. Research live. Not gold. Not DailyRun. Read-only: venue fill history + live deny logs. This page does not place, cancel, flatten, sell, GTC, or start a second Strategy B. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout warn">
<h2>Novig — actual why</h2>
<ul>
{''.join(f'<li>{item}</li>' for item in novig_why)}
</ul>
<p>Balance this read: HTTP {esc(acc.get('balance_http'))}, USD {esc(acc.get('balance_usd'))} (desk-1 was ~$10 historically; this is the live number, not a guess). Keys present: {esc(acc.get('keys_present'))}. No secrets on this page.</p>
</div>

<div class="callout warn">
<h2>Gemini — actual why</h2>
<ul>
{''.join(f'<li>{item}</li>' for item in gemini_why)}
</ul>
<p>Last Gemini fill time: <strong>{esc(last_g.get('time_et') if last_g else 'none in the Oct 1–now filled pull')}</strong>.</p>
</div>

<div class="callout ok">
<h2>Broken vs never the cheapest legal leg</h2>
{broken_html}
<p>{esc(slots_note)}</p>
<p>Lock bot <em>does</em> consider Novig books in pair construction (Kalshi, Gemini, or Polymarket vs Novig). Strategy B venue list is Kalshi / Gemini / Polymarket only. Gemini No with missing size is denied as not a real offer; Gemini can still be the Yes leg.</p>
<p>Live window start: {esc(restart.get('window_start_et'))} ({esc(restart.get('source'))}). Opportunities file keeps the newest 500 distinct looks; this window used {esc(con.get('n_window'))} of {esc(con.get('n_file'))} stored rows (first {esc(con.get('first_at'))}, last {esc(con.get('last_at'))}).</p>
</div>

<h2>Looks vs sends vs denials by venue</h2>
<p class="note">A look is an opportunities row at or under 0.99 after fees. Sent means the log marked sent. A venue is counted if it is the Yes shop or the No shop. Click headers to sort.</p>
{table(
    [("Venue", "text"), ("Looks", "num"), ("Sent", "num"), ("Denied", "num"), ("At or under NET_MAX 0.984", "num"), ("Min net", "num"), ("Max net", "num"), ("Sports", "text")],
    look_rows,
)}

<h2>Which pair shops won the look</h2>
{table([("Yes / No pair", "text"), ("Looks", "num")], pair_rows)}

<h2>Gemini / Novig as Yes vs No</h2>
{table([("Venue", "text"), ("Role", "text"), ("Looks", "num")], partner_rows)}

<h2>Deny reasons in the window</h2>
{table([("Venue in pair", "text"), ("Reason bucket", "text"), ("N", "num")], reason_rows)}

<h2>Looks that included Novig or Gemini and were at or under the send cap</h2>
<p class="note">Empty Novig here means Novig was never cheap enough (or never in the pair) under {esc(str(NET_MAX))}.</p>
{table(
    [("When", "date"), ("Venue", "text"), ("Sport", "text"), ("Game", "text"), ("Pair", "text"), ("Net", "num"), ("Decision", "text"), ("Reason", "text")],
    under_rows,
)}

<h2>Gemini venue fills (qty >= 1, status filled)</h2>
<p class="note">POST /v1/prediction-markets/orders/history status=filled, from 2026-10-01 through now. HTTP {esc(gf.get('http'))}, n={esc(gf.get('n'))}, house={esc(gf.get('n_house'))}.</p>
{table(
    [("Time ET", "date"), ("Symbol", "text"), ("Event", "text"), ("Outcome", "text"), ("Side", "text"), ("Qty", "num"), ("Price", "num"), ("Status", "text")],
    fill_rows,
)}

<h2>Gemini HTTP tickets since window start (venue history)</h2>
<p class="note">Cancelled pull HTTP {esc(gc.get('http'))} n={esc(gc.get('n'))}. Unfiltered pull HTTP {esc(ga.get('http'))} n={esc(ga.get('n'))} note={esc(ga.get('note'))}.</p>
{table(
    [("Time ET", "date"), ("Symbol", "text"), ("Status", "text"), ("Outcome", "text"), ("Qty", "num"), ("Price", "num")],
    gemini_window_rows,
)}

<h2>order_io HTTP in the window</h2>
<p class="note">Local tape, {esc(io.get('n_window'))} rows from {esc(io.get('first'))} to {esc(io.get('last'))}. Not a fill unless qty >= 1.</p>
{table([("Venue", "text"), ("Rows", "num")], io_rows)}
{table([("Venue:kind", "text"), ("Rows", "num")], io_kind_rows)}
<h3>Novig / Gemini order posts</h3>
{table(
    [("When", "date"), ("Venue", "text"), ("Kind", "text"), ("HTTP", "num"), ("Instrument", "text"), ("Fill qty", "num"), ("Note", "text")],
    post_rows,
)}
<h3>HTTP 400+ on Novig / Gemini</h3>
{table(
    [("When", "date"), ("Venue", "text"), ("Kind", "text"), ("HTTP", "num"), ("Note", "text")],
    err_rows,
)}

<h2>Lock vs Strategy B slots right now</h2>
{table([("Lock open bet_key", "text")], lock_rows)}
{table(
    [("Strategy B open game", "text"), ("Stage", "text"), ("Venue", "text"), ("Opened", "date")],
    b_rows,
)}
<p class="note">Last lock skip file: {esc(skip.get('at'))} {esc(skip.get('game'))} {esc(skip.get('reason'))}. orders.jsonl window events: {esc(orders.get('events'))}.</p>

<h2>Supervisor starts (from live_supervisor.log)</h2>
{table(
    [("Time ET", "date"), ("Line", "text")],
    [[h.get("time_et"), h.get("line")] for h in (restart.get("recent") or [])],
)}

<p class="note">Sources: Novig GET /v3/portfolio/fills and GET balance; Gemini POST /v1/prediction-markets/orders/history; local considerations.json (500-row cap), order_io.jsonl, orders.jsonl, strategy_b_watch.json, lock_last_skip.json, live_supervisor.log. Code: live_lock_orders.py, live_strategy_b.py, novig_live.py, live_game_pollers._compared. Sibling owns orders_performance.html. No secrets. No tickets sold.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    return inject_report_page_extras(body)


def main() -> int:
    data = collect()
    DUMP.parent.mkdir(parents=True, exist_ok=True)
    DUMP.write_text(json.dumps(redact(data), indent=2, default=str), encoding="utf-8")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    html = html_page(data)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(PAGE)
    print(f"wrote {PAGE}")
    print(f"dump {DUMP}")
    acc = data.get("novig_account") or {}
    print("novig_orders_live", acc.get("orders_live"), "balance", acc.get("balance_usd"), "fills", (data.get("novig_fills") or {}).get("n_house"))
    last_g = last_gemini_fill(data)
    print("last_gemini_fill", (last_g or {}).get("time_et"))
    print("window", data.get("window_start_et"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
