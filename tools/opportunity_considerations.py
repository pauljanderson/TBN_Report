"""Log of pairs considered for a lock, only when the after-fee cost is at or under 0.99.

The opportunities page keeps the newest 500 distinct looks. A repeated quote
with the same decision and reason does not add another row. Nothing above
0.99 after the documented fees is written.
"""
from __future__ import annotations

import html
import json
import re
import sys
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)
import venue_pace  # noqa: E402
PAGE = STAMP / "opportunities.html"
LOG_PATH = RAW / "considerations.json"
LOCK_PATH = RAW / "considerations.lock"
ORDERS_PATH = RAW / "orders.jsonl"
ET = ZoneInfo("America/New_York")
LOG_MAX = Decimal("0.99")
KEEP = 500
ONE = Decimal("1")
CLOSED = {"closed", "settled", "determined", "finalized", "inactive"}

ASKED = (
    "Paul: “you have the wrong winner here again. can you go back and make sure all of the matches "
    "have the correct winner? Now we need to go back and regenerate all the reports again” "
    "Prior: the opportunities page should show me all opportunities that we considered, "
    "and why they were denied (too high a cost after fees, etc) this should provide a detailed log. "
    "we don't need to log anything that is cost after feed above 0.99"
)
ASKED_LATEST = (
    "the opportunities file is thinking our limit is 0.95, but i changed it to 0.96. "
    "Example skip: “After-fee cost 0.97 is above the 0.95 send line but still at or under 0.99.”"
)
ASKED_UNROUNDED = (
    "don't round — the skip “After-fee cost 0.97 is above the 0.97 send line” hid a hair-over-0.97 net "
    "because the sentence rounded to cents. Show the full after-fee cost so 0.97001 vs 0.97 is visible."
)
ASKED_CATALOG = (
    "this opportunities row seems opposite to what is true: "
    "After-fee cost 0.93 is at or under the 0.98 send line. This catalog pass does not send orders. "
    "The first sentence is the SEND condition, but the decision is denied. That reads backwards."
)
ASKED_ABOVE = (
    "After-fee cost 0.98399 is above the 0.984 send line but still at or under 0.99. "
    "0.98399 is LESS than 0.984, so this reads backwards."
)
ASKED_098 = (
    "Why was this one denied? Page says: catalog scan never sends; live pollers send when "
    "after-fee cost ≤ 0.984 (NET_MAX); after-fee cost on this look is 0.98. Is it a rounding error? "
    "He thought we removed rounding from the after-fee cost field but it doesn't look like it."
)
ASKED_VENUE = (
    "if something was sent I want the return reason from the venue on the opportunities sheet."
)
ASKED_CONFIRM = (
    "Mismatch (tape said X, venue says Y). After we receive a response from an order, "
    "call that venue’s API to see what they have, and use that information to move forward "
    "(fill vs empty cancel vs leftover vs both-legs). Truth = venues, not the HTTP order tape."
)
ASKED_VERIFY = (
    "i would expect to see another row immediately after (in time) to a direct call to "
    "verify the cost after a catalog scan. OR in the reason for denied that we called "
    "and got these numbers after and they were no longer a gap"
)
ASKED_FALSE_SENT = (
    "opportunities page shows SENT both-legs-filled for a game he cannot find on either venue. "
    "Row: Tampa Bay vs Carolina spread New Mexico St. wins by over 9.5 points, Yes kalshi / No novig, "
    "kalshi HTTP 201 fill 1 filled / polymarket HTTP 201 fill 1 filled. Paul sees no order on Kalshi or Poly."
)
GHOST_PREFIX = "False sent (ghost)."


ASKED_VERIFY_NOW = (
    "looks like it took 3 seconds to send the rest recheck. is there any way we can "
    "tighten this up and send immediately?"
)
CATALOG_VERIFY_SOURCE = "catalog verify"
CATALOG_VERIFY_TRIGGER = "REST recheck"
_CATALOG_OLD_REASON = re.compile(
    r"^After-fee cost (?P<amt>\d+\.\d+) is at or under the \d+\.\d+ send line\. "
    r"This catalog pass does not send orders\.?$"
)


def _plain() -> str:
    line = _send_line()
    return (
        "We showed the wrong player as the winner on some Polymarket tennis games, so P&L was backwards; "
        "we checked every settled game against the platform and rebuilt the pages. "
        "This page is a log of bets we looked at as a possible buy of both sides of the same result. "
        "A row is written only when the two prices plus the documented fees add up to 99 cents or less. "
        "After-fee cost is all-in: Kalshi 0.07 × p × (1 − p), Gemini ceil-cent, Polymarket theta × p × (1 − p), "
        "Novig when the market names a coefficient. A missing Novig fee is fee unknown and is not sent. "
        "Wire (the printed ask) is never treated as after-fee. "
        "If that after-fee cost is above 99 cents, it is left off the page. "
        f"We only send when that after-fee cost is at or under the live send cap ({line}, from NET_MAX). "
        "That number is read from the lock bot so this page cannot drift. "
        "The catalog scan never posts from the walk itself. A catalog row that is still at or under that cap is "
        "logged as denied because that pass is a log only. "
        "When that catalog look is in the lock neighborhood (after-fee at or under 0.99 that would have been "
        "a send if live, or near the cap), both live books are GET immediately in parallel — no pace sleep, "
        "no write-then-wait-for-the-next-loop. A second row is written from that REST recheck "
        "(source catalog verify / REST recheck) with millisecond timestamps so the gap is the HTTP round trip. "
        "That follow-up shows each leg’s live ask, size, and after-fee net to at least four decimal places, "
        "and says whether the gap was still there or gone. "
        "If the live books are still at or under the send cap, those already-fetched books are handed to the "
        "same hard-first 1-contract execute as live pollers (lock.on, max open, local cash). No second book GET. "
        "If the gap closed, catalog still does not send. If the REST GET hits 429, that is named on the verify "
        "row and we do not retry. "
        "Skip reasons and the after-fee cost column print the true send-check cost to at least four decimal places "
        f"(0.9841, not 0.98), so a hair over the cap (0.98414 vs {line}) is visible. "
        "The send check compares that true Decimal to NET_MAX; it does not round to cents first. "
        "A catalog-scan two-decimal money() string is not the number that is stored or compared. "
        f"The cap itself still prints as {line} when that is the exact send line. "
        "An older skip that named a tighter cap is not rewritten onto the live send line if that would make "
        f"“above {line}” false (0.98399 is not above 0.984). "
        "Each row is one look: the game, the prices and sizes, whether we sent the order or denied it, and why. "
        "The same look is not repeated. A later look with a new price or a new reason is added. "
        "The page keeps the newest 500 looks, newest first. "
        "A denial does not ring the phone. Sending an order still does. "
        "A pair that was sent, including one where only one side filled, stays on this log with the after-fee cost and the reason. "
        "Each sent row is one attempted lock pair: game, sport, moneyline, Type A lock gap, then two legs "
        "(who $1 pays, Yes/No, platform, send time ET, limit, size, fill or miss, venue fill price) "
        "and a flatten block only when one leg filled. "
        "Kalshi UI Sold Yes is our buy No (fee inside). Kalshi UI Bought Yes is the flatten cover. "
        "Those two Kalshi fills are one round-trip, not two independent directional bets. "
        "A Polymarket HTTP 200 with fill 0, or a Poly leg that was never sent because the gap closed, is not a ticket. "
        "Outcome is both filled, one+flatten, or both miss. "
        "A fill is quantity at least 1 on that venue’s fill-history (Kalshi fill_count, Poly cumQuantity / aggressor id). "
        "HTTP 201 with fill_count 0 is an empty cancel, not fill 1. "
        "A flatten with both Yes and No filled on Kalshi leaves no position; look in fill history, not Open. "
        "A row whose game title and side name different events (Tampa Bay vs Carolina plus New Mexico St. 9.5) is a ghost, not a ticket. "
        "See false_sent_tbcar_nms_20261026.html and aboian_hardt_flatten_autopsy_20261030.html."
    )


def _send_max() -> Decimal:
    import live_lock_orders

    return live_lock_orders.effective_net_max()


def _send_line() -> str:
    import live_lock_orders

    return live_lock_orders.send_line()


def catalog_eligible_reason(amount: Decimal) -> str:
    """Catalog scan never sends. Do not phrase the live send condition as a deny."""
    return (
        f"This is the catalog scan; it never sends. "
        f"Live pollers send when after-fee cost is at or under {_send_line()} (from NET_MAX). "
        f"After-fee cost on this look is {_fmt(amount)}."
    )

_mem_guard = threading.Lock()
_mem_fp: dict[tuple, str] = {}
_page_guard = threading.Lock()
_page_timer: threading.Timer | None = None


def _now() -> str:
    return datetime.now(ET).isoformat(timespec="milliseconds")


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def _fmt(value: Decimal) -> str:
    """User-visible money as the Decimal is. At least four decimal places; never round to cents."""
    import live_lock_orders

    return live_lock_orders._net_text(value)


class _FeeScan:
    def gemini_fee(self, price: Decimal) -> Decimal:
        import live_lock_orders

        return live_lock_orders.gemini_taker_fee(price)


def _recomputed_net(cand: dict | None) -> Decimal | None:
    """Same send-check net as live pollers (pair_net). None when a charging fee is unknown."""
    if not isinstance(cand, dict):
        return None
    try:
        import live_lock_orders

        return live_lock_orders.pair_net(_FeeScan(), cand)
    except Exception:
        return None


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _size_missing(value) -> bool:
    number = _dec(value)
    return number is None or number < ONE


def _blank_or_zero(value) -> bool:
    if value is None or value == "":
        return True
    number = _dec(value)
    return number is None or number <= 0


def _not_real_no(cand: dict) -> str:
    """Gemini No with no size. A size above zero is a real offer."""
    if str(cand.get("no_venue") or "").lower() != "gemini":
        return ""
    size = cand.get("gemini_no_size")
    if size in (None, ""):
        size = cand.get("no_size")
    if not _blank_or_zero(size):
        return ""
    reject = str(cand.get("no_reject") or cand.get("reject_reason") or "").lower()
    if bool(cand.get("no_flipped_yes_bid")) or "flip" in reject:
        return "Not a real No. The No price is the Yes bid flipped, not a No offer you can buy."
    return "Not a real No. Gemini No size is missing or zero."


def _tennessee(title: str, cand: dict) -> bool:
    blob = " ".join(
        str(part or "")
        for part in (
            title,
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


def _is_catalog_verify(cand: dict | None) -> bool:
    src = str((cand or {}).get("source") or "").strip().lower()
    trig = str((cand or {}).get("trigger_source") or "").strip().lower()
    return src == CATALOG_VERIFY_SOURCE or trig == CATALOG_VERIFY_TRIGGER.lower() or src == "rest recheck"


def logged_net(cand: dict, net: Decimal | None = None) -> Decimal | None:
    """After-fee cost when it is at or under 0.99. Otherwise None.

    An explicit Decimal net (live pair_net) wins. Otherwise recompute pair_net
    from the quote so a catalog money() string like 0.98 is not the compared value.
    Fall back to the stored net only when a charging fee is unknown.
    Catalog-verify follow-ups may be over 0.99: that is the 'gap closed' row Paul asked for.
    """
    if isinstance(net, Decimal):
        amount = net
    else:
        amount = _recomputed_net(cand)
        if amount is None:
            amount = _dec(net if net is not None else (cand or {}).get("net"))
    if amount is None:
        return None
    if amount > LOG_MAX and not _is_catalog_verify(cand):
        return None
    return amount


def gate_denial(cand: dict, title: str = "", net: Decimal | None = None) -> str:
    """Plain-English quote denial. Empty when the quote is still eligible to send.

    Empty also when the after-fee cost is missing or above 0.99. Those are not logged.
    """
    amount = logged_net(cand, net)
    if amount is None:
        return ""
    if _tennessee(title, cand):
        return "The closed Tennessee vs Indianapolis 13.5 bet is not sent."
    for field in ("kalshi_status", "gemini_status"):
        if str(cand.get(field) or "").lower() in CLOSED:
            return "The contract is closed."
    not_real = _not_real_no(cand)
    if not_real:
        return not_real
    if _size_missing(cand.get("yes_size")) or _size_missing(cand.get("no_size")):
        return "Missing size."
    if amount > _send_max():
        return (
            f"After-fee cost {_fmt(amount)} is above the {_send_line()} send line "
            "but still at or under 0.99."
        )
    return ""


def reason_from_qualifies(text: str, cand: dict, net: Decimal | None) -> str:
    """Map a live qualifies() reason onto the log. Empty means do not log."""
    amount = logged_net(cand, net)
    if amount is None:
        return ""
    low = (text or "").lower()
    if "tennessee" in low:
        return "The closed Tennessee vs Indianapolis 13.5 bet is not sent."
    if "buyable" in low or "gemini no" in low:
        return _not_real_no(cand) or "Not a real No."
    if "closed" in low:
        return "The contract is closed."
    if "at least 1" in low or "size" in low:
        return "Missing size."
    if " is above " in low or "above the" in low:
        if amount > _send_max():
            return (
                f"After-fee cost {_fmt(amount)} is above the {_send_line()} send line "
                "but still at or under 0.99."
            )
        return text
    if "fee unknown" in low:
        return ""
    return text


def _bet_key(row: dict) -> tuple:
    return (
        row.get("sport") or "",
        row.get("game") or "",
        row.get("market_type") or "",
        row.get("side") or "",
        str(row.get("number") or ""),
        row.get("yes_venue") or "",
        row.get("no_venue") or "",
    )


def _look_key(row: dict) -> tuple:
    """Dedup catalog scan vs catalog verify separately so both rows can sit together."""
    return _bet_key(row) + (str(row.get("source") or ""),)


def _fingerprint(row: dict) -> str:
    parts = list(_bet_key(row)) + [
        row.get("yes_price") or "",
        row.get("no_price") or "",
        row.get("yes_size") or "",
        row.get("no_size") or "",
        row.get("net") or "",
        row.get("decision") or "",
        row.get("reason") or "",
        row.get("venue_return") or "",
        row.get("source") or "",
    ]
    return "\t".join(str(part) for part in parts)


def _row_from(sport: str, game: str, cand: dict, decision: str, reason: str, net: Decimal) -> dict:
    return {
        "at": _now(),
        "sport": sport or str(cand.get("sport") or ""),
        "game": game or str(cand.get("game") or ""),
        "market_type": str(cand.get("market_type") or ""),
        "side": str(cand.get("side") or ""),
        "number": str(cand.get("number") or ""),
        "yes_venue": str(cand.get("yes_venue") or ""),
        "no_venue": str(cand.get("no_venue") or ""),
        "yes_price": str(cand.get("yes_price") or ""),
        "no_price": str(cand.get("no_price") or ""),
        "yes_size": str(cand.get("yes_size") or ""),
        "no_size": str(cand.get("no_size") or ""),
        "net": _fmt(net),
        "source": str(cand.get("source") or cand.get("trigger_source") or ""),
        "decision": decision,
        "reason": reason,
        "venue_return": str(cand.get("venue_return") or ""),
        "trigger_venue": str(cand.get("trigger_venue") or ""),
        "trigger_side": str(cand.get("trigger_side") or ""),
        "trigger_price": str(cand.get("trigger_price") or ""),
        "trigger_seen_at": str(cand.get("trigger_seen_at") or ""),
        "trigger_source": str(cand.get("trigger_source") or ""),
        "filled_venues": str(cand.get("filled_venues") or ""),
        "hold_now": str(cand.get("hold_now") or ""),
        "kalshi_ticker": str(cand.get("kalshi_ticker") or ""),
        "gemini_symbol": str(cand.get("gemini_symbol") or ""),
        "polymarket_slug": str(cand.get("polymarket_slug") or ""),
        "novig_market": str(cand.get("novig_market") or ""),
    }


def _load(raw: str) -> list[dict]:
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _last_fp(rows: list[dict], key: tuple) -> str:
    for row in reversed(rows):
        if _look_key(row) == key:
            return str(row.get("fp") or _fingerprint(row))
    return ""


def record(sport: str, game: str, cand: dict, decision: str, reason: str, net: Decimal | None = None, at: str | None = None) -> bool:
    """Append one distinct look. False when the after-fee cost is above 0.99 or this look is already the latest."""
    if not isinstance(cand, dict) or not reason or decision not in ("sent", "denied"):
        return False
    mixed_ghost = is_mixed_game_side_ghost({"game": game, "side": cand.get("side")})
    if mixed_ghost:
        decision = "denied"
        reason = _ghost_reason(reason)
    amount = logged_net(cand, net)
    if amount is None:
        return False
    row = _row_from(sport, game, cand, decision, reason, amount)
    if mixed_ghost:
        row["ghost"] = True
    if at:
        row["at"] = at
    key = _look_key(row)
    fp = _fingerprint(row)
    row["fp"] = fp
    with _mem_guard:
        if _mem_fp.get(key) == fp:
            return False
    try:
        with venue_pace.FileLock(LOCK_PATH):
            rows = _load(LOG_PATH.read_text(encoding="utf-8")) if LOG_PATH.exists() else []
            if _last_fp(rows, key) == fp:
                with _mem_guard:
                    _mem_fp[key] = fp
                return False
            if decision == "sent":
                # One sent row per bet per timestamp second. Websocket / book
                # recheck / consider quote patches must not stack three "Both
                # legs filled" lines for one attempt (21 Oct 2026 SHSU 9.5).
                at = str(row.get("at") or "")
                already_sent = any(
                    isinstance(prev, dict)
                    and _bet_key(prev) == _bet_key(row)
                    and prev.get("decision") == "sent"
                    and str(prev.get("at") or "") == at
                    for prev in rows
                )
                if already_sent:
                    with _mem_guard:
                        _mem_fp[key] = fp
                    return False
            rows.append(row)
            kept = rows[-KEEP:]
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = LOG_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"rows": kept}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(LOG_PATH)
            with _mem_guard:
                _mem_fp.clear()
                for kept_row in kept:
                    _mem_fp[_look_key(kept_row)] = str(kept_row.get("fp") or "")
    except Exception:
        return False
    _schedule_page()
    if decision == "sent":
        write_page()
    return True


def _should_catalog_verify(denial: str, amount: Decimal | None) -> bool:
    """True when the catalog look is in the lock neighborhood and needs a REST follow-up."""
    if amount is None:
        return False
    text = (denial or "").strip()
    if text in ("Missing size.", "The contract is closed."):
        return False
    if "tennessee" in text.lower() and "indianapolis" in text.lower():
        return False
    if "not a real no" in text.lower():
        return False
    return True


def _catalog_verify_reason(
    catalog_net: Decimal,
    verify_net: Decimal | None,
    notes: list[str],
    *,
    still_gap: bool | None,
    handed: bool = False,
) -> str:
    cap = _send_line()
    was = _fmt(catalog_net)
    extra = " ".join(n for n in notes if n).strip()
    if extra:
        retry = " Did not retry." if "429" in extra else ""
        return (
            f"REST recheck after catalog: {extra} Catalog after-fee was {was}. "
            f"Catalog still does not send.{retry}"
        )
    if verify_net is None:
        return (
            f"REST recheck after catalog: could not recompute after-fee net. "
            f"Catalog after-fee was {was}. Catalog still does not send."
        )
    got = _fmt(verify_net)
    if still_gap:
        if handed:
            return (
                f"REST recheck: still a gap. After-fee net {got} vs cap {cap} "
                f"(catalog was {was}). Handed REST books to hard-first execute "
                f"(1 contract, no second book GET)."
            )
        return (
            f"REST recheck: still a gap. After-fee net {got} vs cap {cap} "
            f"(catalog was {was}). Catalog still does not send; live poller may."
        )
    return (
        f"REST recheck: no longer a gap. After-fee net {got} vs cap {cap}; "
        f"was catalog {was}. Catalog still does not send."
    )


def _begin_catalog_recheck(cand: dict):
    """Start both book GETs immediately (parallel, no pace slot). Never POST."""
    import live_lock_orders

    handle: dict = {
        "yes_spec": live_lock_orders._leg_spec(cand, "yes"),
        "no_spec": live_lock_orders._leg_spec(cand, "no"),
        "missing": [],
        "yes_out": None,
        "no_out": None,
        "threads": [],
    }
    if handle["yes_spec"] is None:
        handle["missing"].append(live_lock_orders._leg_deny_reason(cand, "yes"))
    if handle["no_spec"] is None:
        handle["missing"].append(live_lock_orders._leg_deny_reason(cand, "no"))
    if handle["missing"]:
        return handle

    def _yes() -> None:
        try:
            handle["yes_out"] = live_lock_orders._live_from_book(handle["yes_spec"], pace=False)
        except Exception as exc:
            handle["yes_out"] = (type(exc).__name__, None)

    def _no() -> None:
        try:
            handle["no_out"] = live_lock_orders._live_from_book(handle["no_spec"], pace=False)
        except Exception as exc:
            handle["no_out"] = (type(exc).__name__, None)

    workers = [
        threading.Thread(target=_yes, daemon=True),
        threading.Thread(target=_no, daemon=True),
    ]
    for worker in workers:
        worker.start()
    handle["threads"] = workers
    return handle


def _finish_catalog_recheck(
    handle: dict, cand: dict, catalog_net: Decimal
) -> tuple[dict, Decimal | None, str, dict | None, dict | None]:
    import live_lock_orders

    out = dict(cand)
    out["source"] = CATALOG_VERIFY_SOURCE
    out["trigger_source"] = CATALOG_VERIFY_TRIGGER
    for worker in handle.get("threads") or []:
        worker.join()
    if handle.get("missing"):
        named = ["missing fields:"] + list(handle["missing"])
        return out, catalog_net, _catalog_verify_reason(catalog_net, None, named, still_gap=None), None, None

    notes: list[str] = []
    yes_out = handle.get("yes_out")
    no_out = handle.get("no_out")
    yes_gate, live_yes = yes_out if isinstance(yes_out, tuple) else ("yes book recheck failed", None)
    no_gate, live_no = no_out if isinstance(no_out, tuple) else ("no book recheck failed", None)
    if live_yes is None:
        notes.append(yes_gate or "yes book recheck failed")
    if live_no is None:
        notes.append(no_gate or "no book recheck failed")
    if notes:
        return (
            out,
            catalog_net,
            _catalog_verify_reason(catalog_net, None, notes, still_gap=None),
            None,
            None,
        )

    yes_pay = live_lock_orders._dec(live_yes.get("pay"))
    no_pay = live_lock_orders._dec(live_no.get("pay"))
    if yes_pay is not None:
        out["yes_price"] = format(yes_pay, "f")
    if no_pay is not None:
        out["no_price"] = format(no_pay, "f")
    yes_sz = live_yes.get("quote_size")
    no_sz = live_no.get("quote_size")
    if yes_sz not in (None, ""):
        out["yes_size"] = str(yes_sz)
    if no_sz not in (None, ""):
        out["no_size"] = str(no_sz)
    verify_net = live_lock_orders.pair_net(_FeeScan(), out)
    cap = live_lock_orders.effective_net_max()
    still = verify_net is not None and verify_net <= cap
    return (
        out,
        verify_net,
        _catalog_verify_reason(catalog_net, verify_net, [], still_gap=still),
        live_yes,
        live_no,
    )


def _catalog_rest_recheck(cand: dict, catalog_net: Decimal) -> tuple[dict, Decimal | None, str]:
    """Public book GETs on both legs in parallel. Never POST."""
    handle = _begin_catalog_recheck(cand)
    out, verify_net, reason, _live_yes, _live_no = _finish_catalog_recheck(handle, cand, catalog_net)
    return out, verify_net, reason


def _maybe_catalog_execute(
    sport: str,
    title: str,
    cand: dict,
    verify_net: Decimal | None,
    live_yes: dict | None,
    live_no: dict | None,
    *,
    game_row,
    scan,
    log,
) -> bool:
    """Hand already-fetched REST books to hard-first execute. No second book GET."""
    import live_lock_orders

    if game_row is None or scan is None:
        return False
    if live_yes is None or live_no is None:
        return False
    if verify_net is None or verify_net > live_lock_orders.effective_net_max():
        return False

    def _log(msg: str) -> None:
        if callable(log):
            log(msg)

    try:
        live_lock_orders.execute_locks(
            scan,
            sport,
            title,
            game_row,
            {"candidates": [cand]},
            [],
            _log,
            skip_book_recheck=True,
        )
        return True
    except Exception:
        return False


def record_catalog(
    sport: str,
    game: str,
    candidates: list,
    *,
    game_row=None,
    scan=None,
    log=None,
) -> None:
    """Log catalog looks as denied. Lock-neighborhood looks start a REST recheck immediately.

    Both book GETs run in parallel with no pace sleep. If the live books are still
    at or under the send cap and a scan/game row is in hand, those books are handed
    to live_lock_orders.execute_locks (hard-first, 1 contract, no second book GET).
    """
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        use = dict(cand)
        use["source"] = "catalog scan"
        if not str(use.get("trigger_source") or "").strip():
            use["trigger_source"] = "catalog scan"
        amount = logged_net(use)
        if amount is None:
            continue
        denial = gate_denial(use, game, amount)
        if not denial:
            denial = catalog_eligible_reason(amount)
        catalog_at = _now()
        should = _should_catalog_verify(denial, amount)
        handle = _begin_catalog_recheck(use) if should else None
        record(sport, game, use, "denied", denial, amount, at=catalog_at)
        if handle is None:
            continue
        try:
            verified, verify_net, verify_reason, live_yes, live_no = _finish_catalog_recheck(
                handle, use, amount
            )
        except Exception as exc:
            verified = dict(use)
            verified["source"] = CATALOG_VERIFY_SOURCE
            verified["trigger_source"] = CATALOG_VERIFY_TRIGGER
            verify_net = amount
            live_yes = None
            live_no = None
            verify_reason = _catalog_verify_reason(
                amount, None, [f"REST recheck failed ({type(exc).__name__})"], still_gap=None
            )
        import live_lock_orders

        cap = live_lock_orders.effective_net_max()
        still = (
            verify_net is not None
            and verify_net <= cap
            and live_yes is not None
            and live_no is not None
        )
        will_hand = still and game_row is not None and scan is not None
        if will_hand:
            verify_reason = _catalog_verify_reason(
                amount, verify_net, [], still_gap=True, handed=True
            )
        record(sport, game, verified, "denied", verify_reason, verify_net, at=_now())
        if will_hand:
            _maybe_catalog_execute(
                sport,
                game,
                verified,
                verify_net,
                live_yes,
                live_no,
                game_row=game_row,
                scan=scan,
                log=log,
            )


def _schedule_page() -> None:
    global _page_timer
    with _page_guard:
        if _page_timer is not None and _page_timer.is_alive():
            return
        _page_timer = threading.Timer(1.0, write_page)
        _page_timer.daemon = True
        _page_timer.start()


def _missing_fields_display(row: dict, text: str) -> str:
    """Old 'Missing order fields.' hid which leg/venue body could not be built."""
    raw = (text or "").strip()
    if raw != "Missing order fields.":
        return text
    yv = str(row.get("yes_venue") or "").strip() or "unknown"
    nv = str(row.get("no_venue") or "").strip() or "unknown"
    return (
        f"Missing order fields for a {yv}/{nv} pair: ticker, slug, intent, "
        "Novig market/outcome id, or Novig orders not live. "
        "Live poller send block, not the catalog scan."
    )


def _display_reason(text: str, amount: Decimal | None = None) -> str:
    """Show the live send line even on older log rows that still name a prior cap."""
    import live_lock_orders

    out = live_lock_orders.rewrite_send_line_copy(text)
    match = _CATALOG_OLD_REASON.match((out or "").strip())
    if match:
        named = _dec(match.group("amt"))
        if named is not None:
            out = catalog_eligible_reason(amount if amount is not None else named)
    if amount is not None and amount > _send_max():
        low = (out or "").lower()
        if amount > LOG_MAX or "rest recheck" in low or "no longer a gap" in low or "still a gap" in low:
            return out
        over = (
            f"After-fee cost {_fmt(amount)} is above the {_send_line()} send line "
            "but still at or under 0.99."
        )
        if "catalog scan" in low or "catalog pass" in low:
            return over + " This look was also the catalog scan, which never sends."
        if "is above the" in low and "send line" in low:
            return over
        return over
    if amount is not None:
        out = re.sub(
            r"After-fee cost on this look is \d+\.\d+\.",
            f"After-fee cost on this look is {_fmt(amount)}.",
            out or "",
        )
    return out


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{_esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def is_mixed_game_side_ghost(row: dict) -> bool:
    """Tampa Bay vs Carolina + New Mexico St. is not a real pair. Display-only strike."""
    import live_lock_orders

    if not isinstance(row, dict):
        return False
    return live_lock_orders.pair_labels_conflict(str(row.get("game") or ""), str(row.get("side") or ""))


def _ghost_reason(reason: str) -> str:
    text = (reason or "").strip() or "(empty reason)"
    if text.startswith(GHOST_PREFIX):
        return text
    return (
        "False sent (ghost). No venue order id. Game title and side name different events. "
        "HTTP-OK is not a fill. Original: " + text
    )


def _ghost_overlay(row: dict) -> tuple[str, str]:
    decision = str(row.get("decision") or "")
    reason = str(row.get("reason") or "")
    if not is_mixed_game_side_ghost(row):
        return decision, reason
    return "denied", _ghost_reason(reason)


def strike_mixed_ghosts(rows: list) -> tuple[int, list]:
    """Persist-deny mixed-label sent rows. Idempotent. Does not invent venue orders."""
    n = 0
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        patched = dict(row)
        if is_mixed_game_side_ghost(patched):
            decision, reason = _ghost_overlay(patched)
            changed = (
                str(patched.get("decision") or "") != decision
                or str(patched.get("reason") or "") != reason
                or not patched.get("ghost")
            )
            patched["decision"] = decision
            patched["reason"] = reason
            patched["ghost"] = True
            if changed:
                n += 1
        extra, patched = strike_flatten_hold(patched)
        n += extra
        out.append(patched)
    return n, out


_VENUE_NAMES = ("kalshi", "polymarket", "gemini", "novig")
_QTY_POS = re.compile(
    r"(?:fill(?:_count)?|qty)\s+(?:0\.\d*[1-9]\d*|[1-9]\d*(?:\.\d+)?)",
    re.I,
)
_QTY_ZERO = re.compile(r"(?:fill(?:_count)?|qty)\s+0(?:\.0+)?\b", re.I)


def _chunk_has_fill(chunk: str) -> bool:
    text = chunk or ""
    if _QTY_POS.search(text):
        return True
    return False


def filled_venues_of(row: dict) -> list[str]:
    """Venues with confirm qty > 0 in venue_return / reason. Fill 0 is not a fill."""
    if not isinstance(row, dict):
        return []
    named = str(row.get("filled_venues") or "").strip()
    if named:
        return [part.strip().lower() for part in named.split(",") if part.strip()]
    blob = f"{row.get('venue_return') or ''} {row.get('reason') or ''}"
    found: list[str] = []
    for venue in _VENUE_NAMES:
        if not re.search(rf"\b{venue}\b", blob, re.I):
            continue
        positive = False
        for match in re.finditer(rf"{venue}[^.]*", blob, re.I):
            chunk = match.group(0)
            if _chunk_has_fill(chunk):
                positive = True
                break
        if positive:
            found.append(venue)
    return found


def is_flatten_hold(row: dict) -> bool:
    blob = f"{row.get('reason') or ''} {row.get('venue_return') or ''} {row.get('hold_now') or ''}".lower()
    return "flatten" in blob


def _sold_yes_note(venue: str, side: str) -> str:
    """Kalshi UI Sold Yes = kitchen buy No. Shared with the kitchen Type mapper."""
    try:
        import kalshi_ticker_decode as ktd
    except Exception:
        return "Sold Yes = buy No" if str(venue).lower() == "kalshi" and str(side).lower() == "no" else ""
    if str(venue or "").strip().lower() != "kalshi":
        return ""
    return ktd.sold_yes_buy_no_gloss(side)


def lock_pair_filled_label(row: dict) -> str:
    """Yes X / No Y only for shops with confirm qty > 0. Unfilled shops omitted."""
    filled = {str(v).lower() for v in filled_venues_of(row)}
    yes = str(row.get("yes_venue") or "").strip()
    no = str(row.get("no_venue") or "").strip()
    bits: list[str] = []
    if yes and yes.lower() in filled:
        bits.append(f"Yes {yes}")
    if no and no.lower() in filled:
        note = _sold_yes_note(no, "no")
        bits.append(f"No {no} ({note})" if note else f"No {no}")
    named = {yes.lower(), no.lower()} - {""}
    for shop in filled_venues_of(row):
        if shop not in named:
            bits.append(shop)
    return " / ".join(bits)


def _intended_unfilled(row: dict) -> bool:
    filled = {str(v).lower() for v in filled_venues_of(row)}
    intended = {
        str(row.get("yes_venue") or "").strip().lower(),
        str(row.get("no_venue") or "").strip().lower(),
    } - {""}
    return bool(intended - filled)


def venues_label(row: dict) -> str:
    """Lock pair lists a platform only when confirm qty > 0."""
    yes = str(row.get("yes_venue") or "").strip()
    no = str(row.get("no_venue") or "").strip()
    intended = f"Yes {yes} / No {no}".strip()
    filled = filled_venues_of(row)
    flatten = is_flatten_hold(row)
    decision = str(row.get("decision") or "")
    blob = f"{row.get('reason') or ''} {row.get('venue_return') or ''}".lower()
    pair = lock_pair_filled_label(row)
    if flatten and filled:
        tail = " Flattened - no position remains."
        if "kalshi" in {v.lower() for v in filled}:
            tail = " Flattened Bought Yes on kalshi - no position remains."
        miss = " Other intended shop confirm qty 0 - not listed." if _intended_unfilled(row) else ""
        head = pair or f"Filled {', '.join(filled)}"
        return f"{head}.{tail}{miss}".replace("  ", " ").strip()
    if filled:
        return pair or f"Filled {', '.join(filled)}"
    if decision == "sent" or flatten:
        if "fill 0" in blob or "qty 0" in blob or decision == "sent":
            return "confirm qty 0 - not a ticket (no platform listed)"
        return "confirm qty 0 - not a ticket (no platform listed)"
    return intended


def strike_flatten_hold(row: dict) -> tuple[int, dict]:
    """Stamp filled_venues / hold_now on a flatten sent row. Display-only. No orders."""
    patched = dict(row)
    if not is_flatten_hold(patched):
        return 0, patched
    filled = filled_venues_of(patched)
    changed = 0
    if filled and str(patched.get("filled_venues") or "") != ",".join(filled):
        patched["filled_venues"] = ",".join(filled)
        changed = 1
    if str(patched.get("hold_now") or "") != "none":
        patched["hold_now"] = "none"
        changed = 1
    return changed, patched


TABLE_HEADERS = [
    ("Game", "text"),
    ("Sport", "text"),
    ("Bet type", "text"),
    ("Type", "text"),
    ("Leg 1 who $1 pays", "text"),
    ("Leg 1 side", "text"),
    ("Leg 1 platform", "text"),
    ("Leg 1 send ET", "date"),
    ("Leg 1 limit", "num"),
    ("Leg 1 size", "num"),
    ("Leg 1 fill?", "text"),
    ("Leg 1 fill px", "num"),
    ("Leg 2 who $1 pays", "text"),
    ("Leg 2 side", "text"),
    ("Leg 2 platform", "text"),
    ("Leg 2 send ET", "date"),
    ("Leg 2 limit", "num"),
    ("Leg 2 size", "num"),
    ("Leg 2 fill?", "text"),
    ("Leg 2 fill px", "num"),
    ("Flatten platform", "text"),
    ("Flatten side", "text"),
    ("Flatten send ET", "date"),
    ("Flatten limit", "num"),
    ("Flatten size", "num"),
    ("Flatten fill?", "text"),
    ("Flatten fill px", "num"),
    ("Flatten P&L", "num"),
    ("Outcome", "text"),
    ("After-fee cost", "num"),
    ("Decision", "text"),
    ("Reason", "text"),
]

_HTTP_LEG = re.compile(
    r"(?:(?P<flatten>flatten)\s+)?"
    r"(?P<venue>kalshi|polymarket|gemini|novig)\s+"
    r"HTTP\s+(?P<status>\d+)\s+"
    r"fill\s+(?P<qty>[\d.]+)",
    re.I,
)
_AT_PX = re.compile(r"@\s*(?P<px>\d+\.\d+)")
_VS_SPLIT = re.compile(r"\s+vs\.?\s+", re.I)


def _parse_stamp(value):
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


def _fmt_et(value) -> str:
    stamp = _parse_stamp(value)
    if stamp is None:
        return ""
    return stamp.strftime("%Y-%m-%d %H:%M:%S ET")


def _cents(value) -> str:
    number = _dec(value)
    if number is None:
        return ""
    text = format(number * 100, "f").rstrip("0").rstrip(".")
    return text + "\u00a2"


def _qty_text(value) -> str:
    number = _dec(value)
    if number is None:
        return ""
    if number == number.to_integral_value():
        return format(number.quantize(Decimal("1")), "f")
    return format(number, "f")


def _other_player(game: str, side: str) -> str:
    parts = _VS_SPLIT.split(str(game or "").strip())
    if len(parts) != 2:
        return ""
    left, right = parts[0].strip(), parts[1].strip()
    named = str(side or "").strip().lower()
    left_l, right_l = left.lower(), right.lower()
    left_last = left_l.split()[-1] if left_l else ""
    right_last = right_l.split()[-1] if right_l else ""
    if left_l and (left_l in named or named in left_l or (left_last and left_last in named)):
        return right
    if right_l and (right_l in named or named in right_l or (right_last and right_last in named)):
        return left
    return right


def _who_pays(game: str, side: str, outcome: str) -> str:
    named = str(side or "").strip()
    if str(outcome or "").lower() == "yes":
        return named or "Yes"
    other = _other_player(game, named)
    if other:
        return other
    return f"not {named}" if named else "No"


def _decision_sentence(text: str) -> str:
    raw = (text or "").strip()
    match = re.search(r"\b(?:kalshi|polymarket|gemini|novig)\s+HTTP\b", raw, re.I)
    if match:
        raw = raw[: match.start()].strip().rstrip(".")
    return raw


def _parse_http_legs(blob: str) -> list[dict]:
    text = blob or ""
    matches = list(_HTTP_LEG.finditer(text))
    out: list[dict] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[match.start() : end]
        px = None
        at = _AT_PX.search(chunk)
        if at:
            px = at.group("px")
        out.append(
            {
                "flatten": bool(match.group("flatten")),
                "venue": match.group("venue").lower(),
                "status": match.group("status"),
                "qty": match.group("qty"),
                "px": px,
                "sent": True,
            }
        )
    return out


def _blank_leg() -> dict:
    return {
        "who": "",
        "side": "",
        "side_key": "",
        "platform": "",
        "send_et": "",
        "limit": "",
        "size": "",
        "fill": "",
        "fill_px": "",
        "ui": "",
        "qty": None,
        "house": None,
        "fee": None,
        "after_fee": None,
        "yes_limit": None,
        "sent": False,
        "step": "",
    }


def _fill_label(qty, *, posted: bool, decision_sent: bool) -> str:
    number = _dec(qty) if qty is not None else None
    if posted:
        if number is not None and number > 0:
            return f"fill {_qty_text(number)}"
        return "miss 0"
    if decision_sent:
        return "never sent"
    return "not sent"


def _kalshi_fee(price) -> Decimal | None:
    number = _dec(price)
    if number is None:
        return None
    try:
        import live_lock_orders

        return live_lock_orders.kalshi_fee_amount(number)
    except Exception:
        return None


def _stamp_kalshi_ui(leg: dict) -> None:
    if str(leg.get("platform") or "").lower() != "kalshi":
        return
    house = _dec(leg.get("house"))
    fee = _dec(leg.get("fee"))
    if fee is None and house is not None:
        fee = _kalshi_fee(house)
        if fee is not None:
            leg["fee"] = fee
    after = _dec(leg.get("after_fee"))
    if after is None and house is not None and fee is not None:
        after = house + fee
        leg["after_fee"] = after
    if after is None:
        return
    side = str(leg.get("side_key") or "").lower()
    if side == "no":
        sold = ONE - after
        yes_lim = _dec(leg.get("yes_limit"))
        if yes_lim is None and house is not None:
            yes_lim = ONE - house
        leg["ui"] = f"Kalshi UI Sold Yes {_cents(sold)} Limit {_cents(yes_lim)}"
    elif side == "yes":
        yes_lim = _dec(leg.get("yes_limit")) or house
        leg["ui"] = f"Kalshi UI Bought Yes {_cents(after)} Limit {_cents(yes_lim)}"


def _side_cell(leg: dict) -> str:
    side = str(leg.get("side") or "")
    ui = str(leg.get("ui") or "")
    if side and ui:
        return f"{side} ({ui})"
    return side or ui


def _apply_http(leg: dict, hit: dict, *, decision_sent: bool) -> None:
    leg["sent"] = True
    qty = _dec(hit.get("qty"))
    leg["qty"] = qty if qty is not None else Decimal("0")
    px = hit.get("px")
    if px:
        leg["fill_px"] = str(px)
        house = _dec(px)
        if house is not None:
            leg["house"] = house
            if not leg.get("limit"):
                leg["limit"] = str(house)
    leg["fill"] = _fill_label(leg["qty"], posted=True, decision_sent=decision_sent)


def _apply_order(leg: dict, order: dict, *, decision_sent: bool) -> None:
    leg["sent"] = True
    leg["step"] = str(order.get("step") or "")
    if order.get("sent_at") or order.get("at"):
        leg["send_et"] = _fmt_et(order.get("sent_at") or order.get("at"))
    house = _dec(order.get("house_cash") or order.get("quote_price") or order.get("wire"))
    fee = _dec(order.get("fee"))
    after = _dec(order.get("after_fee"))
    yes_lim = _dec(order.get("limit_price"))
    if house is not None:
        leg["house"] = house
    if fee is not None:
        leg["fee"] = fee
    if after is not None:
        leg["after_fee"] = after
    if yes_lim is not None:
        leg["yes_limit"] = yes_lim
    side = str(order.get("side") or leg.get("side_key") or "").lower()
    if side == "no" and house is not None:
        leg["limit"] = format(house, "f")
    elif yes_lim is not None:
        leg["limit"] = format(yes_lim, "f")
    elif house is not None:
        leg["limit"] = format(house, "f")
    qty = _dec(order.get("confirm_qty") if order.get("confirm_qty") not in (None, "") else order.get("tape_qty"))
    if qty is None and order.get("http_status") not in (None, ""):
        qty = Decimal("0")
    if qty is not None:
        leg["qty"] = qty
        if qty > 0 and house is not None:
            leg["fill_px"] = format(house, "f")
        elif qty > 0 and order.get("quote_price"):
            leg["fill_px"] = str(order.get("quote_price"))
    posted = bool(order.get("http_status") not in (None, "") or order.get("order_id"))
    if posted:
        leg["fill"] = _fill_label(leg.get("qty"), posted=True, decision_sent=decision_sent)
        if qty is not None and qty > 0:
            leg["size"] = _qty_text(qty)
        elif not leg.get("size"):
            leg["size"] = "1"


def _load_sent_orders(path: Path | None = None) -> list[dict]:
    """Sent tape rows for send-time / fee overlay. Never POSTs. Skips secrets."""
    file_path = path or ORDERS_PATH
    if not file_path.exists():
        return []
    out: list[dict] = []
    try:
        with file_path.open(encoding="utf-8") as handle:
            for line in handle:
                if '"sent"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict) or str(row.get("event") or "") != "sent":
                    continue
                if not row.get("sent_at") and not row.get("at"):
                    continue
                step = str(row.get("step") or "").strip().lower()
                if step not in {"hard", "easy", "flatten", "simultaneous", ""}:
                    continue
                out.append(
                    {
                        "event": "sent",
                        "sent_at": row.get("sent_at") or row.get("at"),
                        "venue": row.get("venue"),
                        "side": row.get("side"),
                        "step": row.get("step"),
                        "game": row.get("game"),
                        "limit_price": row.get("limit_price"),
                        "quote_price": row.get("quote_price"),
                        "http_status": row.get("http_status"),
                        "confirm_qty": row.get("confirm_qty"),
                        "tape_qty": row.get("tape_qty"),
                        "house_cash": row.get("house_cash") or row.get("wire"),
                        "fee": row.get("fee"),
                        "after_fee": row.get("after_fee"),
                        "order_id": row.get("order_id"),
                    }
                )
    except Exception:
        return []
    return out


def _orders_for_row(row: dict, sent_orders: list[dict] | None) -> list[dict]:
    if not sent_orders:
        return []
    at = _parse_stamp(row.get("at"))
    game = str(row.get("game") or "").strip().lower()
    shops = {
        str(row.get("yes_venue") or "").strip().lower(),
        str(row.get("no_venue") or "").strip().lower(),
    } - {""}
    matched: list[dict] = []
    for order in sent_orders:
        stamp = _parse_stamp(order.get("sent_at") or order.get("at"))
        if at is not None:
            if stamp is None:
                continue
            delta = (at - stamp).total_seconds()
            if delta < -8 or delta > 60:
                continue
        ogame = str(order.get("game") or "").strip().lower()
        if ogame and game and ogame != game and game not in ogame and ogame not in game:
            continue
        venue = str(order.get("venue") or "").strip().lower()
        step = str(order.get("step") or "").strip().lower()
        if step != "flatten" and shops and venue and venue not in shops:
            continue
        matched.append(order)
    return matched


def consideration_not_a_lock(row: dict) -> bool:
    """Team-named Over plus a game-total market_type is two questions, not a lock."""
    import price_memory

    row = row if isinstance(row, dict) else {}
    parts = [
        row.get("market_type"),
        row.get("kalshi_ticker"),
        row.get("gemini_symbol"),
        row.get("polymarket_slug"),
    ]
    kinds = price_memory.settlement_kinds(*parts)
    side = str(row.get("side") or "")
    if re.search(r"\b(over|under)\b", side, re.I):
        prefix = re.split(r"\bover\b|\bunder\b", side, maxsplit=1, flags=re.I)[0].strip()
        prefix_l = re.sub(r"\s+", " ", prefix.lower()).strip()
        generic = prefix_l in {
            "", "the", "game", "total", "points", "point",
            "the game", "the total", "points total", "combined", "match",
        }
        if prefix and not generic:
            kinds.add("team_total")
        elif str(row.get("market_type") or "").lower() == "total":
            kinds.add("total")
    return len(kinds) > 1


def _attempt_type(row: dict) -> str:
    if consideration_not_a_lock(row):
        return "not a lock (two directional)"
    src = str(row.get("source") or row.get("trigger_source") or "").strip().lower()
    if src in {CATALOG_VERIFY_SOURCE, "rest recheck"} or "catalog verify" in src:
        return "catalog verify"
    if "catalog" in src:
        return "catalog scan"
    if str(row.get("decision") or "") == "sent":
        return "A lock gap"
    return "A lock look"


def _leg_filled(leg: dict | None) -> bool:
    if not isinstance(leg, dict):
        return False
    qty = _dec(leg.get("qty"))
    return qty is not None and qty > 0


def _outcome(yes: dict, no: dict, flatten: dict | None, *, decision: str) -> str:
    if decision != "sent":
        return "not sent"
    yf, nf = _leg_filled(yes), _leg_filled(no)
    ff = _leg_filled(flatten) if flatten else False
    if yf and nf:
        return "both filled"
    if (yf or nf) and (flatten or ff):
        return "one+flatten"
    if yf or nf:
        return "one-leg"
    return "both miss"


def attempt_from_row(row: dict, sent_orders: list[dict] | None = None) -> dict:
    """One attempted lock pair: two legs plus flatten when one-leg filled."""
    row = row if isinstance(row, dict) else {}
    decision, reason = _ghost_overlay(row)
    sent = decision == "sent"
    game = str(row.get("game") or "")
    side_name = str(row.get("side") or "")
    yes = _blank_leg()
    no = _blank_leg()
    yes.update(
        {
            "who": _who_pays(game, side_name, "yes"),
            "side": "Yes",
            "side_key": "yes",
            "platform": str(row.get("yes_venue") or ""),
            "limit": str(row.get("yes_price") or ""),
            "size": "1" if sent else str(row.get("yes_size") or ""),
            "house": _dec(row.get("yes_price")),
            "fill": _fill_label(None, posted=False, decision_sent=sent),
        }
    )
    no.update(
        {
            "who": _who_pays(game, side_name, "no"),
            "side": "No",
            "side_key": "no",
            "platform": str(row.get("no_venue") or ""),
            "limit": str(row.get("no_price") or ""),
            "size": "1" if sent else str(row.get("no_size") or ""),
            "house": _dec(row.get("no_price")),
            "fill": _fill_label(None, posted=False, decision_sent=sent),
        }
    )
    flatten = None
    blob = f"{row.get('venue_return') or ''} {row.get('reason') or ''}"
    yes_v = str(yes.get("platform") or "").lower()
    no_v = str(no.get("platform") or "").lower()
    for hit in _parse_http_legs(blob):
        if hit.get("flatten"):
            if flatten is None:
                flatten = _blank_leg()
            flatten["platform"] = hit.get("venue") or flatten.get("platform")
            if _leg_filled(no) and not _leg_filled(yes):
                flatten["side"], flatten["side_key"] = "Yes", "yes"
            elif _leg_filled(yes) and not _leg_filled(no):
                flatten["side"], flatten["side_key"] = "No", "no"
            else:
                flatten["side"] = flatten.get("side") or "Yes"
                flatten["side_key"] = flatten.get("side_key") or "yes"
            flatten["who"] = _who_pays(game, side_name, flatten["side_key"])
            flatten["size"] = flatten.get("size") or "1"
            _apply_http(flatten, hit, decision_sent=sent)
            continue
        venue = str(hit.get("venue") or "").lower()
        if venue == no_v:
            _apply_http(no, hit, decision_sent=sent)
        elif venue == yes_v:
            _apply_http(yes, hit, decision_sent=sent)
        elif no_v and venue == no_v:
            _apply_http(no, hit, decision_sent=sent)
        elif yes_v:
            _apply_http(yes, hit, decision_sent=sent)
        else:
            _apply_http(no if no_v else yes, hit, decision_sent=sent)
    for order in _orders_for_row(row, sent_orders):
        step = str(order.get("step") or "").lower()
        venue = str(order.get("venue") or "").lower()
        oside = str(order.get("side") or "").lower()
        if step == "flatten":
            if flatten is None:
                flatten = _blank_leg()
            flatten["platform"] = order.get("venue") or flatten.get("platform")
            flatten["side"] = "Yes" if oside != "no" else "No"
            flatten["side_key"] = oside if oside in {"yes", "no"} else "yes"
            flatten["who"] = _who_pays(game, side_name, flatten["side_key"])
            flatten["size"] = flatten.get("size") or "1"
            _apply_order(flatten, order, decision_sent=sent)
            continue
        if oside == "no" or (not oside and venue == no_v):
            _apply_order(no, order, decision_sent=sent)
        elif oside == "yes" or venue == yes_v:
            _apply_order(yes, order, decision_sent=sent)
        elif venue == no_v:
            _apply_order(no, order, decision_sent=sent)
        else:
            _apply_order(yes, order, decision_sent=sent)
    if sent and not yes.get("sent"):
        yes["fill"] = "never sent"
    if sent and not no.get("sent"):
        no["fill"] = "never sent"
    # Keep the intended shop on a miss / never-sent lock leg. Hiding it made
    # Aboian/Eala look like two Kalshi tickets instead of Kalshi + Poly.
    _stamp_kalshi_ui(yes)
    _stamp_kalshi_ui(no)
    if flatten:
        if not flatten.get("who"):
            flatten["who"] = _who_pays(game, side_name, flatten.get("side_key") or "yes")
        if not flatten.get("side"):
            flatten["side"] = "Yes"
            flatten["side_key"] = "yes"
        _stamp_kalshi_ui(flatten)
        no_after = _dec(no.get("after_fee")) if str(no.get("platform") or "").lower() == "kalshi" else None
        yes_after = _dec(flatten.get("after_fee")) if str(flatten.get("side_key") or "") == "yes" else None
        if no_after is None and str(yes.get("platform") or "").lower() == "kalshi" and str(yes.get("side_key") or "") == "no":
            no_after = _dec(yes.get("after_fee"))
        if no_after is not None and yes_after is not None:
            flatten["pnl"] = ONE - no_after - yes_after
        elif _leg_filled(no) and _leg_filled(flatten):
            n_after = _dec(no.get("after_fee"))
            f_after = _dec(flatten.get("after_fee"))
            if n_after is not None and f_after is not None:
                flatten["pnl"] = ONE - n_after - f_after
    yf, nf = _leg_filled(yes), _leg_filled(no)
    if nf and not yf:
        leg1, leg2 = no, yes
    elif yf and not nf:
        leg1, leg2 = yes, no
    elif str(no.get("step") or "").lower() == "hard":
        leg1, leg2 = no, yes
    elif str(yes.get("step") or "").lower() == "hard":
        leg1, leg2 = yes, no
    else:
        leg1, leg2 = yes, no
    amount = logged_net(row)
    net_text = _fmt(amount) if amount is not None else str(row.get("net") or "")
    pnl = flatten.get("pnl") if flatten else None
    return {
        "game": game,
        "sport": str(row.get("sport") or ""),
        "bet_type": str(row.get("market_type") or ""),
        "type": _attempt_type(row),
        "yes": yes,
        "no": no,
        "leg1": leg1,
        "leg2": leg2,
        "flatten": flatten,
        "outcome": _outcome(yes, no, flatten, decision=decision),
        "decision": decision,
        "reason": _decision_sentence(_missing_fields_display(row, reason)),
        "net": net_text,
        "pnl": pnl,
    }


def _leg_tds(leg: dict | None, *, include_who: bool) -> str:
    blank = _blank_leg() if not isinstance(leg, dict) else leg
    cells = []
    if include_who:
        cells.append(f"<td>{_esc(blank.get('who') or '')}</td>")
    cells.extend(
        [
            f"<td>{_esc(_side_cell(blank))}</td>",
            f"<td>{_esc(blank.get('platform') or '')}</td>",
            f"<td>{_esc(blank.get('send_et') or '')}</td>",
            f"<td>{_esc(blank.get('limit') or '')}</td>",
            f"<td>{_esc(blank.get('size') or '')}</td>",
            f"<td>{_esc(blank.get('fill') or '')}</td>",
            f"<td>{_esc(blank.get('fill_px') or '')}</td>",
        ]
    )
    return "".join(cells)


def _flatten_tds(flatten: dict | None) -> str:
    if not isinstance(flatten, dict):
        return "".join(["<td></td>"] * 8)
    pnl = flatten.get("pnl")
    pnl_txt = _fmt(pnl) if isinstance(pnl, Decimal) else str(pnl or "")
    return (
        f"<td>{_esc(flatten.get('platform') or '')}</td>"
        f"<td>{_esc(_side_cell(flatten))}</td>"
        f"<td>{_esc(flatten.get('send_et') or '')}</td>"
        f"<td>{_esc(flatten.get('limit') or '')}</td>"
        f"<td>{_esc(flatten.get('size') or '')}</td>"
        f"<td>{_esc(flatten.get('fill') or '')}</td>"
        f"<td>{_esc(flatten.get('fill_px') or '')}</td>"
        f"<td>{_esc(pnl_txt)}</td>"
    )


def _cells(row: dict, sent_orders: list[dict] | None = None) -> str:
    view = attempt_from_row(row, sent_orders)
    amount = logged_net(row)
    reason = _display_reason(view.get("reason") or "", amount)
    return (
        "<tr>"
        + f"<td>{_esc(view.get('game') or '')}</td>"
        + f"<td>{_esc(view.get('sport') or '')}</td>"
        + f"<td>{_esc(view.get('bet_type') or '')}</td>"
        + f"<td>{_esc(view.get('type') or '')}</td>"
        + _leg_tds(view.get("leg1"), include_who=True)
        + _leg_tds(view.get("leg2"), include_who=True)
        + _flatten_tds(view.get("flatten"))
        + f"<td>{_esc(view.get('outcome') or '')}</td>"
        + f"<td>{_esc(view.get('net') or '')}</td>"
        + f"<td>{_esc(view.get('decision') or '')}</td>"
        + f"<td>{_esc(reason)}</td>"
        + "</tr>"
    )


def write_page() -> Path:
    """Rewrite opportunities.html from the newest 500 logged looks."""
    import importlib

    dest = PAGE
    log_path = LOG_PATH
    lock_path = LOCK_PATH
    this = sys.modules[__name__]
    try:
        mtime = Path(__file__).stat().st_mtime
    except Exception:
        mtime = None
    if mtime is not None and getattr(this, "_src_mtime", None) != mtime:
        fresh = importlib.reload(this)
        fresh._src_mtime = Path(__file__).stat().st_mtime
        fresh.PAGE = dest
        fresh.LOG_PATH = log_path
        fresh.LOCK_PATH = lock_path
        return fresh.write_page()
    rows: list = []
    try:
        with venue_pace.FileLock(lock_path):
            rows = _load(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
            struck, struck_rows = strike_mixed_ghosts(rows)
            if struck:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = log_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps({"rows": struck_rows}, ensure_ascii=False), encoding="utf-8")
                tmp.replace(log_path)
            rows = struck_rows
    except Exception:
        try:
            rows = _load(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
        except Exception:
            rows = []
    shown = []
    for row in reversed(rows):
        amount = logged_net(row)
        if amount is None:
            continue
        shown.append(row)
        if len(shown) >= KEEP:
            break
    sent_orders = _load_sent_orders()
    ncol = str(len(TABLE_HEADERS))
    if not shown:
        body_rows = [f'<tr><td colspan="{ncol}">No considered pair at or under 0.99 after fees yet.</td></tr>']
    else:
        body_rows = [_cells(row, sent_orders) for row in shown]
    table = (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + "".join(_th(label, kind) for label, kind in TABLE_HEADERS)
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )
    body = f"""
<h1>Considered pairs</h1>
<p class="note">America/New_York. Not on GitHub Pages.</p>
<div class="callout"><h2>What you asked</h2><p>{_esc(ASKED)}</p><p>{_esc(ASKED_LATEST)}</p><p>{_esc(ASKED_UNROUNDED)}</p><p>{_esc(ASKED_CATALOG)}</p><p>{_esc(ASKED_ABOVE)}</p><p>{_esc(ASKED_098)}</p><p>{_esc(ASKED_VENUE)}</p><p>{_esc(ASKED_CONFIRM)}</p><p>{_esc(ASKED_VERIFY)}</p><p>{_esc(ASKED_VERIFY_NOW)}</p><p>{_esc(ASKED_FALSE_SENT)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{_esc(_plain())}</p></div>
<p class="note">Near misses vs the live send line (today + last 48h, including over-cap rechecks the 500-row log may have rotated out). That page's tables were gathered vs 0.984; live send cap is now {_esc(_send_line())}: <a href="lock_near_misses_20261025.html">lock_near_misses_20261025.html</a>. Cap bump: <a href="lock_net_max_099_20261025.html">lock_net_max_099_20261025.html</a>.</p>
<p class="note">Why a catalog row that printed after-fee 0.98 was denied vs the old NET_MAX 0.984 (rounding display, now gone): <a href="lock_098_deny_rounding_20261025.html">lock_098_deny_rounding_20261025.html</a>.</p>
<p class="note">A catalog or live row is logged only when the cost after the documented fees is at or under 0.99. A catalog-verify follow-up (source catalog verify / REST recheck) is the exception: it is written even when the live books reprint over 0.99, so you can see the gap closed. The send line is {_esc(_send_line())} (from NET_MAX). Catalog verify starts both book GETs immediately in parallel (no pace sleep). If that live net is still at or under the cap, those books are handed to hard-first execute with no second book GET. If the gap closed, catalog does not send. Sent rows include the order HTTP and the venue-confirm fill qty. Click column headers to sort. Newest look is first. The page keeps 500 rows. Note: <a href="lock_catalog_verify_row_20261026.html">lock_catalog_verify_row_20261026.html</a>. Ghost mixed-label “sent both filled” autopsy: <a href="false_sent_tbcar_nms_20261026.html">false_sent_tbcar_nms_20261026.html</a>.</p>
{SWIPE_NOTE_HTML}
<h2>Consideration log</h2>
<p class="note">Each row is one attempted lock pair. Leg 1 / Leg 2 are the two shops we tried to buy. Flatten is only when one of those filled. Kalshi Sold Yes is our buy No; Bought Yes is the flatten cover — one round-trip, not two mystery tickets. A Poly fill 0 or a Poly leg that was never sent is not a ticket. Click column headers to sort.</p>
{table}
<p class="note">Updated {_esc(_now())}. {len(shown)} row(s) on the page.</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Considered pairs</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
{body}
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    page = inject_report_page_extras(page)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(dest)
    return dest
