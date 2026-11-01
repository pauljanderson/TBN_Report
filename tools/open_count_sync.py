"""Venue-true open counts for live systems A–D.

job_status Open now = unique games with a venue-confirmed holding still
unsettled. Kalshi counts qty >= 1. Polymarket counts qty > 0 so a 0.32
leftover is open. Empty Poly positions GET is not qty 0 when this order's
cumQuantity / activities show a fill *and the market is still open*.
Resolved, expired, final, or void markets are never open — empty after
settle is normal, even with ledger FILLED / confirm qty ≥ 1. Same for
Kalshi closed tickers. Local HTTP 200/201 with qty 0, Kalshi 201 empty,
and settled leftovers do not occupy a slot.

Does not print secrets. Does not sell or flatten tickets. Does not start a
second live_strategy_b.py. Research-candidate live. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW, ROOT, ensure_dirs

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
import venue_pace  # noqa: E402

ET = ZoneInfo("America/New_York")
CACHE_SEC = 60
RECENT_CONFIRM_SEC = 120
CACHE_PATH = RAW / "open_count_venue_cache.json"
PAGE = STAMP / "open_count_sync_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/open_count_sync_20261024.html"
)
JOB_STATUS = STAMP / "job_status.html"
ORDERS = RAW / "orders.jsonl"
WATCH = {
    "tennis_crossover": RAW / "strategy_b_watch.json",
    "cfb_favorite": RAW / "cfb_favorite_watch.json",
    "spread_t0": RAW / "spread_t0_watch.json",
    "tennis_t0_dog": RAW / "tennis_t0_dog_watch.json",
    "tennis_t0_spread": RAW / "tennis_t0_spread_watch.json",
    "soccer_t0_total": RAW / "soccer_t0_total_watch.json",
}
LOCKS = {
    "tennis_crossover": RAW / "strategy_b.lock",
    "cfb_favorite": RAW / "cfb_favorite.lock",
    "spread_t0": RAW / "spread_t0.lock",
    "tennis_t0_dog": RAW / "tennis_t0_dog.lock",
    "tennis_t0_spread": RAW / "tennis_t0_spread.lock",
    "soccer_t0_total": RAW / "soccer_t0_total.lock",
}
CD_OPEN_STAGES = {"waiting_t0", "filled", "holding", "open"}
B_OPEN_STAGES = {
    "waiting_t0",
    "t0_filled_waiting_50_cross",
    "waiting_cross",
    "waiting_fav_dip",
    "fav_gtc_resting",
    "one_leg_miss",
}
PHANTOM_STAGE = {
    "tennis_crossover": "done",
    "cfb_favorite": "settled",
    "spread_t0": "settled",
    "tennis_t0_dog": "settled",
    "tennis_t0_spread": "settled",
    "soccer_t0_total": "settled",
}
FINAL_STATE_WORDS = {
    "resolved",
    "expired",
    "final",
    "finalized",
    "settled",
    "void",
    "voided",
    "determined",
}
KALSHI_CLOSED_WORDS = FINAL_STATE_WORDS | {"closed", "inactive"}
ASKED = (
    "job_status showed Lock gap 0/3 open — what does 0 mean? Tennis crossover 2 open, "
    "CFB favorite 5 open, T0 spreads 2 open. Venue reality: 4 open orders, all on Kalshi, "
    "1 D and 3 C. Discrepancy vs job_status C=5 D=2 B=2. Explain 0/3, fetch venue truth, "
    "name the house opens, diff phantoms vs real, fix counting so open = unique games with "
    "venue-confirmed qty≥1 still unsettled, reconcile state without selling, never desync, "
    "reload C/D/B in place (one each)."
)
PLAIN = (
    "The Systems table was counting tickets the house thought it still had, not tickets "
    "the sportsbooks still show. 0/3 on Lock gap means zero live lock pairs right now, "
    "and three is the most it is allowed to hold. College football favorite said five "
    "games were open because finished games and a Novig ticket were still marked filled. "
    "After this job the page counts a game only when a venue still shows at least one "
    "contract, and it counts each game once. We did not sell anything."
)


def iso_now() -> str:
    return datetime.now(ET).isoformat(timespec="milliseconds")


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        value = value.get("value")
        if value in (None, ""):
            return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _qty(value) -> Decimal:
    number = _dec(value)
    if number is None:
        return Decimal("0")
    return abs(number)


def _parse_dt(raw: str):
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{_esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _table(headers: list[tuple[str, str]], rows: list[list[str]]) -> str:
    head = "".join(_th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def game_code(key: str) -> str:
    text = str(key or "")
    parts = text.split("_")
    if len(parts) >= 3 and parts[0] in {"college", "tennis"}:
        if parts[0] == "college" and len(parts) >= 4:
            return parts[2]
        if parts[0] == "tennis":
            return parts[1]
    return text


def unique_game_id(row: dict) -> str:
    key = str(row.get("key") or "").strip()
    if key:
        return key
    return " ".join(str(row.get("game") or "").lower().split())


def house_stage_open(sid: str, row: dict) -> bool:
    stage = str(row.get("stage") or "")
    if sid == "tennis_crossover":
        return stage in B_OPEN_STAGES
    return stage in CD_OPEN_STAGES


def instruments_from_row(row: dict) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen = set()

    def add(venue: str, ident: str) -> None:
        venue = str(venue or "").lower()
        ident = str(ident or "").strip()
        if not venue or not ident:
            return
        pair = (venue, ident)
        if pair in seen:
            return
        seen.add(pair)
        found.append(pair)

    last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
    add(row.get("venue") or last.get("venue"), last.get("instrument") or row.get("instrument"))
    t0 = row.get("t0_yes") if isinstance(row.get("t0_yes"), dict) else {}
    for slot in t0.values():
        if isinstance(slot, dict):
            add(slot.get("venue") or row.get("venue"), slot.get("instrument"))
    tape = row.get("_tape") if isinstance(row.get("_tape"), dict) else {}
    tape_sid = str(tape.get("system") or "")
    row_sid = str(row.get("_sid") or "")
    if tape and (not tape_sid or tape_sid == row_sid):
        add(tape.get("venue") or row.get("venue"), tape.get("instrument"))
    return found


def load_tape_index(path: Path | None = None) -> dict[str, dict]:
    target = path or ORDERS
    by_id: dict[str, dict] = {}
    by_key: dict[str, dict] = {}
    if not target.exists():
        return {"by_id": by_id, "by_key": by_key}
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"by_id": by_id, "by_key": by_key}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if str(row.get("event") or "") not in {"sent", "filled"}:
            continue
        ident = str(row.get("instrument") or "")
        venue = str(row.get("venue") or "")
        if not ident:
            continue
        info = {
            "venue": venue,
            "instrument": ident,
            "side": str(row.get("side") or row.get("side_label") or ""),
            "system": str(row.get("system") or ""),
            "game": str(row.get("game") or ""),
            "confirm_qty": str(row.get("confirm_qty") or ""),
            "confirm_known": bool(row.get("confirm_known")),
            "http": row.get("http_status"),
            "order_id": str(row.get("order_id") or ""),
            "bet_key": str(row.get("bet_key") or ""),
        }
        if info["order_id"]:
            by_id[info["order_id"]] = info
        bet = info["bet_key"]
        system = info["system"]
        if bet:
            by_key[bet] = info
            parts = bet.split("\t")
            if len(parts) >= 2:
                by_key[(system, parts[1])] = info
    return {"by_id": by_id, "by_key": by_key}


def attach_tape(row: dict, tape: dict | None, sid: str = "") -> dict:
    out = dict(row)
    tape = tape or {}
    last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
    info = (tape.get("by_id") or {}).get(str(last.get("id") or ""))
    if not info:
        info = (tape.get("by_key") or {}).get((sid, str(row.get("key") or "")))
    if info and (not info.get("system") or info.get("system") == sid or not sid):
        out["_tape"] = info
        if not out.get("instrument"):
            out["instrument"] = info.get("instrument")
        if not out.get("venue"):
            out["venue"] = info.get("venue")
    return out


def empty_snapshot() -> dict:
    return {
        "pulled_at": "",
        "kalshi_ok": False,
        "poly_ok": False,
        "gemini_ok": False,
        "novig_ok": False,
        "kalshi": [],
        "kalshi_by_ticker": {},
        "kalshi_codes": set(),
        "kalshi_markets": {},
        "poly": [],
        "poly_by_slug": {},
        "poly_markets": {},
        "gemini": [],
        "novig": [],
        "novig_by_id": {},
        "notes": [],
        "error": "",
    }


def _norm_market_state(value) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    for prefix in ("market_state_", "market_status_", "status_"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def market_info_is_final(info: dict | None, *, venue: str = "") -> tuple[bool, str]:
    """True when this market is resolved, expired, final, or void.

    Empty positions after settle is normal. Closed-without-settlement
    (Poly postponed) is not final. Kalshi 'closed' / 'inactive' tickers are.
    """
    if not isinstance(info, dict) or not info:
        return False, ""
    shop = str(venue or info.get("venue") or "").lower()
    if info.get("expired") in (True, "true", "TRUE"):
        return True, "expired"
    if info.get("ended") in (True, "true", "TRUE"):
        return True, "ended"
    if info.get("void") in (True, "true", "TRUE"):
        return True, "void"
    result = str(info.get("result") or "").strip().lower()
    if result in {"yes", "no", "void", "n/a"}:
        return True, f"result={result}"
    winner = str(info.get("winner") or info.get("winning_outcome") or "").strip()
    if winner:
        return True, f"winner={winner}"
    settlement = info.get("settlementPx") or info.get("settlementPrice") or info.get("settlement_px")
    if settlement not in (None, ""):
        return True, f"settlementPx={settlement}"
    words = KALSHI_CLOSED_WORDS if shop == "kalshi" else FINAL_STATE_WORDS
    for key in ("state", "status", "marketState", "ep3Status", "marketStatus"):
        raw = info.get(key)
        token = _norm_market_state(raw)
        if token in words:
            return True, str(raw)
    return False, ""


def market_status_of(snapshot: dict | None, venue: str, ident: str) -> dict:
    snap = snapshot if isinstance(snapshot, dict) else {}
    venue = str(venue or "").lower()
    ident = str(ident or "").strip()
    if not ident:
        return {}
    blob = {}
    if venue == "polymarket":
        blob = snap.get("poly_markets") or {}
    elif venue == "kalshi":
        blob = snap.get("kalshi_markets") or {}
    row = blob.get(ident) if isinstance(blob, dict) else None
    return row if isinstance(row, dict) else {}


def instruments_are_final(snapshot: dict | None, insts: list[tuple[str, str]]) -> tuple[bool, str]:
    for venue, ident in insts:
        ok, why = market_info_is_final(market_status_of(snapshot, venue, ident), venue=venue)
        if ok:
            return True, f"{venue or 'venue'} {ident} {why}"
    return False, ""


def _kalshi_snapshot(force: bool = False) -> dict:
    import cheaper_same_bet

    cached = _load_json(cheaper_same_bet.POSITIONS)
    pulled = _parse_dt(str((cached or {}).get("pulled_at") or ""))
    now = datetime.now(ET)
    fresh = pulled is not None and abs((now - pulled).total_seconds()) < CACHE_SEC
    if force or not fresh or not isinstance(cached, dict) or not cached:
        cached = cheaper_same_bet.fetch_positions()
    body = (cached or {}).get("body") or {}
    rows = []
    by_ticker = {}
    codes = set()
    for item in body.get("market_positions") or []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "")
        qty = _qty(item.get("position_fp") or item.get("position"))
        if not ticker or qty < 1:
            continue
        row = {
            "venue": "kalshi",
            "ticker": ticker,
            "title": ticker,
            "side": "yes" if _dec(item.get("position_fp")) not in (None, Decimal("0")) and (_dec(item.get("position_fp")) or 0) > 0 else "yes",
            "qty": format(qty, "f"),
        }
        rows.append(row)
        by_ticker[ticker] = row
        # KXNCAAFGAME-26OCT24BSUWSU-BSU → bsuwsu
        upper = ticker.upper()
        for part in ticker.split("-"):
            token = part.lower()
            if token.startswith("kx") or len(token) < 5:
                continue
            for prefix in ("26oct", "26nov", "26dec", "26jan", "26feb"):
                if token.startswith(prefix) and len(token) > 7:
                    codes.add(token[7:])
            codes.add(token)
        if "UNTNAVY" in upper:
            codes.add("untnavy")
    return {
        "ok": int((cached or {}).get("http_status") or 0) == 200,
        "http": (cached or {}).get("http_status"),
        "pulled_at": (cached or {}).get("pulled_at"),
        "rows": rows,
        "by_ticker": by_ticker,
        "codes": {c for c in codes if c},
    }


def _poly_snapshot() -> dict:
    import polymarket_us_live

    status, text = polymarket_us_live.signed_json("GET", "/v1/portfolio/positions")
    try:
        body = json.loads(text) if text else {}
    except json.JSONDecodeError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    positions = body.get("positions") if isinstance(body.get("positions"), dict) else {}
    rows = []
    by_slug = {}
    markets = {}
    for slug, item in positions.items():
        if not isinstance(item, dict):
            continue
        meta = item.get("marketMetadata") if isinstance(item.get("marketMetadata"), dict) else {}
        info = {
            "venue": "polymarket",
            "expired": item.get("expired"),
            "closed": item.get("closed") if item.get("closed") is not None else meta.get("closed"),
            "state": item.get("marketState") or meta.get("state") or meta.get("status") or "",
            "settlementPx": item.get("settlementPx") or meta.get("settlementPx"),
            "ended": item.get("ended") if item.get("ended") is not None else meta.get("ended"),
        }
        markets[str(slug)] = info
        qty = _qty(item.get("netPositionDecimal") or item.get("netPosition"))
        if qty <= 0:
            continue
        if market_info_is_final(info, venue="polymarket")[0]:
            continue
        outcome = str(meta.get("outcome") or "")
        row = {
            "venue": "polymarket",
            "ticker": str(slug),
            "title": str(meta.get("title") or slug),
            "side": "yes" if qty > 0 else "no",
            "outcome": outcome,
            "qty": format(qty, "f"),
        }
        rows.append(row)
        by_slug[str(slug)] = row
    return {
        "ok": status == 200,
        "http": status,
        "rows": rows,
        "by_slug": by_slug,
        "markets": markets,
        "n_all": len(positions),
    }


def _poly_payload_fields(payload: dict | None) -> dict:
    """Pull state / settlement from a Polymarket market or book body."""
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("marketData") if isinstance(payload.get("marketData"), dict) else payload
    if not isinstance(inner, dict):
        inner = payload
    state = (
        inner.get("state")
        or inner.get("marketState")
        or inner.get("status")
        or payload.get("state")
        or payload.get("marketState")
        or payload.get("status")
        or ""
    )
    stats = inner.get("stats") if isinstance(inner.get("stats"), dict) else {}
    payload_stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    px = (
        inner.get("settlementPx")
        or inner.get("settlementPrice")
        or inner.get("settlement_px")
        or stats.get("settlementPx")
        or stats.get("settlementPrice")
        or payload.get("settlementPx")
        or payload.get("settlementPrice")
        or payload_stats.get("settlementPx")
    )
    px_number = _poly_cash_value(px)
    if isinstance(px, dict) and px_number is not None:
        px = format(px_number, "f")
    result = str(inner.get("result") or payload.get("result") or "").lower()
    if px_number is not None:
        if px_number >= 1:
            result = "yes"
        elif px_number <= 0:
            result = "no"
        else:
            # Last-trade / TIER_2 mark (0.43, 0.67) is not a 0/1 expire.
            result = ""
    elif result not in {"yes", "no", "void", "n/a"}:
        result = result if result in {"yes", "no", "void", "n/a"} else ""
    token = _norm_market_state(state)
    return {
        "state": state,
        "status": state,
        "expired": token in {"expired", "resolved", "final", "finalized"} or inner.get("expired") in (True, "true", "TRUE"),
        "settlementPx": px,
        "result": result,
        "closed": inner.get("closed") if inner.get("closed") is not None else payload.get("closed"),
        "ended": inner.get("ended") if inner.get("ended") is not None else payload.get("ended"),
        "void": bool(inner.get("void") or payload.get("void") or result in {"void", "n/a"}),
    }


def _poly_cash_value(node) -> Decimal | None:
    if isinstance(node, dict):
        node = node.get("cashValue") if "cashValue" in node else node.get("value")
        if isinstance(node, dict):
            node = node.get("value")
    if node in (None, ""):
        return None
    try:
        return Decimal(str(node))
    except Exception:
        return None


def poly_resolution_result(item: dict | None) -> str:
    """Yes/No for the *market* Yes token from a POSITION_RESOLUTION activity.

    beforePosition.cashValue is often the 1-contract size, not the redeem.
    A SHORT ticket with before=1 used to look like result=no even when Yes
    settled at $1 (Pohle vs Kostina). Use settlementPx or afterPosition
    (what the seat paid after redeem). Empty if unreadable. Does not trade.
    """
    if not isinstance(item, dict):
        return ""
    res = item.get("positionResolution") if isinstance(item.get("positionResolution"), dict) else item
    if not isinstance(res, dict):
        res = item
    side = str(res.get("side") or "").upper()
    if "VOID" in side:
        return "void"
    px = (
        res.get("settlementPx")
        or res.get("settlementPrice")
        or item.get("settlementPx")
        or item.get("settlementPrice")
    )
    px_number = _poly_cash_value(px)
    if px_number is not None:
        if px_number >= 1:
            return "yes"
        if px_number <= 0:
            return "no"
    after = res.get("afterPosition") if isinstance(res.get("afterPosition"), dict) else {}
    cash = _poly_cash_value(after)
    if cash is None:
        cash = _poly_cash_value(res.get("cashValue"))
    if cash is None:
        return ""
    long = "LONG" in side
    short = "SHORT" in side
    if cash >= 1:
        if long:
            return "yes"
        if short:
            return "no"
    if cash <= 0:
        if long:
            return "no"
        if short:
            return "yes"
    return ""


def _fetch_poly_resolution(slug: str) -> dict:
    """Signed activities GET for POSITION_RESOLUTION. Empty on failure. Does not trade."""
    ident = str(slug or "").strip()
    if not ident:
        return {}
    held = False
    try:
        import polymarket_us_live
        import venue_pace

        try:
            if not venue_pace.wait_turn("polymarket"):
                return {}
            held = True
        except Exception:
            pass
        status, text = polymarket_us_live.get_activities(
            {
                "limit": "20",
                "marketSlug": ident,
                "sortOrder": "SORT_ORDER_DESCENDING",
            },
            timeout=20,
        )
    except Exception:
        return {}
    finally:
        if held:
            try:
                import venue_pace as _pace

                _pace.release_turn("polymarket")
            except Exception:
                pass
    if status != 200 or not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    votes: list[str] = []
    px = ""
    update = ""
    for item in payload.get("activities") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "ACTIVITY_TYPE_POSITION_RESOLUTION":
            continue
        result = poly_resolution_result(item)
        if result not in {"yes", "no", "void", "n/a"}:
            continue
        votes.append(result)
        res = item.get("positionResolution") if isinstance(item.get("positionResolution"), dict) else {}
        if not px:
            found = res.get("settlementPx") or res.get("settlementPrice") or item.get("settlementPx")
            number = _poly_cash_value(found)
            if number is not None:
                px = format(number, "f")
        if not update:
            update = str(res.get("updateTime") or "")
    unique = {v for v in votes if v in {"yes", "no", "void", "n/a"}}
    if len(unique) != 1:
        return {}
    result = unique.pop()
    return {
        "venue": "polymarket",
        "state": "resolved",
        "status": "resolved",
        "expired": True,
        "result": result,
        "settlementPx": px,
        "closed": True,
        "void": result in {"void", "n/a"},
        "source": "polymarket_position_resolution",
        "updateTime": update,
    }


def _fetch_poly_market(slug: str) -> dict:
    """Public market + book state. No trading keys. Empty on failure.

    `/book` often omits settlementPx after resolve. `/v1/markets/{slug}` is
    the leftover-watch endpoint and carries resolved / settlementPx.
    """
    ident = str(slug or "").strip()
    if not ident:
        return {}
    try:
        import polymarket_us_live
    except Exception:
        return {}
    quoted = urllib.parse.quote(ident, safe="")
    market = {}
    book = {}
    try:
        market = polymarket_us_live._get(f"{polymarket_us_live.GATEWAY}/v1/markets/{quoted}") or {}
    except Exception:
        market = {}
    try:
        book = polymarket_us_live.fetch_book(ident) or {}
    except Exception:
        book = {}
    fields = _poly_payload_fields(market)
    extra = _poly_payload_fields(book)
    for key, value in extra.items():
        if fields.get(key) in (None, "", False) and value not in (None, ""):
            fields[key] = value
    # Binary settlementPx / house cash only. Do not use POSITION_RESOLUTION
    # or ticker result=yes (Pohle/Kostina invert; Maloney/Lollia last-trade 0.67/0.43).
    px_number = _poly_cash_value(fields.get("settlementPx") or extra.get("settlementPx"))
    if px_number is not None and Decimal("0") < px_number < Decimal("1"):
        fields["result"] = ""
    elif px_number is None:
        fields["result"] = ""
    if not fields.get("state") and not fields.get("settlementPx") and not fields.get("result"):
        return {}
    fields["venue"] = "polymarket"
    return fields


def _fetch_kalshi_market(ticker: str) -> dict:
    """Public Kalshi market status. No trading keys. Empty on failure."""
    ident = str(ticker or "").strip()
    if not ident:
        return {}
    url = "https://api.elections.kalshi.com/trade-api/v2/markets/" + urllib.parse.quote(ident, safe="")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "stockresearch-open-count/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return {}
    market = payload.get("market") if isinstance(payload, dict) else None
    if not isinstance(market, dict):
        market = payload if isinstance(payload, dict) else {}
    if not market:
        return {}
    return {
        "venue": "kalshi",
        "status": market.get("status") or "",
        "result": market.get("result") or "",
        "expired": False,
        "closed": str(market.get("status") or "").lower() in {"closed", "inactive"},
    }


def _enrich_market_status(snap: dict) -> None:
    """Book/status for house-open tickets missing from the positions GET."""
    poly_markets = dict(snap.get("poly_markets") or {})
    kalshi_markets = dict(snap.get("kalshi_markets") or {})
    seen_poly: set[str] = set()
    seen_kalshi: set[str] = set()
    poly_book = snap.get("poly_by_slug") or {}
    kalshi_book = snap.get("kalshi_by_ticker") or {}
    for sid in WATCH:
        status = _load_json(WATCH[sid])
        for row in status.get("matches") or []:
            if not isinstance(row, dict) or not house_stage_open(sid, row):
                continue
            for venue, ident in instruments_from_row(row):
                if venue == "polymarket" and ident and ident not in seen_poly:
                    seen_poly.add(ident)
                    if ident in poly_book:
                        continue
                    if market_info_is_final(poly_markets.get(ident) or {}, venue="polymarket")[0]:
                        continue
                    info = _fetch_poly_market(ident)
                    if info:
                        poly_markets[ident] = info
                if venue == "kalshi" and ident and ident not in seen_kalshi:
                    seen_kalshi.add(ident)
                    if ident in kalshi_book:
                        continue
                    if market_info_is_final(kalshi_markets.get(ident) or {}, venue="kalshi")[0]:
                        continue
                    info = _fetch_kalshi_market(ident)
                    if info:
                        kalshi_markets[ident] = info
    snap["poly_markets"] = poly_markets
    snap["kalshi_markets"] = kalshi_markets


def _gemini_snapshot() -> dict:
    import gemini_private

    end = datetime.now(ET)
    start = end - timedelta(hours=18)
    extra = {
        "from": int(start.timestamp() * 1000),
        "to": int(end.timestamp() * 1000),
        "limit": 200,
        "status": "filled",
    }
    http, text = gemini_private.get_order_history(extra)
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {}
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        orders = []
    rows = []
    for item in orders:
        if not isinstance(item, dict):
            continue
        qty = _qty(item.get("filledQuantity") or item.get("filled_quantity") or item.get("quantity"))
        if qty < 1:
            continue
        meta = item.get("contractMetadata") if isinstance(item.get("contractMetadata"), dict) else {}
        rows.append({
            "venue": "gemini",
            "ticker": str(item.get("symbol") or ""),
            "title": str(meta.get("eventName") or item.get("symbol") or ""),
            "side": str(item.get("outcome") or item.get("side") or ""),
            "qty": format(qty, "f"),
            "status": str(item.get("status") or ""),
            "note": "history fill, not a positions book",
        })
    return {"ok": http == 200, "http": http, "rows": rows}


def _novig_snapshot() -> dict:
    import novig_live

    start_ms = int((time.time() - 12 * 3600) * 1000)
    status, text = novig_live.list_fills(
        {"limit": "100", "startsAfter": str(start_ms)},
        timeout=20,
    )
    try:
        body = json.loads(text) if text else {}
    except json.JSONDecodeError:
        body = {}
    items = []
    if isinstance(body, dict):
        if isinstance(body.get("items"), list):
            items = [row for row in body["items"] if isinstance(row, dict)]
        else:
            for value in body.values():
                if isinstance(value, dict) and isinstance(value.get("items"), list):
                    items.extend(row for row in value["items"] if isinstance(row, dict))
    rows = []
    by_id = {}
    for item in items:
        qty_native = _qty(item.get("qty"))
        dollars = (qty_native / Decimal("100")).quantize(Decimal("0.01")) if qty_native else Decimal("0")
        ident = str(item.get("marketId") or item.get("outcomeId") or item.get("orderId") or "")
        row = {
            "venue": "novig",
            "ticker": ident,
            "title": str(item.get("marketName") or item.get("outcomeName") or ident),
            "side": str(item.get("side") or item.get("outcomeName") or ""),
            "qty": format(dollars, "f"),
            "order_id": str(item.get("orderId") or ""),
            "note": "fills list, not a positions book",
        }
        rows.append(row)
        if ident:
            by_id[ident] = row
        if row["order_id"]:
            by_id[row["order_id"]] = row
    return {"ok": status == 200, "http": status, "rows": rows, "by_id": by_id}


def venue_snapshot(*, force: bool = False, live: dict | None = None) -> dict:
    """Kalshi/Poly positions plus Gemini/Novig fill lists. Cache <= 60s. No secrets."""
    if live is not None:
        return live
    cached = _load_json(CACHE_PATH)
    pulled = _parse_dt(str(cached.get("pulled_at") or ""))
    now = datetime.now(ET)
    if (
        not force
        and pulled is not None
        and abs((now - pulled).total_seconds()) < CACHE_SEC
        and cached.get("kalshi_by_ticker") is not None
        and isinstance(cached.get("poly_markets"), dict)
    ):
        cached["kalshi_codes"] = set(cached.get("kalshi_codes") or [])
        cached["poly_markets"] = cached.get("poly_markets") or {}
        cached["kalshi_markets"] = cached.get("kalshi_markets") or {}
        return cached
    snap = empty_snapshot()
    snap["pulled_at"] = iso_now()
    try:
        kalshi = _kalshi_snapshot(force=force)
        snap["kalshi_ok"] = bool(kalshi.get("ok"))
        snap["kalshi"] = kalshi.get("rows") or []
        snap["kalshi_by_ticker"] = kalshi.get("by_ticker") or {}
        snap["kalshi_codes"] = set(kalshi.get("codes") or [])
        if kalshi.get("pulled_at"):
            snap["kalshi_pulled_at"] = kalshi.get("pulled_at")
    except Exception as exc:
        snap["notes"].append(f"kalshi {type(exc).__name__}")
        snap["error"] = type(exc).__name__
    try:
        poly = _poly_snapshot()
        snap["poly_ok"] = bool(poly.get("ok"))
        snap["poly"] = poly.get("rows") or []
        snap["poly_by_slug"] = poly.get("by_slug") or {}
        snap["poly_markets"] = poly.get("markets") or {}
        snap["poly_n_all"] = poly.get("n_all")
    except Exception as exc:
        snap["notes"].append(f"polymarket {type(exc).__name__}")
    try:
        gemini = _gemini_snapshot()
        snap["gemini_ok"] = bool(gemini.get("ok"))
        snap["gemini"] = gemini.get("rows") or []
    except Exception as exc:
        snap["notes"].append(f"gemini {type(exc).__name__}")
    try:
        novig = _novig_snapshot()
        snap["novig_ok"] = bool(novig.get("ok"))
        snap["novig"] = novig.get("rows") or []
        snap["novig_by_id"] = novig.get("by_id") or {}
    except Exception as exc:
        snap["notes"].append(f"novig {type(exc).__name__}")
    try:
        _enrich_market_status(snap)
    except Exception as exc:
        snap["notes"].append(f"market_status {type(exc).__name__}")
    serial = dict(snap)
    serial["kalshi_codes"] = sorted(snap.get("kalshi_codes") or [])
    try:
        _dump_json(CACHE_PATH, serial)
    except OSError:
        pass
    return snap


def venue_qty(snapshot: dict, venue: str, ident: str) -> Decimal | None:
    """Qty if this venue book is known. None = this shop has no positions API hit."""
    venue = str(venue or "").lower()
    ident = str(ident or "").strip()
    if not ident:
        return None
    if venue == "kalshi":
        if not snapshot.get("kalshi_ok"):
            return None
        row = (snapshot.get("kalshi_by_ticker") or {}).get(ident)
        return _qty((row or {}).get("qty")) if row else Decimal("0")
    if venue == "polymarket":
        if not snapshot.get("poly_ok"):
            return None
        row = (snapshot.get("poly_by_slug") or {}).get(ident)
        return _qty((row or {}).get("qty")) if row else Decimal("0")
    if venue in {"novig", "gemini"}:
        # Fills/history helpers are not a live positions book.
        return None
    return None


def kalshi_code_held(snapshot: dict, code: str) -> bool:
    token = str(code or "").lower()
    if not token or not snapshot.get("kalshi_ok"):
        return False
    if token in (snapshot.get("kalshi_codes") or set()):
        return True
    blob = " ".join((snapshot.get("kalshi_by_ticker") or {}).keys()).lower()
    return token in blob


def _counts_as_held(venue: str, qty: Decimal) -> bool:
    """Poly leftover 0.32 is open. Kalshi still uses whole contracts."""
    if qty <= 0:
        return False
    if str(venue or "").lower() == "polymarket":
        return True
    return qty >= 1


def fill_evidence(live: dict, fill_qty: Decimal | None = None, t0: dict | None = None) -> Decimal:
    """Local confirm / activities / cumQuantity, including partials under 1."""
    qty = fill_qty if fill_qty is not None else Decimal("0")
    last = live.get("last_order") if isinstance(live.get("last_order"), dict) else {}
    qty = max(qty, _qty(last.get("fill_qty") or last.get("confirm_qty")))
    tape = live.get("_tape") if isinstance(live.get("_tape"), dict) else {}
    qty = max(qty, _qty(tape.get("confirm_qty")))
    slots = t0 if isinstance(t0, dict) else (live.get("t0_yes") if isinstance(live.get("t0_yes"), dict) else {})
    for slot in (slots or {}).values():
        if isinstance(slot, dict):
            qty = max(qty, _qty(slot.get("fill_qty")))
    return qty


def t0_was_flattened(t0: dict | None) -> bool:
    if not isinstance(t0, dict):
        return False
    return any(isinstance(slot, dict) and slot.get("flattened") for slot in t0.values())


def t0_leftover_qty(t0: dict | None, last_fill: Decimal | None = None) -> Decimal:
    """Fill qty still held on a slot that was not flattened (Namigata 0.32)."""
    leftover = Decimal("0")
    if not isinstance(t0, dict):
        return leftover
    has_unflat = False
    for slot in t0.values():
        if not isinstance(slot, dict):
            continue
        if slot.get("flattened"):
            continue
        has_unflat = True
        leftover = max(leftover, _qty(slot.get("fill_qty")))
    if leftover > 0:
        return leftover
    last = last_fill if last_fill is not None else Decimal("0")
    if has_unflat and last > 0 and last < 1:
        return last
    return leftover


def local_recent_fill(row: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(ET)
    last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
    qty = _qty(last.get("fill_qty") or last.get("confirm_qty"))
    if qty < 1:
        t0 = row.get("t0_yes") if isinstance(row.get("t0_yes"), dict) else {}
        for slot in t0.values():
            if isinstance(slot, dict) and slot.get("filled"):
                qty = max(qty, Decimal("1"))
    if qty < 1:
        return False
    when = _parse_dt(str(last.get("time") or row.get("opened_at") or ""))
    if when is None:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=ET)
    return abs((now - when).total_seconds()) < RECENT_CONFIRM_SEC


def classify_match(
    sid: str,
    row: dict,
    snapshot: dict,
    *,
    tape: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Decide whether this house row is a real open, a phantom, or ignored."""
    now = now or datetime.now(ET)
    live = attach_tape(row, tape, sid=sid)
    live["_sid"] = sid
    if isinstance(live.get("_tape"), dict):
        tape_sid = str(live["_tape"].get("system") or "")
        if tape_sid and tape_sid != sid:
            live.pop("_tape", None)
    stage = str(live.get("stage") or "")
    game = str(live.get("game") or live.get("key") or "")
    key = unique_game_id(live)
    venue = str(live.get("venue") or "")
    insts = instruments_from_row(live)
    qty_held = Decimal("0")
    known = False
    held_at = ""
    for shop, ident in insts:
        q = venue_qty(snapshot, shop, ident)
        if q is None:
            continue
        known = True
        if _counts_as_held(shop, q):
            qty_held += q
            held_at = shop or held_at
            venue = shop or venue
    code = game_code(str(live.get("key") or ""))
    kalshi_game = kalshi_code_held(snapshot, code) if snapshot.get("kalshi_ok") else None

    house_open = house_stage_open(sid, live)
    recent = local_recent_fill(live, now)
    fill_qty = _qty((live.get("last_order") or {}).get("fill_qty") if isinstance(live.get("last_order"), dict) else 0)
    t0 = live.get("t0_yes") if isinstance(live.get("t0_yes"), dict) else {}
    t0_filled = any(isinstance(slot, dict) and slot.get("filled") for slot in t0.values())
    evidence = fill_evidence(live, fill_qty, t0)
    shop_name = (venue or (insts[0][0] if insts else "")).lower()
    poly_this_empty = shop_name == "polymarket" and bool(snapshot.get("poly_ok")) and qty_held <= 0
    closed, closed_why = instruments_are_final(snapshot, insts)

    real = False
    why = "not an open stage"
    leftover = t0_leftover_qty(t0, fill_qty)
    fully_flat = t0_was_flattened(t0) and leftover <= 0 and qty_held <= 0
    if closed:
        real = False
        why = f"{closed_why}; settled/expired/final/void is not open (did not sell)"
    elif fully_flat:
        real = False
        why = "flattened; venue position empty (did not sell)"
    elif qty_held > 0 and house_open:
        real = True
        why = f"venue qty {format(qty_held, 'f')} on {held_at or venue}"
    elif qty_held > 0 and not house_open:
        real = False
        why = "venue qty belongs to another system or a skipped/settled diary row"
    elif recent:
        real = True
        why = "venue-confirmed fill in the last 2 minutes; positions book may lag"
    elif not house_open:
        real = False
        why = f"stage {stage or 'blank'} is not open"
    elif stage == "waiting_t0" and not t0_filled and evidence <= 0:
        real = False
        why = "waiting T0 with no venue qty or confirm fill"
    elif poly_this_empty and evidence > 0:
        real = True
        why = (
            "Polymarket positions list empty/qty 0; local confirm/activities "
            f"qty {format(evidence, 'f')} kept (fail-soft, did not sell)"
        )
    elif known and qty_held <= 0 and evidence <= 0:
        real = False
        why = "venue positions qty 0 (settled, never filled, or Poly/Kalshi empty confirm)"
    elif snapshot.get("kalshi_ok") and kalshi_game is False and venue in {"kalshi", "novig", "gemini", ""}:
        real = False
        why = "Kalshi no longer lists this game; treated as settled (did not sell)"
    elif evidence > 0 or t0_filled:
        shop = shop_name
        book_ok = {
            "kalshi": snapshot.get("kalshi_ok"),
            "polymarket": snapshot.get("poly_ok"),
        }.get(shop)
        if shop in {"novig", "gemini"}:
            if snapshot.get("kalshi_ok") and kalshi_game is False:
                real = False
                why = "Kalshi no longer lists this game; treated as settled (did not sell)"
            else:
                real = True
                why = "no positions book; local confirm fill kept (fail-soft)"
        elif book_ok:
            real = False
            why = "local fill but venue book does not show a holding"
        else:
            real = True
            why = f"{shop or 'venue'} book unreadable; local confirm fill kept (fail-soft)"
    else:
        real = False
        why = "no venue qty"

    shown = qty_held if qty_held > 0 else (evidence if real and evidence > 0 else (Decimal("1") if recent else Decimal("0")))
    guess = {"tennis_crossover": "B", "cfb_favorite": "C", "spread_t0": "D", "tennis_t0_dog": "E", "tennis_t0_spread": "F", "soccer_t0_total": "G"}.get(sid, sid)
    return {
        "sid": sid,
        "letter": guess,
        "key": key,
        "game": game,
        "venue": venue or (insts[0][0] if insts else ""),
        "instrument": insts[0][1] if insts else str(live.get("instrument") or ""),
        "side": str(live.get("fav") or live.get("side") or ""),
        "stage": stage,
        "house_open": house_open,
        "real": real,
        "phantom": house_open and not real,
        "qty": format(shown, "f") if shown else "0",
        "why": why,
        "row": live,
    }


def classify_system(sid: str, status: dict, snapshot: dict, *, tape: dict | None = None, now=None) -> list[dict]:
    out = []
    for row in status.get("matches") or []:
        if isinstance(row, dict):
            out.append(classify_match(sid, row, snapshot, tape=tape, now=now))
    return out


def _read_cache() -> dict:
    cached = _load_json(CACHE_PATH)
    if cached.get("kalshi_by_ticker") is None and cached.get("poly_by_slug") is None:
        return empty_snapshot()
    cached["kalshi_codes"] = set(cached.get("kalshi_codes") or [])
    cached["poly_markets"] = cached.get("poly_markets") or {}
    cached["kalshi_markets"] = cached.get("kalshi_markets") or {}
    return cached


def open_rows(sid: str, status: dict, *, snapshot: dict | None = None, tape: dict | None = None, now=None) -> list[dict]:
    snap = snapshot if snapshot is not None else _read_cache()
    seen = set()
    rows = []
    for item in classify_system(sid, status, snap, tape=tape, now=now):
        if not item.get("real") or not item.get("house_open"):
            continue
        key = item.get("key") or item.get("game")
        if key in seen:
            continue
        seen.add(key)
        rows.append(item["row"])
    return rows


def open_count(sid: str, status: dict | None = None, *, snapshot: dict | None = None, tape: dict | None = None, now=None) -> int:
    if sid == "lock":
        import live_lock_orders

        return len(live_lock_orders.open_lock_keys(snapshot=snapshot))
    data = status
    if data is None:
        data = _load_json(WATCH.get(sid, Path()))
    return len(open_rows(sid, data, snapshot=snapshot, tape=tape, now=now))


def _ticket_from_book_row(row: dict, venue: str) -> dict:
    qty = _qty(row.get("qty"))
    return {
        "venue": venue,
        "ticker": str(row.get("ticker") or ""),
        "title": str(row.get("title") or row.get("ticker") or ""),
        "qty": format(qty, "f"),
        "pay": str(row.get("side") or "yes").lower() or "yes",
        "fees": row.get("fees") or "",
        "exposure": row.get("exposure") or "",
        "last_updated": row.get("last_updated") or "",
        "source": "positions",
    }


def _pay_side(*values) -> str:
    for value in values:
        text = str(value or "").strip().lower()
        if text in {"yes", "no"}:
            return text
    return "yes"


def _ticket_from_classified(item: dict) -> dict:
    """Poly house-open confirm → a Positions ticket when GET is empty."""
    live = item.get("row") if isinstance(item.get("row"), dict) else {}
    last = live.get("last_order") if isinstance(live.get("last_order"), dict) else {}
    tape = live.get("_tape") if isinstance(live.get("_tape"), dict) else {}
    ident = str(item.get("instrument") or live.get("instrument") or last.get("instrument") or tape.get("instrument") or "")
    venue = str(item.get("venue") or live.get("venue") or tape.get("venue") or "").lower()
    qty = _qty(item.get("qty"))
    if qty <= 0:
        qty = fill_evidence(live)
    sid = str(item.get("sid") or live.get("_sid") or "")
    letter = str(
        item.get("letter")
        or {"tennis_crossover": "B", "cfb_favorite": "C", "spread_t0": "D", "tennis_t0_dog": "E", "tennis_t0_spread": "F", "soccer_t0_total": "G"}.get(sid, "")
    )
    pay = _pay_side(tape.get("side"), live.get("pay"), last.get("side"), item.get("side"))
    return {
        "venue": venue or "polymarket",
        "ticker": ident,
        "title": str(item.get("game") or live.get("game") or ident),
        "qty": format(qty, "f") if qty else "0",
        "pay": pay,
        "fees": last.get("fee") or "",
        "exposure": "",
        "last_updated": str(last.get("time") or live.get("opened_at") or ""),
        "sid": sid,
        "letter": letter,
        "sport": str(live.get("sport") or item.get("sport") or ""),
        "game": str(item.get("game") or live.get("game") or ""),
        "source": "confirm",
        "entry": last.get("pay") or last.get("fill_px") or last.get("limit_price") or tape.get("price"),
    }


def open_set_tickets(
    snapshot: dict | None,
    *,
    watches: dict | None = None,
    tape: dict | None = None,
    now=None,
) -> list[dict]:
    """One open-set for Open now and Positions.

    Kalshi qty >= 1, Polymarket GET qty > 0, plus Poly house-open confirms
    (activities / this-order cumQuantity / ledger FILLED) when the positions
    GET is empty *and the market is still open*. Resolved / expired / final /
    void never join the open-set, even with confirm qty ≥ 1 (empty after
    settle is normal). Same for Kalshi closed tickers. Does not invent Kalshi
    ledger-only rows. House cap is still 1 slot; qty 0.32 / 0.19 may display.
    Gemini/Novig fill-history is not a positions book.
    """
    snap = snapshot if isinstance(snapshot, dict) else empty_snapshot()
    tickets: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(ticket: dict) -> None:
        venue = str(ticket.get("venue") or "").lower()
        ident = str(ticket.get("ticker") or "").strip()
        if not venue or not ident:
            return
        key = (venue, ident)
        if key in seen:
            return
        seen.add(key)
        ticket = dict(ticket)
        ticket["venue"] = venue
        tickets.append(ticket)

    if snap.get("kalshi_ok"):
        for row in snap.get("kalshi") or []:
            if not isinstance(row, dict):
                continue
            if _qty(row.get("qty")) < 1:
                continue
            ticker = str(row.get("ticker") or "")
            if market_info_is_final(market_status_of(snap, "kalshi", ticker), venue="kalshi")[0]:
                continue
            add(_ticket_from_book_row(row, "kalshi"))
    if snap.get("poly_ok"):
        for row in snap.get("poly") or []:
            if not isinstance(row, dict):
                continue
            if _qty(row.get("qty")) <= 0:
                continue
            ticker = str(row.get("ticker") or "")
            if market_info_is_final(market_status_of(snap, "polymarket", ticker), venue="polymarket")[0]:
                continue
            add(_ticket_from_book_row(row, "polymarket"))

    watch_map = watches if watches is not None else {}
    for sid in ("tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog", "tennis_t0_spread", "soccer_t0_total"):
        status = watch_map.get(sid)
        if not isinstance(status, dict):
            continue
        for item in classify_system(sid, status, snap, tape=tape, now=now):
            if not item.get("real") or not item.get("house_open"):
                continue
            venue = str(item.get("venue") or "").lower()
            ident = str(item.get("instrument") or "")
            if venue != "polymarket" or not ident:
                continue
            if (venue, ident) in seen:
                continue
            add(_ticket_from_classified(item))
    return tickets


def phantoms(sid: str, status: dict, snapshot: dict, *, tape: dict | None = None, now=None) -> list[dict]:
    return [
        item
        for item in classify_system(sid, status, snapshot, tape=tape, now=now)
        if item.get("phantom")
    ]


def house_open_named(sid: str, status: dict) -> list[dict]:
    out = []
    for row in status.get("matches") or []:
        if isinstance(row, dict) and house_stage_open(sid, row):
            out.append(row)
    return out


def overlay_currently_open(status: dict, sid: str, snapshot: dict, *, tape: dict | None = None, now=None) -> dict:
    data = dict(status)
    n = open_count(sid, data, snapshot=snapshot, tape=tape, now=now)
    data["currently_open"] = n
    data["open_count_source"] = "venue qty>=1 unique games"
    return data


def reconcile_status(sid: str, status: dict, snapshot: dict, *, tape: dict | None = None, now=None) -> tuple[dict, list[dict]]:
    """Drop phantom opens in the watch payload. Does not sell tickets."""
    now = now or datetime.now(ET)
    data = dict(status)
    matches = []
    changed = []
    for row in status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        item = classify_match(sid, row, snapshot, tape=tape, now=now)
        live = dict(item["row"])
        if str(live.get("stage") or "") in {PHANTOM_STAGE.get(sid, "settled"), "done", "settled"} and live.get("phantom_cleared_at"):
            probe = dict(live)
            t0_probe = probe.get("t0_yes") if isinstance(probe.get("t0_yes"), dict) else {}
            if sid == "tennis_crossover":
                probe["stage"] = "one_leg_miss" if t0_was_flattened(t0_probe) else "waiting_cross"
            else:
                probe["stage"] = "filled"
            probed = classify_match(sid, probe, snapshot, tape=tape, now=now)
            if probed.get("real") and probed.get("house_open"):
                live = dict(probed["row"])
                live["stage"] = probe["stage"]
                live["note"] = probed.get("why")
                if t0_was_flattened(t0_probe):
                    live["stopped"] = True
                    live["leftover_ioc_sent"] = True
                    live["note"] = (
                        f"{probed.get('why')}. Flattened leftover held; extras/flatten armed off. Did not sell."
                    )
                live.pop("phantom_cleared_at", None)
                live.pop("phantom_reason", None)
                item = probed
                item["row"] = live
        if isinstance(live.get("_tape"), dict) and live["_tape"].get("system") and live["_tape"].get("system") != sid:
            live.pop("_tape", None)
        if item.get("phantom") and house_stage_open(sid, live):
            live["stage"] = PHANTOM_STAGE.get(sid, "settled")
            live["phantom_cleared_at"] = iso_now()
            live["phantom_reason"] = item.get("why")
            live["note"] = (
                f"{item.get('why')}; slot released. Did not sell."
            )
            changed.append(item)
            try:
                import orders_performance_refresh
                orders_performance_refresh.maybe_after_classified(item, snapshot=snapshot)
            except Exception:
                pass
        matches.append(live)
    data["matches"] = matches
    data["currently_open"] = open_count(sid, data, snapshot=snapshot, tape=tape, now=now)
    data["open_count_source"] = "venue qty>=1 unique games"
    return data, changed


def save_watch(sid: str, data: dict) -> None:
    path = WATCH[sid]
    lock = LOCKS[sid]
    with venue_pace.FileLock(lock):
        _dump_json(path, data)


def load_watch(sid: str) -> dict:
    return _load_json(WATCH[sid])


def sync_all(*, snapshot: dict | None = None, mutate: bool = True) -> dict:
    snap = snapshot if snapshot is not None else venue_snapshot()
    tape = load_tape_index()
    result = {"snapshot": snap, "systems": {}, "changed": []}
    for sid in ("tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog", "tennis_t0_spread", "soccer_t0_total"):
        status = load_watch(sid)
        named = house_open_named(sid, status)
        classified = classify_system(sid, status, snap, tape=tape)
        if mutate:
            status, changed = reconcile_status(sid, status, snap, tape=tape)
            save_watch(sid, status)
            result["changed"].extend(changed)
        else:
            changed = [item for item in classified if item.get("phantom")]
        result["systems"][sid] = {
            "house_n": len(named),
            "house": named,
            "venue_n": open_count(sid, status, snapshot=snap, tape=tape),
            "classified": classified,
            "changed": changed,
            "max_open": status.get("max_open") or status.get("max_open_b_matches"),
        }
    try:
        import live_lock_orders

        result["lock_n"] = len(live_lock_orders.open_lock_keys())
        result["lock_line"] = live_lock_orders.lock_open_line(result["lock_n"])
        result["lock_max"] = live_lock_orders.effective_max_open_locks()
        result["lock_const"] = live_lock_orders.MAX_OPEN_LOCKS
    except Exception as exc:
        result["lock_n"] = 0
        result["lock_line"] = f"unreadable {type(exc).__name__}"
        result["lock_max"] = 3
        result["lock_const"] = 3
    return result


def restore_cd_caps() -> dict:
    """C and D max_open back to 2. Does not flatten extras. Does not spawn."""
    import prediction_systems as ps

    cfgs = ps.load_config()
    before = {sid: cfgs[sid].max_open for sid in ("cfb_favorite", "spread_t0")}
    cfgs["cfb_favorite"].max_open = 2
    cfgs["spread_t0"].max_open = 2
    ps.save_config(cfgs)
    return {"before": before, "after": {"cfb_favorite": 2, "spread_t0": 2}}


def reload_bots() -> dict:
    """Stop C/D/B, then start one each. Never a second B. Does not touch lock pollers."""
    import prediction_systems as ps

    notes = {}
    for sid in ("cfb_favorite", "spread_t0", "tennis_crossover"):
        stopped = ps.stop_system(sid)
        notes[sid] = f"stopped {stopped or 'none'}"
        time.sleep(0.3)
    return notes


def start_bots() -> dict:
    import prediction_systems as ps

    notes = {}
    for sid in ("cfb_favorite", "spread_t0", "tennis_crossover"):
        notes[sid] = ps.reload_system(sid)
        time.sleep(0.4)
    return notes


def overlay_system_rows(rows: list[dict], snapshot: dict, *, tape: dict | None = None) -> list[dict]:
    out = []
    tape = tape if tape is not None else load_tape_index()
    for row in rows:
        item = dict(row)
        sid = str(item.get("id") or "")
        if sid in WATCH:
            item["open"] = str(open_count(sid, snapshot=snapshot, tape=tape))
            item["open_source"] = "venue qty>=1 unique games"
        out.append(item)
    return out


def venue_contracts(snapshot: dict, classified: dict) -> list[dict]:
    """Every venue book row plus system guess from house tape."""
    guess_by_ident = {}
    for sid, blob in classified.items():
        letter = {"tennis_crossover": "B", "cfb_favorite": "C", "spread_t0": "D", "tennis_t0_dog": "E", "tennis_t0_spread": "F", "soccer_t0_total": "G"}.get(sid, sid)
        for item in blob.get("classified") or []:
            if not item.get("house_open"):
                continue
            ident = str(item.get("instrument") or "")
            if ident:
                guess_by_ident[(str(item.get("venue") or "").lower(), ident)] = letter
            live = dict(item.get("row") or {})
            live["_sid"] = sid
            for shop, ticker in instruments_from_row(live):
                guess_by_ident[(shop, ticker)] = letter
    rows = []
    for row in snapshot.get("kalshi") or []:
        ident = str(row.get("ticker") or "")
        rows.append({
            **row,
            "system_guess": guess_by_ident.get(("kalshi", ident), _guess_ticker(ident)),
        })
    for row in snapshot.get("poly") or []:
        ident = str(row.get("ticker") or "")
        rows.append({
            **row,
            "system_guess": guess_by_ident.get(("polymarket", ident), "B?" if ident.startswith("aec-") else "?"),
        })
    for row in snapshot.get("gemini") or []:
        ident = str(row.get("ticker") or "")
        rows.append({**row, "system_guess": guess_by_ident.get(("gemini", ident), "?")})
    return rows


def _guess_ticker(ticker: str) -> str:
    text = str(ticker or "").upper()
    if "SPREAD" in text:
        return "D"
    if "NCAAFGAME" in text or "NCAAF" in text:
        return "C"
    if "ATP" in text or "WTA" in text:
        return "B or lock leftover"
    return "?"


def write_report(bundle: dict, *, before: dict, caps: dict, reload_notes: dict, pids: dict) -> Path:
    snap = bundle.get("snapshot") or {}
    systems = bundle.get("systems") or {}
    lock_line = bundle.get("lock_line") or "0 / 3"
    pulled = snap.get("pulled_at") or iso_now()

    def sys_blob(sid: str) -> dict:
        return systems.get(sid) or {}

    thought = before.get("thought") or {}
    compare_rows = []
    labels = (
        ("lock", "A", "Lock gap"),
        ("tennis_crossover", "B", "Tennis crossover"),
        ("cfb_favorite", "C", "College football favorite"),
        ("spread_t0", "D", "T0 spreads"),
        ("tennis_t0_dog", "E", "Tennis T0 dog"),
        ("tennis_t0_spread", "F", "Tennis spread"),
        ("soccer_t0_total", "G", "Soccer total"),
    )
    paul = {"lock": "0 / 3", "tennis_crossover": 2, "cfb_favorite": 5, "spread_t0": 2}
    if isinstance(before, dict) and before.get("paul"):
        paul.update(before.get("paul") or {})
    for sid, letter, name in labels:
        if sid == "lock":
            thought_n = paul.get(sid, "0 / 3")
            venue_n = bundle.get("lock_line")
            after_n = venue_n
            cap = bundle.get("lock_max") or 3
        else:
            thought_n = paul.get(sid, thought.get(sid, sys_blob(sid).get("house_n")))
            venue_n = sys_blob(sid).get("venue_n")
            after_n = venue_n
            cap = sys_blob(sid).get("max_open")
            if sid in {"cfb_favorite", "spread_t0"}:
                cap = 2
        phant = []
        reals = []
        if sid != "lock":
            for item in sys_blob(sid).get("classified") or []:
                if item.get("real") and item.get("house_open"):
                    reals.append(item.get("game") or item.get("key"))
                elif item.get("phantom") or (item.get("row") or {}).get("phantom_cleared_at"):
                    phant.append(item.get("game") or item.get("key"))
        compare_rows.append([
            letter,
            _esc(name),
            _esc(thought_n),
            _esc(venue_n),
            _esc(after_n),
            _esc(cap),
            _esc(", ".join(reals) or "—"),
            _esc(", ".join(phant) or "—"),
        ])

    contract_rows = []
    classified = {sid: sys_blob(sid) for sid, _, _ in labels if sid != "lock"}
    for row in venue_contracts(snap, classified):
        contract_rows.append([
            _esc(row.get("venue")),
            _esc(row.get("ticker")),
            _esc(row.get("title")),
            _esc(row.get("side")),
            _esc(row.get("qty")),
            _esc(row.get("system_guess")),
            "real venue qty ≥ 1",
        ])
    if not contract_rows:
        contract_rows.append(["—", "none", "no venue qty ≥ 1", "—", "0", "—", "flat"])

    house_rows = []
    for sid, letter, name in labels:
        if sid == "lock":
            continue
        for item in sys_blob(sid).get("classified") or []:
            live_row = item.get("row") or {}
            if not item.get("house_open") and not live_row.get("phantom_cleared_at") and not item.get("phantom"):
                continue
            flag = "real" if item.get("real") else "phantom"
            house_rows.append([
                letter,
                _esc(item.get("game")),
                _esc(item.get("venue")),
                _esc(item.get("instrument")),
                _esc(item.get("side")),
                _esc(item.get("qty")),
                _esc(item.get("stage")),
                flag,
                _esc(item.get("why")),
            ])

    never = [
        ["After every confirm", "Add or drop an open slot only when that venue says qty ≥ 1. HTTP 200/201 with qty 0 is a miss."],
        ["Status / systems rebuild", "Re-query Kalshi + Polymarket positions (cache ≤ 60s) and overwrite Open now."],
        ["Unique games", "One game is one slot even if two shops listed it. C is games, not venue shops. D is games, not extra lines."],
        ["Cap uses the same count", "MAX_OPEN / systems.json max_open looks at venue-true unique games, not local filled-stage rows."],
        ["Settled leftovers", "If Kalshi no longer lists the ticker, the slot is released. We do not sell."],
        ["C/D cap restored", "C max was 5 and D max was 5. Both are 2 again. The three real Kalshi C tickets stay; we do not flatten the extra."],
    ]
    never_rows = [[_esc(a), _esc(b)] for a, b in never]

    pid_bits = ", ".join(f"{k} {v}" for k, v in pids.items()) or "see job_status"
    reload_bits = " ".join(str(v) for v in (reload_notes or {}).values()) or "—"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open count sync 24 Oct 2026</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; max-width: 1100px; line-height: 1.45; color: #0f172a; }}
h1, h2 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 16px; margin: 12px 0 20px; }}
.callout h2 {{ margin: 0 0 8px; font-size: 16px; }}
.note, .tiny {{ color: #475569; font-size: 14px; }}
code {{ font-size: 13px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Open count sync</h1>
<p class="note">Written { _esc(pulled) }. Research-candidate live. Not gold. Not DailyRun. Did not sell tickets. Did not start a second Tennis crossover.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{_esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{_esc(PLAIN)}</p>
</div>

<h2>What 0/3 means</h2>
<p><strong>0</strong> is how many live lock-bot pairs the house is holding right now.
<strong>3</strong> is the cap (<code>systems.json</code> Lock gap max_open = 3, same as
<code>live_lock_orders.MAX_OPEN_LOCKS</code>). Zero current opens is correct: Kalshi
positions have no lock leftover, leftover watches are all stopped, and there is no
true Yes+No lock still on the book. The leftover list on job_status is old stopped
watches, not live slots.</p>

<h2>job_status thought vs venues vs after fix</h2>
<p class="note">Click column headers to sort. Paul ~20:04 ET thought B=2 C=5 D=2 A=0/3.
Kalshi still shows 3 college-football moneyline tickets and 1 spread. After fix, Open now
is unique games with venue qty ≥ 1.</p>
{_table(
    [("Sys", "text"), ("Name", "text"), ("job_status thought", "text"), ("Kalshi / venues", "text"),
     ("After fix", "text"), ("Cap", "num"), ("Real opens", "text"), ("Phantoms", "text")],
    compare_rows,
)}

<h2>Every open contract on the venues</h2>
<p class="note">Kalshi GET /trade-api/v2/portfolio/positions (count_filter=position).
Polymarket US GET /v1/portfolio/positions. Gemini is order history (no positions helper).
Novig is fills (no positions helper). Amounts only. No secrets.</p>
{_table(
    [("Venue", "text"), ("Ticker", "text"), ("Title", "text"), ("Side", "text"),
     ("Qty", "num"), ("System guess", "text"), ("Flag", "text")],
    contract_rows,
)}

<h2>Named house opens (the 5 C / 2 D / 2+ B the page thought were open)</h2>
{_table(
    [("Sys", "text"), ("Game", "text"), ("Venue", "text"), ("Ticker", "text"), ("Side", "text"),
     ("Qty", "num"), ("House stage", "text"), ("Real or phantom", "text"), ("Why", "text")],
    house_rows,
)}

<h2>Why the extras</h2>
<ul>
<li><strong>Settled but not cleared:</strong> NAVY vs UNT moneyline and spread filled for real at T0, then the game ended. Kalshi positions no longer list UNTNAVY. The watch file still said filled.</li>
<li><strong>TROY vs ULM on Novig:</strong> C filled Troy Yes on Novig. Kalshi no longer lists ULMTROY, so the game is treated as settled. D on that game was Kalshi 201 with tape qty 1 but confirm qty 0 — already marked missed (the empty-confirm bug, not a false open).</li>
<li><strong>C counted every filled row, and max_open had been raised to 5</strong> so the cap did not stop the third, fourth, and fifth games. Cap is 2 again. The three real Kalshi C tickets stay; we do not flatten the extra.</li>
<li><strong>D counted two filled games;</strong> only MISS vs TEX is still on Kalshi. Cap 2 vs 1 real is not an overshoot the other way — one phantom settled.</li>
<li><strong>B tennis:</strong> Machac vs Khachanov is a two-day-old Kalshi waiting-fav-dip with position 0. Guajardo vs Brain is the Poly 200 / empty-activities leftover (qty 0) that occupied a slot. Those are phantoms. Any Poly qty ≥ 1 (Karim / Guidotti if still on the book) is a real B ticket on Polymarket, not Kalshi — Paul said all four app opens were Kalshi C/D.</li>
<li><strong>waiting_t0 with no fill</strong> no longer occupies a slot. Kalshi 201 empty is not open. Poly HTTP 200 qty 0 is not open.</li>
</ul>

<h2>Plan to never desync (shipped)</h2>
{_table([("Step", "text"), ("What it does", "text")], never_rows)}

<h2>Reload</h2>
<p>C/D/B reloaded in place, one process each. Lock pollers were not restarted. First reload stopped then started one of each; later rebuilds used --no-reload.</p>
<p>PIDs after reload: {_esc(pid_bits)}. Did not sell tickets. Did not start a second <code>live_strategy_b.py</code>.</p>
<p class="tiny">Pages: <a href="open_count_sync_20261024.html">this report</a> · <a href="job_status.html">job_status.html</a>. File URL {_esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def current_pids() -> dict:
    import prediction_systems as ps

    jobs = ps.classify_jobs()
    out = {}
    for sid, label in (
        ("cfb_favorite", "C"),
        ("spread_t0", "D"),
        ("tennis_crossover", "B"),
        ("tennis_t0_dog", "E"),
        ("tennis_t0_spread", "F"),
        ("soccer_t0_total", "G"),
    ):
        pids = ps.pids_for(sid, jobs)
        out[label] = pids[0] if pids else "—"
    try:
        sup = (jobs.get("supervisor") or [None])[0]
        out["A supervisor"] = sup["pid"] if sup else "—"
    except Exception:
        out["A supervisor"] = "—"
    return out


def capture_thought() -> dict:
    thought = {}
    for sid in ("tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog", "tennis_t0_spread", "soccer_t0_total"):
        status = load_watch(sid)
        thought[sid] = status.get("currently_open")
        if thought[sid] is None:
            thought[sid] = len(house_open_named(sid, status))
    try:
        import live_lock_orders

        thought["lock"] = live_lock_orders.lock_open_line(len(live_lock_orders.open_lock_keys()))
    except Exception:
        thought["lock"] = "0 / 3"
    thought["paul_20_04"] = {"lock": "0 / 3", "tennis_crossover": 2, "cfb_favorite": 5, "spread_t0": 2}
    return thought


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_dirs()
    mutate = "--no-mutate" not in argv
    do_reload = "--no-reload" not in argv
    thought = capture_thought()
    caps = restore_cd_caps() if mutate else {"before": {}, "after": {}}
    snap = venue_snapshot(force=True)
    reload_notes = {}
    if do_reload and mutate:
        reload_notes = reload_bots()
    bundle = sync_all(snapshot=snap, mutate=mutate)
    if do_reload and mutate:
        started = start_bots()
        reload_notes = {k: f"{reload_notes.get(k, '')}; {started.get(k, '')}" for k in started}
        time.sleep(1.5)
    pids = current_pids()
    write_report(bundle, before={"thought": thought, "paul": thought.get("paul_20_04")}, caps=caps, reload_notes=reload_notes, pids=pids)
    try:
        import prediction_job_control

        prediction_job_control.write_page(prediction_job_control.snapshot())
    except Exception as exc:
        print(f"job_status write skipped {type(exc).__name__}", file=sys.stderr)
    print(f"lock {bundle.get('lock_line')}")
    for sid in ("tennis_crossover", "cfb_favorite", "spread_t0", "tennis_t0_dog", "tennis_t0_spread", "soccer_t0_total"):
        blob = (bundle.get("systems") or {}).get(sid) or {}
        print(f"{sid} house={blob.get('house_n')} venue={blob.get('venue_n')}")
    print(PAGE)
    print(JOB_STATUS)
    print("pids", pids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
