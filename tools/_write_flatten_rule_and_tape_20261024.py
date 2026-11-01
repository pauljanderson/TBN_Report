"""Research only: live flatten rule from code + one-leg tape.

Does not place, cancel, flatten, sell, or rest GTC. Does not start a second
live_strategy_b.py. Does not change the live flatten rule. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
import json
import re
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
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from write_orders_performance import (  # noqa: E402
    ddec,
    game_norm,
    game_winner,
    last_name,
    load_settlements,
    parse_dt,
    same_player,
    ticker_result,
)

oneleg = __import__("_write_one_leg_miss_gtc_vs_flatten_20261023")

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "flatten_rule_and_tape_20261024.html"
ONE = Decimal("1")
ABSORB_LO = Decimal("0.05")
ABSORB_HI = Decimal("0.95")
SKIP_ABSORBED_AT = datetime(2026, 10, 23, 11, 0, 0, tzinfo=ET)
WATCH_DEADLINE = getattr(live_lock_orders, "WATCH_DEADLINE", None)

ASKED = (
    "Tell him about the flatten rule in place. He thinks he'd like to adjust it "
    "but might want some data first."
)

# Venue-confirmed winners from prior Drive stamps / Paul answers. Not name guesses.
KNOWN_WINNERS = {
    "meligeni alves vs zarate": ("alves", "Kalshi MEL result=yes / ZAR result=no, alves_zarate_20261023.html"),
    "moutet vs paul": ("paul", "Moutet vs Paul T0: Paul Yes paid; moutet_paul_t0_20261023.html"),
    "ribecai vs houkes": ("ribecai", "Paul: bought No Ribecai, $1 payout, lost — Ribecai won"),
}


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


def venue_label(name: str | None) -> str:
    return oneleg.venue_label(name)


def load_jsonl(path: Path) -> list[dict]:
    return oneleg.load_jsonl(path)


def leftover_player(row: dict) -> str:
    """Player the leftover contract is on. Kalshi suffix MEL/ZAR vs both names in that half of vs."""
    fill = row["fill"]
    game = str(row.get("game") or "")
    inst = str(fill.get("instrument") or "")
    suffix = inst.rsplit("-", 1)[-1].strip().lower()
    parts = re.split(r"\bvs\.?\b", game_norm(game))
    if suffix and len(suffix) >= 3 and not suffix[:3].isdigit() and not suffix.startswith("aec"):
        for part in parts:
            bits = [tok for tok in part.split() if tok]
            if any(tok.startswith(suffix[:3]) or suffix.startswith(tok[:3]) for tok in bits):
                return last_name(part)
    named = oneleg.ticker_player(inst, game)
    if named:
        return named
    claim = re.sub(r"\bwins?\b", "", str(row.get("player") or ""), flags=re.I).strip()
    return last_name(claim) or claim


def flatten_attempt_of(row: dict, events: list[dict]) -> dict:
    """HTTP + skip-reason + confirm qty for the flatten of this one-leg."""
    later = oneleg.later_sends(events, row["pair"]["end_index"], row["key"], None)
    sents = [
        ev for ev in later
        if ev.get("event") == "sent" and str(ev.get("step") or "") in {"flatten", "extra-flatten"}
    ]
    flags = [ev for ev in later if ev.get("event") in {"flatten_filled", "flatten_miss"}]
    skips = [
        ev for ev in later
        if ev.get("event") == "skip" and "flatten" in str(ev.get("reason") or ev.get("note") or "").lower()
    ]
    reason = str((skips[0].get("reason") if skips else "") or "")
    sent = sents[0] if sents else None
    posted = sent is not None
    attempted = posted or bool(flags) or bool(skips) or bool(reason)
    if "flatten book empty" in reason or "flatten no takeable size" in reason:
        attempted = True
        posted = posted
    if "flatten spec missing" in reason:
        attempted = True
    status = {
        "attempted": attempted,
        "posted": posted,
        "reason": reason,
        "http": row.get("flatten_http") or "",
        "qty": Decimal("1") if row.get("flatten_filled") else Decimal("0"),
        "sent_at": oneleg.event_time(sent) if sent else (parse_dt(skips[0].get("at")) if skips else None),
        "side": str((sent or {}).get("side") or (flags[0].get("side") if flags else "") or ""),
        "venue": str((sent or {}).get("venue") or (flags[0].get("venue") if flags else "") or row["fill"]["venue"]),
        "instrument": str((sent or {}).get("instrument") or row["fill"].get("instrument") or ""),
        "limit": ddec((sent or {}).get("limit_price") or (sent or {}).get("quote_price")),
    }
    if row.get("flatten_filled"):
        status["qty"] = Decimal("1")
        status["outcome"] = "flatten filled"
    elif posted and not row.get("flatten_filled"):
        status["outcome"] = "flatten miss (HTTP posted, confirm qty 0)"
    elif "no takeable size" in reason:
        status["outcome"] = "flatten not posted — no takeable size of 1"
    elif "book empty" in reason:
        status["outcome"] = "flatten not posted — book empty"
    elif attempted:
        status["outcome"] = "flatten attempted, no fill"
    else:
        status["outcome"] = "flatten not on tape (leftover-watch era or skip not logged)"
    fill_t = row.get("start")
    flat_t = status.get("sent_at")
    if fill_t and flat_t:
        status["minutes"] = round((flat_t - fill_t).total_seconds() / 60.0, 2)
    else:
        status["minutes"] = None
    return status


def leftover_watch_of(row: dict, stats: list[dict]) -> dict:
    game = game_norm(str(row.get("game") or ""))
    start = row.get("start")
    hits = []
    for ev in stats:
        if game_norm(str(ev.get("game") or "")) != game:
            continue
        seen = parse_dt(ev.get("seen_at"))
        if start and seen and seen < start - timedelta(minutes=2):
            continue
        hits.append(ev)
    events = [str(ev.get("event") or "") for ev in hits]
    stop = next(
        (
            ev for ev in hits
            if str(ev.get("event") or "") in {
                "deadline", "resolved_first", "never_profitable", "ioc_miss",
                "ioc_filled", "ioc_partial", "already_both",
            }
        ),
        None,
    )
    minutes = None
    if stop is not None:
        minutes = stop.get("minutes_open")
        if minutes is None and start:
            seen = parse_dt(stop.get("seen_at"))
            if seen:
                minutes = round((seen - start).total_seconds() / 60.0, 2)
    return {
        "n": len(hits),
        "events": events,
        "stop": str((stop or {}).get("event") or ""),
        "minutes": minutes,
        "ioc_filled": any(ev == "ioc_filled" for ev in events),
        "ioc_miss": any(ev == "ioc_miss" for ev in events),
    }


def known_winner(game: str) -> tuple[str, str]:
    g = game_norm(game)
    for needle, pair in KNOWN_WINNERS.items():
        if needle in g or g in needle:
            return pair
    return "", ""


def player_on_game(player: str, game: str) -> bool:
    if not player or not game:
        return False
    parts = re.split(r"\bvs\.?\b", game_norm(game))
    return any(same_player(player, part) or same_player(player, last_name(part)) for part in parts)


def absorb_winner_from_ticks(row: dict) -> tuple[str, str]:
    """Last absorbing Yes print on this game after the leftover fill. Not a venue GET."""
    sport = str(row.get("sport") or "").lower()
    market = str(row.get("market") or "").lower()
    if "football" in sport and market in {"total", "totals", "spread", "over", "under"}:
        return "", "totals/spread leftover — not a moneyline absorb"
    start = row.get("start")
    ticks = row.get("_game_yes_ticks") or []
    game = str(row.get("game") or "")
    if start is None or not ticks:
        return "", "no Yes ticks after fill"
    last_hi = None
    last_lo = None
    for tick in ticks:
        seen = parse_dt(tick.get("seen_at"))
        if seen is None or seen <= start:
            continue
        px = ddec(tick.get("price"))
        if px is None:
            continue
        player = last_name(str(tick.get("side") or ""))
        if not player or not player_on_game(player, game):
            continue
        if px >= ABSORB_HI:
            last_hi = (player, px, seen)
        elif px <= ABSORB_LO:
            last_lo = (player, px, seen)
    if last_hi:
        return last_hi[0], f"Yes ask {money4(last_hi[1])} at {clock(last_hi[2])} (absorb ≥95¢)"
    if last_lo:
        return "!" + last_lo[0], f"{last_lo[0]} Yes ask {money4(last_lo[1])} at {clock(last_lo[2])} (absorb ≤5¢)"
    return "", "ticks exist, no 5¢/95¢ absorb after fill on this title's names"


def attach_game_yes_ticks(misses: list[dict]) -> None:
    for row in misses:
        row["_game_yes_ticks"] = []
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in misses:
        groups[(row.get("_sport") or "", row.get("_day") or "")].append(row)
    for (sport, day), group in groups.items():
        if not day:
            continue
        needles = set()
        for row in group:
            needles.update(tok for tok in oneleg.game_tokens(str(row.get("game") or "")) if len(tok) >= 3)
        ticks = []
        import price_memory
        for tick in price_memory.iter_ticks(sport=sport or None, day=day or None):
            if str(tick.get("pay") or "").lower() != "yes":
                continue
            blob = str(tick.get("game") or "").lower()
            if needles and not any(tok in blob for tok in needles):
                continue
            ticks.append(tick)
        for row in group:
            want = oneleg.game_tokens(str(row.get("game") or ""))
            matched = []
            for tick in ticks:
                have = oneleg.game_tokens(str(tick.get("game") or ""))
                if len(want) >= 2:
                    if not (want <= have):
                        continue
                elif not (want and have and (want & have)):
                    continue
                matched.append(tick)
            row["_game_yes_ticks"] = matched


def hold_to_settle(row: dict, settlements: list[dict]) -> dict:
    fill = row["fill"]
    player = leftover_player(row)
    book = str(fill.get("side") or "").lower()
    inst = str(fill.get("instrument") or "")
    cost = (fill.get("cash") or Decimal("0")) + (fill.get("fee") or Decimal("0"))
    ticker = ticker_result(settlements, inst)
    source = ""
    winner = ""
    if ticker in {"yes", "no"}:
        winner = player if ticker == "yes" else ("!" + player if player else "")
        source = f"settlement cache ticker result={ticker}"
    if not winner:
        gw = game_winner(settlements, str(row.get("game") or ""))
        if gw:
            winner = gw
            source = f"settlement cache game winner {gw}"
    if not winner:
        known, why = known_winner(str(row.get("game") or ""))
        if known:
            winner = known
            source = why
    if not winner:
        absorb, why = absorb_winner_from_ticks(row)
        if absorb:
            winner = absorb
            source = why
    if not winner:
        return {
            "status": "unknown",
            "winner": "",
            "source": source or "no settlement ticker, no absorb, no prior venue fact",
            "pnl": None,
        }
    lost_named = winner.startswith("!")
    named = winner[1:] if lost_named else winner
    player_won = (not lost_named) and same_player(player, named)
    if lost_named:
        player_won = not same_player(player, named)
    if book == "yes":
        leftover_won = player_won
    elif book == "no":
        leftover_won = not player_won
    else:
        return {"status": "unknown", "winner": named, "source": source, "pnl": None}
    pnl = (ONE - cost) if leftover_won else (Decimal("0") - cost)
    return {
        "status": "win" if leftover_won else "lose",
        "winner": named if not lost_named else f"not {named}",
        "source": source,
        "pnl": pnl,
    }


def slice_rows(misses: list[dict], start: datetime | None, end: datetime | None = None) -> list[dict]:
    out = []
    for row in misses:
        stamp = row.get("start")
        if stamp is None:
            continue
        if start is not None and stamp < start:
            continue
        if end is not None and stamp >= end:
            continue
        out.append(row)
    return out


def summarize_slice(rows: list[dict]) -> dict:
    flats = [row for row in rows if row.get("flatten_filled") and row.get("flatten_pnl") is not None]
    flat_pnls = [row["flatten_pnl"] for row in flats]
    wins = [row for row in flats if row["flatten_pnl"] > 0]
    holds = [row for row in rows if row.get("hold") and row["hold"].get("pnl") is not None]
    hold_pnls = [row["hold"]["pnl"] for row in holds]
    both = [
        row for row in rows
        if row.get("flatten_pnl") is not None and row.get("hold") and row["hold"].get("pnl") is not None
    ]
    delta = [(row["hold"]["pnl"] - row["flatten_pnl"]) for row in both]
    leftover_held = [
        row for row in rows
        if not row.get("flatten_filled") and row.get("hold") and row["hold"].get("pnl") is not None
    ]
    leftover_lose = [row for row in leftover_held if row["hold"]["status"] == "lose"]
    leftover_win = [row for row in leftover_held if row["hold"]["status"] == "win"]
    flatten_cost_good = [
        row for row in both
        if row["hold"]["status"] == "win" and row["hold"]["pnl"] > row["flatten_pnl"]
    ]
    gtc_known = [row for row in rows if row.get("gtc_fill") is not None]
    gtc_yes = [row for row in gtc_known if row.get("gtc_fill")]
    return {
        "n": len(rows),
        "n_flatten": len(flats),
        "n_flatten_attempt": sum(1 for row in rows if (row.get("flat_attempt") or {}).get("attempted")),
        "n_flatten_miss": sum(
            1 for row in rows
            if (row.get("flat_attempt") or {}).get("attempted") and not row.get("flatten_filled")
        ),
        "sum_flatten": sum(flat_pnls, Decimal("0")),
        "n_flatten_win": len(wins),
        "flatten_win_pct": (Decimal(len(wins)) / Decimal(len(flats)) * 100) if flats else None,
        "n_hold": len(holds),
        "sum_hold": sum(hold_pnls, Decimal("0")),
        "n_both": len(both),
        "sum_delta": sum(delta, Decimal("0")),
        "n_flatten_dumped_winner": len(flatten_cost_good),
        "sum_flatten_dumped_winner": sum(
            (row["hold"]["pnl"] - row["flatten_pnl"]) for row in flatten_cost_good
        ) if flatten_cost_good else Decimal("0"),
        "n_leftover_settled": len(leftover_held),
        "n_leftover_win": len(leftover_win),
        "n_leftover_lose": len(leftover_lose),
        "sum_leftover": sum((row["hold"]["pnl"] for row in leftover_held), Decimal("0")) if leftover_held else Decimal("0"),
        "sum_actual_known": (
            sum(flat_pnls, Decimal("0"))
            + sum((row["hold"]["pnl"] for row in leftover_held), Decimal("0"))
        ),
        "n_gtc_known": len(gtc_known),
        "n_gtc_fill": len(gtc_yes),
        "pct_gtc": (Decimal(len(gtc_yes)) / Decimal(len(gtc_known)) * 100) if gtc_known else None,
        "median_flat_min": statistics.median(
            [row["flat_attempt"]["minutes"] for row in rows if (row.get("flat_attempt") or {}).get("minutes") is not None]
        ) if any((row.get("flat_attempt") or {}).get("minutes") is not None for row in rows) else None,
    }


def slice_table_rows(rows: list[dict]) -> tuple[list[list[str]], list[str]]:
    out = []
    for row in rows:
        fill = row["fill"]
        miss = row["miss"]
        att = row.get("flat_attempt") or {}
        hold = row.get("hold") or {}
        watch = row.get("watch") or {}
        delay = row.get("delay_s")
        gtc = {True: "yes", False: "no", None: "unknown"}[row.get("gtc_fill")]
        fill_txt = (
            f"{esc(venue_label(fill['venue']))} {esc(fill['side'])} "
            f"{money4(fill['cash'])} fee {money4(fill['fee'])} HTTP {esc(fill['http'])}"
        )
        miss_txt = (
            f"{esc(venue_label(miss['venue']))} {esc(miss['side'])} "
            f"ask {money4(miss.get('quote'))} limit {money4(miss.get('limit'))} "
            f"HTTP {esc(miss['http'])} qty 0"
        )
        flat_txt = esc(att.get("outcome") or "")
        if att.get("http"):
            flat_txt += f" HTTP {esc(att.get('http'))} qty {esc(att.get('qty'))}"
        if row.get("flatten_cash") is not None:
            flat_txt += f" @ {money4(row.get('flatten_cash'))} fee {money4(row.get('flatten_fee'))}"
        hold_txt = esc(hold.get("status") or "unknown")
        if hold.get("winner"):
            hold_txt += f" (winner {esc(hold.get('winner'))})"
        leftover_txt = "flattened"
        if not row.get("flatten_filled"):
            if watch.get("ioc_filled"):
                leftover_txt = "leftover watch later filled a hedge"
            elif watch.get("stop"):
                leftover_txt = f"leftover; watch {esc(watch.get('stop'))}"
            else:
                leftover_txt = "leftover; no watch stop on tape"
        mins = att.get("minutes")
        give = watch.get("minutes")
        mins_txt = "" if mins is None else f"{mins:.2f}"
        give_txt = "" if give is None else f"{give:.2f}"
        out.append([
            esc(clock(row.get("start"))),
            esc(row.get("game") or ""),
            esc(row.get("sport") or ""),
            fill_txt,
            miss_txt,
            flat_txt,
            dollars(row.get("flatten_pnl")),
            leftover_txt,
            hold_txt,
            dollars(hold.get("pnl")),
            dollars(
                (hold.get("pnl") - row["flatten_pnl"])
                if hold.get("pnl") is not None and row.get("flatten_pnl") is not None
                else None
            ),
            mins_txt,
            give_txt,
            gtc,
            "" if delay is None else f"{delay:.0f}",
            esc(hold.get("source") or row.get("tick_status") or ""),
        ])
    return out


def event_headers() -> list[tuple[str, str]]:
    return [
        ("When ET", "date"),
        ("Game", "text"),
        ("Sport", "text"),
        ("Filled leftover", "text"),
        ("Missed lock leg", "text"),
        ("Flatten attempt", "text"),
        ("Flatten P&L $", "num"),
        ("If flatten missed", "text"),
        ("Hold-to-settle", "text"),
        ("Hold P&L $", "num"),
        ("Hold − flatten $", "num"),
        ("Minutes to flatten", "num"),
        ("Minutes to leftover give-up", "num"),
        ("Missed ask came back?", "text"),
        ("Come-back delay s", "num"),
        ("Winner source", "text"),
    ]


def summary_row(label: str, s: dict) -> list[str]:
    pct = (
        f"{format(s['flatten_win_pct'].quantize(Decimal('0.1')), 'f')}%"
        if s["flatten_win_pct"] is not None else "—"
    )
    gtc = (
        f"{s['n_gtc_fill']}/{s['n_gtc_known']}"
        + (f" ({format(s['pct_gtc'].quantize(Decimal('0.1')), 'f')}%)" if s["pct_gtc"] is not None else "")
    )
    return [
        esc(label),
        str(s["n"]),
        str(s["n_flatten_attempt"]),
        str(s["n_flatten"]),
        str(s["n_flatten_miss"]),
        dollars(s["sum_flatten"]),
        pct,
        str(s["n_hold"]),
        dollars(s["sum_hold"]),
        dollars(s["sum_delta"]),
        str(s["n_flatten_dumped_winner"]),
        dollars(s["sum_flatten_dumped_winner"]),
        dollars(s["sum_leftover"]),
        gtc,
    ]


def named_examples(misses: list[dict]) -> str:
    moutet = [row for row in misses if "moutet" in str(row.get("game") or "").lower()]
    alves = [row for row in misses if "alves" in str(row.get("game") or "").lower() and "zarate" in str(row.get("game") or "").lower()]
    bits = ["<h2>Named examples — not the whole book</h2>"]
    bits.append(
        "<p>These two titles are the ones Paul already asked about. They sit in the "
        "full table; they are not a second sample.</p>"
    )
    bits.append("<h3>Moutet vs Paul — leftover then flatten</h3>")
    if not moutet:
        bits.append("<p>No lock-bot one-leg row matched.</p>")
    else:
        bits.append("<ul>")
        for row in moutet:
            fill = row["fill"]
            hold = row.get("hold") or {}
            extra = ""
            cash = fill.get("cash")
            if cash is not None and cash >= Decimal("0.80"):
                extra = (
                    " Kalshi UI Sold Yes = buy No. The 13¢ Polymarket Yes never filled; "
                    "this leftover was Kalshi No Moutet at 84¢."
                )
            elif str(fill.get("side") or "").lower() == "no":
                extra = " Kalshi UI Sold Yes = buy No on that ticker."
            bits.append(
                "<li>"
                f"{esc(clock(row.get('start')))}: leftover "
                f"{esc(venue_label(fill['venue']))} {esc(fill['side'])} "
                f"{money4(fill['cash'])} fee {money4(fill['fee'])}. "
                f"Flatten {(dollars(row.get('flatten_pnl')) if row.get('flatten_filled') else 'missed')}. "
                f"Hold-to-settle {esc(hold.get('status') or 'unknown')} "
                f"{dollars(hold.get('pnl'))} "
                f"({esc(hold.get('source') or '')})."
                f"{extra}"
                "</li>"
            )
        bits.append("</ul>")
        bits.append(
            '<p class="note">Detail: <a href="moutet_paul_t0_20261023.html">'
            "moutet_paul_t0_20261023.html</a>.</p>"
        )
    bits.append("<h3>Meligeni Alves vs Zarate — three flattens</h3>")
    if len(alves) != 3:
        bits.append(f"<p>Lock-bot one-leg rows on this title: {len(alves)} (expected 3).</p>")
    bits.append("<ul>")
    for i, row in enumerate(alves, 1):
        fill = row["fill"]
        hold = row.get("hold") or {}
        bits.append(
            "<li>"
            f"#{i} {esc(clock(row.get('start')))}: leftover "
            f"{esc(venue_label(fill['venue']))} {esc(fill['side'])} "
            f"{money4(fill['cash'])}. Flatten {dollars(row.get('flatten_pnl'))}. "
            f"Hold-to-settle would have been {esc(hold.get('status') or 'unknown')} "
            f"{dollars(hold.get('pnl'))}. Winner Alves (Kalshi MEL result=yes)."
            "</li>"
        )
    bits.append("</ul>")
    bits.append(
        '<p class="note">Lock tape: <a href="alves_zarate_20261023.html">'
        "alves_zarate_20261023.html</a>. Combined lock flatten cash on that page "
        "was −$0.0488 with fees. Flattened before finalize, so Alves winning does "
        "not change booked lock cash.</p>"
    )
    return "\n".join(bits)


def write_html(misses: list[dict], counts: dict, slices: dict[str, dict], now: datetime) -> None:
    inc = slices["inception"]
    skip = slices["since_skip"]
    last = slices["last48"]
    pct_gtc = (
        f"{format(inc['pct_gtc'].quantize(Decimal('0.1')), 'f')}%"
        if inc["pct_gtc"] is not None else "—"
    )
    headline = (
        f"{inc['n']} lock-bot one-leg events since inception. "
        f"{inc['n_flatten']} flatten fills, net {dollars(inc['sum_flatten'])} with fees "
        f"(round-trip win% {esc(format(inc['flatten_win_pct'].quantize(Decimal('0.1')), 'f') + '%' if inc['flatten_win_pct'] is not None else '—')}). "
        f"Booked cash on rows with a known leftover winner "
        f"(flatten P&L where we dumped + hold P&L where we did not): "
        f"{dollars(inc['sum_actual_known'])}. "
        f"If we had never flattened and held those same leftovers to settlement "
        f"(N={inc['n_hold']} known winners): {dollars(inc['sum_hold'])}. "
        f"On the {inc['n_both']} flattened rows that also have a winner, hold minus flatten is "
        f"{dollars(inc['sum_delta'])}."
    )
    summary_headers = [
        ("Slice", "text"),
        ("N one-leg", "num"),
        ("Flatten attempted", "num"),
        ("Flatten filled", "num"),
        ("Flatten miss / not posted", "num"),
        ("Net flatten P&L $", "num"),
        ("Flatten round-trip win%", "num"),
        ("N hold-to-settle known", "num"),
        ("Hold-to-settle P&L $", "num"),
        ("Hold − flatten $", "num"),
        ("Flatten dumped a later winner", "num"),
        ("$ left on those dumps", "num"),
        ("Leftover (not flattened) settled P&L $", "num"),
        ("Missed ask came back", "text"),
    ]
    event_rows = slice_table_rows(misses)
    event_total = [
        f"N={inc['n']}", "", "", "", "",
        f"{inc['n_flatten']} filled",
        dollars(inc["sum_flatten"]),
        "",
        f"{inc['n_hold']} known",
        dollars(inc["sum_hold"]),
        dollars(inc["sum_delta"]),
        "", "",
        f"{inc['n_gtc_fill']}/{inc['n_gtc_known']}",
        "",
        "",
    ]
    net_max = format(live_lock_orders.NET_MAX, "f")
    size = format(live_lock_orders.SIZE, "f")
    tick = live_lock_orders.WATCH_TICK_SEC
    deadline = (
        WATCH_DEADLINE.strftime("%Y-%m-%d %H:%M %Z")
        if WATCH_DEADLINE is not None
        else "none (removed 2026-10-24; leftover runs until settle / hedge fill / lock off / max-open)"
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
{report_page_extras.CACHE_META}
{report_page_extras.FORCE_RELOAD_SCRIPT}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flatten rule and tape — 24 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
h3 {{ font-size: 1rem; margin: 1rem 0 0.3rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.hold {{ background: #eef2ff; border-color: #a5b4fc; }}
.note {{ color: #475569; font-size: 14px; }}
.hl {{ font-size: 1.12rem; }}
ul {{ margin-top: 0.3rem; }}
code {{ font-size: 0.9em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Flatten rule in place, and the tape since inception</h1>
<p class="note">Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. America/New_York. Research only. Not gold. Not DailyRun. Live flatten unchanged. Did not sell. Did not rest GTC. Did not start a second Strategy B. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>We tried to buy Yes on one shop and No on another for the same settlement, so a $1 payout covers the two tickets. Both orders go out at once as Immediate-or-Cancel (IOC: fill now or cancel). Sometimes only one shop fills. <strong>Flatten</strong> means dump that filled ticket back on <em>the same shop</em> by buying the opposite contract there, so we are not hanging a naked bet. <strong>Leftover</strong> means we failed to dump it and still hold it.</p>
<p>On Kalshi, buying No is posted as selling Yes. The Yes page then shows Sold Yes. That is the same cash as buying No. Polymarket buying No is a short buy. Size is one contract. Flatten is not trying to stay under the {esc(net_max)} lock cap — it is an unwind, even at a loss.</p>
</div>

<div class="callout ok">
<h2>Headline</h2>
<p class="hl"><strong>{esc(headline)}</strong></p>
<p>Missed price on the other venue came back on {esc(inc['n_gtc_fill'])} of {esc(inc['n_gtc_known'])} one-legs with later ticks ({esc(pct_gtc)} of known). The 23 Oct page was 13/27 of known; this refresh is through {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. A later ask print is not a guaranteed Good-Till-Cancel (GTC) fill. GTC leftover is <strong>not wired</strong>.</p>
</div>

<div class="callout hold">
<h2>HOLD — Paul chooses</h2>
<p>This page does not recommend wiring a new rule. Even if one column looks one-sided, the call is HOLD and you choose. Research only. Flatten-first stays as it is in live code until you say otherwise.</p>
</div>

<h2>Current rule (from live code, 24 Oct 2026)</h2>
<p class="note">Source: <code>tools/live_lock_orders.py</code>. Leftover tick also runs from <code>tools/live_game_pollers.py</code> (<code>ensure_watch_ticker</code> + a 60-second supervisor tick). The poller module docstring still says leftover “about every 20 seconds”; that comment is stale. Live cadence is <code>WATCH_TICK_SEC = {esc(tick)}</code>. Twenty seconds in code is websocket quote freshness (<code>WS_WATCH_FRESH_SEC</code>), not the sleep.</p>
<div class="callout">
<ol>
<li><strong>Send both legs together.</strong> After a live book recheck, two IOCs leave at the same time, size {esc(size)}, only if both books still have takeable size of 1 and after-fee net is at or under {esc(net_max)}.</li>
<li><strong>Both fill</strong> (Yes+No same player, or dual-Yes on opposite tennis names): keep them. No flatten. No leftover. No <code>orders_stopped.json</code>.</li>
<li><strong>Neither fills:</strong> latch is not written. Stop.</li>
<li><strong>Exactly one fills — flatten-first.</strong> Immediately buy the opposite on <em>that same venue and instrument</em> at the rechecked book ask. 1 IOC. This is <code>flatten_filled_leg</code>. It does <strong>not</strong> use NET_MAX {esc(net_max)} (<code>_one_ioc</code> skips <code>_profit_block</code> when <code>_flatten</code> is set). Dead function <code>_recovery_leg</code> is not called here: we do <strong>not</strong> retry the missed lock shop before flattening.</li>
<li><strong>Flatten fills:</strong> we are flat. No leftover watch. Latch is not written.</li>
<li><strong>Flatten misses</strong> (empty book, no takeable size of 1, or IOC qty 0): leftover watch starts. Then <code>orders_stopped.json</code> is written. That latch blocks <em>new</em> lock pairs. It does not stop leftover watch, and it does not stop flatten/recovery posts tagged <code>_watch_recovery</code>.</li>
<li><strong>Leftover watch</strong> (only after flatten miss): every {esc(tick)} second, quote true hedges of the filled player. Among venues whose after-fee net of leftover + hedge is at or under {esc(net_max)}, send one IOC, 1 contract, cheapest qualifying. A fill, a partial, or a zero-fill miss all mark that leftover attempt done — no second leftover IOC. Watch also stops on resolved market, never-profitable leftover, or the hard deadline {esc(deadline)} (that deadline is in the past as of this page, so leftover hunting currently dies as soon as the watch ticks).</li>
<li><strong>Same-shop opposite only for flatten.</strong> Buy Yes leftover → buy No (Kalshi: Sold Yes) on <em>that</em> venue/ticker. Buy No leftover → buy Yes on that same ticker. We never flatten a Kalshi Yes by selling a Gemini No.</li>
<li><strong>What leftover watch may buy after flatten misses:</strong> the missed intended instrument, same-player No on another shop, or opponent Yes that completes a dual-Yes lock. <strong>Never opponent-No as a hedge of a Yes-dog leftover</strong> (Goffin / Onclin). That gate is still live in <code>_hedge_outcome_for_venue</code>.</li>
<li><strong>Order on a tick that could do several things:</strong> new-pair send is blocked if the latch is on or a leftover watch is open. Flatten of a just-filled one-leg runs inside that send, before leftover watch, before the latch. Leftover watch does not fire flatten-uncapped again; after a miss it only sends NET_MAX hedges, once.</li>
<li><strong>Lock gap off:</strong> leftover/flatten still run. New lock pairs do not.</li>
<li><strong>GTC leftover:</strong> not wired. Live Kalshi/Gemini/Poly/Novig lock and flatten bodies are IOC. The only GTC in this module is <code>probe_gemini_once</code>, a maker-or-cancel that refuses to run while <code>ORDERS_ENABLED</code> is true and cancels if still open. Not leftover flatten.</li>
</ol>
</div>
<p class="note">Kalshi: Yes = bid, No = ask (UI Sold Yes). Polymarket: Yes = BUY_LONG, No = BUY_SHORT. Gemini: <code>outcome</code> yes/no, <code>timeInForce</code> immediate-or-cancel. Size cap stays 1.</p>

<h2>Decision table — slices</h2>
<p class="note">Inception = every lock-bot simultaneous one-leg since the stamp started. Since skip-absorbed-B = leftover fills at or after 2026-10-23 11:00 ET, after lock stopped hunting tennis games Strategy B still holds (including absorbed T0). Last 48 hours = leftover fills at or after {esc((now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M ET"))}. Hold-to-settle uses venue ticker result, then a prior venue-confirmed winner, then in-match Yes absorb (≥95¢ / ≤5¢). Unknown stays unknown. Click headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{table(summary_headers, [
    summary_row("Inception", inc),
    summary_row("Since skip-absorbed-B (2026-10-23 11:00 ET)", skip),
    summary_row("Last 48 hours", last),
])}

<p class="note">Simultaneous lock-bot pairs on tape: {esc(counts.get("n_simultaneous_pairs"))}. Both filled {esc(counts.get("n_both_filled"))}. Both empty {esc(counts.get("n_both_unfilled"))}. One-leg {esc(counts.get("n_one_leg"))}. Ambiguous qty {esc(counts.get("n_unknown_qty"))}. Strategy B extra-flatten / T0-flatten is a separate helper on the same <code>flatten_filled_leg</code>; those tennis-b rows are not in this lock-bot book.</p>

{named_examples(misses)}

<h2>If flatten-first is costing money vs leftovers we failed to dump</h2>
<p>Flatten dumped a leftover that later would have won on <strong>{esc(inc['n_flatten_dumped_winner'])}</strong> known rows. Dollars left on the table versus those dumps: <strong>{esc(dollars(inc['sum_flatten_dumped_winner']))}</strong> (hold P&amp;L minus actual flatten P&amp;L). Leftovers we did <em>not</em> flatten, then settled: N={esc(inc['n_leftover_settled'])}, {esc(inc['n_leftover_win'])} won / {esc(inc['n_leftover_lose'])} lost, net {esc(dollars(inc['sum_leftover']))}.</p>
<p>Read those two numbers together. A small flatten-loss book can still be cheaper than holding dogs that go to zero. A large dump of a leftover that later paid $1 is the other mistake. Neither number is a wire instruction.</p>

<h2>Every lock-bot one-leg since inception</h2>
<p class="note">Venue-confirm qty ≥ 1 on one shop and qty 0 on the other. Flatten P&amp;L is leftover all-in plus flatten all-in versus $1, with documented fees. Hold-to-settle is the same leftover held to the winner, no flatten. Swipe sideways to see more columns.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{table(event_headers(), event_rows, event_total)}

<h2>Options, not wires</h2>
<p>Sketches only. None of these is implemented. None is gold.</p>
<ol>
<li><strong>Wait N seconds before flatten.</strong> Keep the leftover, let leftover watch hunt the missed lock shop first, then flatten if still naked. Tradeoff: the same-shop opposite may vanish in those N seconds (today flatten is one-shot at the rechecked book).</li>
<li><strong>GTC flatten on the same shop.</strong> Rest a Good-Till-Cancel opposite on the origin ticker instead of IOC. Cancel-on-resolve is still missing, so a live GTC could still be open after the match ends. Not wired.</li>
<li><strong>Never flatten tennis.</strong> Tennis leftovers move fast; some dumped winners in the table are tennis. College-football leftovers are a different animal. This would be a sport gate, not a new exit math.</li>
<li><strong>Only flatten if the same-shop opposite is within X¢ of the leftover fill.</strong> Dump when the round-trip is close to $1; otherwise hold. Today flatten ignores NET_MAX and will pay a wide spread (see Fruhvirtova flatten around −20¢).</li>
</ol>

<h2>What this page did not do</h2>
<ul>
<li>Did not change the live flatten rule.</li>
<li>Did not rest GTC, sell tickets, or start a second <code>live_strategy_b.py</code>.</li>
<li>Did not overwrite <code>orders_performance.html</code> beyond a one-line sibling link if present.</li>
<li>Research only. Not gold. Not DailyRun.</li>
</ul>
<p class="note">Sources: <code>tools/live_lock_orders.py</code> (flatten_filled_leg, _send_pair, _one_ioc NET_MAX skip, leftover watch, latch), <code>tools/live_game_pollers.py</code> (ensure_watch_ticker, supervisor tick), local <code>orders.jsonl</code> / <code>order_io.jsonl</code> / leftover_watch_stats.jsonl / venue fill-history pull / price_memory ticks / odds_cross_settlements cache. Prior stamps: one_leg_miss_gtc_vs_flatten_20261023.html, moutet_paul_t0_20261023.html, alves_zarate_20261023.html, orders.html. Pulled {esc(now.strftime("%Y-%m-%d %H:%M ET"))}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}")


def maybe_link_orders_performance() -> None:
    path = STAMP / "orders_performance.html"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    marker = "flatten_rule_and_tape_20261024.html"
    line = (
        f'<p class="note">Flatten rule (live, unchanged) and one-leg tape: '
        f'<a href="{marker}">{marker}</a>.</p>\n'
    )
    if marker in text:
        return
    needle = "<h1>Live prediction-market orders performance</h1>"
    if needle not in text:
        print("orders_performance.html: no h1 needle; skipped one-line link")
        return
    path.write_text(text.replace(needle, needle + "\n" + line, 1), encoding="utf-8")
    print(f"linked {path}")


def main() -> None:
    now = datetime.now(ET)
    print("building one-leg events", flush=True)
    misses, counts = oneleg.build_events()
    print(f"one-leg N={len(misses)}", flush=True)
    oneleg.attach_ticks(misses)
    attach_game_yes_ticks(misses)
    events = load_jsonl(RAW / "orders.jsonl")
    watch_stats = load_jsonl(RAW / "leftover_watch_stats.jsonl")
    settlements = load_settlements()
    for row in misses:
        row["flat_attempt"] = flatten_attempt_of(row, events)
        row["watch"] = leftover_watch_of(row, watch_stats)
        row["hold"] = hold_to_settle(row, settlements)
    slices = {
        "inception": summarize_slice(misses),
        "since_skip": summarize_slice(slice_rows(misses, SKIP_ABSORBED_AT)),
        "last48": summarize_slice(slice_rows(misses, now - timedelta(hours=48))),
    }
    write_html(misses, counts, slices, now)
    maybe_link_orders_performance()
    print(json.dumps({
        "n": slices["inception"]["n"],
        "flatten_filled": slices["inception"]["n_flatten"],
        "flatten_pnl": str(slices["inception"]["sum_flatten"]),
        "hold_pnl": str(slices["inception"]["sum_hold"]),
        "hold_minus_flatten": str(slices["inception"]["sum_delta"]),
        "gtc_comeback": f"{slices['inception']['n_gtc_fill']}/{slices['inception']['n_gtc_known']}",
        "since_skip_n": slices["since_skip"]["n"],
        "last48_n": slices["last48"]["n"],
        "dumped_winners": slices["inception"]["n_flatten_dumped_winner"],
    }, indent=2))


if __name__ == "__main__":
    main()
