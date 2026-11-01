"""Send a 1-contract lock when the live compare nets $0.95 or less.

Paul authorized this on 2026-10-18: execute when the locked profit is at least
$0.05 a contract. Research only. Not gold. Not DailyRun. The size cap stays 1.

A lock is Yes on one venue and No on the other for the same settlement. The
fee is the documented fee on the charging leg only. Kalshi is not given a fee.
The closed Tennessee vs Indianapolis 13.5 trade is never sent.

Adopted one-leg policy (2026-10-31, Paul):
  1. First / hard leg: IOC.
  2. If hard fills → second / easy leg: GTC at the original miss limit L
     (marketable take now + rest the remainder). Do not IOC-then-repost.
  3. If the GTC is still open after ONE_LEG_GTC_WAIT_SEC (180s):
       - held pay ≤ CHEAP_EXIT_MAX (25¢): exit — same-shop flatten if tighter,
         else market sell. Do not hold cheap dogs.
       - held pay > 25¢: one IOC to complete the lock at ≤ break-even
         (optional +BE_COMPLETE_SLIP); if that misses → hold to settlement.
  4. Cancel-on-resolve for resting second-leg GTCs is required.

Secrets stay in secrets/. This module logs status, instrument, side, limit, and
size. It does not log keys, signatures, or auth headers.

Orders stay off by default in bare clones and cloud VMs. Trading PC turns them
on with env LOCK_ORDERS_ENABLED=1 and/or stamp file raw/orders_enabled.on
(orders_enabled.off always wins). See orders_enabled().
"""
from __future__ import annotations

import json
import os
import time
import uuid
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path

import gemini_private
import kalshi_private
import polymarket_us_live
import venue_pace

ROOT = Path(__file__).resolve().parents[1]
try:
    from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
except Exception:  # pragma: no cover - bare clone without prediction_paths
    STAMP = ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"
    RAW = STAMP / "raw"
ORDERS = RAW / "orders.jsonl"
ORDER_LOCK = RAW / "orders.lock"
ONE_LEG_WATCH = RAW / "one_leg_gtc_watch.jsonl"
LAST_SKIP = RAW / "lock_last_skip.json"
ORDERS_ENABLED_STAMP_ON = RAW / "orders_enabled.on"
ORDERS_ENABLED_STAMP_OFF = RAW / "orders_enabled.off"
ONE = Decimal("1")
CENT = Decimal("0.01")
NET_MAX = Decimal("0.95")
_DEFAULT_NET_MAX = Decimal("0.95")
SIZE = Decimal("1")
KALSHI_TICK = Decimal("0.0001")
POLY_TICK = Decimal("0.001")
# Second-leg GTC wait, then cheap-exit / BE-complete / hold (Paul 2026-10-31).
ONE_LEG_GTC_WAIT_SEC = 180
CHEAP_EXIT_MAX = Decimal("0.25")
BE_COMPLETE_SLIP = Decimal("0.01")  # allow BE + 1¢ on the optional complete IOC
# Aggressive exit limits when a live quote is not passed in.
MARKET_SELL_FLOOR = Decimal("0.01")
MARKET_BUY_CEILING = Decimal("0.99")
MAX_OPEN_LOCKS = 3
CLOSED = {"closed", "settled", "determined", "finalized", "inactive"}
_capability: dict[str, tuple[float, bool, str]] = {}

# Module flag (default False). Prefer orders_enabled() which also honors env + stamps.
# Tests and local overrides may assign ORDERS_ENABLED = True.
ORDERS_ENABLED = False


def effective_net_max() -> Decimal:
    """systems.json lock.net_max when Paul set it; else NET_MAX / module default.

    Tests that assign NET_MAX away from the default pin that cap.
    """
    current = Decimal(str(NET_MAX))
    if current != _DEFAULT_NET_MAX:
        return current
    try:
        import prediction_systems

        raw = getattr(prediction_systems.get_system("lock"), "net_max", None)
        if raw is not None:
            val = Decimal(str(raw))
            if val > 0:
                return val
    except Exception:
        pass
    return current


def send_line() -> str:
    """User-facing send cap from systems.json lock.net_max, else NET_MAX."""
    return format(effective_net_max(), "f")


def rewrite_send_line_copy(text: str) -> str:
    """Show the live NET_MAX in skip/status copy that still names a prior cap."""
    import re

    line = send_line()
    cap = effective_net_max()
    out = str(text or "")

    def _amt(raw: str) -> Decimal | None:
        try:
            return Decimal(raw)
        except Exception:
            return None

    def swap(pattern: str, repl: str) -> None:
        nonlocal out

        def sub(match: re.Match) -> str:
            if match.group("n") == "0.99":
                return match.group(0)
            return repl

        out = re.sub(pattern, sub, out)

    def cost_above_line(match: re.Match) -> str:
        if match.group("n") == "0.99":
            return match.group(0)
        amount = _amt(match.group("amt"))
        if amount is None or amount <= cap:
            return match.group(0)
        return f"{match.group('lead')}{match.group('amt')} is above the {line} send line"

    out = re.sub(
        r"(?P<lead>After-fee cost )(?P<amt>\d+\.\d+) is above the (?P<n>\d+\.\d+) send line",
        cost_above_line,
        out,
    )
    swap(r"(?<!above the )(?P<n>\d+\.\d+) send line", f"{line} send line")
    swap(r"the (?P<n>\d+\.\d+) cap", f"the {line} cap")
    swap(r"net at or under (?P<n>\d+\.\d+)", f"net at or under {line}")
    swap(r"net <= (?P<n>\d+\.\d+)", f"net <= {line}")
    swap(r"net is \$(?P<n>\d+\.\d+)", f"net is ${line}")
    return out


def orders_enabled() -> bool:
    """True only when venue order HTTP is allowed.

    Priority (first match wins):
      1. raw/orders_enabled.off exists → False
      2. LOCK_ORDERS_ENABLED env: 1/true/yes/on → True; 0/false/no/off → False
      3. raw/orders_enabled.on exists → True
      4. ORDERS_ENABLED module flag (default False)
    """
    if ORDERS_ENABLED_STAMP_OFF.exists():
        return False
    env = os.environ.get("LOCK_ORDERS_ENABLED", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    if ORDERS_ENABLED_STAMP_ON.exists():
        return True
    return bool(ORDERS_ENABLED)


def _iso_now() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def maybe_resume_one_leg_watch(log) -> str:
    """GTC adopt: leftover IOC resume may be absent. Sender ticks GTC watches instead."""
    del log
    return "gtc-adopt"


def ensure_watch_ticker(log) -> None:
    """No-op after GTC adopt. live_lock_sender ticks tick_one_leg_gtc_watches itself."""
    del log


def record_send_skip(reason: str, title: str = "", key: str = "", spec: dict | None = None) -> None:
    """Write the last send-gate / flatten skip to orders.jsonl and lock_last_skip.json."""
    row = {
        "event": "skip",
        "reason": str(reason or "").strip()[:400],
        "game": title,
        "bet_key": key,
        "at": _iso_now(),
    }
    if isinstance(spec, dict):
        if spec.get("venue"):
            row["venue"] = spec.get("venue")
        if spec.get("instrument"):
            row["instrument"] = spec.get("instrument")
    try:
        _append(row)
    except Exception:
        pass
    try:
        LAST_SKIP.parent.mkdir(parents=True, exist_ok=True)
        LAST_SKIP.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        pass


def effective_max_open_locks() -> int:
    """systems.json lock.max_open when set; otherwise MAX_OPEN_LOCKS (3)."""
    try:
        import prediction_systems

        n = int(prediction_systems.get_system("lock").max_open)
        if n >= 1:
            return n
    except Exception:
        pass
    return int(MAX_OPEN_LOCKS)


def lock_system_on() -> bool:
    """False when Lock gap (A) is off in systems.json. GTC leftover ticks still run."""
    try:
        import prediction_systems

        return bool(prediction_systems.get_system("lock").on)
    except Exception:
        return True


def lock_open_denial(open_n: int | None = None) -> str:
    cap = effective_max_open_locks()
    n = int(cap if open_n is None else open_n)
    return f"Already have {n} open lock pair(s); max_open_locks={cap}."


def lock_open_line(open_n: int | None = None) -> str:
    cap = effective_max_open_locks()
    n = int(cap if open_n is None else open_n)
    return f"{n} / {cap}"


def open_lock_keys(
    rows: list[dict] | None = None,
    *,
    snapshot=None,
    overlay: bool | None = None,
    include_watches: bool = True,
    **_kwargs,
) -> list[str]:
    """Unique bet_keys occupying a max_open slot (house tape).

    GTC merge dropped the full venue-overlay kitchen; this keeps the send cap
    honest from orders.jsonl + open second-leg GTC watches. snapshot/overlay
    accepted for open_count_sync callers and ignored here.
    """
    del snapshot, overlay
    tape = rows if rows is not None else _read_orders()
    state: dict[str, str] = {}
    order: list[str] = []
    for row in tape:
        if not isinstance(row, dict):
            continue
        key = str(row.get("bet_key") or "")
        if not key or key.startswith("tennis-b"):
            continue
        if key not in state:
            state[key] = "clear"
            order.append(key)
        event = row.get("event")
        if event in ("filled", "one_leg"):
            state[key] = "position"
        elif event == "flatten_filled":
            state[key] = "clear"
        elif event == "claim" and state[key] != "position":
            state[key] = "working"
        elif event == "sent" and state[key] != "position":
            state[key] = "sent"
        elif event in ("both_unfilled", "preflight_skip", "skip") and state[key] == "working":
            state[key] = "clear"
    out = [key for key in order if state.get(key) in ("position", "working", "sent")]
    if include_watches:
        try:
            for row in open_second_leg_gtc_watches():
                key = str(row.get("bet_key") or "")
                if key and key not in out:
                    out.append(key)
        except Exception:
            pass
    return out


def lock_slots_full(open_keys: list[str] | None = None) -> bool:
    keys = list(open_keys if open_keys is not None else open_lock_keys())
    return len(keys) >= effective_max_open_locks()


def _money(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", ""))
    except Exception:
        return None


def _public_note(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "response was not json"
    if not isinstance(data, dict):
        return "response was not an object"
    text = str(data.get("message") or data.get("reason") or data.get("error") or data.get("code") or "")
    text = " ".join(text.split())[:240]
    lowered = text.lower()
    if any(word in lowered for word in ("signature", "secret", "bearer", "api key", "apikey")):
        return "rejected"
    return text or "no message"


def historical_tennessee_13_5(title: str, game: dict, cand: dict) -> bool:
    """The already-closed Tennessee vs Indianapolis 13.5. Never send it."""
    blob = " ".join(
        str(part)
        for part in (
            title,
            game.get("title_gemini") if isinstance(game, dict) else "",
            game.get("title_kalshi") if isinstance(game, dict) else "",
            game.get("codes") if isinstance(game, dict) else "",
            cand.get("side"),
            cand.get("number"),
            cand.get("kalshi_ticker"),
            cand.get("gemini_symbol"),
            cand.get("market_type"),
        )
    ).lower()
    teams = ("tennessee" in blob or "titans" in blob) and ("indianapolis" in blob or "colts" in blob)
    line = str(cand.get("number") or "") in ("13.5", "13.50") or "13.5" in blob
    return bool(teams and line)


def whole_size(value) -> bool:
    number = _dec(value)
    return number is not None and number >= SIZE


def pair_net(scan, cand: dict) -> Decimal | None:
    """Gross plus the documented fee on each charging leg. None when a fee is unknown."""
    yes = _dec(cand.get("yes_price"))
    no = _dec(cand.get("no_price"))
    if yes is None or no is None:
        return None
    fee = Decimal("0")
    for venue, price in ((str(cand.get("yes_venue") or "").lower(), yes), (str(cand.get("no_venue") or "").lower(), no)):
        if venue == "kalshi":
            continue
        if venue == "gemini":
            fee += scan.gemini_fee(price)
            continue
        if venue == "polymarket":
            part = polymarket_us_live.taker_fee(price, cand.get("fee_coefficient"))
            if part is None:
                saved = _dec(cand.get("polymarket_fee"))
                if saved is None:
                    return None
                part = saved
            fee += part
            continue
        return None
    return yes + no + fee


def same_settlement_candidate(cand: dict) -> tuple[bool, str]:
    """Send-time gate. Team total ≠ game total ≠ spread ≠ moneyline."""
    import price_memory

    row = cand if isinstance(cand, dict) else {}
    why = price_memory.settlement_mismatch_reason(
        row.get("market_type"),
        row.get("kalshi_ticker"),
        row.get("kalshi_yes_ticker"),
        row.get("kalshi_no_ticker"),
        row.get("gemini_symbol"),
        row.get("polymarket_slug"),
        row.get("novig_market"),
    )
    if why:
        return False, why
    return True, ""


def same_settlement_legs(*specs: dict) -> tuple[bool, str]:
    """REST recheck sees bet type on each instrument, not the line number alone."""
    import price_memory

    parts: list[str] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        parts.append(str(spec.get("instrument") or ""))
        parts.append(str(spec.get("market_type") or ""))
    why = price_memory.settlement_mismatch_reason(*parts)
    if why:
        return False, why
    return True, ""


def qualifies(scan, cand: dict, title: str, game: dict) -> tuple[bool, str]:
    if historical_tennessee_13_5(title, game, cand):
        return False, "closed Tennessee vs Indianapolis 13.5 is not sent"
    ok, why = same_settlement_candidate(cand)
    if not ok:
        return False, why
    import kalshi_same_direction as ksd

    bad, why_sd = ksd.candidate_is_same_direction_double(cand)
    if bad:
        return False, why_sd
    if scan.gemini_no_rejection(cand):
        return False, "Gemini No is not a buyable offer"
    for field in ("kalshi_status", "gemini_status"):
        if str(cand.get(field) or "").lower() in CLOSED:
            return False, "contract is closed"
    if not whole_size(cand.get("yes_size")) or not whole_size(cand.get("no_size")):
        return False, "both books need at least 1 contract"
    net = pair_net(scan, cand)
    if net is None:
        return False, "fee unknown"
    cap = effective_net_max()
    if net > cap:
        return False, f"net {_money(net)} is above {send_line()}"
    return True, f"net {_money(net)}"


def _norm_num(value) -> str:
    number = _dec(value)
    if number is None:
        return ""
    if number == number.to_integral():
        return str(int(number))
    return format(number.normalize(), "f")


def leg_moves(fresh: list[dict], cand: dict) -> tuple[Decimal | None, Decimal | None]:
    """Absolute move since the last check for the Yes leg and the No leg."""
    found = {"yes": None, "no": None}
    kind = str(cand.get("market_type") or "")
    number = _norm_num(cand.get("number"))
    for outcome, venue_key in (("yes", "yes_venue"), ("no", "no_venue")):
        venue = str(cand.get(venue_key) or "").lower()
        best: Decimal | None = None
        seen = False
        for row in fresh or []:
            if str(row.get("venue") or "").lower() != venue:
                continue
            if str(row.get("pay") or "").lower() != outcome:
                continue
            if str(row.get("market_type") or "") != kind:
                continue
            if _norm_num(row.get("number")) != number:
                continue
            move = _dec(row.get("move"))
            if move is None:
                continue
            seen = True
            size = abs(move)
            if best is None or size > best:
                best = size
        found[outcome] = best if seen else None
    return found["yes"], found["no"]



# --- thin-first (merged from tools/_merge_backup/live_lock_orders.py) ---
VENUE_MISS_RANK = {
    "gemini": 3,
    "kalshi": 2,
    "polymarket": 1,
    "novig": 0,
}

def _venue_miss_rank(spec: dict | None) -> int:
    """Higher = historically more one-leg misses. Frozen VENUE_MISS_RANK."""
    venue = str((spec or {}).get("venue") or "").lower()
    return int(VENUE_MISS_RANK.get(venue, 0))

def _pick_hard_leg(first: dict, second: dict) -> tuple[dict, dict]:
    """Hard = smaller REST ask size. Tie: worse fill venue, else pricier cash.

    Research freeze 2026-10-24 (Paul sequential hard-first). Size is primary.
    Simultaneous dual IOC is not this path.
    """
    sa = _takeable_size(first)
    sb = _takeable_size(second)
    if sa is None:
        sa = Decimal("0")
    if sb is None:
        sb = Decimal("0")
    if sa < sb:
        return first, second
    if sb < sa:
        return second, first
    ra, rb = _venue_miss_rank(first), _venue_miss_rank(second)
    if ra > rb:
        return first, second
    if rb > ra:
        return second, first
    pa = _dec(first.get("pay")) or Decimal("0")
    pb = _dec(second.get("pay")) or Decimal("0")
    if pa > pb:
        return first, second
    if pb > pa:
        return second, first
    ordered = _sort_legs_for_log([first, second])
    return ordered[0], ordered[1]

def flatten_filled_leg(log, key: str, title: str, filled_spec: dict) -> dict:
    """IOC buy opposite on the filled venue/instrument. Not a NET_MAX lock; an unwind."""
    blank = {
        "filled": False,
        "advance": False,
        "payload": None,
        "status": 0,
        "note": "flatten spec missing",
        "pay": "",
        "spec": filled_spec,
        "step": "flatten",
        "posted": False,
    }
    held = _dec(
        filled_spec.get("fill_qty") or filled_spec.get("confirm_qty") or filled_spec.get("qty")
    )
    if held is not None and Decimal("0") < held < SIZE:
        blank["note"] = f"not flattening as 1 (venue qty {format(held, 'f')})"
        record_send_skip(blank["note"], title, key)
        return blank
    spec = _flatten_spec(filled_spec)
    if spec is None:
        record_send_skip("flatten spec missing", title, key)
        return blank
    ask, note = fetch_book_ask(spec, pace=False)
    if ask is None:
        blank["note"] = f"flatten book empty ({note})"
        record_send_skip(blank["note"], title, key)
        _phone_watch_note("Flatten missed", f"Flatten not sent. {title}. {blank['note']}.")
        return blank
    size = _takeable_size(spec)
    if size is None or size < SIZE:
        saw = "missing" if size is None else format(size, "f")
        blank["note"] = f"flatten no takeable size (saw {saw})"
        record_send_skip(blank["note"], title, key)
        _phone_watch_note("Flatten missed", f"Flatten not sent. {title}. {blank['note']}.")
        return blank
    spec["quote_source"] = "book"
    spec["quote_price"] = format(ask, "f")
    spec["quote_seen_at"] = _iso_now()
    spec["_bet_key"] = key
    _phone_watch_note(
        "Flatten sent",
        f"Flatten send. {title}. {spec['venue']} {spec['instrument']} {spec['outcome']} ask {spec['quote_price']}.",
    )
    outcome = _one_ioc(log, key, spec, ask, "flatten", _send, None, None)
    filled = leg_filled_at_least_one(outcome)
    _append({
        "event": "flatten_filled" if filled else "flatten_miss",
        "bet_key": key,
        "game": title,
        "venue": spec["venue"],
        "instrument": spec["instrument"],
        "side": spec["outcome"],
        "limit_price": outcome.get("pay") or spec.get("quote_price"),
        "http_status": outcome.get("status"),
        "note": outcome.get("note") or "",
        "step": "flatten",
    })
    if filled:
        try:
            import orders_performance_refresh
            orders_performance_refresh.maybe_after_flatten(title, key, filled=True)
        except Exception:
            pass
    record_send_skip("flatten filled" if filled else f"flatten missed {outcome.get('note') or ''}", title, key)
    _phone_watch_note(
        "Flatten filled" if filled else "Flatten missed",
        f"Flatten {'filled' if filled else 'missed'}. {title}. {spec['venue']} {spec['instrument']} {spec['outcome']}.",
    )
    return outcome

def _takeable_size(spec: dict | None) -> Decimal | None:
    size = _dec((spec or {}).get("quote_size"))
    if size is None:
        return None
    return size

def _sort_legs_for_log(legs: list[dict]) -> list[dict]:
    """Deterministic listing only. Alphabetical venue name. Not a send preference."""
    return sorted(legs, key=lambda leg: (str(leg.get("venue") or ""), str(leg.get("outcome") or "")))

def ordered_outcomes(cand: dict, fresh: list[dict]) -> list[str]:
    """Yes or No labels in send order. Missing moves send Kalshi first."""
    yes_move, no_move = leg_moves(fresh, cand)
    venues = {
        "yes": str(cand.get("yes_venue") or "").lower(),
        "no": str(cand.get("no_venue") or "").lower(),
    }
    if yes_move is None or no_move is None:
        if "kalshi" in venues.values():
            first = "yes" if venues["yes"] == "kalshi" else "no"
            return [first, "no" if first == "yes" else "yes"]
        return ["yes", "no"]
    if yes_move > no_move:
        return ["yes", "no"]
    if no_move > yes_move:
        return ["no", "yes"]
    if venues["yes"] == "kalshi":
        return ["yes", "no"]
    if venues["no"] == "kalshi":
        return ["no", "yes"]
    return ["yes", "no"]


def _kalshi_tif(tif: str) -> str:
    if tif == "gtc":
        return "good_till_canceled"
    return "immediate_or_cancel"


def _gemini_tif(tif: str) -> str:
    if tif == "gtc":
        return "good-till-cancel"
    return "immediate-or-cancel"


def _polymarket_tif(tif: str) -> str:
    if tif == "gtc":
        return "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    return "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"


def kalshi_order_body(ticker: str, outcome: str, pay: Decimal, client_order_id: str, tif: str = "ioc") -> dict:
    """V2 event order. bid buys Yes. ask sells Yes, which buys No at 1 - price."""
    if outcome == "yes":
        price = pay.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
        side = "bid"
    elif outcome == "no":
        price = (ONE - pay).quantize(KALSHI_TICK, rounding=ROUND_CEILING)
        side = "ask"
    else:
        raise ValueError("outcome")
    return {
        "ticker": ticker,
        "client_order_id": client_order_id,
        "side": side,
        "count": "1.00",
        "price": format(price, "f"),
        "time_in_force": _kalshi_tif(tif),
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
    }


def gemini_order_payload(symbol: str, outcome: str, pay: Decimal, tif: str = "ioc") -> dict:
    price = pay.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
    return {
        "symbol": symbol,
        "orderType": "limit",
        "side": "buy",
        "quantity": "1",
        "price": format(price, "f"),
        "outcome": outcome,
        "timeInForce": _gemini_tif(tif),
    }


def polymarket_api_price(intent: str, pay: Decimal) -> Decimal:
    """Long-side price. A short buy at `pay` is sent as 1 - pay, rounded so we do not pay more."""
    if intent in ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_SELL_LONG"):
        return pay.quantize(POLY_TICK, rounding=ROUND_DOWN)
    if intent in ("ORDER_INTENT_BUY_SHORT", "ORDER_INTENT_SELL_SHORT"):
        return (ONE - pay).quantize(POLY_TICK, rounding=ROUND_CEILING)
    raise ValueError("intent")


def polymarket_order_body(slug: str, intent: str, api_price: Decimal, tif: str = "ioc") -> dict:
    # GTC must rest on the book — sync execution would treat a partial like IOC.
    sync = tif != "gtc"
    return {
        "marketSlug": slug,
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": format(api_price, "f"), "currency": "USD"},
        "quantity": 1,
        "tif": _polymarket_tif(tif),
        "intent": intent,
        "participateDontInitiate": False,
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        "synchronousExecution": sync,
        "maxBlockTime": "3" if sync else "0",
    }


def _opposite_outcome(outcome: str) -> str:
    if outcome == "yes":
        return "no"
    if outcome == "no":
        return "yes"
    raise ValueError("outcome")


def _poly_sell_intent(buy_intent: str) -> str | None:
    mapping = {
        "ORDER_INTENT_BUY_LONG": "ORDER_INTENT_SELL_LONG",
        "ORDER_INTENT_BUY_SHORT": "ORDER_INTENT_SELL_SHORT",
    }
    return mapping.get(str(buy_intent or ""))


def _poly_flip_intent(intent: str) -> str | None:
    mapping = {
        "ORDER_INTENT_BUY_LONG": "ORDER_INTENT_BUY_SHORT",
        "ORDER_INTENT_BUY_SHORT": "ORDER_INTENT_BUY_LONG",
        "ORDER_INTENT_SELL_LONG": "ORDER_INTENT_SELL_SHORT",
        "ORDER_INTENT_SELL_SHORT": "ORDER_INTENT_SELL_LONG",
    }
    return mapping.get(str(intent or ""))


def build_buy_leg_spec(
    *,
    venue: str,
    instrument: str,
    outcome: str,
    pay: Decimal,
    tif: str = "ioc",
    intent: str | None = None,
) -> dict | None:
    """Build a buy-leg order spec from watch/raw fields (not a candidate row)."""
    venue = str(venue or "").lower()
    outcome = str(outcome or "").lower()
    if pay is None or pay <= 0 or pay >= 1:
        return None
    if venue == "kalshi":
        if not instrument:
            return None
        body = kalshi_order_body(instrument, outcome, pay, str(uuid.uuid4()), tif=tif)
        return {
            "venue": "kalshi",
            "instrument": instrument,
            "outcome": outcome,
            "pay": format(pay, "f"),
            "limit": body["price"],
            "tif": tif,
            "body": body,
        }
    if venue == "gemini":
        if not instrument:
            return None
        payload = gemini_order_payload(instrument, outcome, pay, tif=tif)
        return {
            "venue": "gemini",
            "instrument": instrument,
            "outcome": outcome,
            "pay": format(pay, "f"),
            "limit": payload["price"],
            "tif": tif,
            "body": payload,
        }
    if venue == "polymarket":
        if not instrument or not intent:
            return None
        try:
            api_price = polymarket_api_price(intent, pay)
        except ValueError:
            return None
        if api_price < Decimal("0.01") or api_price > Decimal("0.99"):
            return None
        body = polymarket_order_body(instrument, intent, api_price, tif=tif)
        return {
            "venue": "polymarket",
            "instrument": instrument,
            "outcome": outcome,
            "pay": format(pay, "f"),
            "limit": body["price"]["value"],
            "tif": tif,
            "body": body,
        }
    return None


def build_flatten_spec(
    *,
    venue: str,
    instrument: str,
    held_side: str,
    opposite_pay: Decimal | None = None,
    held_intent: str | None = None,
    tif: str = "ioc",
) -> dict | None:
    """Same-shop IOC buy of the opposite outcome (flatten_filled_leg shape)."""
    pay = opposite_pay if opposite_pay is not None else MARKET_BUY_CEILING
    opp = _opposite_outcome(str(held_side or "").lower())
    intent = _poly_flip_intent(held_intent) if str(venue or "").lower() == "polymarket" else None
    return build_buy_leg_spec(
        venue=venue,
        instrument=instrument,
        outcome=opp,
        pay=pay,
        tif=tif,
        intent=intent,
    )


def build_market_sell_spec(
    *,
    venue: str,
    instrument: str,
    held_side: str,
    held_intent: str | None = None,
    tif: str = "ioc",
) -> dict | None:
    """Aggressive IOC to dump the held ticket (hit bids / lift asks)."""
    venue = str(venue or "").lower()
    held_side = str(held_side or "").lower()
    if not instrument or held_side not in ("yes", "no"):
        return None
    if venue == "kalshi":
        # Held Yes → ask low (sell Yes). Held No → bid high (buy Yes closes No).
        if held_side == "yes":
            price = MARKET_SELL_FLOOR.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
            side = "ask"
            pay = MARKET_SELL_FLOOR
        else:
            price = MARKET_BUY_CEILING.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
            side = "bid"
            pay = MARKET_BUY_CEILING
        body = {
            "ticker": instrument,
            "client_order_id": str(uuid.uuid4()),
            "side": side,
            "count": "1.00",
            "price": format(price, "f"),
            "time_in_force": _kalshi_tif(tif),
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": False,
        }
        return {
            "venue": "kalshi",
            "instrument": instrument,
            "outcome": held_side,
            "pay": format(pay, "f"),
            "limit": body["price"],
            "tif": tif,
            "body": body,
            "exit": "market_sell",
        }
    if venue == "gemini":
        price = MARKET_SELL_FLOOR.quantize(KALSHI_TICK, rounding=ROUND_DOWN)
        body = {
            "symbol": instrument,
            "orderType": "limit",
            "side": "sell",
            "quantity": "1",
            "price": format(price, "f"),
            "outcome": held_side,
            "timeInForce": _gemini_tif(tif),
        }
        return {
            "venue": "gemini",
            "instrument": instrument,
            "outcome": held_side,
            "pay": format(MARKET_SELL_FLOOR, "f"),
            "limit": body["price"],
            "tif": tif,
            "body": body,
            "exit": "market_sell",
        }
    if venue == "polymarket":
        sell_intent = _poly_sell_intent(held_intent or "")
        if not sell_intent:
            return None
        # Sell long hits bids at floor; sell short lifts asks near ceiling of long price.
        cash_pay = MARKET_SELL_FLOOR if sell_intent == "ORDER_INTENT_SELL_LONG" else MARKET_BUY_CEILING
        try:
            api_price = polymarket_api_price(sell_intent, cash_pay)
        except ValueError:
            return None
        body = polymarket_order_body(instrument, sell_intent, api_price, tif=tif)
        return {
            "venue": "polymarket",
            "instrument": instrument,
            "outcome": held_side,
            "pay": format(cash_pay, "f"),
            "limit": body["price"]["value"],
            "tif": tif,
            "body": body,
            "exit": "market_sell",
        }
    return None


def fee_kalshi_style(pay: Decimal) -> Decimal:
    """Kalshi-style 0.07 × p × (1 − p). Used for BE math when venue fee is unknown."""
    raw = Decimal("0.07") * pay * (ONE - pay)
    if raw < 0:
        raw = Decimal("0")
    return raw.quantize(CENT, rounding=ROUND_HALF_UP)


def break_even_miss_pay(filled_pay: Decimal, filled_fee: Decimal | None = None) -> Decimal:
    """Highest miss pay that still locks at ≥ $0 after fees (Kalshi-style fee on miss)."""
    fee1 = filled_fee if filled_fee is not None else fee_kalshi_style(filled_pay)
    target = ONE - filled_pay - fee1
    lo, hi = Decimal("0"), ONE
    for _ in range(80):
        mid = (lo + hi) / 2
        if mid + fee_kalshi_style(mid) < target:
            lo = mid
        else:
            hi = mid
    return hi.quantize(CENT, rounding=ROUND_DOWN)


def one_leg_deadline_action(
    *,
    held_pay: Decimal,
    gtc_filled: bool,
    waited_sec: float,
    be_complete_available: bool | None = None,
    wait_sec: int = ONE_LEG_GTC_WAIT_SEC,
    cheap_max: Decimal = CHEAP_EXIT_MAX,
) -> str:
    """Pure policy after a second-leg GTC is working.

    Returns one of:
      keep_waiting | done_gtc_filled | exit_cheap | try_be_complete | hold_to_settle
    """
    if gtc_filled:
        return "done_gtc_filled"
    if waited_sec < wait_sec:
        return "keep_waiting"
    if held_pay <= cheap_max:
        return "exit_cheap"
    if be_complete_available is True:
        return "try_be_complete"
    if be_complete_available is False:
        return "hold_to_settle"
    return "try_be_complete"


def choose_cheap_exit(*, flatten_all_in: Decimal | None, market_sell_proceeds: Decimal | None, held_pay: Decimal) -> str:
    """Pick the less-bad ≤25¢ exit. flatten = buy opposite; market_sell = sell the held ticket."""
    flatten_loss = None if flatten_all_in is None else (held_pay + flatten_all_in - ONE)
    sell_loss = None if market_sell_proceeds is None else (held_pay - market_sell_proceeds)
    if flatten_loss is None and sell_loss is None:
        return "market_sell"
    if flatten_loss is None:
        return "market_sell"
    if sell_loss is None:
        return "flatten"
    return "flatten" if flatten_loss <= sell_loss else "market_sell"


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def filled_contracts(payload) -> Decimal:
    """Contracts filled, from the fields the three venues return. Zero when unknown."""
    if not isinstance(payload, (dict, list)):
        return Decimal("0")
    qty_keys = ("fill_count", "filledQuantity", "filled_quantity", "cumQuantity", "executedQuantity", "quantityFilled")
    best = Decimal("0")
    for node in _walk(payload):
        status = str(node.get("status") or node.get("state") or node.get("orderState") or "").lower()
        if status in ("filled", "executed", "complete", "completed"):
            best = max(best, SIZE)
        for key in qty_keys:
            number = _dec(node.get(key))
            if number is not None and number > best:
                best = number
    return best


def order_still_open(payload) -> bool:
    if not isinstance(payload, (dict, list)):
        return False
    for node in _walk(payload):
        status = str(node.get("status") or node.get("state") or node.get("orderState") or "").lower()
        remaining = _dec(node.get("remaining_count") or node.get("remainingQuantity") or node.get("leavesQuantity"))
        if status in ("open", "resting", "new", "accepted", "pending"):
            return True
        if remaining is not None and remaining > 0 and status not in ("canceled", "cancelled", "expired", "rejected"):
            return True
    return False


def bet_blocked(rows: list[dict], bet_key: str, pid_alive) -> bool:
    """True when this bet is open, filled, or claimed by a process that is still alive."""
    phase = "clear"
    claim_pid = None
    for row in rows:
        if row.get("bet_key") != bet_key:
            continue
        event = row.get("event")
        if event == "claim":
            if phase != "position":
                phase = "working"
                claim_pid = row.get("pid")
        elif event == "sent":
            if phase != "position":
                phase = "sent"
        elif event in ("filled", "one_leg"):
            phase = "position"
        elif event == "both_unfilled" and phase != "position":
            phase = "clear"
        elif event == "preflight_skip" and phase == "working":
            phase = "clear"
    if phase in ("position", "sent"):
        return True
    if phase == "working":
        try:
            return bool(claim_pid) and bool(pid_alive(int(claim_pid)))
        except (TypeError, ValueError):
            return True
    return False


def _read_orders() -> list[dict]:
    if not ORDERS.exists():
        return []
    rows = []
    for line in ORDERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _append_unlocked(row: dict) -> None:
    ORDERS.parent.mkdir(parents=True, exist_ok=True)
    with ORDERS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _append(row: dict) -> None:
    with venue_pace.FileLock(ORDER_LOCK):
        _append_unlocked(row)


def _kalshi_ticker_for_outcome(cand: dict, outcome: str) -> str:
    """Per-leg Kalshi instrument. Yes and No must not silently share a false pair."""
    outcome = str(outcome or "").lower()
    specific = str(
        cand.get(f"kalshi_{outcome}_ticker")
        or cand.get(f"{outcome}_kalshi_ticker")
        or cand.get(f"{outcome}_ticker")
        or cand.get(f"{outcome}_ident")
        or ""
    ).strip()
    if specific:
        return specific
    return str(cand.get("kalshi_ticker") or "").strip()


def _leg_spec(cand: dict, outcome: str, tif: str = "ioc") -> dict | None:
    venue = str(cand.get(f"{outcome}_venue") or "").lower()
    pay = _dec(cand.get(f"{outcome}_price"))
    if pay is None or pay <= 0 or pay >= 1:
        return None
    market_type = str(cand.get("market_type") or "")
    if venue == "kalshi":
        ticker = _kalshi_ticker_for_outcome(cand, outcome)
        if not ticker:
            return None
        body = kalshi_order_body(ticker, outcome, pay, str(uuid.uuid4()), tif=tif)
        return {
            "venue": "kalshi",
            "instrument": ticker,
            "outcome": outcome,
            "pay": format(pay, "f"),
            "limit": body["price"],
            "tif": tif,
            "body": body,
            "market_type": market_type,
        }
    if venue == "gemini":
        symbol = str(cand.get("gemini_symbol") or "")
        if not symbol:
            return None
        payload = gemini_order_payload(symbol, outcome, pay, tif=tif)
        return {
            "venue": "gemini",
            "instrument": symbol,
            "outcome": outcome,
            "pay": format(pay, "f"),
            "limit": payload["price"],
            "tif": tif,
            "body": payload,
            "market_type": market_type,
        }
    if venue == "polymarket":
        slug = str(cand.get("polymarket_slug") or "")
        intent = str(cand.get("polymarket_intent") or "")
        if not slug or not intent:
            return None
        try:
            api_price = polymarket_api_price(intent, pay)
        except ValueError:
            return None
        if api_price < Decimal("0.01") or api_price > Decimal("0.99"):
            return None
        body = polymarket_order_body(slug, intent, api_price, tif=tif)
        return {
            "venue": "polymarket",
            "instrument": slug,
            "outcome": outcome,
            "pay": format(pay, "f"),
            "limit": body["price"]["value"],
            "tif": tif,
            "body": body,
            "market_type": market_type,
        }
    return None


def _with_tif(spec: dict, tif: str) -> dict:
    """Rebuild an existing leg spec at the same pay/outcome with a new TIF."""
    venue = spec["venue"]
    outcome = spec["outcome"]
    pay = _dec(spec.get("pay"))
    if pay is None:
        raise ValueError("pay")
    if venue == "kalshi":
        body = kalshi_order_body(spec["instrument"], outcome, pay, str(uuid.uuid4()), tif=tif)
        limit = body["price"]
    elif venue == "gemini":
        body = gemini_order_payload(spec["instrument"], outcome, pay, tif=tif)
        limit = body["price"]
    elif venue == "polymarket":
        intent = str((spec.get("body") or {}).get("intent") or "")
        api_price = polymarket_api_price(intent, pay)
        body = polymarket_order_body(spec["instrument"], intent, api_price, tif=tif)
        limit = body["price"]["value"]
    else:
        raise ValueError("venue")
    out = dict(spec)
    out["body"] = body
    out["limit"] = limit
    out["tif"] = tif
    return out


def _capability_ok(venue: str, now: float) -> tuple[bool, str]:
    cached = _capability.get(venue)
    if cached and now - cached[0] < 300:
        return cached[1], cached[2]
    ok, reason = _probe(venue)
    _capability[venue] = (now, ok, reason)
    return ok, reason


def _probe(venue: str) -> tuple[bool, str]:
    try:
        if venue == "kalshi":
            status, usd = kalshi_private.balance_usd()
            if status == 200 and usd is not None:
                return True, f"kalshi balance {usd}"
            return False, f"kalshi balance http {status}"
        if venue == "gemini":
            status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "GET")
            if status != 200:
                status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "POST")
            if status != 200:
                return False, f"gemini terms http {status} {_public_note(body)}"
            data = json.loads(body)
            if data.get("hasAcceptedLatest") is True:
                return True, "gemini terms accepted"
            return False, "gemini prediction-market terms are not accepted"
        if venue == "polymarket":
            status, body = polymarket_us_live.signed_json("GET", "/v1/account/balances")
            if status != 200:
                return False, f"polymarket balance http {status} {_public_note(body)}"
            return True, "polymarket balance read"
    except Exception as exc:
        return False, type(exc).__name__
    return False, "unknown venue"


def _affordable(spec: dict, balances: dict[str, Decimal]) -> bool:
    cash = balances.get(spec["venue"])
    pay = _dec(spec["pay"])
    if cash is None or pay is None:
        return False
    return cash >= pay


def _read_balances() -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    try:
        status, usd = kalshi_private.balance_usd()
        if status == 200 and usd is not None:
            out["kalshi"] = Decimal(usd)
    except Exception:
        pass
    try:
        status, body = gemini_private.private_call("/v1/balances", None, "POST")
        if status == 200:
            data = json.loads(body)
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, dict) and str(row.get("currency") or "").upper() == "USD":
                        number = _dec(row.get("available"))
                        if number is not None:
                            out["gemini"] = number
    except Exception:
        pass
    try:
        status, body = polymarket_us_live.signed_json("GET", "/v1/account/balances")
        if status == 200:
            data = json.loads(body)
            for row in data.get("balances") or []:
                if isinstance(row, dict) and str(row.get("currency") or "USD").upper() == "USD":
                    number = _dec(row.get("buyingPower"))
                    if number is not None:
                        out["polymarket"] = number
    except Exception:
        pass
    return out


def _preview(spec: dict) -> tuple[bool, str]:
    if not orders_enabled():
        return False, "placing orders is off"
    if spec["venue"] != "polymarket":
        return True, "no preview endpoint"
    status, body = polymarket_us_live.signed_json("POST", "/v1/order/preview", {"request": spec["body"]})
    if status == 200:
        return True, "preview 200"
    return False, f"preview http {status} {_public_note(body)}"


def _send(spec: dict) -> tuple[int, dict | None, str]:
    if not orders_enabled():
        return 0, None, "placing orders is off"
    if spec["venue"] == "kalshi":
        status, body = kalshi_private.signed_call("POST", "/trade-api/v2/portfolio/events/orders", spec["body"])
    elif spec["venue"] == "gemini":
        status, body = gemini_private.private_call("/v1/prediction-markets/order", spec["body"], "POST")
    elif spec["venue"] == "polymarket":
        status, body = polymarket_us_live.signed_json("POST", "/v1/orders", spec["body"])
    else:
        return 0, None, "unknown venue"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    return status, payload if isinstance(payload, (dict, list)) else None, _public_note(body)


def _order_id(payload) -> str:
    if not isinstance(payload, (dict, list)):
        return ""
    for node in _walk(payload):
        for key in ("order_id", "orderId", "id"):
            value = node.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _cancel(spec: dict, payload) -> tuple[int, str]:
    if not orders_enabled():
        return 0, "placing orders is off"
    order_id = _order_id(payload)
    if not order_id:
        return 0, "no order id"
    if spec["venue"] == "kalshi":
        status, body = kalshi_private.signed_call(
            "DELETE",
            f"/trade-api/v2/portfolio/events/orders/{order_id}",
            query={"market_ticker": spec["instrument"]},
        )
        return status, _public_note(body)
    if spec["venue"] == "gemini":
        try:
            gid = int(order_id)
        except ValueError:
            return 0, "gemini order id was not an integer"
        status, body = gemini_private.private_call("/v1/prediction-markets/order/cancel", {"orderId": gid}, "POST")
        return status, _public_note(body)
    if spec["venue"] == "polymarket":
        status, body = polymarket_us_live.signed_json(
            "POST",
            f"/v1/order/{order_id}/cancel",
            {"marketSlug": spec["instrument"]},
        )
        return status, _public_note(body)
    return 0, "unknown venue"


def _log_sent(log, spec: dict, status: int) -> None:
    log(
        f"order sent venue={spec['venue']} instrument={spec['instrument']} side={spec['outcome']} "
        f"limit={spec['limit']} size=1 http={status}"
    )


def _log_one_leg(log, spec: dict) -> None:
    log(
        f"ONE LEG venue={spec['venue']} contract={spec['instrument']} side={spec['outcome']} "
        f"size=1 price={spec['pay']}"
    )


def _execution_price(payload, outcome: str) -> str:
    """Fill price from the venue response, when it sent one. Empty when it did not."""
    if not isinstance(payload, (dict, list)):
        return ""
    preferred = "yes_price_dollars" if outcome == "yes" else "no_price_dollars"
    found = ""
    for node in _walk(payload):
        if node.get(preferred) not in (None, ""):
            found = str(node.get(preferred))
        elif not found:
            for key in ("avg_price", "averagePrice", "filledPrice"):
                if node.get(key) not in (None, ""):
                    found = str(node.get(key))
                    break
    return found


def one_leg_message(
    title: str,
    first: dict,
    first_payload,
    second: dict,
    status2: int,
    note2: str,
    second_payload,
    *,
    gtc_resting: bool = False,
) -> str:
    """Phone and log text. Separate from the under-$1 opportunity ping."""
    fill = _execution_price(first_payload, str(first.get("outcome") or ""))
    price = f"fill {fill}" if fill else f"limit {first.get('pay')}"
    order_id = _order_id(first_payload)
    order_bit = f" order {order_id}" if order_id else ""
    other_id = _order_id(second_payload)
    other_bit = f" order {other_id}" if other_id else ""
    if gtc_resting:
        trailing = (
            f"Second leg GTC resting at L={second.get('pay')} for up to "
            f"{ONE_LEG_GTC_WAIT_SEC}s (then ≤{CHEAP_EXIT_MAX} exit / else BE-complete or hold)."
        )
    else:
        trailing = "Second leg GTC did not rest; applying deadline exit rules."
    return (
        "one leg filled, other leg did not. "
        f"{title}. Filled {first.get('venue')} {first.get('outcome')} {first.get('instrument')} "
        f"{price} size 1{order_bit}. "
        f"Other leg {second.get('venue')} {second.get('outcome')} {second.get('instrument')} "
        f"http {status2} {note2}{other_bit}. {trailing}"
    )


def alert_one_leg(
    log,
    title: str,
    first: dict,
    first_payload,
    second: dict,
    status2: int,
    note2: str,
    second_payload,
    *,
    gtc_resting: bool = False,
) -> None:
    """Supervisor log, a durable HTML note, and one phone attempt. Does not send an order."""
    message = one_leg_message(
        title, first, first_payload, second, status2, note2, second_payload, gtc_resting=gtc_resting
    )
    log(message)
    row = {
        "seen_at": "",
        "game": title,
        "filled_venue": first.get("venue"),
        "contract": first.get("instrument"),
        "side": first.get("outcome"),
        "price": _execution_price(first_payload, str(first.get("outcome") or "")) or str(first.get("pay") or ""),
        "order_id": _order_id(first_payload),
        "other_venue": second.get("venue"),
        "other_contract": second.get("instrument"),
        "other_side": second.get("outcome"),
        "other_result": f"http {status2} {note2}",
        "other_order_id": _order_id(second_payload),
        "note": (
            "one leg filled; second-leg GTC resting at L"
            if gtc_resting
            else "one leg filled; second-leg GTC did not rest"
        ),
        "policy": "gtc_second_leg_180s_cheap_exit_or_hold",
    }
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        row["seen_at"] = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    except Exception:
        row["seen_at"] = ""
    try:
        import stream_health

        stream_health.append_one_leg_alert(row)
    except Exception as exc:
        log(f"one leg note failed {type(exc).__name__}")
    _phone_one_leg(log, message)


def _phone_one_leg(log, message: str) -> None:
    """One ntfy attempt. The helper retries a timeout. This does not place an order."""
    try:
        import ntfy_job_done

        url = f"{ntfy_job_done.NTFY_BASE}/{ntfy_job_done.PAUL_TOPIC}"
        status = ntfy_job_done._post(url, message, "One leg filled")
    except Exception as exc:
        log(f"one leg phone alert failed {type(exc).__name__}")
        return
    if status and 200 <= status < 300:
        log(f"one leg phone alert http {status}")
    else:
        log(f"one leg phone alert failed http {status or 'timeout'}")


_orders_off_logged: set[str] = set()


def _note_orders_off(log, key: str) -> None:
    """One skip line per bet. Does not call a venue."""
    if key in _orders_off_logged:
        return
    with venue_pace.FileLock(ORDER_LOCK):
        already = any(
            row.get("bet_key") == key and row.get("event") == "orders_off"
            for row in _read_orders()
        )
        if already:
            _orders_off_logged.add(key)
            return
        _append_unlocked({
            "event": "orders_off",
            "bet_key": key,
            "note": "placing orders is off",
        })
    _orders_off_logged.add(key)
    log("order skipped; placing orders is off")


def execute_locks(scan, sport: str, title: str, game: dict, result: dict, fresh: list[dict], log) -> None:
    """Send qualifying pairs. Pairs under $1 but above $0.95 stay alerts only."""
    if result.get("closed"):
        return
    candidates = [row for row in (result.get("candidates") or []) if isinstance(row, dict)]
    ready = []
    for cand in candidates:
        ok, reason = qualifies(scan, cand, title, game if isinstance(game, dict) else {})
        if ok:
            ready.append((cand, reason))
    if not ready:
        return
    if not lock_system_on():
        why = "Lock gap system is off"
        log(f"order skip {title}; {why}")
        record_send_skip(why, title)
        return
    open_now = open_lock_keys()
    if lock_slots_full(open_now):
        why = lock_open_denial(len(open_now))
        log(f"order skip {title}; {why}")
        record_send_skip(why, title)
        return
    if not orders_enabled():
        for cand, _reason in ready:
            key = scan._trade_bet_key(sport, game, cand)
            _note_orders_off(log, key)
        return
    import time
    now = time.time()
    for cand, reason in ready:
        key = scan._trade_bet_key(sport, game, cand)
        built: list[dict] = []
        for outcome in ("yes", "no"):
            spec = _leg_spec(cand, outcome)
            if spec is None:
                log(f"order skip {title} {reason} missing order fields for {outcome}")
                built = []
                break
            built.append(spec)
        if len(built) != 2:
            continue
        hard, easy = _pick_hard_leg(built[0], built[1])
        legs = [hard, easy]
        venues = [leg["venue"] for leg in legs]
        blocked_reason = ""
        for venue in venues:
            ok, why = _capability_ok(venue, now)
            if not ok:
                blocked_reason = why
                break
        if blocked_reason:
            log(f"order skip both legs {title} {blocked_reason}")
            continue
        balances = _read_balances()
        balance_note = " ".join(f"{name}={_money(amount)}" for name, amount in sorted(balances.items()))
        log(f"balances before send {balance_note or 'none parsed'}")
        if any(venue not in balances for venue in venues) or any(not _affordable(leg, balances) for leg in legs):
            log(f"order skip both legs {title} balance does not cover 1 contract")
            continue
        preview_reason = ""
        for leg in legs:
            ok, why = _preview(leg)
            if not ok:
                preview_reason = why
                break
        if preview_reason:
            log(f"order skip both legs {title} {preview_reason}")
            continue
        with venue_pace.FileLock(ORDER_LOCK):
            if bet_blocked(_read_orders(), key, _pid_alive):
                log(f"order skip duplicate {title} {cand.get('market_type')} {cand.get('side')} {cand.get('number')}")
                continue
            _append_unlocked({
                "event": "claim",
                "bet_key": key,
                "sport": sport,
                "game": title,
                "market_type": cand.get("market_type"),
                "side": cand.get("side"),
                "number": cand.get("number"),
                "net": reason,
                "pid": os.getpid(),
            })
        _send_pair(log, key, title, legs)


def _append_watch(row: dict) -> None:
    ONE_LEG_WATCH.parent.mkdir(parents=True, exist_ok=True)
    with venue_pace.FileLock(ORDER_LOCK):
        with ONE_LEG_WATCH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _read_watch_rows() -> list[dict]:
    if not ONE_LEG_WATCH.exists():
        return []
    rows = []
    for line in ONE_LEG_WATCH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def open_second_leg_gtc_watches(rows: list[dict] | None = None) -> list[dict]:
    """Latest open GTC second-leg watches (not filled/cancelled/exited/held)."""
    latest: dict[str, dict] = {}
    for row in rows if rows is not None else _read_watch_rows():
        key = str(row.get("bet_key") or "")
        if not key:
            continue
        event = row.get("event")
        if event == "second_leg_gtc_open":
            latest[key] = row
        elif event in {
            "second_leg_gtc_filled",
            "second_leg_gtc_cancelled",
            "one_leg_exit_cheap",
            "one_leg_be_complete",
            "one_leg_hold_to_settle",
            "second_leg_gtc_resolve_cancel",
        }:
            latest.pop(key, None)
    return list(latest.values())


def cancel_second_leg_gtc_on_resolve(log, *, bet_key: str | None = None, reason: str = "market_resolved") -> int:
    """Cancel resting second-leg GTCs when the market resolves. Returns cancels attempted."""
    open_rows = open_second_leg_gtc_watches()
    n = 0
    for row in open_rows:
        if bet_key and row.get("bet_key") != bet_key:
            continue
        spec = {
            "venue": row.get("second_venue"),
            "instrument": row.get("second_instrument"),
        }
        payload = {"order_id": row.get("second_order_id")}
        if not spec["venue"] or not row.get("second_order_id"):
            continue
        status, note = _cancel(spec, payload)
        n += 1
        log(
            f"second-leg GTC resolve-cancel bet={row.get('bet_key')} "
            f"venue={spec['venue']} http={status} {note} reason={reason}"
        )
        _append_watch({
            "event": "second_leg_gtc_resolve_cancel",
            "bet_key": row.get("bet_key"),
            "reason": reason,
            "http_status": status,
            "note": note,
            "ts": time.time(),
        })
        _append({
            "event": "second_leg_gtc_resolve_cancel",
            "bet_key": row.get("bet_key"),
            "reason": reason,
            "http_status": status,
            "note": note,
        })
    return n


def _send_watch_exit(log, *, key: str, kind: str, spec: dict | None) -> tuple[int, dict | None, str]:
    """Send a cheap-exit / BE-complete IOC when orders are on. Returns (http, payload, note)."""
    if spec is None:
        log(f"one-leg {kind} bet={key} skip: could not build order spec")
        return 0, None, "no order spec"
    status, payload, note = _send(spec)
    _log_sent(log, spec, status)
    _append({
        "event": f"one_leg_{kind}_sent",
        "bet_key": key,
        "venue": spec.get("venue"),
        "instrument": spec.get("instrument"),
        "side": spec.get("outcome"),
        "limit_price": spec.get("limit"),
        "tif": spec.get("tif") or "ioc",
        "size": "1",
        "http_status": status,
        "note": note,
        "order_id": _order_id(payload),
        "exit": spec.get("exit") or kind,
    })
    return status, payload, note


def tick_one_leg_gtc_watches(
    log,
    *,
    now: float | None = None,
    be_ask: dict[str, Decimal] | None = None,
    flatten_ask: dict[str, Decimal] | None = None,
    market_sell_bid: dict[str, Decimal] | None = None,
) -> list[str]:
    """Advance open second-leg GTC watches past the 180s deadline.

    be_ask: optional map bet_key → current complementary ask (cash pay) for BE-complete.
    flatten_ask / market_sell_bid: optional cash quotes so choose_cheap_exit can pick
    the tighter path; when missing, prefer market_sell (policy default without quotes).

    When orders_enabled(): cancel the resting GTC, then actually send flatten /
    market-sell / BE-complete IOC. When off: cancel is skipped and decisions are
    logged+recorded only.
    """
    now = time.time() if now is None else now
    enabled = orders_enabled()
    actions: list[str] = []
    for row in open_second_leg_gtc_watches():
        opened_raw = row.get("opened_at")
        opened = float(now if opened_raw is None else opened_raw)
        waited = now - opened
        held = _dec(row.get("held_pay")) or Decimal("0")
        miss_l = _dec(row.get("miss_limit_l"))
        be = _dec(row.get("break_even_pay"))
        if be is None and held > 0:
            be = break_even_miss_pay(held)
        key = str(row.get("bet_key") or "")
        ask = None if be_ask is None else be_ask.get(key)
        flat_q = None if flatten_ask is None else flatten_ask.get(key)
        sell_q = None if market_sell_bid is None else market_sell_bid.get(key)
        be_available = None
        if ask is not None and be is not None:
            be_available = ask <= (be + BE_COMPLETE_SLIP)
        action = one_leg_deadline_action(
            held_pay=held,
            gtc_filled=False,
            waited_sec=waited,
            be_complete_available=be_available,
        )
        if action == "keep_waiting":
            continue
        # Deadline: cancel resting GTC first (no-op HTTP when orders are off).
        cancel_spec = {
            "venue": row.get("second_venue"),
            "instrument": row.get("second_instrument"),
        }
        payload = {"order_id": row.get("second_order_id")}
        if row.get("second_order_id") and cancel_spec["venue"]:
            status, note = _cancel(cancel_spec, payload)
            log(
                f"second-leg GTC deadline-cancel bet={key} venue={cancel_spec['venue']} "
                f"http={status} {note} action={action} orders_enabled={enabled}"
            )
            _append_watch({
                "event": "second_leg_gtc_cancelled",
                "bet_key": key,
                "http_status": status,
                "note": note,
                "action": action,
                "orders_enabled": enabled,
                "ts": now,
            })
        if action == "exit_cheap":
            exit_kind = choose_cheap_exit(
                flatten_all_in=flat_q,
                market_sell_proceeds=sell_q,
                held_pay=held,
            )
            log(
                f"one-leg cheap exit bet={key} held={held} prefer={exit_kind} "
                f"orders_enabled={enabled}"
            )
            send_status, send_note = 0, "orders off"
            if enabled:
                held_intent = row.get("held_intent")
                if exit_kind == "flatten":
                    exit_spec = build_flatten_spec(
                        venue=str(row.get("held_venue") or ""),
                        instrument=str(row.get("held_instrument") or ""),
                        held_side=str(row.get("held_side") or ""),
                        opposite_pay=flat_q if flat_q is not None else MARKET_BUY_CEILING,
                        held_intent=held_intent,
                    )
                else:
                    exit_spec = build_market_sell_spec(
                        venue=str(row.get("held_venue") or ""),
                        instrument=str(row.get("held_instrument") or ""),
                        held_side=str(row.get("held_side") or ""),
                        held_intent=held_intent,
                    )
                send_status, _payload, send_note = _send_watch_exit(
                    log, key=key, kind=f"exit_cheap_{exit_kind}", spec=exit_spec
                )
            _append_watch({
                "event": "one_leg_exit_cheap",
                "bet_key": key,
                "held_pay": str(held),
                "prefer": exit_kind,
                "orders_enabled": enabled,
                "http_status": send_status,
                "note": send_note,
                "ts": now,
            })
            _append({
                "event": "one_leg_exit_cheap",
                "bet_key": key,
                "held_pay": str(held),
                "prefer": exit_kind,
                "orders_enabled": enabled,
                "http_status": send_status,
                "note": send_note,
            })
            actions.append(f"{key}:exit_cheap:{exit_kind}")
            continue
        if action == "try_be_complete":
            cap = (be + BE_COMPLETE_SLIP) if be is not None else miss_l
            if ask is not None and cap is not None:
                cap = min(cap, ask)
            log(
                f"one-leg BE-complete attempt bet={key} held={held} "
                f"be={be} cap={cap} ask={ask} orders_enabled={enabled}"
            )
            _append_watch({
                "event": "one_leg_be_complete",
                "bet_key": key,
                "held_pay": str(held),
                "break_even_pay": str(be) if be is not None else None,
                "cap": str(cap) if cap is not None else None,
                "ask": str(ask) if ask is not None else None,
                "orders_enabled": enabled,
                "ts": now,
            })
            if be_available is False:
                _append_watch({
                    "event": "one_leg_hold_to_settle",
                    "bet_key": key,
                    "held_pay": str(held),
                    "reason": "be_complete_unavailable",
                    "ts": now,
                })
                _append({
                    "event": "one_leg_hold_to_settle",
                    "bet_key": key,
                    "held_pay": str(held),
                    "reason": "be_complete_unavailable",
                })
                actions.append(f"{key}:hold_to_settle")
            elif not enabled:
                _append_watch({
                    "event": "one_leg_hold_to_settle",
                    "bet_key": key,
                    "held_pay": str(held),
                    "reason": "orders_off_recorded_be_intent",
                    "ts": now,
                })
                _append({
                    "event": "one_leg_hold_to_settle",
                    "bet_key": key,
                    "held_pay": str(held),
                    "reason": "orders_off_recorded_be_intent",
                })
                actions.append(f"{key}:hold_to_settle")
            else:
                if cap is None:
                    actions.append(f"{key}:hold_to_settle")
                    _append_watch({
                        "event": "one_leg_hold_to_settle",
                        "bet_key": key,
                        "held_pay": str(held),
                        "reason": "no_be_cap",
                        "ts": now,
                    })
                else:
                    be_spec = build_buy_leg_spec(
                        venue=str(row.get("second_venue") or ""),
                        instrument=str(row.get("second_instrument") or ""),
                        outcome=str(row.get("second_side") or ""),
                        pay=cap,
                        tif="ioc",
                        intent=row.get("second_intent"),
                    )
                    send_status, payload, send_note = _send_watch_exit(
                        log, key=key, kind="be_complete", spec=be_spec
                    )
                    filled = filled_contracts(payload) if send_status in (200, 201) else Decimal("0")
                    if be_spec is None or filled < SIZE:
                        _append_watch({
                            "event": "one_leg_hold_to_settle",
                            "bet_key": key,
                            "held_pay": str(held),
                            "reason": "be_complete_miss_or_error",
                            "http_status": send_status,
                            "note": send_note,
                            "ts": now,
                        })
                        _append({
                            "event": "one_leg_hold_to_settle",
                            "bet_key": key,
                            "held_pay": str(held),
                            "reason": "be_complete_miss_or_error",
                            "http_status": send_status,
                            "note": send_note,
                        })
                        actions.append(f"{key}:hold_to_settle")
                    else:
                        _append({
                            "event": "filled",
                            "bet_key": key,
                            "venue": be_spec.get("venue"),
                            "instrument": be_spec.get("instrument"),
                            "side": be_spec.get("outcome"),
                            "size": "1",
                            "price": be_spec.get("pay"),
                            "note": "be_complete",
                        })
                        actions.append(f"{key}:try_be_complete")
            continue
        if action == "hold_to_settle":
            log(f"one-leg hold-to-settle bet={key} held={held}")
            _append_watch({
                "event": "one_leg_hold_to_settle",
                "bet_key": key,
                "held_pay": str(held),
                "ts": now,
            })
            _append({
                "event": "one_leg_hold_to_settle",
                "bet_key": key,
                "held_pay": str(held),
            })
            actions.append(f"{key}:hold_to_settle")
    return actions


def _send_pair(log, key: str, title: str, legs: list[dict]) -> None:
    """Hard leg IOC, then easy leg GTC at L (adopted 2026-10-31)."""
    import kalshi_same_direction as ksd

    bad, why = ksd.legs_are_same_direction_double(legs)
    if bad:
        log(f"order skip both legs {title}; {why}")
        _append({
            "event": "skip",
            "bet_key": key,
            "game": title,
            "note": why,
        })
        return
    ok_settle, why_settle = same_settlement_legs(*legs)
    if not ok_settle:
        log(f"order skip both legs {title}; {why_settle}")
        _append({
            "event": "skip",
            "bet_key": key,
            "game": title,
            "note": why_settle,
        })
        return
    first, second = legs[0], _with_tif(legs[1], "gtc")
    status, payload, note = _send(first)
    first_payload = payload
    _log_sent(log, first, status)
    _append({
        "event": "sent",
        "bet_key": key,
        "venue": first["venue"],
        "instrument": first["instrument"],
        "side": first["outcome"],
        "limit_price": first["limit"],
        "tif": first.get("tif") or "ioc",
        "size": "1",
        "http_status": status,
        "note": note,
        "order_id": _order_id(payload),
    })
    filled = filled_contracts(payload) if status in (200, 201) else Decimal("0")
    if status in (200, 201) and order_still_open(payload) and filled < SIZE:
        cancel_status, cancel_note = _cancel(first, payload)
        log(f"order cancel venue={first['venue']} instrument={first['instrument']} http={cancel_status} {cancel_note}")
        filled = Decimal("0")
    if filled < SIZE:
        log(f"order first leg not filled {title} {first['venue']} {first['outcome']}; second leg not sent")
        _append({"event": "both_unfilled", "bet_key": key, "venue": first["venue"], "http_status": status, "note": note})
        return
    _append({
        "event": "filled",
        "bet_key": key,
        "venue": first["venue"],
        "instrument": first["instrument"],
        "side": first["outcome"],
        "size": "1",
        "price": first["pay"],
    })
    status2, payload2, note2 = _send(second)
    _log_sent(log, second, status2)
    _append({
        "event": "sent",
        "bet_key": key,
        "venue": second["venue"],
        "instrument": second["instrument"],
        "side": second["outcome"],
        "limit_price": second["limit"],
        "tif": "gtc",
        "size": "1",
        "http_status": status2,
        "note": note2,
        "order_id": _order_id(payload2),
    })
    filled2 = filled_contracts(payload2) if status2 in (200, 201) else Decimal("0")
    resting = bool(status2 in (200, 201) and order_still_open(payload2) and filled2 < SIZE)
    if filled2 >= SIZE:
        _append({
            "event": "filled",
            "bet_key": key,
            "venue": second["venue"],
            "instrument": second["instrument"],
            "side": second["outcome"],
            "size": "1",
            "price": second["pay"],
        })
        log(f"order both legs filled {title}")
        return
    # Do NOT cancel a resting second-leg GTC — that is the wait-for-L policy.
    held_pay = _dec(first.get("pay")) or Decimal("0")
    miss_l = _dec(second.get("pay"))
    be_pay = break_even_miss_pay(held_pay)
    _log_one_leg(log, first)
    _append({
        "event": "one_leg",
        "bet_key": key,
        "venue": first["venue"],
        "instrument": first["instrument"],
        "side": first["outcome"],
        "size": "1",
        "price": first["pay"],
        "second_venue": second["venue"],
        "second_instrument": second["instrument"],
        "second_side": second["outcome"],
        "second_http": status2,
        "second_tif": "gtc",
        "second_resting": resting,
        "miss_limit_l": str(miss_l) if miss_l is not None else None,
        "break_even_pay": str(be_pay),
        "note": note2,
    })
    if resting:
        opened = time.time()
        held_intent = (first.get("body") or {}).get("intent")
        second_intent = (second.get("body") or {}).get("intent")
        watch = {
            "event": "second_leg_gtc_open",
            "bet_key": key,
            "game": title,
            "held_venue": first["venue"],
            "held_instrument": first["instrument"],
            "held_side": first["outcome"],
            "held_pay": first["pay"],
            "held_intent": held_intent,
            "second_venue": second["venue"],
            "second_instrument": second["instrument"],
            "second_side": second["outcome"],
            "second_intent": second_intent,
            "miss_limit_l": str(miss_l) if miss_l is not None else None,
            "break_even_pay": str(be_pay),
            "second_order_id": _order_id(payload2),
            "opened_at": opened,
            "wait_sec": ONE_LEG_GTC_WAIT_SEC,
            "cheap_exit_max": str(CHEAP_EXIT_MAX),
        }
        _append_watch(watch)
        _append({"event": "second_leg_gtc_open", "bet_key": key, "order_id": _order_id(payload2), "opened_at": opened})
        log(
            f"second-leg GTC resting {title} venue={second['venue']} L={second.get('pay')} "
            f"wait={ONE_LEG_GTC_WAIT_SEC}s be={be_pay}"
        )
    alert_one_leg(
        log,
        title,
        first,
        first_payload,
        second,
        status2,
        note2,
        payload2,
        gtc_resting=resting,
    )


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def smoke() -> dict:
    """Balance reads and Gemini terms. Does not place an order."""
    report = {}
    try:
        status, usd = kalshi_private.balance_usd()
        report["kalshi_http"] = status
        report["kalshi_usd"] = usd
    except Exception as exc:
        report["kalshi_http"] = type(exc).__name__
    try:
        status, body = gemini_private.private_call("/v1/balances", None, "POST")
        report["gemini_balance_http"] = status
        if status == 200:
            data = json.loads(body)
            usd = None
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, dict) and str(row.get("currency") or "").upper() == "USD":
                        usd = row.get("available")
            report["gemini_usd"] = usd
        else:
            report["gemini_balance_note"] = _public_note(body)
    except Exception as exc:
        report["gemini_balance_http"] = type(exc).__name__
    try:
        status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "GET")
        if status != 200:
            status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "POST")
        report["gemini_terms_http"] = status
        if status == 200:
            data = json.loads(body)
            report["gemini_terms_accepted"] = bool(data.get("hasAcceptedLatest"))
        else:
            report["gemini_terms_note"] = _public_note(body)
    except Exception as exc:
        report["gemini_terms_http"] = type(exc).__name__
    try:
        status, body = polymarket_us_live.signed_json("GET", "/v1/account/balances")
        report["polymarket_http"] = status
        if status == 200:
            data = json.loads(body)
            power = None
            for row in data.get("balances") or []:
                if isinstance(row, dict):
                    power = row.get("buyingPower")
            report["polymarket_buying_power"] = power
        else:
            report["polymarket_note"] = _public_note(body)
    except Exception as exc:
        report["polymarket_http"] = type(exc).__name__
    report["orders_sent"] = 0
    return report


if __name__ == "__main__":
    import sys
    if "--smoke" in sys.argv:
        print(json.dumps(smoke(), default=str))
    else:
        print("Pass --smoke to read balances. This command does not place an order.")
