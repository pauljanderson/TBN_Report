"""Detect Kalshi same-direction doubles that look like locks but are not.

On Kalshi tennis/team moneylines, each player (or team) is its own market under
one event ticker prefix:

  KXATPCHALLENGERMATCH-26NOV01GIMPEN-GIM
  KXATPCHALLENGERMATCH-26NOV01GIMPEN-PEN

Yes on GIM + No on PEN both pay if Gima wins. That is a same-direction double,
not a hedge / lock. GIMPEN 2026-11-01 lost both legs (−$0.85). TAGDAR won both.

A true lock is Yes + No of the *same* market ticker, or Yes on one venue and No
on another venue for the same settlement.

Does not place, cancel, or sell. No secrets.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


_EVENT_SUFFIX = re.compile(r"^(?P<event>.+)-(?P<code>[A-Z0-9]{2,6})$")


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", ""))
    except Exception:
        return None


def kalshi_event_prefix(ticker: str) -> str:
    """Event key with the trailing market/player code stripped.

    KXATPCHALLENGERMATCH-26NOV01GIMPEN-GIM → KXATPCHALLENGERMATCH-26NOV01GIMPEN
    Empty when the ticker has no trailing -CODE.
    """
    text = str(ticker or "").strip().upper()
    if not text:
        return ""
    match = _EVENT_SUFFIX.match(text)
    if not match:
        return ""
    return match.group("event")


def kalshi_market_code(ticker: str) -> str:
    text = str(ticker or "").strip().upper()
    match = _EVENT_SUFFIX.match(text)
    return match.group("code") if match else ""


def complementary_kalshi_markets(left: str, right: str) -> bool:
    """True when two different market tickers share one Kalshi event prefix."""
    a = str(left or "").strip().upper()
    b = str(right or "").strip().upper()
    if not a or not b or a == b:
        return False
    ea, eb = kalshi_event_prefix(a), kalshi_event_prefix(b)
    return bool(ea and eb and ea == eb)


def _outcome_of(leg: dict) -> str:
    raw = str(
        leg.get("outcome")
        or leg.get("side")
        or leg.get("pay")
        or leg.get("outcome_side")
        or ""
    ).strip().lower()
    if raw in {"yes", "no"}:
        return raw
    if raw in {"bid", "buy_yes", "long"}:
        return "yes"
    if raw in {"ask", "buy_no", "short", "sell"}:
        # Kalshi buy-No posts as ask / sell Yes.
        return "no"
    return raw


def _instrument_of(leg: dict) -> str:
    return str(
        leg.get("instrument")
        or leg.get("ticker")
        or leg.get("market_ticker")
        or leg.get("kalshi_ticker")
        or ""
    ).strip()


def candidate_kalshi_tickers(cand: dict) -> tuple[str, str]:
    """Best-effort Yes/No instruments from a lock candidate row (any shop)."""
    row = cand if isinstance(cand, dict) else {}
    single = str(row.get("kalshi_ticker") or row.get("ticker") or "").strip()
    yes = str(
        row.get("kalshi_yes_ticker")
        or row.get("yes_kalshi_ticker")
        or row.get("yes_ticker")
        or row.get("yes_ident")
        or row.get("yes_instrument")
        or ""
    ).strip()
    no = str(
        row.get("kalshi_no_ticker")
        or row.get("no_kalshi_ticker")
        or row.get("no_ticker")
        or row.get("no_ident")
        or row.get("no_instrument")
        or ""
    ).strip()
    yes_venue = str(row.get("yes_venue") or "").lower()
    no_venue = str(row.get("no_venue") or "").lower()
    # When both legs claim Kalshi but only one shared ticker was filled in,
    # do not invent a second market — that would false-positive a true lock.
    if yes_venue == "kalshi" and not yes:
        yes = single
    if no_venue == "kalshi" and not no:
        no = single
    # Cross-venue / poly: still surface explicit per-side instruments.
    if not yes:
        yes = str(row.get("yes_symbol") or row.get("yes_slug") or "").strip()
    if not no:
        no = str(row.get("no_symbol") or row.get("no_slug") or "").strip()
    return yes, no


def complementary_instruments(left: str, right: str) -> bool:
    """True when two instruments are opponent markets of one event.

    Kalshi trailing -CODE form is the primary detector. Also treats two
    distinct Polymarket/Gemini ids that share a long common prefix and differ
    only in a short trailing player token as complementary.
    """
    if complementary_kalshi_markets(left, right):
        return True
    a = str(left or "").strip()
    b = str(right or "").strip()
    if not a or not b or a.lower() == b.lower():
        return False
    # slug-or-symbol: foo-bar-GIM vs foo-bar-PEN / foo_bar_gim vs foo_bar_pen
    for sep in ("-", "_"):
        if sep not in a or sep not in b:
            continue
        a_parts, b_parts = a.split(sep), b.split(sep)
        if len(a_parts) < 2 or len(b_parts) < 2:
            continue
        if a_parts[:-1] == b_parts[:-1] and a_parts[-1].lower() != b_parts[-1].lower():
            # Require short trailing codes (player/team tokens), not full names.
            if 2 <= len(a_parts[-1]) <= 12 and 2 <= len(b_parts[-1]) <= 12:
                return True
    return False


def is_same_direction_double(leg_a: dict, leg_b: dict) -> bool:
    """Yes on market A + No on complementary market B (any venue)."""
    if not isinstance(leg_a, dict) or not isinstance(leg_b, dict):
        return False
    inst_a, inst_b = _instrument_of(leg_a), _instrument_of(leg_b)
    if not complementary_instruments(inst_a, inst_b):
        return False
    out_a, out_b = _outcome_of(leg_a), _outcome_of(leg_b)
    return {out_a, out_b} == {"yes", "no"}


def is_same_direction_kalshi_double(leg_a: dict, leg_b: dict) -> bool:
    """Back-compat alias — now venue-agnostic complementary Yes+No."""
    return is_same_direction_double(leg_a, leg_b)


def same_direction_reason(leg_a: dict, leg_b: dict) -> str:
    if not is_same_direction_double(leg_a, leg_b):
        return ""
    a, b = _instrument_of(leg_a), _instrument_of(leg_b)
    va = str(leg_a.get("venue") or "").lower() or "venue"
    vb = str(leg_b.get("venue") or "").lower() or "venue"
    return (
        "same-direction double (not a lock): "
        f"{_outcome_of(leg_a)} {va}:{a} + {_outcome_of(leg_b)} {vb}:{b} "
        "pay on the same winner"
    )


def candidate_is_same_direction_double(cand: dict) -> tuple[bool, str]:
    """Send-time gate for a Yes/No candidate that secretly points at two opponent markets."""
    yes_t, no_t = candidate_kalshi_tickers(cand)
    if not yes_t or not no_t:
        return False, ""
    yes_venue = str((cand or {}).get("yes_venue") or "kalshi").lower()
    no_venue = str((cand or {}).get("no_venue") or "kalshi").lower()
    yes_leg = {"instrument": yes_t, "outcome": "yes", "venue": yes_venue}
    no_leg = {"instrument": no_t, "outcome": "no", "venue": no_venue}
    why = same_direction_reason(yes_leg, no_leg)
    return bool(why), why


def legs_are_same_direction_double(legs: Iterable[dict]) -> tuple[bool, str]:
    rows = [leg for leg in legs if isinstance(leg, dict)]
    if len(rows) < 2:
        return False, ""
    for i, left in enumerate(rows):
        for right in rows[i + 1 :]:
            why = same_direction_reason(left, right)
            if why:
                return True, why
    return False, ""


def open_book_blocks_same_direction(
    new_legs: Iterable[dict],
    open_rows: Iterable[dict],
) -> tuple[bool, str]:
    """Send-time gate vs already-open tape/venue book.

    Blocks Yes on player B when we already hold No on complementary player A
    (and the reverse). Dual-Yes (Strategy B) is not blocked.
    """
    legs = [leg for leg in new_legs if isinstance(leg, dict)]
    opens = [row for row in open_rows if isinstance(row, dict)]
    if not legs or not opens:
        return False, ""
    for leg in legs:
        for row in opens:
            why = same_direction_reason(leg, row)
            if why:
                return True, f"open-book {why}"
    return False, ""


def find_same_direction_stacks(rows: Iterable[dict]) -> list[dict]:
    """Group fill/position/settlement rows by event prefix; flag Yes+No complementary stacks."""
    by_event: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        inst = _instrument_of(row)
        event = kalshi_event_prefix(inst)
        if not event:
            continue
        by_event.setdefault(event, []).append(row)
    found: list[dict] = []
    for event, group in sorted(by_event.items()):
        # Collapse to one row per ticker with a representative outcome.
        by_ticker: dict[str, dict] = {}
        for row in group:
            inst = _instrument_of(row).upper()
            # Prefer an explicit yes/no outcome; position sign can imply side.
            outcome = _outcome_of(row)
            if outcome not in {"yes", "no"}:
                pos = _dec(row.get("position_fp") or row.get("position") or row.get("qty"))
                if pos is not None:
                    outcome = "yes" if pos > 0 else "no" if pos < 0 else ""
                yes_n = _dec(row.get("yes_count_fp"))
                no_n = _dec(row.get("no_count_fp"))
                if yes_n is not None and yes_n > 0:
                    outcome = "yes"
                elif no_n is not None and no_n > 0:
                    outcome = "no"
            if outcome not in {"yes", "no"}:
                continue
            by_ticker[inst] = {"instrument": inst, "outcome": outcome, "venue": "kalshi", "raw": row}
        tickers = list(by_ticker.values())
        for i, left in enumerate(tickers):
            for right in tickers[i + 1 :]:
                if is_same_direction_kalshi_double(left, right):
                    found.append(
                        {
                            "event": event,
                            "legs": [
                                {"ticker": left["instrument"], "outcome": left["outcome"]},
                                {"ticker": right["instrument"], "outcome": right["outcome"]},
                            ],
                            "reason": same_direction_reason(left, right),
                        }
                    )
    return found


def settlement_pnl_usd(row: dict) -> Decimal | None:
    """With-fee P&L for one Kalshi settlement row.

    `revenue` is cents (100 = $1). Many Yes+No flatten rows report revenue 0;
    when counts exist, infer payout from market_result × winning count.
    """
    if not isinstance(row, dict):
        return None
    cost = (_dec(row.get("yes_total_cost_dollars")) or Decimal("0")) + (
        _dec(row.get("no_total_cost_dollars")) or Decimal("0")
    )
    fee = _dec(row.get("fee_cost")) or Decimal("0")
    revenue_raw = _dec(row.get("revenue"))
    revenue = None
    if revenue_raw is not None:
        # API stores face revenue in cents.
        revenue = (revenue_raw / Decimal("100")).quantize(Decimal("0.0001"))
    if revenue is None or revenue == 0:
        result = str(row.get("market_result") or "").lower()
        yes_n = _dec(row.get("yes_count_fp")) or Decimal("0")
        no_n = _dec(row.get("no_count_fp")) or Decimal("0")
        if result == "yes" and yes_n > 0:
            revenue = yes_n
        elif result == "no" and no_n > 0:
            revenue = no_n
        elif revenue is None:
            revenue = Decimal("0")
    return (revenue - cost - fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
