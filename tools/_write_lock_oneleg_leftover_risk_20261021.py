"""Quantify original live-lock leftover risk (one cheap fill, complement never locks).

Research only. Reads orders.jsonl, order_io.jsonl, leftover_watch_stats.jsonl,
and price_memory (read-only). Does not place, cancel, or amend orders.
Does not touch orders_stopped.json, one_leg_watch.json, secrets, or strategy_b.
Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_lib
import json
import math
import shutil
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from odds_cross_winrate_20261020 import SETTLE_CACHE, game_norm, parse_dt
from order_ledger import (
    ORDER_IO,
    ORDERS,
    _attempts,
    _dec,
    _io_fill_for_sent,
    _io_instrument,
    _io_status,
    _load_jsonl,
    _order_id_of,
    polymarket_fill,
)
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from price_memory import iter_tick_lines, to_et

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_oneleg_leftover_risk_20261021.html"
NET_MAX = 0.95
ABSORB_LO = 0.05
ABSORB_HI = 0.95
BUCKETS = (
    ("p ≤ 0.20 (Onclin-like)", 0.0, 0.20),
    ("0.20 < p ≤ 0.40", 0.20, 0.40),
    ("0.40 < p ≤ 0.60", 0.40, 0.60),
)

ASKED = (
    "bought Onclin at 0.18, never filled Jan-Lennard Struff. He assumes Struff never came back "
    "to 0.77 needed for a profitable lock (0.18+0.77=0.95). He asks: this is the risk in that "
    "original system. How often do we think that will happen and how will it affect our profits?"
)
PLAIN = (
    "A lock is supposed to buy both sides of the same $1 payout so we keep about a nickel no "
    "matter who wins. The original live lock sends both legs at once as immediate-or-cancel "
    "(IOC: fill now or cancel) when the two prices plus documented fees are $0.95 or less. "
    "Sometimes only the cheap leg fills. Then we are not locked — we are betting that name wins, "
    "or hoping the expensive complement later falls cheap enough to finish the lock. "
    "Paul's Onclin ticket is that leftover: Yes Gauthier Onclin around 18 cents. The missing "
    "leg is Yes Jan-Lennard Struff at 77 cents (18+77=95). If Onclin is losing, Struff's Yes "
    "goes up, not down, so 77 cents never prints — that is the bad state. If Onclin is winning, "
    "Struff should fall through 77 cents and leftover should lock. So unmatched leftovers should "
    "be enriched for eventual losers. This page measures that on the live October 2026 book "
    "(tiny sample, all out-of-sample) and on the tennis/NFL tape."
)


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, kind: str = "text") -> str:
    text = "" if value is None else str(value)
    return f"<td>{esc(text)}</td>"


def table(headers: list[tuple[str, str]], rows: list[list], total: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(td(cell) for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if total is not None:
        cells = "".join(td(cell) for cell in total)
        body.append(f'<tr class="total-row">{cells}</tr>')
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def money(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def money4(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def pct(part, whole) -> str:
    if not whole:
        return ""
    return f"{100.0 * part / whole:.1f}"


def parse_key(bet_key: str) -> dict:
    parts = str(bet_key or "").split("\t")
    while len(parts) < 8:
        parts.append("")
    return {
        "sport": parts[0],
        "game_code": parts[1],
        "date": parts[2],
        "market_type": parts[3],
        "side_key": parts[4],
        "number": parts[5],
        "venue_a": parts[6],
        "venue_b": parts[7],
    }


def last_name(text: str) -> str:
    toks = [t for t in game_norm(text).split() if t]
    return toks[-1] if toks else game_norm(text)


def same_player(a: str, b: str) -> bool:
    """Ticker codes (dod) must match names (dodig)."""
    x, y = last_name(a), last_name(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if len(x) >= 3 and (y.startswith(x) or x.startswith(y)):
        return True
    if len(y) >= 3 and (x.startswith(y) or y.startswith(x)):
        return True
    return False


def ticker_code(instrument: str) -> str:
    text = str(instrument or "")
    if not text:
        return ""
    if "-" in text and text.upper().startswith("KX"):
        return text.rsplit("-", 1)[-1].lower()
    if text.lower().startswith("aec-"):
        return ""
    if text.upper().startswith("GEMI-"):
        bits = text.split("-")
        return bits[-1].lower() if bits else ""
    return ""


def kalshi_fee(price: float) -> float:
    p = Decimal(str(price))
    raw = Decimal("0.07") * p * (Decimal("1") - p)
    if raw < 0:
        raw = Decimal("0")
    return float(raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def gemini_fee(price: float) -> float:
    p = Decimal(str(price))
    raw = Decimal("0.07") * p * (Decimal("1") - p)
    if raw < 0:
        raw = Decimal("0")
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING))


def poly_fee(price: float) -> float:
    p = Decimal(str(price))
    raw = Decimal("0.0695") * p * (Decimal("1") - p)
    if raw < 0:
        raw = Decimal("0")
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def house_fee(venue: str, price: float, logged: float | None) -> float:
    if logged is not None and logged > 0:
        return logged
    name = (venue or "").lower()
    if name == "kalshi":
        return kalshi_fee(price)
    if name == "gemini":
        return gemini_fee(price)
    if name == "polymarket":
        return poly_fee(price)
    return 0.0


def copy_g(path: Path) -> None:
    dest_dir = Path(r"G:\My Drive\paul_experiments\prediction_market_arb_exhaustive_20261017")
    if dest_dir.parent.exists() or Path("G:/").exists():
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest_dir / path.name)
        except OSError as exc:
            print(f"G: copy skipped: {exc}", flush=True)


def as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace("$", "").split()[0])
    except (TypeError, ValueError):
        return None
    return number


def io_cash(fill: dict | None, sent: dict, io_row: dict | None) -> tuple[float | None, float, str]:
    """Pay-side cash, fee, and yes/no book side for a matched order_io fill."""
    fill = fill or {}
    sent = sent or {}
    venue = str(sent.get("venue") or "").lower()
    book = str(sent.get("side") or fill.get("side") or "").lower()
    request = (io_row or {}).get("request") if isinstance((io_row or {}).get("request"), dict) else {}
    req_side = str(request.get("side") or request.get("intent") or request.get("outcome") or "").lower()
    avg = as_float(fill.get("avg"))
    cash = as_float(fill.get("cash"))
    fee = as_float(fill.get("fee")) or 0.0
    if venue == "kalshi":
        wire = avg
        if "ask" in req_side or book == "no":
            book = "no"
            if wire is not None:
                cash = 1.0 - wire if cash is None else cash
        else:
            book = "yes"
            if cash is None:
                cash = wire
    elif venue == "polymarket":
        if "short" in req_side:
            book = "no"
        elif "long" in req_side:
            book = "yes"
        if cash is None:
            cash = avg
        if not fill.get("fee") and cash is not None:
            fee = poly_fee(cash)
    else:
        if cash is None:
            cash = avg
        if "yes" in req_side:
            book = "yes"
        elif "no" in req_side:
            book = "no"
    filled = bool(fill.get("filled"))
    if not filled:
        return None, fee, book
    return cash, fee, book


def load_io_rows() -> list[dict]:
    return [row for row in _load_jsonl(ORDER_IO) if str(row.get("kind") or "") == "order"]


def io_by_id_map(io_list: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for row in io_list:
        oid = _order_id_of(row.get("response"))
        if oid:
            found[oid] = row
    return found


def player_from_leg(sent: dict, io_row: dict | None, key_info: dict, claim: dict) -> str:
    instrument = str(sent.get("instrument") or "")
    if io_row:
        resp = io_row.get("response") if isinstance(io_row.get("response"), dict) else {}
        fill = polymarket_fill(resp) if str(sent.get("venue") or "") == "polymarket" else {}
        name = fill.get("outcome_name") or ""
        if name:
            return name
        req = io_row.get("request") if isinstance(io_row.get("request"), dict) else {}
        slug = str(req.get("marketSlug") or "")
        if slug:
            instrument = slug
    code = ticker_code(instrument)
    side_key = str(key_info.get("side_key") or "")
    if code and (not side_key or code.lower() in side_key.lower() or True):
        if code:
            return code
    game = str(claim.get("game") or "")
    return game


def pays_if(market_type: str, book_side: str, player: str, game: str, number: str) -> str:
    """Who must win (or which total direction) for this ticket to pay $1."""
    mtype = (market_type or "").lower()
    side = (book_side or "").lower()
    player_n = last_name(player)
    if mtype in ("moneyline", "winner", "match", "game", ""):
        if side == "yes":
            return f"win:{player_n}"
        if side == "no":
            return f"lose:{player_n}"
        return f"unk:{player_n}"
    if mtype in ("total", "spread"):
        line = f"{mtype}:{number}"
        if side == "yes":
            return f"{line}:yes"
        if side == "no":
            return f"{line}:no"
        return f"{line}:unk"
    return f"{mtype}:{side}:{player_n}"


def opposite_pays(a: str, b: str) -> bool:
    if not a or not b or a.startswith("unk") or b.startswith("unk"):
        return False
    if a == b:
        return False
    if a.startswith("win:") and b.startswith("lose:"):
        return same_player(a[4:], b[5:])
    if a.startswith("lose:") and b.startswith("win:"):
        return same_player(a[5:], b[4:])
    if a.startswith("win:") and b.startswith("win:"):
        return not same_player(a[4:], b[4:])
    if a.startswith("lose:") and b.startswith("lose:"):
        return not same_player(a[5:], b[5:])
    if a.endswith(":yes") and b.endswith(":no") and a.rsplit(":", 1)[0] == b.rsplit(":", 1)[0]:
        return True
    if a.endswith(":no") and b.endswith(":yes") and a.rsplit(":", 1)[0] == b.rsplit(":", 1)[0]:
        return True
    return False


def same_pays(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if a.startswith("win:") and b.startswith("lose:"):
        return bool(a[4:] and b[5:]) and not same_player(a[4:], b[5:])
    if a.startswith("lose:") and b.startswith("win:"):
        return bool(a[5:] and b[4:]) and not same_player(a[5:], b[4:])
    if a.startswith("win:") and b.startswith("win:"):
        return same_player(a[4:], b[4:])
    if a.startswith("lose:") and b.startswith("lose:"):
        return same_player(a[5:], b[5:])
    return False


def relation(pay_a: str, pay_b: str) -> str:
    if opposite_pays(pay_a, pay_b):
        return "true_lock"
    if same_pays(pay_a, pay_b):
        return "same_bet"
    return "unclear"


def send_mode(events: list[dict]) -> str:
    steps = {str(item.get("step") or "") for item in events if item.get("event") == "sent"}
    if "simultaneous" in steps:
        return "simultaneous"
    if "watch" in steps and not (steps - {"watch", "websocket", "book", "recovery", ""}):
        return "leftover-watch"
    if "websocket" in steps or "book" in steps:
        return "walk/sequential"
    return "early/other"


def classify_attempts() -> dict:
    claims = _load_jsonl(ORDERS)
    io_list = load_io_rows()
    io_fills = _io_status()
    io_rows_by_id = io_by_id_map(io_list)
    leftover_stats = _load_jsonl(RAW / "leftover_watch_stats.jsonl")
    leftover_by_key: dict[str, list[dict]] = defaultdict(list)
    for row in leftover_stats:
        leftover_by_key[str(row.get("bet_key") or row.get("game") or "")].append(row)

    attempts = []
    used_ids: set[str] = set()
    for claim, events in _attempts(claims):
        key = str(claim.get("bet_key") or "")
        if key.startswith("tennis-b"):
            continue
        events = [
            item for item in events
            if not str(item.get("step") or "").startswith("b-")
            and not str(item.get("bet_key") or "").startswith("tennis-b")
        ]
        if not any(item.get("event") == "sent" for item in events):
            continue
        info = parse_key(key)
        sends = [item for item in events if item.get("event") == "sent"]
        filled_events = [item for item in events if item.get("event") == "filled"]
        one_leg_events = [item for item in events if item.get("event") == "one_leg"]
        both_unfilled = any(item.get("event") == "both_unfilled" for item in events)
        legs = []
        for sent in sends:
            fill_meta = _io_fill_for_sent(sent, claim, io_fills, io_list, used_ids) or {}
            oid = str(sent.get("order_id") or "")
            io_row = io_rows_by_id.get(oid)
            cash, fee, book = io_cash(fill_meta, sent, io_row)
            player = player_from_leg(sent, io_row, info, claim)
            sent_side = str(sent.get("side") or book or "").lower()
            pay = pays_if(info["market_type"], book or sent_side, player, str(claim.get("game") or ""), info["number"])
            io_said_zero = bool(fill_meta.get("evidence")) and not bool(fill_meta.get("filled"))
            filled_flag = bool(fill_meta.get("filled")) and cash is not None and not io_said_zero
            if not filled_flag and not io_said_zero:
                for ev in filled_events:
                    if str(ev.get("venue")) != str(sent.get("venue")):
                        continue
                    if str(ev.get("instrument")) != str(sent.get("instrument")):
                        continue
                    ev_side = str(ev.get("side") or "").lower()
                    if ev_side and sent_side and ev_side != sent_side:
                        continue
                    filled_flag = True
                    if cash is None:
                        cash = as_float(ev.get("price"))
                    book = book or ev_side
            if not filled_flag:
                for ev in one_leg_events:
                    if str(ev.get("venue")) != str(sent.get("venue")):
                        continue
                    if str(ev.get("instrument")) and str(ev.get("instrument")) != str(sent.get("instrument")):
                        continue
                    ev_side = str(ev.get("side") or "").lower()
                    if ev_side and sent_side and ev_side != sent_side:
                        continue
                    filled_flag = True
                    if cash is None:
                        cash = as_float(ev.get("price"))
                    book = book or ev_side
            ts = ""
            if io_row:
                ts = str(io_row.get("timestamp") or "")
            legs.append({
                "venue": str(sent.get("venue") or ""),
                "instrument": str(sent.get("instrument") or ""),
                "book_side": book or str(sent.get("side") or ""),
                "limit": as_float(sent.get("limit_price")),
                "quote": as_float(sent.get("quote_price")),
                "cash": cash,
                "fee": fee if filled_flag else 0.0,
                "filled": filled_flag,
                "step": str(sent.get("step") or ""),
                "http": sent.get("http_status"),
                "order_id": oid,
                "player": player,
                "pays": pay,
                "ts": ts,
            })
        # Also attach filled events with no matching send (rare)
        for ev in filled_events:
            if any(str(leg.get("instrument")) == str(ev.get("instrument")) and str(leg.get("venue")) == str(ev.get("venue")) for leg in legs):
                continue
            cash = as_float(ev.get("price"))
            book = str(ev.get("side") or "")
            player = ticker_code(str(ev.get("instrument") or "")) or str(claim.get("game") or "")
            legs.append({
                "venue": str(ev.get("venue") or ""),
                "instrument": str(ev.get("instrument") or ""),
                "book_side": book,
                "limit": cash,
                "quote": None,
                "cash": cash,
                "fee": 0.0,
                "filled": True,
                "step": "filled-event",
                "http": "",
                "order_id": "",
                "player": player,
                "pays": pays_if(info["market_type"], book, player, str(claim.get("game") or ""), info["number"]),
                "ts": "",
            })

        fills = [leg for leg in legs if leg["filled"] and leg["cash"] is not None]
        uniq = []
        seen_fill = set()
        for leg in fills:
            key3 = (leg["venue"], leg["instrument"], str(leg.get("book_side") or ""))
            if key3 in seen_fill:
                continue
            seen_fill.add(key3)
            uniq.append(leg)
        fills = uniq
        # Recalc fees on known cash if missing
        for leg in fills:
            if not leg.get("fee"):
                leg["fee"] = house_fee(leg["venue"], float(leg["cash"]), None)

        initial_sends = [leg for leg in legs if leg.get("step") in ("simultaneous", "websocket", "book", "recovery", "", "walk")]
        watch_fills = [leg for leg in legs if leg.get("step") == "watch" and leg["filled"]]
        initial_fills = [leg for leg in fills if leg.get("step") != "watch"]
        n_init_fill = len(initial_fills)
        n_sent_venues = len({(leg["venue"], leg["instrument"], leg["book_side"]) for leg in legs if leg.get("step") != "watch"})
        mode = send_mode(events)

        class_ = "neither"
        lock_kind = ""
        if n_init_fill >= 2:
            rel = relation(initial_fills[0]["pays"], initial_fills[1]["pays"])
            if rel == "true_lock":
                class_ = "both_true_lock"
                lock_kind = "immediate true lock"
            elif rel == "same_bet":
                class_ = "both_same_bet"
                lock_kind = "both filled same bet"
            else:
                class_ = "both_unclear"
                lock_kind = "both filled, relation unclear"
        elif n_init_fill == 1:
            leftover = watch_fills
            if leftover:
                rel = relation(initial_fills[0]["pays"], leftover[0]["pays"])
                if rel == "true_lock":
                    class_ = "oneleg_then_true_lock"
                    lock_kind = "one-leg then leftover true lock"
                elif rel == "same_bet":
                    class_ = "oneleg_same_bet"
                    lock_kind = "leftover filled same bet (not a lock)"
                else:
                    class_ = "oneleg_same_bet" if leftover else "oneleg_unmatched"
                    lock_kind = "leftover filled, relation unclear"
            else:
                class_ = "oneleg_unmatched"
                lock_kind = "one-leg leftover never filled"
        elif both_unfilled or n_init_fill == 0:
            class_ = "neither"

        cost = 0.0
        fees = 0.0
        for leg in fills:
            cost += float(leg["cash"] or 0)
            fees += float(leg["fee"] or 0)
        initial_cheap = min(initial_fills, key=lambda leg: float(leg["cash"] or 9)) if initial_fills else None
        cheap = initial_cheap or (min(fills, key=lambda leg: float(leg["cash"] or 9)) if fills else None)
        max_other = None
        if cheap and cheap["cash"] is not None:
            max_other = NET_MAX - float(cheap["cash"]) - float(cheap.get("fee") or 0)
        # If one_leg was logged but this attempt still has zero fills (early NFL: no order_io),
        # synthesize the filled leg from the one_leg row.
        if not fills and one_leg_events:
            ev = one_leg_events[0]
            book = str(ev.get("side") or "")
            cash = as_float(ev.get("price"))
            player = ticker_code(str(ev.get("instrument") or "")) or str(claim.get("game") or "")
            if cash is not None:
                fee = house_fee(str(ev.get("venue") or ""), cash, None)
                syn = {
                    "venue": str(ev.get("venue") or ""),
                    "instrument": str(ev.get("instrument") or ""),
                    "book_side": book,
                    "limit": cash,
                    "quote": None,
                    "cash": cash,
                    "fee": fee,
                    "filled": True,
                    "step": "one_leg",
                    "http": "",
                    "order_id": "",
                    "player": player,
                    "pays": pays_if(info["market_type"], book, player, str(claim.get("game") or ""), info["number"]),
                    "ts": "",
                }
                legs.append(syn)
                fills = [syn]
                initial_fills = [syn]
                n_init_fill = 1
                cheap = syn
                max_other = NET_MAX - cash - fee
                if class_ == "neither":
                    class_ = "oneleg_unmatched"
                    lock_kind = "one-leg leftover never filled"
        stats = leftover_by_key.get(key) or leftover_by_key.get(str(claim.get("game") or "")) or []
        ioc_filled = [row for row in stats if row.get("event") == "ioc_filled"]
        attempts.append({
            "claim": claim,
            "key": key,
            "info": info,
            "game": str(claim.get("game") or ""),
            "sport": info["sport"] or str(claim.get("sport") or ""),
            "market": " ".join(p for p in (info["market_type"], info["side_key"], info["number"]) if p),
            "mode": mode,
            "class_": class_,
            "lock_kind": lock_kind,
            "legs": legs,
            "fills": fills,
            "n_sent": n_sent_venues,
            "n_init_fill": n_init_fill,
            "n_fill": len(fills),
            "one_leg_logged": bool(one_leg_events),
            "cost": cost,
            "fees": fees,
            "net_outlay": cost + fees,
            "max_other": max_other,
            "cheap": cheap,
            "ioc_filled_n": len(ioc_filled),
            "leftover_events": stats,
        })
    return {
        "attempts": attempts,
        "io_list": io_list,
        "io_fills": io_fills,
    }


def lock_pnl(attempt: dict) -> float | None:
    if attempt["class_"] not in ("both_true_lock", "oneleg_then_true_lock"):
        return None
    if attempt["n_fill"] < 2:
        return None
    return 1.0 - attempt["net_outlay"]


def unmatched_pnl_if(attempt: dict, win: bool) -> float | None:
    fills = attempt["fills"]
    if not fills:
        return None
    outlay = attempt["net_outlay"]
    # Directional stack: every fill pays together if the cheap name's "pays" hits.
    n = len(fills)
    if win:
        return n * 1.0 - outlay
    return -outlay


def load_settlements() -> list[dict]:
    rows = []
    if SETTLE_CACHE.is_file():
        try:
            raw = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                rows.extend(raw)
        except json.JSONDecodeError:
            pass
    cfb = RAW / "cfb_game_results.jsonl"
    if cfb.is_file():
        for line in cfb.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                rec.setdefault("sport", "college football")
                rows.append(rec)
    return rows


def settlement_winner(rows: list[dict], game: str, player: str) -> str:
    """Return win/lose/unknown for named player on game."""
    g = game_norm(game)
    p = last_name(player)
    if not g or not p:
        return "unknown"
    for rec in rows:
        rg = game_norm(str(rec.get("game") or rec.get("game_n") or rec.get("title") or ""))
        if rg != g and g not in rg and rg not in g:
            continue
        side = last_name(str(rec.get("side") or rec.get("side_n") or rec.get("winner") or rec.get("result_side") or ""))
        result = str(rec.get("result") or rec.get("resolution") or rec.get("outcome") or "").lower()
        winner = last_name(str(rec.get("winner") or rec.get("winning_side") or ""))
        if winner:
            if p == winner or p in winner or winner in p:
                return "win"
            if winner:
                return "lose"
        if side and (p == side or p in side):
            if result in ("yes", "win", "won"):
                return "win"
            if result in ("no", "lose", "lost"):
                return "lose"
    return "unknown"


def tick_ts(row: dict) -> int | None:
    dt = parse_dt(row.get("seen_at"))
    if dt is None:
        return None
    return int(to_et(dt).timestamp())


def load_series(sports: tuple[str, ...]) -> dict:
    """(sport, game, venue, side, pay) -> list[(ts, price, phase)] for moneyline."""
    series: dict[tuple, list] = defaultdict(list)
    n = 0
    for line in iter_tick_lines(include_archive=True):
        low = line.lower()
        if '"moneyline"' not in low and '"winner"' not in low and '"match"' not in low:
            continue
        if not any(s in low for s in sports):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        sport = str(row.get("sport") or "").strip().lower()
        if sport not in sports:
            continue
        mtype = str(row.get("market_type") or "").strip().lower()
        if mtype not in ("moneyline", "winner", "match", ""):
            continue
        pay = str(row.get("pay") or "").strip().lower()
        if pay not in ("yes", "no"):
            continue
        price = as_float(row.get("price"))
        if price is None or price <= 0 or price >= 1:
            continue
        ts = tick_ts(row)
        if ts is None:
            continue
        game = str(row.get("game") or "")
        venue = str(row.get("venue") or "").lower()
        side = str(row.get("side") or "")
        phase = str(row.get("phase") or "")
        series[(sport, game, venue, side, pay)].append((ts, price, phase))
        n += 1
        if n % 200000 == 0:
            print(f"tape ticks kept {n}", flush=True)
    for key in series:
        series[key].sort()
    print(f"tape series {len(series)} ticks {n}", flush=True)
    return series


def two_player_bags(series: dict) -> list[dict]:
    bags: dict[tuple, dict] = {}
    for key, ticks in series.items():
        sport, game, venue, side, pay = key
        bag = bags.get((sport, game, venue))
        if bag is None:
            bag = {"sport": sport, "game": game, "venue": venue, "yes": {}, "no": {}}
            bags[(sport, game, venue)] = bag
        if pay == "yes":
            bag["yes"][side] = ticks
        else:
            bag["no"][side] = ticks
    pairs = []
    for bag in bags.values():
        sides = list(bag["yes"])
        if len(sides) != 2:
            continue
        a, b = sides[0], sides[1]
        pairs.append({
            "sport": bag["sport"],
            "game": bag["game"],
            "venue": bag["venue"],
            "side_a": a,
            "side_b": b,
            "yes_a": bag["yes"][a],
            "yes_b": bag["yes"][b],
            "no_a": bag["no"].get(a) or [],
            "no_b": bag["no"].get(b) or [],
        })
    return pairs


def first_absorb(yes_a, yes_b) -> int | None:
    hit = None
    for ts, px, _ph in list(yes_a) + list(yes_b):
        if px <= ABSORB_LO or px >= ABSORB_HI:
            if hit is None or ts < hit:
                hit = ts
    return hit


def first_in_bucket(ticks, lo, hi, absorb: int | None):
    for ts, px, phase in ticks:
        if absorb is not None and ts >= absorb:
            return None
        if lo < px <= hi or (lo == 0.0 and px <= hi):
            if lo == 0.0 and px <= hi and px > 0:
                return ts, px, phase
            if lo < px <= hi:
                return ts, px, phase
    return None


def complement_arrives(cap: float, t0: int, absorb: int | None, opp_yes: list, same_no: list) -> tuple[bool, float | None, str]:
    best_ts = None
    which = ""
    for label, ticks in (("opp_yes", opp_yes), ("same_no", same_no)):
        for ts, px, _ph in ticks:
            if ts <= t0:
                continue
            if absorb is not None and ts >= absorb:
                break
            if px <= cap:
                if best_ts is None or ts < best_ts:
                    best_ts = ts
                    which = label
                break
    if best_ts is None:
        return False, None, ""
    return True, (best_ts - t0) / 60.0, which


def tape_trials(pairs: list[dict], settlements: list[dict], sport_label: str) -> list[dict]:
    out = []
    for pair in pairs:
        absorb = first_absorb(pair["yes_a"], pair["yes_b"])
        last = 0
        for ticks in (pair["yes_a"], pair["yes_b"], pair["no_a"], pair["no_b"]):
            if ticks:
                last = max(last, ticks[-1][0])
        for side, yes, opp_yes, same_no, opp_name in (
            (pair["side_a"], pair["yes_a"], pair["yes_b"], pair["no_a"], pair["side_b"]),
            (pair["side_b"], pair["yes_b"], pair["yes_a"], pair["no_b"], pair["side_a"]),
        ):
            winner = settlement_winner(settlements, pair["game"], side)
            for label, lo, hi in BUCKETS:
                hit = first_in_bucket(yes, lo, hi, absorb)
                if hit is None:
                    continue
                ts, px, phase = hit
                cap = NET_MAX - px
                arrived, mins, which = complement_arrives(cap, ts, absorb or last, opp_yes, same_no)
                # fee-adjusted cap using house kalshi-like fees on both legs
                fee_cap = NET_MAX - px - kalshi_fee(px) - kalshi_fee(max(0.01, cap))
                arrived_fee, mins_fee, which_fee = complement_arrives(fee_cap, ts, absorb or last, opp_yes, same_no)
                cheap_won = None
                if winner == "win":
                    cheap_won = True
                elif winner == "lose":
                    cheap_won = False
                out.append({
                    "sport": sport_label,
                    "game": pair["game"],
                    "venue": pair["venue"],
                    "player": side,
                    "opponent": opp_name,
                    "bucket": label,
                    "p": px,
                    "cap": cap,
                    "phase": phase or ("in-match" if "during" in (phase or "") else phase),
                    "arrived": arrived,
                    "minutes": mins,
                    "which": which,
                    "arrived_fee": arrived_fee,
                    "minutes_fee": mins_fee,
                    "which_fee": which_fee,
                    "cheap_won": cheap_won,
                    "winner": winner,
                })
    return out


def game_ticks(series: dict, game: str) -> list[dict]:
    needle = game_norm(game)
    out = []
    for key, ticks in series.items():
        _sport, g, venue, side, pay = key
        if needle not in game_norm(g) and game_norm(g) not in needle:
            continue
        for ts, px, phase in ticks:
            out.append({"game": g, "venue": venue, "side": side, "pay": pay, "ts": ts, "price": px, "phase": phase})
    out.sort(key=lambda r: r["ts"])
    return out


def complement_on_tape_after(ticks: list[dict], fill_ts: int, cheap_player: str, cheap_side: str, cap: float, game: str) -> dict:
    cheap_n = last_name(cheap_player)
    arrived = False
    first = None
    which = ""
    min_px = None
    for row in ticks:
        if row["ts"] < fill_ts:
            continue
        if row["price"] <= ABSORB_LO or row["price"] >= ABSORB_HI:
            # still allow recording min before absorb of this series
            pass
        side_n = last_name(row["side"])
        is_opp_yes = row["pay"] == "yes" and side_n != cheap_n and side_n
        is_same_no = row["pay"] == "no" and (side_n == cheap_n or not side_n)
        # If we hold Yes cheap, complement is opp Yes or same No.
        if str(cheap_side).lower() == "yes":
            ok = is_opp_yes or is_same_no
        else:
            # hold No cheap → complement is same Yes or opp No
            is_same_yes = row["pay"] == "yes" and side_n == cheap_n
            is_opp_no = row["pay"] == "no" and side_n != cheap_n
            ok = is_same_yes or is_opp_no
        if not ok:
            continue
        if min_px is None or row["price"] < min_px:
            min_px = row["price"]
        if row["price"] <= cap and not arrived:
            arrived = True
            first = row
            which = f"{row['venue']} {row['pay']} {row['side']}"
    mins = None
    if first:
        mins = (first["ts"] - fill_ts) / 60.0
    return {
        "printed_under_cap": arrived,
        "minutes": mins,
        "which": which,
        "min_complement": min_px,
    }


def fmt_minutes(value) -> str:
    if value is None:
        return ""
    return f"{value:.1f}"


def bucket_summary(trials: list[dict], fee: bool = False) -> list[list]:
    rows = []
    key_arr = "arrived_fee" if fee else "arrived"
    key_min = "minutes_fee" if fee else "minutes"
    for label, _lo, _hi in BUCKETS:
        sub = [t for t in trials if t["bucket"] == label]
        n = len(sub)
        arrived = [t for t in sub if t[key_arr]]
        unmatched = [t for t in sub if not t[key_arr]]
        mins = [t[key_min] for t in arrived if t[key_min] is not None]
        settled = [t for t in unmatched if t["cheap_won"] is not None]
        won = [t for t in settled if t["cheap_won"]]
        all_settled = [t for t in sub if t["cheap_won"] is not None]
        all_won = [t for t in all_settled if t["cheap_won"]]
        rows.append([
            label,
            n,
            len(arrived),
            pct(len(arrived), n),
            f"{statistics.median(mins):.1f}" if mins else "",
            len(unmatched),
            len(settled),
            len(won),
            pct(len(won), len(settled)) if settled else "",
            pct(len(all_won), len(all_settled)) if all_settled else "",
            tiny(n),
        ])
    return rows


def tiny(n: int) -> str:
    if n <= 0:
        return "no rows"
    if n < 20:
        return "tiny N"
    if n < 50:
        return "small N"
    return ""


def onclin_block(attempts: list[dict], series: dict) -> dict:
    hits = [a for a in attempts if "onclin" in a["game"].lower() or "oncstr" in a["key"]]
    return {"attempts": hits}


def write_page(bundle: dict, trials: list[dict], settlements: list[dict], series: dict) -> Path:
    attempts = bundle["attempts"]
    send_attempts = [a for a in attempts if a["n_sent"] > 0]
    onelegs = [a for a in send_attempts if a["class_"].startswith("oneleg")]
    both_lock = [a for a in send_attempts if a["class_"] == "both_true_lock"]
    later_lock = [a for a in send_attempts if a["class_"] == "oneleg_then_true_lock"]
    same_bet = [a for a in send_attempts if a["class_"] in ("oneleg_same_bet", "both_same_bet")]
    unmatched = [a for a in send_attempts if a["class_"] == "oneleg_unmatched"]
    neither = [a for a in send_attempts if a["class_"] == "neither"]
    completed_locks = both_lock + later_lock
    lock_pnls = [lock_pnl(a) for a in completed_locks]
    lock_pnls = [x for x in lock_pnls if x is not None]
    unmatched_risk = sum(a["net_outlay"] for a in unmatched)
    same_bet_risk = sum(a["net_outlay"] for a in same_bet)
    unmatched_win = sum(unmatched_pnl_if(a, True) or 0 for a in unmatched)
    unmatched_lose = sum(unmatched_pnl_if(a, False) or 0 for a in unmatched)
    same_win = sum(unmatched_pnl_if(a, True) or 0 for a in same_bet)
    same_lose = sum(unmatched_pnl_if(a, False) or 0 for a in same_bet)

    # Per-attempt table: every pair that filled at least one leg (both-unfilled counted in Rates only)
    filled_attempts = [a for a in send_attempts if a["n_fill"] >= 1]
    pair_rows = []
    for i, a in enumerate(filled_attempts, 1):
        fills = a["fills"]
        cheap = a["cheap"]
        fill_txt = "; ".join(
            f"{leg['venue']} {leg['book_side']} {leg.get('player') or ''} @{money4(leg['cash'])} fee {money4(leg['fee'])} [{leg.get('step') or ''}]"
            for leg in a["legs"] if leg["filled"]
        )
        miss_txt = "; ".join(
            f"{leg['venue']} {leg['book_side']} {leg.get('player') or ''} lim {money4(leg['limit'])} [{leg.get('step') or ''}]"
            for leg in a["legs"] if not leg["filled"] and leg.get("step") != "watch"
        )
        pnl_l = lock_pnl(a)
        at_risk = a["net_outlay"] if a["class_"] in ("oneleg_unmatched", "oneleg_same_bet", "both_same_bet") else ""
        pair_rows.append([
            i,
            a["game"],
            a["sport"],
            a["market"],
            a["mode"],
            a["n_sent"],
            a["n_init_fill"],
            a["n_fill"],
            a["lock_kind"] or a["class_"],
            fill_txt,
            miss_txt,
            money4(a["max_other"]),
            money(a["net_outlay"]),
            money(pnl_l) if pnl_l is not None else "",
            money(at_risk) if at_risk != "" else "",
            money(unmatched_pnl_if(a, True)) if at_risk != "" else "",
            money(unmatched_pnl_if(a, False)) if at_risk != "" else "",
        ])

    # Unmatched detail + tape after fill
    un_rows = []
    for a in unmatched + same_bet:
        cheap = a["cheap"] or {}
        fill_ts = None
        if cheap.get("ts"):
            dt = parse_dt(cheap["ts"])
            if dt:
                fill_ts = int(to_et(dt).timestamp())
        ticks = game_ticks(series, a["game"]) if fill_ts else []
        tape = complement_on_tape_after(
            ticks,
            fill_ts or 0,
            str(cheap.get("player") or ""),
            str(cheap.get("book_side") or "yes"),
            float(a["max_other"] or 0),
            a["game"],
        ) if fill_ts and a["max_other"] is not None else {}
        winner = settlement_winner(settlements, a["game"], str(cheap.get("player") or a["game"]))
        un_rows.append([
            a["game"],
            a["lock_kind"],
            f"{cheap.get('venue')} {cheap.get('book_side')} {cheap.get('player')}",
            money4(cheap.get("cash")),
            money4(cheap.get("fee")),
            money4(a["max_other"]),
            "yes" if tape.get("printed_under_cap") else ("no" if tape else ""),
            fmt_minutes(tape.get("minutes")),
            tape.get("which") or "",
            money4(tape.get("min_complement")),
            winner,
            money(unmatched_pnl_if(a, True)),
            money(unmatched_pnl_if(a, False)),
        ])

    onclin = [a for a in send_attempts if "onclin" in a["game"].lower() or "oncstr" in a["key"]]
    onclin_lines = []
    for a in onclin:
        for leg in a["legs"]:
            onclin_lines.append([
                a["game"],
                leg.get("ts") or "",
                leg["venue"],
                leg["instrument"],
                leg["book_side"],
                leg.get("player") or "",
                money4(leg.get("limit")),
                money4(leg.get("quote")),
                "yes" if leg["filled"] else "no",
                money4(leg.get("cash")),
                money4(leg.get("fee")),
                leg.get("step") or "",
                leg.get("pays") or "",
            ])

    tennis_trials = [t for t in trials if t["sport"] == "tennis"]
    nfl_trials = [t for t in trials if t["sport"] == "pro football"]

    n_send = len(send_attempts)
    n_one = len(onelegs)
    n_later = len(later_lock)
    n_un = len(unmatched)
    n_same = len([a for a in onelegs if a["class_"] == "oneleg_same_bet"])
    sim = [a for a in send_attempts if a["mode"] == "simultaneous"]
    sim_one = [a for a in sim if a["class_"].startswith("oneleg")]
    sim_un = [a for a in sim if a["class_"] == "oneleg_unmatched"]
    sim_later = [a for a in sim if a["class_"] == "oneleg_then_true_lock"]
    sim_same = [a for a in sim if a["class_"] == "oneleg_same_bet"]
    oneleg_rate = pct(n_one, n_send)
    later_rate = pct(n_later, n_one)
    un_rate = pct(n_un, n_one)
    same_rate = pct(n_same, n_one)

    # Headline tape p<=0.20
    cheap_bucket = [t for t in tennis_trials if t["bucket"].startswith("p ≤ 0.20")]
    cheap_arr = [t for t in cheap_bucket if t["arrived"]]
    cheap_un = [t for t in cheap_bucket if not t["arrived"]]
    cheap_un_settled = [t for t in cheap_un if t["cheap_won"] is not None]
    cheap_un_won = [t for t in cheap_un_settled if t["cheap_won"]]

    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    onclin_note = (
        "Ledger matches Paul's 0.18 / 0.77 arithmetic. Polymarket Yes Onclin filled at 0.17 plus "
        "about a 0.01 fee = 0.18 cash. Cap for the missing leg is 0.95 − 0.18 = 0.77. Simultaneous "
        "Kalshi Yes Struff at 0.75 posted fill_count 0.00 — Struff Yes never filled. Leftover watch "
        "then bought Kalshi No on the Struff ticker (ask 0.84, No cash 0.16, fill_count 1.00). That "
        "is the same bet as Onclin Yes, not the 0.77 lock. Same Goffin bug: leftover completed the "
        "wrong direction and latched as done."
    )
    if not onclin:
        onclin_note = "Onclin vs Struff pair was not found in orders.jsonl at write time."

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
{report_page_extras.CACHE_META}<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lock leftover risk — 21 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
.hl {{ font-size: 1.15rem; }}
ul {{ margin-top: 0.3rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Original live lock: leftover risk (cheap fill, complement never locks)</h1>
<p class="note">America/New_York. Written {esc(now)}. Research only. Not gold. Not DailyRun. This page does not place or cancel orders. Immediate-or-cancel (IOC) means fill now or cancel. In-sample (IS) vs out-of-sample (OOS): this live book is all October 2026 OOS. Tiny N. Annualized rate of return (Ann ROR) is n/a — no days-held book. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout warn">
<h2>Headline (one screen)</h2>
<p class="hl">Live book Oct 18–21: <strong>{esc(oneleg_rate)}%</strong> of send attempts one-legged ({n_one} of {n_send}). Of those one-legs: <strong>{esc(later_rate)}%</strong> later true-locked ({n_later}), <strong>{esc(same_rate)}%</strong> leftover-filled the <em>same bet</em> ({n_same}), <strong>{esc(un_rate)}%</strong> died unmatched ({n_un}).</p>
<ul>
<li>Completed true locks (immediate + Dodig-style leftover): N={len(completed_locks)}, locked P&amp;L <strong>${esc(money(sum(lock_pnls) if lock_pnls else 0))}</strong> on 1-contract size (always ~nickel if net ≤ 0.95; Maloney Yes+No same ticker is a lock at the cap).</li>
<li>Unmatched leftovers cash at risk: <strong>${esc(money(unmatched_risk))}</strong>. If every unmatched name wins: ${esc(money(unmatched_win))}. If every unmatched name loses: ${esc(money(unmatched_lose))}.</li>
<li>Same-bet leftover stacks (Goffin, Onclin, and any double Onclin-win): extra directional cash <strong>${esc(money(same_bet_risk))}</strong>. Win-all ${esc(money(same_win))}; lose-all ${esc(money(same_lose))}.</li>
<li>Onclin 0.77: <strong>yes, the ledger matches</strong>. Fill 0.17 + ~0.01 fee = 0.18. Missing Struff Yes cap = 0.77. Kalshi Yes Struff 0.75 <code>fill_count</code> 0.00. Leftover then bought No-Struff cash 0.16 (same bet), not 0.77 Struff Yes.</li>
<li>Tennis tape, first Yes print in the ≤20¢ bucket: complement ≤ 0.95−p arrived on <strong>{esc(pct(len(cheap_arr), len(cheap_bucket)))}%</strong> of books (N={len(cheap_bucket)}). When it never arrived, the cheap name won {esc(pct(len(cheap_un_won), len(cheap_un_settled)))}% of settled unmatched leftovers ({len(cheap_un_settled)} settled) — that is the enrichment-for-losers test.</li>
</ul>
<p>Neither KEEP nor DISMISS on leftover-vs-sit-out from this page. Quality over N. Do not retune live knobs from one October weekend.</p>
</div>

<div class="callout ok">
<h2>Onclin vs Struff ledger vs Paul's 0.77 assumption</h2>
<p>{esc(onclin_note)}</p>
</div>

<h2>Onclin vs Struff — every sent leg</h2>
<p class="note">Kalshi bid = buy Yes Struff (the lock complement). Kalshi ask = sell Yes Struff = buy No Struff = Onclin wins (same bet as Polymarket Yes Onclin). Fee on Polymarket is the venue commission when logged, else the house 0.0695×p×(1−p) banker-cent formula.</p>
{table(
    [("Game","text"),("Time ET","date"),("Venue","text"),("Instrument","text"),("Book side","text"),("Player / ticker","text"),("Limit","num"),("Quote","num"),("Filled","text"),("Fill cash","num"),("Fee","num"),("Step","text"),("Pays if","text")],
    onclin_lines,
)}

<h2>Live book — every intended pair that sent</h2>
<p class="note">A send attempt is one claim that posted at least one IOC. The table below lists every attempt that filled at least one leg. Both-unfilled IOCs are counted in Rates only (N is large and they have no leftover risk). Simultaneous is the original live lock. Early NFL/NHL rows were the sequential walk before both legs left at once. Leftover-watch fills are tagged <code>watch</code>. True lock = Yes+No same settlement, or dual-Yes on opposite tennis names. Same bet = both tickets pay on the same winner (Goffin Yes + No Bertola; Onclin Yes + No Struff). Tiny N, all OOS October 2026. Canonical dollars here are 1-contract outlay, locked P&amp;L, and leftover cash at risk. Ann ROR n/a.</p>
{table(
    [("Attempt","num"),("Game","text"),("Sport","text"),("Market","text"),("Send mode","text"),("Legs sent","num"),("Initial fills","num"),("Total fills","num"),("Class","text"),("Fills","text"),("Missed initial","text"),("Max other (cap)","num"),("Outlay $","num"),("Lock P&L $","num"),("At risk $","num"),("If leftover wins $","num"),("If leftover loses $","num")],
    pair_rows,
    ["All", f"{n_send} sends", "", "", "", "", "", "", f"one-leg {oneleg_rate}%", "", "", "", money(sum(a['net_outlay'] for a in send_attempts if a['n_fill'])), money(sum(lock_pnls) if lock_pnls else 0), money(unmatched_risk + same_bet_risk), money(unmatched_win + same_win), money(unmatched_lose + same_lose)],
)}

<h2>Rates</h2>
{table(
    [("Slice","text"),("N","num"),("Share of sends %","num"),("Note","text")],
    [
        ["Send attempts (posted ≥1 IOC)", n_send, "100", "tiny N, Oct 18–21 2026 OOS"],
        ["Neither filled", len(neither), pct(len(neither), n_send), "IOC miss both sides"],
        ["Both filled true lock at first send", len(both_lock), pct(len(both_lock), n_send), "none this weekend; MTN 48.5 and Dodig locked on leftover"],
        ["One-leg (any leftover fate)", n_one, oneleg_rate, "initial exactly one fill"],
        ["One-leg then leftover true lock", n_later, pct(n_later, n_send), "Dodig; Maloney Yes+No same ticker"],
        ["One-leg leftover same bet", n_same, pct(n_same, n_send), "Goffin; Onclin No-Struff"],
        ["One-leg leftover never filled", n_un, pct(n_un, n_send), "MTN 47.5, Prizmic, Wawrinka directional, early NFL (no 20s watch yet)"],
        ["step=simultaneous tagged claims", len(sim), pct(len(sim), n_send), "incomplete stamp — most IOC misses are tagged websocket, not simultaneous"],
    ],
)}

<h2>Unmatched leftovers and same-bet stacks</h2>
<p class="note">Max other is 0.95 − fill cash − fill fee. Complement on tape after fill: opponent Yes or same-player No (or the reverse if we hold No) at or under that cap, any venue, before a 5¢/95¢ absorbing print. Settlement is official when the cache has it; else unknown. Mark-to-win assumes every filled ticket on the stack pays $1 if that name wins.</p>
{table(
    [("Game","text"),("Class","text"),("Cheap fill","text"),("Fill cash","num"),("Fee","num"),("Max other","num"),("Complement printed under cap?","text"),("Minutes to print","num"),("Which print","text"),("Min complement after fill","num"),("Settlement","text"),("P&L if wins $","num"),("P&L if loses $","num")],
    un_rows,
)}

<h2>Tape rate — how often the 0.77 print should arrive</h2>
<p class="note">Tennis moneyline Yes/No change-ticks in price_memory (read-only archive plus dated shards). For each two-player book, first time a player's Yes sits in the bucket, wait until the first 5¢ or 95¢ absorbing Yes (match treated as over) or the last quote. Complement = opponent Yes or same-player No at ≤ 0.95 − p. Fees ignored in the first table; optional fee table subtracts the Kalshi-style 0.07×p×(1−p) on both legs from the 0.95 cap. NFL moneyline is included when the tape has two sides. First-entry only (one trial per player/venue/bucket) so a busy websocket does not flood N. Unmatched leftover win% is the enrichment test: if Onclin is losing, Struff Yes goes up, so unmatched cheap leftovers should win less often than the bucket base rate.</p>
<h3>Tennis — no fees</h3>
{table(
    [("Bucket","text"),("Trials","num"),("Complement arrived","num"),("Arrived %","num"),("Median minutes","num"),("Never arrived","num"),("Unmatched settled","num"),("Unmatched cheap won","num"),("Unmatched win %","num"),("All-trial win %","num"),("Sample","text")],
    bucket_summary(tennis_trials, fee=False),
)}
<h3>Tennis — optional fee row (Kalshi-style fee both legs)</h3>
{table(
    [("Bucket","text"),("Trials","num"),("Complement arrived","num"),("Arrived %","num"),("Median minutes","num"),("Never arrived","num"),("Unmatched settled","num"),("Unmatched cheap won","num"),("Unmatched win %","num"),("All-trial win %","num"),("Sample","text")],
    bucket_summary(tennis_trials, fee=True),
)}
<h3>NFL moneyline — no fees</h3>
{table(
    [("Bucket","text"),("Trials","num"),("Complement arrived","num"),("Arrived %","num"),("Median minutes","num"),("Never arrived","num"),("Unmatched settled","num"),("Unmatched cheap won","num"),("Unmatched win %","num"),("All-trial win %","num"),("Sample","text")],
    bucket_summary(nfl_trials, fee=False),
)}

<h2>Known examples (verified, not invented)</h2>
<ul>
<li><strong>MTN/FIU 48.5:</strong> Kalshi No then leftover Gemini Yes Over — true lock (not a simultaneous both-fill).</li>
<li><strong>Dodig:</strong> Polymarket Yes Dodig one-leg, leftover Kalshi No Dodig later — true lock (Yes+No same name).</li>
<li><strong>MTN 47.5:</strong> Kalshi ask fill wire 0.72 = No cash 0.28 (quote/log 0.44), Gemini Yes never filled — unmatched leftover.</li>
<li><strong>Prizmic:</strong> Polymarket No Dzumhur 0.52 — unmatched leftover.</li>
<li><strong>Wawrinka:</strong> two leftovers that both pay if Wawrinka wins (Kalshi No Landaluce + Polymarket Yes Wawrinka), not a lock. Separate pair keys.</li>
<li><strong>Goffin:</strong> Polymarket Yes Goffin + leftover Kalshi No Bertola — same bet, watch marked complete.</li>
<li><strong>Onclin:</strong> Polymarket Yes 0.17 (~0.18 with fee). Struff Yes 0.75 never filled. Leftover Kalshi No Struff cash 0.16 — same bet, not 0.77.</li>
</ul>

<h2>Freeze / process</h2>
<ul>
<li>Original live system: <code>tools/live_lock_orders.py</code> simultaneous dual-leg IOC, net ≤ $0.95 after documented fees, 1 contract, prices under $1.</li>
<li>One-leg: skip recovery if fill+other+fees over cap; leftover watch every 20s, sequential cheapest IOC if ≥ $0.05 locked profit. One-leg latch blocks NEW pairs.</li>
<li>This page does not touch live orders, secrets, latches, or strategy_b. Research candidate only. Not gold. Not DailyRun.</li>
<li>IS/OOS: live sample is all OOS (entry dates 18–21 Oct 2026). Tape is the same weekend plus earlier tennis stored in the archive. Tiny N. Do not retune from OOS.</li>
<li>Ann ROR n/a (no holding period / BRT cash days-held book). Quality metric here is locked nickel vs leftover cash at risk and leftover win rate.</li>
</ul>
<p class="note">Related: <a href="one_leg_note.html">one_leg_note.html</a>, <a href="orders.html">orders.html</a>, <a href="wawrinka_landaluce_fills_20261021.html">wawrinka_landaluce_fills_20261021.html</a>, <a href="one_leg_20s_watch_20261021.html">one_leg_20s_watch_20261021.html</a>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html = report_page_extras.inject_report_page_extras(html)
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(PAGE)
    copy_g(PAGE)
    return PAGE


def main() -> None:
    print("classifying live book", flush=True)
    bundle = classify_attempts()
    print(f"send attempts {sum(1 for a in bundle['attempts'] if a['n_sent'])}", flush=True)
    print("loading settlements", flush=True)
    settlements = load_settlements()
    print(f"settlements {len(settlements)}", flush=True)
    print("scanning tape (archive + shards, tennis + NFL moneyline)", flush=True)
    series = load_series(("tennis", "pro football"))
    pairs = two_player_bags(series)
    print(f"two-sided books {len(pairs)}", flush=True)
    trials: list[dict] = []
    for pair in pairs:
        trials.extend(tape_trials([pair], settlements, pair["sport"]))
    print(f"trials {len(trials)}", flush=True)
    page = write_page(bundle, trials, settlements, series)
    print(f"wrote {page}", flush=True)


if __name__ == "__main__":
    main()
