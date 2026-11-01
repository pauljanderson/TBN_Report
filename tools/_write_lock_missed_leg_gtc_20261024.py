"""Research only: missed-leg GTC hit rate on lock-bot one-legs.

Would a Good-Till-Cancel (GTC) at the intended missed-leg REST ask have
traded before settlement? Does not place, cancel, rest, or wire GTC.
Does not sell. Does not start a second live_strategy_b.py. Does not
edit live_lock_orders.py. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import price_memory  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from write_orders_performance import (  # noqa: E402
    ddec,
    load_settlements,
    parse_dt,
    ticker_result,
)

oneleg = __import__("_write_one_leg_miss_gtc_vs_flatten_20261023")
flatten = __import__("_write_flatten_rule_and_tape_20261024")

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_missed_leg_gtc_20261024.html"
ONE = Decimal("1")
NET_MAX = live_lock_orders.NET_MAX
ABSORB_LO = Decimal("0.05")
ABSORB_HI = Decimal("0.95")
PROXY = "best ask ≤ intended GTC limit (price_memory stores venue asks, not last/trade/bid)"

ASKED = (
    "If we get one side of a lock, what is the probability we would fill the "
    "other desired side if we put in a GTC at that price? How many of them "
    "would have hit eventually? That price = the intended missed-leg limit we "
    "already decided to pay (the REST ask we tried / would have IOCd), not a "
    "chase. Same settlement Yes+No (or twin). Not flatten on the filled shop — "
    "this is the other venue's missing lock leg resting as GTC."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if total:
        cells = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def money4(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value))
    except Exception:
        return esc(value)
    return format(number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")


def cents(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value))
    except Exception:
        return esc(value)
    return f"{format((number * Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')}¢"


def dollars(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value))
    except Exception:
        return esc(value)
    signed = format(number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")
    if number > 0:
        signed = "+" + signed
    return f"${signed}"


def clock(value) -> str:
    stamp = parse_dt(value) if not isinstance(value, datetime) else value
    if stamp is None:
        return ""
    return stamp.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S")


def pct_txt(num: int, den: int) -> str:
    if den <= 0:
        return "—"
    value = (Decimal(num) / Decimal(den) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{format(value, 'f')}%"


def delay_txt(seconds) -> str:
    if seconds is None:
        return "—"
    try:
        number = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if number < 120:
        return f"{int(round(number))}s"
    return f"{number / 60:.1f} min ({int(round(number))}s)"


def count_tape_events(events: list[dict]) -> dict:
    one_leg = 0
    lock_one_leg = 0
    for row in events:
        if row.get("event") != "one_leg":
            continue
        one_leg += 1
        if oneleg.is_lock_bot(row):
            lock_one_leg += 1
    return {"n_one_leg_event": one_leg, "n_lock_one_leg_event": lock_one_leg}


def settlement_hit(row: dict, settlements: list[dict]) -> dict:
    """Earliest cache/result row for this leftover ticker or game after the miss."""
    fill = row["fill"]
    miss = row["miss"]
    tickers = {
        str(fill.get("instrument") or "").strip(),
        str(miss.get("instrument") or "").strip(),
    }
    tickers.discard("")
    game = flatten.game_norm(str(row.get("game") or ""))
    start = row.get("start")
    best = None
    for rec in settlements:
        ticker = str(rec.get("ticker") or "").strip()
        result = str(rec.get("result") or "").lower()
        stamp = parse_dt(rec.get("occurrence") or rec.get("settled_at") or rec.get("at"))
        match = False
        if ticker and ticker in tickers:
            match = True
        else:
            rg = flatten.game_norm(str(rec.get("game") or rec.get("game_n") or ""))
            if game and rg and (rg == game or game in rg or rg in game):
                market_w = str(row.get("market") or "").lower()
                market_t = str(rec.get("market_type") or "").lower()
                if not market_w or not market_t or market_w in market_t or market_t in market_w:
                    match = True
        if not match:
            continue
        if start and stamp and stamp < start - timedelta(minutes=5):
            continue
        if best is None or (stamp and (best["stamp"] is None or stamp < best["stamp"])):
            best = {"result": result, "stamp": stamp, "ticker": ticker, "source": rec.get("source") or rec.get("venue")}
    return best or {}


def classify_game(row: dict, settlements: list[dict]) -> None:
    hold = row.get("hold") or {}
    watch = row.get("watch") or {}
    settle = settlement_hit(row, settlements)
    absorb = row.get("absorb_at")
    start = row.get("start")
    status = "unknown"
    until = None
    why = ""
    result = str(settle.get("result") or "").lower()
    if result in {"void", "cancelled", "canceled", "invalid"}:
        status = "void"
        until = settle.get("stamp")
        why = f"settlement cache result={result}"
    elif hold.get("status") in {"win", "lose"}:
        status = "settled"
        until = settle.get("stamp") or absorb
        why = str(hold.get("source") or "hold-to-settle winner")
    elif watch.get("stop") == "resolved_first":
        status = "settled"
        until = start + timedelta(minutes=float(watch["minutes"])) if start and watch.get("minutes") is not None else absorb
        why = "leftover watch resolved_first"
    elif absorb is not None:
        status = "settled"
        until = absorb
        why = "in-match Yes absorb (≥95¢ / ≤5¢) used as settle proxy"
    elif result in {"yes", "no", "win", "lose"}:
        status = "settled"
        until = settle.get("stamp")
        why = f"settlement cache result={result}"
    else:
        last_tick = row.get("last_tick_at")
        now = datetime.now(ET)
        if start and (now - start).total_seconds() < 36 * 3600 and not absorb:
            status = "still_open"
            until = now
            why = "no settle/void/absorb yet; listed separately, out of headline denom"
        else:
            status = "unknown"
            until = last_tick
            why = "no venue result, no absorb, no leftover resolved; not proven open or settled"
    if until is None:
        until = row.get("last_tick_at")
    row["game_status"] = status
    row["window_until"] = until
    row["game_status_why"] = why
    row["settle_result"] = result


def first_ask_touch(ticks: list[dict], after: datetime, until: datetime | None, limit: Decimal) -> tuple:
    best_t = None
    best_px = None
    for tick in ticks:
        seen = parse_dt(tick.get("seen_at"))
        if seen is None or seen <= after:
            continue
        if until and seen > until:
            continue
        price = ddec(tick.get("price"))
        if price is None:
            continue
        if price <= limit:
            return seen, price, "best ask ≤ GTC limit"
        if best_px is None or price < best_px:
            best_px = price
            best_t = seen
    return None, best_px, "best ask never ≤ GTC limit before settle/void"


def attach_ask_ticks(misses: list[dict]) -> None:
    """Load send-day plus following days. Ticks are asks, not prints."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in misses:
        start = row["start"]
        sport = str(row.get("sport") or "")
        if sport.startswith("tennis"):
            sport = "tennis"
        day = start.astimezone(ET).strftime("%Y-%m-%d") if start else ""
        row["_sport"] = sport
        row["_day"] = day
        if start:
            for offset in range(0, 3):
                extra = (start.astimezone(ET) + timedelta(days=offset)).strftime("%Y-%m-%d")
                groups[(sport, extra)].append(row)
        else:
            groups[(sport, day)].append(row)
    cache: dict[tuple[str, str], list[dict]] = {}
    for (sport, day), group in groups.items():
        if not day:
            cache[(sport, day)] = []
            continue
        needles = set()
        for row in group:
            needles.update(tok for tok in oneleg.game_tokens(str(row.get("game") or "")) if len(tok) >= 3)
        ticks = []
        for tick in price_memory.iter_ticks(sport=sport or None, day=day or None):
            blob = str(tick.get("game") or "").lower()
            if needles and not any(tok in blob for tok in needles):
                continue
            ticks.append(tick)
        cache[(sport, day)] = ticks
        print(f"ticks {sport} {day} kept {len(ticks)} / needles {len(needles)}", flush=True)
    for row in misses:
        start = row["start"]
        sport = row.get("_sport") or ""
        game = str(row.get("game") or "")
        miss = row["miss"]
        limit = miss.get("gtc_limit")
        venue = miss.get("venue")
        player = str(row.get("player") or "")
        # Rest the missed lock leg as a buy on that venue/side. Do not flip
        # inverted Poly No to Yes — that is the wrong book for this GTC.
        tick_player = oneleg.ticker_player(str(miss.get("instrument") or ""), game) or player
        pay = str(miss.get("side") or "").lower()
        miss["tick_pay"] = pay
        miss["tick_player"] = tick_player
        ticks = []
        if start:
            for offset in range(0, 3):
                extra = (start.astimezone(ET) + timedelta(days=offset)).strftime("%Y-%m-%d")
                ticks.extend(cache.get((sport, extra), []))
        else:
            ticks.extend(cache.get((sport, row.get("_day") or ""), []))
        matched = [
            tick for tick in ticks
            if oneleg.tick_matches_leg(tick, game, row["market"], row["number"], venue, pay, tick_player)
        ]
        if not matched:
            matched = [
                tick for tick in ticks
                if oneleg.tick_matches_leg(tick, game, row["market"], row["number"], venue, pay, "")
            ]
        row["ticks_n"] = len(matched)
        row["ticks_game_n"] = len(ticks)
        last_seen = None
        for tick in matched:
            seen = parse_dt(tick.get("seen_at"))
            if seen and (last_seen is None or seen > last_seen):
                last_seen = seen
        row["last_tick_at"] = last_seen
        row["absorb_at"] = oneleg.absorb_time(ticks, start) if start else None
        if not ticks:
            row["tick_status"] = "unknown — no ticks for this game/day"
            row["gtc_hit"] = None
            continue
        if not matched:
            row["tick_status"] = "unknown — ticks exist for the game, not this venue/side/pay"
            row["gtc_hit"] = None
            continue
        if start is None or limit is None:
            row["tick_status"] = "unknown — missing miss time or GTC limit"
            row["gtc_hit"] = None
            continue
        row["_matched_ticks"] = matched
        row["_tick_limit"] = limit


def score_gtc(row: dict) -> None:
    miss = row["miss"]
    fill = row["fill"]
    limit = miss.get("gtc_limit")
    start = row.get("start")
    until = row.get("window_until")
    matched = row.get("_matched_ticks") or []
    if row.get("gtc_hit") is None and (not matched or start is None or limit is None):
        row["gtc_fee"] = None
        row["gtc_net"] = None
        row["legal_lock"] = None
        row["legal_why"] = row.get("tick_status") or "unknown ticks"
        row["gtc_pnl"] = None
        row["complementary"] = False
        return
    touch_t, touch_px, why = first_ask_touch(matched, start, until, limit)
    row["touch_at"] = touch_t
    row["touch_px"] = touch_px if touch_t is not None else touch_px
    row["min_later_ask"] = None if touch_t is not None else touch_px
    row["touch_why"] = why
    if touch_t is None:
        row["gtc_hit"] = False
        row["delay_s"] = None
        row["tick_status"] = why
    else:
        row["gtc_hit"] = True
        row["delay_s"] = (touch_t - start).total_seconds()
        row["tick_status"] = why
    pay = miss.get("tick_pay") or str(miss.get("side") or "")
    miss_fee = oneleg.estimate_fee(
        {
            "venue": miss.get("venue"),
            "outcome": pay,
            "pay": limit,
            "fee_coefficient": (miss.get("sent") or {}).get("fee_coefficient"),
        },
        limit,
    )
    if miss.get("io"):
        req = miss["io"].get("request") if isinstance(miss["io"].get("request"), dict) else {}
        miss_fee = oneleg.estimate_fee(
            {
                "venue": miss.get("venue"),
                "outcome": pay,
                "pay": limit,
                "fee_coefficient": req.get("feeRateBps") or req.get("fee_coefficient"),
            },
            limit,
        )
    row["gtc_fee"] = miss_fee
    fill_allin = row.get("fill_allin") or Decimal("0")
    gtc_allin = (limit or Decimal("0")) + (miss_fee or Decimal("0"))
    net = fill_allin + gtc_allin
    row["gtc_net"] = net
    prices_only = fill_allin + (limit or Decimal("0"))
    if net <= NET_MAX:
        row["legal_lock"] = True
        row["legal_why"] = f"all-in net {money4(net)} ≤ NET_MAX {money4(NET_MAX)}"
    elif prices_only <= NET_MAX < net:
        row["legal_lock"] = False
        row["legal_why"] = (
            f"prices {money4(prices_only)} still ≤ {money4(NET_MAX)}; "
            f"taker fee {money4(miss_fee)} pushes all-in to {money4(net)} over NET_MAX"
        )
    else:
        row["legal_lock"] = False
        row["legal_why"] = f"all-in net {money4(net)} > NET_MAX {money4(NET_MAX)} even before extra fee nuance"
    fill_side = str(fill.get("side") or "").lower()
    miss_side = str(miss.get("side") or "").lower()
    fill_player = oneleg.ticker_player(str(fill.get("instrument") or ""), str(row.get("game") or "")) or str(row.get("player") or "")
    miss_player = miss.get("tick_player") or str(row.get("player") or "")
    if {fill_side, miss_side} == {"yes", "no"}:
        complementary = True
    elif fill_side == "yes" and miss_side == "yes":
        complementary = bool(fill_player and miss_player) and not flatten.same_player(fill_player, miss_player)
    else:
        complementary = False
    row["complementary"] = complementary
    if row["gtc_hit"] and complementary:
        if row["game_status"] == "void":
            row["gtc_pnl"] = Decimal("0")
            row["gtc_pnl_note"] = "void: both legs should refund; lock P&L booked 0"
        else:
            row["gtc_pnl"] = ONE - fill_allin - gtc_allin
    else:
        row["gtc_pnl"] = None
        if row["gtc_hit"] and not complementary:
            row["tick_status"] = "ask ≤ limit; not a complementary $1 pair"


def actual_pnl(row: dict) -> tuple:
    if row.get("flatten_filled") and row.get("flatten_pnl") is not None:
        return row["flatten_pnl"], "flatten"
    hold = row.get("hold") or {}
    if hold.get("pnl") is not None:
        return hold["pnl"], f"leftover hold-to-settle ({hold.get('status')})"
    watch = row.get("watch") or {}
    if watch.get("ioc_filled"):
        return None, "leftover watch later filled a hedge (not scored as flatten)"
    return None, "unknown actual"


def summarize(misses: list[dict], counts: dict, tape: dict) -> dict:
    settled = [row for row in misses if row.get("game_status") in {"settled", "void"}]
    open_rows = [row for row in misses if row.get("game_status") == "still_open"]
    unknown_game = [row for row in misses if row.get("game_status") == "unknown"]
    denom = [
        row for row in settled
        if row.get("gtc_hit") is not None
    ]
    hits = [row for row in denom if row.get("gtc_hit")]
    delays = [row["delay_s"] for row in hits if row.get("delay_s") is not None]
    legal_hits = [row for row in hits if row.get("legal_lock")]
    fee_break = [
        row for row in hits
        if row.get("legal_lock") is False and "pushes all-in" in str(row.get("legal_why") or "")
    ]
    lock_pnls = [row["gtc_pnl"] for row in hits if row.get("gtc_pnl") is not None]
    both = []
    for row in hits:
        act, _why = actual_pnl(row)
        if row.get("gtc_pnl") is not None and act is not None:
            both.append(row)
    ask_known_all = [row for row in misses if row.get("gtc_hit") is not None]
    ask_hits_all = [row for row in ask_known_all if row.get("gtc_hit")]
    open_already = [row for row in open_rows if row.get("gtc_hit")]
    return {
        "n": len(misses),
        "n_pairs": counts.get("n_simultaneous_pairs"),
        "n_both_filled": counts.get("n_both_filled"),
        "n_both_unfilled": counts.get("n_both_unfilled"),
        "n_unknown_qty": counts.get("n_unknown_qty"),
        "n_one_leg_event": tape.get("n_one_leg_event"),
        "n_lock_one_leg_event": tape.get("n_lock_one_leg_event"),
        "n_settled": len(settled),
        "n_open": len(open_rows),
        "n_unknown_game": len(unknown_game),
        "n_denom": len(denom),
        "n_hit": len(hits),
        "pct": pct_txt(len(hits), len(denom)),
        "median_s": statistics.median(delays) if delays else None,
        "n_legal": len(legal_hits),
        "n_fee_break": len(fee_break),
        "n_lock_pnl": len(lock_pnls),
        "sum_gtc": sum(lock_pnls, Decimal("0")) if lock_pnls else Decimal("0"),
        "n_both_pnl": len(both),
        "sum_gtc_both": sum((row["gtc_pnl"] for row in both), Decimal("0")) if both else Decimal("0"),
        "sum_actual": sum((actual_pnl(row)[0] for row in both), Decimal("0")) if both else Decimal("0"),
        "sum_delta": sum((row["gtc_pnl"] - actual_pnl(row)[0] for row in both), Decimal("0")) if both else Decimal("0"),
        "n_ask_known_all": len(ask_known_all),
        "n_ask_hit_all": len(ask_hits_all),
        "n_open_already": len(open_already),
        "n_unknown_ticks": sum(1 for row in settled if row.get("gtc_hit") is None),
        "n_flatten": sum(1 for row in misses if row.get("flatten_filled")),
        "sum_flatten": sum(
            (row["flatten_pnl"] for row in misses if row.get("flatten_pnl") is not None),
            Decimal("0"),
        ),
    }


def write_html(misses: list[dict], summary: dict, now: datetime) -> None:
    med = summary["median_s"]
    med_txt = delay_txt(med)
    headline = (
        f"{summary['n_hit']} / {summary['n_denom']} = {summary['pct']} "
        f"would have hit a GTC at the missed REST ask before settle"
    )
    headers = [
        ("When ET", "date"),
        ("Game", "text"),
        ("Sport", "text"),
        ("Filled venue/side", "text"),
        ("Missed venue/side", "text"),
        ("Intended GTC limit", "num"),
        ("Hit GTC?", "text"),
        ("Seconds", "num"),
        ("First ask ≤ limit", "num"),
        ("Still a lock ≤0.984?", "text"),
        ("GTC lock P&L", "num"),
        ("Actual flatten/leftover P&L", "num"),
        ("GTC − actual", "num"),
        ("Game status", "text"),
        ("Proxy / ticks", "text"),
    ]
    rows = []
    for row in misses:
        fill = row["fill"]
        miss = row["miss"]
        hit = {True: "yes", False: "no", None: "unknown"}[row.get("gtc_hit")]
        legal = row.get("legal_lock")
        if legal is True:
            legal_txt = "yes if filled at limit"
        elif legal is False:
            legal_txt = "no if filled — " + esc(row.get("legal_why") or "")
        else:
            legal_txt = "unknown"
        act, act_why = actual_pnl(row)
        gtc_pnl = row.get("gtc_pnl")
        delta = (gtc_pnl - act) if gtc_pnl is not None and act is not None else None
        fill_txt = (
            f"{esc(oneleg.venue_label(fill['venue']))} {esc(fill['side'])} "
            f"{money4(fill['cash'])} fee {money4(fill['fee'])}"
        )
        miss_txt = (
            f"{esc(oneleg.venue_label(miss['venue']))} {esc(miss['side'])} "
            f"REST ask {money4(miss.get('quote'))} posted limit {money4(miss.get('limit'))} "
            f"HTTP {esc(miss['http'])} qty 0"
        )
        delay = row.get("delay_s")
        rows.append([
            esc(clock(row.get("start"))),
            esc(row.get("game") or ""),
            esc(row.get("sport") or ""),
            fill_txt,
            miss_txt,
            money4(miss.get("gtc_limit")),
            hit,
            "" if delay is None else f"{delay:.0f}",
            money4(row.get("touch_px") if row.get("gtc_hit") else row.get("min_later_ask")),
            legal_txt,
            cents(gtc_pnl),
            f"{cents(act)} {esc(act_why)}" if act is not None else esc(act_why),
            cents(delta),
            f"{esc(row.get('game_status'))} — {esc(row.get('game_status_why') or '')}",
            esc(row.get("tick_status") or ""),
        ])
    total = [
        f"N={summary['n']}",
        "",
        "",
        "",
        "",
        "",
        f"{summary['n_hit']}/{summary['n_denom']}",
        med_txt,
        "",
        f"{summary['n_legal']} still ≤0.984",
        cents(summary["sum_gtc"]),
        cents(summary["sum_actual"]),
        cents(summary["sum_delta"]),
        f"{summary['n_open']} still open",
        f"{summary['n_unknown_ticks']} settled, no ticks",
    ]
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
{report_page_extras.CACHE_META}
{report_page_extras.FORCE_RELOAD_SCRIPT}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Missed-leg GTC hit rate — 24 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.hold {{ background: #eef2ff; border-color: #a5b4fc; }}
.note {{ color: #475569; font-size: 14px; }}
.hl {{ font-size: 1.15rem; }}
ul {{ margin-top: 0.3rem; }}
code {{ font-size: 0.9em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Missed lock leg: would a GTC at that price have hit?</h1>
<p class="note">Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. America/New_York. Research only. Not gold. Not DailyRun. In-sample on the same lock-bot tape Paul is looking at. Did not wire GTC. Did not sell. Did not start a second Strategy B. Did not edit <code>live_lock_orders.py</code>. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A lock is two tickets on the same result — Yes in one shop and No in another (or the tennis twin: Yes on each player). Both go out as Immediate-or-Cancel (IOC: take it now or the leftover dies). Sometimes only one shop fills. Today we dump that ticket on the same shop (flatten). The other idea is to <em>leave a resting buy</em> on the shop that missed, at the same price we already agreed to pay, and wait.</p>
<p>Good-Till-Cancel (GTC) means that resting buy stays on the book until it fills or we cancel it. “That price” is the REST ask we already tried (or would have IOCd) — not a chase higher. This page does not turn that on. It asks, after each historical miss: did that shop’s offer come back to our limit before the game was over, and would the two tickets still have been a legal lock under 98.4 cents all-in?</p>
</div>

<div class="callout ok">
<h2>Headline</h2>
<p class="hl"><strong>{esc(headline)}</strong>. Median time-to-touch among hits: {esc(med_txt)}. Still-open games ({esc(summary['n_open'])}) are out of that denominator and listed in the table. {esc(summary['n_unknown_ticks'])} settled row(s) have no usable later ticks (unknown, not a “no”).</p>
<p>Of those {esc(summary['n_hit'])} hits, <strong>{esc(summary['n_legal'])}</strong> would still have been a legal lock at or under NET_MAX 0.984 versus the original filled cash (fill all-in + GTC limit + estimated taker fee). {esc(summary['n_fee_break'])} hit(s) would have broken 0.984 because of fees even though the two prices alone were still in cap. Complementary GTC lock P&amp;L on {esc(summary['n_lock_pnl'])} hit rows: {esc(cents(summary['sum_gtc']))}. On the {esc(summary['n_both_pnl'])} of those that also have flatten/leftover P&amp;L, GTC {esc(cents(summary['sum_gtc_both']))} minus actual {esc(cents(summary['sum_actual']))} is {esc(cents(summary['sum_delta']))}.</p>
</div>

<div class="callout hold">
<h2>HOLD — GTC is not wired</h2>
<p>Live lock and flatten bodies stay IOC. Cancel-on-resolve for a leftover GTC is still missing, so a live rest could still be open after the match ends. This is not gold and not DailyRun. Another agent owns hard-leg-first and the both-sides drought page; this file does not overwrite <code>lock_both_sides_20261024.html</code>.</p>
</div>

<h2>What “hit” means on this tape</h2>
<ul>
<li><strong>Proxy used:</strong> {esc(PROXY)}. A later best-ask at or under the intended limit is the fill condition for a resting <em>buy</em> that is willing to take: the offer came back to our price.</li>
<li><strong>Not the same as a print:</strong> we do not store last/trade. We also do not store bids. A bid ≥ limit would also fill a resting buy (seller hits us). Missing bids/prints is a false-<em>negative</em> risk — some GTCs might have filled without the ask ever quoting ≤ limit in our poll. False-<em>positive</em> risk: the ask flickered ≤ limit without takeable size of 1, or we would not have had queue priority. Size-1 is not on these ticks.</li>
<li><strong>Window:</strong> from the miss until settle/void (settlement cache occurrence, leftover <code>resolved_first</code>, or in-match Yes absorb ≥95¢ / ≤5¢ as a settle proxy). Still-open games are excluded from k/N.</li>
<li><strong>Price:</strong> intended missed-leg pay from the IOC recheck ask when present, else the posted limit (same as the 23 Oct GTC page). Not a chase.</li>
<li><strong>Legal lock:</strong> original filled cash + fee, plus GTC fill at ≤ limit + estimated taker fee, versus NET_MAX 0.984. The filled leg’s later prices do not change that cash. If taker fees alone push over 0.984 while the two prices stay in cap, the table says so. Maker fees on a resting bid are not modeled (could be cheaper; we do not claim that).</li>
</ul>
<p class="note">Prior ask-come-back stamps used the same tick store and are not identical to this headline. 23 Oct page: 13/27 of known, median 82s (<a href="one_leg_miss_gtc_vs_flatten_20261023.html">one_leg_miss_gtc_vs_flatten_20261023.html</a>). Flatten tape 24 Oct 18:19 ET: 14/31 of known (<a href="flatten_rule_and_tape_20261024.html">flatten_rule_and_tape_20261024.html</a>). Those counted send-day ask come-back, including still-open, and stopped at absorb/last tick rather than settle. This refresh is through {esc(now.strftime("%Y-%m-%d %H:%M ET"))}, settle window, open games out of denom.</p>

<h2>Universe</h2>
<p>Universe from flatten + both-sides: <strong>32 simultaneous lock-bot one-legs</strong> / <strong>47</strong> <code>event=one_leg</code> diary rows / <strong>69</strong> dual lock sends on the both-sides page. This table is the 32 (refreshed through today). Simultaneous IOC pairs on tape: {esc(summary['n_pairs'])}. Both filled {esc(summary['n_both_filled'])}. Both empty {esc(summary['n_both_unfilled'])}. One-leg {esc(summary['n'])}. Ambiguous qty {esc(summary['n_unknown_qty'])}. Diary <code>event=one_leg</code>: {esc(summary['n_one_leg_event'])} (all lock-bot). Dual-send frequency stays on <a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a> (not overwritten here).</p>
<p class="note">Settled or void in the headline denom: {esc(summary['n_settled'])} one-legs, of which {esc(summary['n_denom'])} have later missed-book ticks. Still open: {esc(summary['n_open'])} ({esc(summary['n_open_already'])} already show an ask ≤ limit while the game is still live — not counted as a settled hit). Unknown game status: {esc(summary['n_unknown_game'])}. Flatten fills on this book: {esc(summary['n_flatten'])}, flatten P&amp;L {esc(cents(summary['sum_flatten']))}.</p>
<p class="note">Ask ≤ limit on <em>all</em> one-legs with ticks, including still-open (the old 14/31 style): {esc(summary['n_ask_hit_all'])}/{esc(summary['n_ask_known_all'])} = {esc(pct_txt(summary['n_ask_hit_all'], summary['n_ask_known_all']))}.</p>

<h2>Every lock-bot one-leg</h2>
<p class="note">Click column headers to sort. P&amp;L is dollars per 1-contract pair, shown in cents. GTC lock P&amp;L is $1 minus both all-in costs when the pair is a complementary Yes+No (or tennis twin). Actual is flatten round-trip when we dumped, else leftover hold-to-settle. Swipe sideways to see more columns.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{table(headers, rows, total)}

<h2>What this does not do</h2>
<ul>
<li>Does not rest or wire GTC. Cancel-on-resolve is still missing.</li>
<li>Does not change D=0.25 or NET_MAX 0.984.</li>
<li>Does not flatten, sell, start a second Strategy B, edit <code>live_lock_orders.py</code>, or commit.</li>
</ul>
<p class="note">Sources: local <code>orders.jsonl</code> / <code>order_io.jsonl</code> (simultaneous IOC, confirm qty), venue fill-history pull when present, <code>price_memory</code> ask ticks (dated shards plus archive), leftover_watch_stats, odds_cross_settlements cache. House fees: Kalshi GET fee when present else 0.07×p×(1−p); Polymarket theta×p×(1−p); Gemini 0.07×p×(1−p) ceiled to a cent. Pulled {esc(now.strftime("%Y-%m-%d %H:%M ET"))}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def main() -> None:
    now = datetime.now(ET)
    print("building one-leg events", flush=True)
    misses, counts = oneleg.build_events()
    print(f"one-leg N={len(misses)} pairs={counts.get('n_simultaneous_pairs')}", flush=True)
    events = oneleg.load_jsonl(RAW / "orders.jsonl")
    tape = count_tape_events(events)
    print("loading ask ticks (send day + next two)", flush=True)
    attach_ask_ticks(misses)
    flatten.attach_game_yes_ticks(misses)
    watch_stats = flatten.load_jsonl(RAW / "leftover_watch_stats.jsonl")
    settlements = load_settlements()
    for row in misses:
        row["flat_attempt"] = flatten.flatten_attempt_of(row, events)
        row["watch"] = flatten.leftover_watch_of(row, watch_stats)
        row["hold"] = flatten.hold_to_settle(row, settlements)
        classify_game(row, settlements)
        score_gtc(row)
    summary = summarize(misses, counts, tape)
    write_html(misses, summary, now)
    print(json.dumps({
        "n": summary["n"],
        "hit": summary["n_hit"],
        "denom": summary["n_denom"],
        "pct": summary["pct"],
        "median_s": summary["median_s"],
        "legal": summary["n_legal"],
        "fee_break": summary["n_fee_break"],
        "open": summary["n_open"],
        "ask_all": f"{summary['n_ask_hit_all']}/{summary['n_ask_known_all']}",
        "pairs": summary["n_pairs"],
        "one_leg_events": summary["n_one_leg_event"],
        "page": str(PAGE),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
