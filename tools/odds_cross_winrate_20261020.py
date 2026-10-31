"""Implied-odds up-cross win rates from prediction-market price memory.

Research only. Reads public catalogs and public venue APIs. Does not place,
cancel, or amend orders. Does not print secrets. Does not touch orders_stopped.json.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from price_memory import iter_tick_lines, market_type_from, norm_number, norm_side, parse_time, sport_from_name, to_et
HISTORY = RAW / "price_memory.jsonl"
PAGE = STAMP / "odds_cross_winrate_20261020.html"
SETTLE_CACHE = RAW / "odds_cross_settlements_20261020.json"
CROSSES_CACHE = RAW / "odds_cross_events_20261020.json"
CROSSES_FULL = RAW / "odds_cross_full_20261020.json"
DECADE_CACHE = RAW / "odds_cross_decade_20261020.json"
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 stockresearch-odds-cross/1.0", "Accept": "application/json"}

ASKED = (
    "Take a look at the predictions system and tell me if they're what the results are when a game "
    "is on and the odds go from under 55% to over 60%, what are the odds that is a winner?  Do the "
    "same for 50% and 40%, 45 and 35? And maybe some others. Give me a report in HTML. keep track "
    "of these by sport and venue and game time did it cross before the game? during the game "
    "(at what time) ? give me as much data as you can. i'm looking to see if there is a certain "
    "percent of certain events that once they cross over for example the 60% mark that there is "
    "actually a 70% chance they win, etc."
)
ASKED_ROI = (
    "Follow-up: if we bet no on a side that goes from 60-70 during 15m - 60m after the start of a match, "
    "what would our average return on investment be? (given the results we've tracked thus far)"
)
ASKED_DECADE = (
    "ok. so can we also make the bands 30-39, 40-49, etc. and show the win % based on that"
)
PLAIN = (
    "A prediction-market price is a dollar from 0 to 1. That dollar is also an implied chance: "
    "0.60 means the venue is pricing that side at 60 percent. This page watches each named side's "
    "Yes price (the price you would pay for that side to happen). A hysteresis up-cross means the "
    "price was strictly below a lower floor, and later printed strictly above a higher bar. We "
    "count the first time that happens for each game, side, venue, and band — not every later tick. "
    "Then we ask: after that first cross, did that side actually win? Official win/loss comes from "
    "venue settlement (Kalshi result, Gemini resolution side). Markets that are still open stay "
    "pending and are left out of win rate. A last print at 99 cents, and not a $1.00 empty ask, "
    "is shown only as a labeled proxy, not as an official result. Split by sport, venue, and whether the cross was "
    "before listed start or at/after start, plus minutes into the game when we have a start time."
)
PLAIN_DECADE = (
    "A decade band is a ten-point implied-odds bucket. 30–39 means the Yes price printed at least "
    "once between 30 cents and 39 cents (0.30 ≤ price < 0.40). That is not hysteresis, and it is "
    "not “first print above a bar.” Two counts sit on this page and they are not the same: "
    "first print in each band lets a side land in several buckets in one game (opens 0.32, later "
    "prints 0.51 → 30–39 and 50–59; 40–49 only if a print actually sat in 0.40–0.50). Opener only "
    "uses the first Yes print we ever saw for that game, side, and venue — an opener at 0.72 is "
    "only 70–79. Win is still official Kalshi or Gemini settlement of that named side. Moneyline "
    "(who wins the game) is the primary table; spreads and totals are shown separately so they "
    "are not mixed into the moneyline win percent."
)

HYSTERESIS = [
    ("55→60", 0.55, 0.60),
    ("50→60", 0.50, 0.60),
    ("40→50", 0.40, 0.50),
    ("50→55", 0.50, 0.55),
    ("45→55", 0.45, 0.55),
    ("35→45", 0.35, 0.45),
    ("35→40", 0.35, 0.40),
    ("40→45", 0.40, 0.45),
    ("45→50", 0.45, 0.50),
    ("60→70", 0.60, 0.70),
    ("70→80", 0.70, 0.80),
]
SIMPLE_BARS = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80]
DECADE_LABELS = [f"{lo:02d}–{lo + 9:02d}" for lo in range(0, 100, 10)]
LEFTOVER_LABEL = "00–29 leftover"
DECADE_ORDER = {label: i for i, label in enumerate(DECADE_LABELS + [LEFTOVER_LABEL])}
DATE_TOKENS = ("26OCT16", "26OCT17", "26OCT18", "26OCT19", "26OCT20", "26OCT21")
EXTRA_SERIES = [
    "KXATPMATCH", "KXATPCHALLENGERMATCH", "KXWTAMATCH",
    "KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL", "KXNFLTEAMTOTAL",
    "KXNHLGAME", "KXNHLSPREAD", "KXNHLTOTAL",
    "KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL",
    "KXMLBGAME", "KXMLBSPREAD", "KXMLBTOTAL",
    "KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL",
    "KXWNBAGAME",
    "KXUCLGAME", "KXUCLSPREAD", "KXUCLTOTAL",
    "KXEPLGAME", "KXEPLSPREAD", "KXEPLTOTAL",
    "KXLIGAMXGAME", "KXLIGAMXSPREAD", "KXLIGAMXTOTAL",
    "KXMLSGAME", "KXNCAAMBGAME",
]
STOP = {"vs", "v", "the", "at", "fc", "cf", "sc", "and", "game"}


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, num: bool = False) -> str:
    text = "" if value is None else str(value)
    return f'<td>{esc(text)}</td>'


def http_get(url: str, tries: int = 3) -> dict | list | None:
    delay = 1.5
    for attempt in range(tries):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            return None
        except Exception:
            if attempt < tries - 1:
                time.sleep(delay)
                continue
            return None
    return None


def game_norm(text: str) -> str:
    low = uniclean(text)
    low = re.sub(r"\s+vs\.?\s+", " vs ", low)
    low = re.sub(r"\s+", " ", low).strip()
    return low


def uniclean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def side_keys(side: str, sport: str) -> list[str]:
    toks = [t for t in re.findall(r"[a-z0-9]+", uniclean(side)) if t not in STOP]
    if not toks:
        return []
    out = [" ".join(toks)]
    if (sport or "").lower() == "tennis" and len(toks) >= 2:
        out.append(toks[-1])
    return list(dict.fromkeys(out))


def as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 1:
        return None
    return number


def decade_label(price: float) -> str | None:
    """Disjoint decade: 30–39 is 0.30 ≤ price < 0.40. Skips exact 0 and 1."""
    if price is None or price <= 0.0 or price >= 1.0:
        return None
    d = Decimal(str(price)).quantize(Decimal("0.0001"))
    if d <= 0 or d >= 1:
        return None
    lo = (int(d * 100) // 10) * 10
    if lo < 0 or lo >= 100:
        return None
    return f"{lo:02d}–{lo + 9:02d}"


def in_leftover_0_29(price: float) -> bool:
    if price is None or price <= 0.0 or price >= 1.0:
        return False
    d = Decimal(str(price)).quantize(Decimal("0.0001"))
    return Decimal("0") < d < Decimal("0.30")


def iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return to_et(dt).isoformat()


def parse_dt(value) -> datetime | None:
    return parse_time(value) if value else None


def timing_bucket(cross_at: datetime | None, start: datetime | None) -> tuple[str, str, str]:
    """Return timing label, minutes-into-game text, and during-bucket."""
    if cross_at is None or start is None:
        return "unknown", "", "unknown"
    cross_at = to_et(cross_at)
    start = to_et(start)
    if cross_at < start:
        return "before", "", "before"
    minutes = (cross_at - start).total_seconds() / 60.0
    if minutes < 15:
        bucket = "0–15m"
    elif minutes < 60:
        bucket = "15–60m"
    else:
        bucket = "60m+"
    return "during", f"{minutes:.1f}", bucket


def pct(wins: int, n: int) -> str:
    if n <= 0:
        return ""
    return f"{100.0 * wins / n:.1f}"


def tiny_note(n: int) -> str:
    if n <= 0:
        return "no settled rows"
    if n < 20:
        return "tiny sample"
    if n < 50:
        return "small sample"
    return ""


class KeyState:
    __slots__ = (
        "sport", "game", "kind", "side", "side_key", "number", "venue",
        "game_start", "last_price", "last_seen", "first_below", "h_done", "s_done",
    )

    def __init__(self, rec: dict):
        self.sport = rec.get("sport") or "unknown"
        self.game = rec.get("game") or ""
        self.kind = rec.get("market_type") or ""
        self.side = rec.get("side") or rec.get("side_label") or ""
        self.side_key = rec.get("side_key") or norm_side(self.side, self.kind)
        self.number = rec.get("number") or ""
        self.venue = rec.get("venue") or ""
        self.game_start = rec.get("game_start") or ""
        self.last_price = None
        self.last_seen = ""
        self.first_below = {}
        self.h_done = set()
        self.s_done = set()


def stream_crosses() -> dict:
    print("streaming yes ticks (archive + shards)", flush=True)
    states: dict[str, KeyState] = {}
    h_crosses: list[dict] = []
    s_crosses: list[dict] = []
    n_lines = 0
    n_yes = 0
    seen_min = None
    seen_max = None
    sports: dict[str, int] = defaultdict(int)
    venues: dict[str, int] = defaultdict(int)
    for line in iter_tick_lines():
            n_lines += 1
            if n_lines % 250000 == 0:
                print(f"  {n_lines} lines, {len(h_crosses)} hysteresis crosses", flush=True)
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if (rec.get("pay") or "yes").lower() != "yes":
                continue
            price = as_float(rec.get("price"))
            if price is None:
                continue
            # Kalshi's empty book after settlement prints Yes ask 1.00 / 0.00
            # on both sides. Those are not tradable implied odds.
            if price <= 0.0 or price >= 1.0:
                continue
            key = rec.get("key") or ""
            if not key:
                continue
            n_yes += 1
            seen = rec.get("seen_at") or ""
            if seen:
                if seen_min is None or seen < seen_min:
                    seen_min = seen
                if seen_max is None or seen > seen_max:
                    seen_max = seen
            st = states.get(key)
            if st is None:
                st = KeyState(rec)
                states[key] = st
                sports[st.sport] += 1
                venues[st.venue] += 1
            else:
                if rec.get("game_start") and not st.game_start:
                    st.game_start = rec.get("game_start") or ""
                if rec.get("sport") and st.sport in ("", "unknown"):
                    st.sport = rec["sport"]
            st.last_price = price
            st.last_seen = seen
            start = st.game_start
            for hid, lo, hi in HYSTERESIS:
                if hid in st.h_done:
                    continue
                if price < lo:
                    if hid not in st.first_below:
                        st.first_below[hid] = (price, seen)
                    continue
                if hid in st.first_below and price > hi:
                    below_px, below_at = st.first_below[hid]
                    cross_dt = parse_dt(seen)
                    start_dt = parse_dt(start)
                    timing, mins, bucket = timing_bucket(cross_dt, start_dt)
                    h_crosses.append({
                        "key": key,
                        "band": hid,
                        "lo": lo,
                        "hi": hi,
                        "sport": st.sport,
                        "game": st.game,
                        "market_type": st.kind,
                        "side": st.side,
                        "side_key": st.side_key,
                        "number": st.number,
                        "venue": st.venue,
                        "cross_time": seen,
                        "game_start": start,
                        "timing": timing,
                        "minutes_into_game": mins,
                        "during_bucket": bucket if timing == "during" else timing,
                        "first_below": below_px,
                        "first_below_at": below_at,
                        "first_above": price,
                        "phase_feed": rec.get("phase") or "",
                    })
                    st.h_done.add(hid)
            for bar in SIMPLE_BARS:
                if bar in st.s_done:
                    continue
                if price > bar:
                    cross_dt = parse_dt(seen)
                    start_dt = parse_dt(start)
                    timing, mins, bucket = timing_bucket(cross_dt, start_dt)
                    s_crosses.append({
                        "key": key,
                        "band": f"first>{int(bar * 100)}",
                        "bar": bar,
                        "sport": st.sport,
                        "game": st.game,
                        "market_type": st.kind,
                        "side": st.side,
                        "side_key": st.side_key,
                        "number": st.number,
                        "venue": st.venue,
                        "cross_time": seen,
                        "game_start": start,
                        "timing": timing,
                        "minutes_into_game": mins,
                        "during_bucket": bucket if timing == "during" else timing,
                        "first_above": price,
                        "phase_feed": rec.get("phase") or "",
                    })
                    st.s_done.add(bar)
    last_map = {
        key: {"price": st.last_price, "seen_at": st.last_seen, "game_start": st.game_start, "sport": st.sport}
        for key, st in states.items()
    }
    print(
        f"stream done lines={n_lines} yes_ticks={n_yes} keys={len(states)} "
        f"h_crosses={len(h_crosses)} s_crosses={len(s_crosses)}",
        flush=True,
    )
    return {
        "n_lines": n_lines,
        "n_yes": n_yes,
        "n_keys": len(states),
        "seen_min": seen_min or "",
        "seen_max": seen_max or "",
        "sports": dict(sports),
        "venues": dict(venues),
        "h_crosses": h_crosses,
        "s_crosses": s_crosses,
        "last_map": last_map,
    }


def _decade_event(key: str, st: "KeyState", rec: dict, price: float, seen: str, band: str, defn: str) -> dict:
    start = st.game_start
    cross_dt = parse_dt(seen)
    start_dt = parse_dt(start)
    timing, mins, bucket = timing_bucket(cross_dt, start_dt)
    return {
        "key": key,
        "band": band,
        "sport": st.sport,
        "game": st.game,
        "market_type": st.kind,
        "side": st.side,
        "side_key": st.side_key,
        "number": st.number,
        "venue": st.venue,
        "cross_time": seen,
        "game_start": start,
        "timing": timing,
        "minutes_into_game": mins,
        "during_bucket": bucket if timing == "during" else timing,
        "first_above": price,
        "phase_feed": rec.get("phase") or "",
        "defn": defn,
    }


def stream_decade_bands() -> dict:
    """First print in each decade band, plus opener-only, per (game, side, venue)."""
    print("streaming decade bands (archive + shards)", flush=True)
    states: dict[str, KeyState] = {}
    first_in_band: list[dict] = []
    opener: list[dict] = []
    n_lines = 0
    n_yes = 0
    for line in iter_tick_lines():
            n_lines += 1
            if n_lines % 250000 == 0:
                print(
                    f"  decade {n_lines} lines, first_in_band={len(first_in_band)} opener={len(opener)}",
                    flush=True,
                )
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if (rec.get("pay") or "yes").lower() != "yes":
                continue
            price = as_float(rec.get("price"))
            if price is None or price <= 0.0 or price >= 1.0:
                continue
            key = rec.get("key") or ""
            if not key:
                continue
            n_yes += 1
            seen = rec.get("seen_at") or ""
            st = states.get(key)
            if st is None:
                st = KeyState(rec)
                states[key] = st
            else:
                if rec.get("game_start") and not st.game_start:
                    st.game_start = rec.get("game_start") or ""
                if rec.get("sport") and st.sport in ("", "unknown"):
                    st.sport = rec["sport"]
            band = decade_label(price)
            if band is None:
                continue
            if "opener" not in st.h_done:
                opener.append(_decade_event(key, st, rec, price, seen, band, "opener"))
                st.h_done.add("opener")
            if band not in st.s_done:
                first_in_band.append(_decade_event(key, st, rec, price, seen, band, "first_in_band"))
                st.s_done.add(band)
            if in_leftover_0_29(price) and LEFTOVER_LABEL not in st.s_done:
                first_in_band.append(
                    _decade_event(key, st, rec, price, seen, LEFTOVER_LABEL, "first_in_band")
                )
                st.s_done.add(LEFTOVER_LABEL)
    leftover_open = []
    for row in opener:
        px = as_float(row.get("first_above"))
        if px is not None and in_leftover_0_29(px):
            item = dict(row)
            item["band"] = LEFTOVER_LABEL
            leftover_open.append(item)
    opener.extend(leftover_open)
    print(
        f"decade stream done lines={n_lines} yes_ticks={n_yes} keys={len(states)} "
        f"first_in_band={len(first_in_band)} opener={len(opener)}",
        flush=True,
    )
    return {
        "n_lines": n_lines,
        "n_yes": n_yes,
        "n_keys": len(states),
        "first_in_band": first_in_band,
        "opener": opener,
    }


def load_decade_cache() -> dict | None:
    if not DECADE_CACHE.is_file():
        return None
    try:
        data = json.loads(DECADE_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "first_in_band" not in data or "opener" not in data:
        return None
    print(f"reusing decade cache {DECADE_CACHE}", flush=True)
    return data


def save_decade_cache(payload: dict) -> None:
    DECADE_CACHE.write_text(json.dumps({
        "n_lines": payload.get("n_lines"),
        "n_yes": payload.get("n_yes"),
        "n_keys": payload.get("n_keys"),
        "first_in_band": payload["first_in_band"],
        "opener": payload["opener"],
    }), encoding="utf-8")
    print(f"cached decade bands {DECADE_CACHE}", flush=True)


def add_settlement(store: list[dict], row: dict) -> None:
    result = (row.get("result") or "").strip().lower()
    if result not in ("yes", "no"):
        return
    row = dict(row)
    row["result"] = result
    row["game_n"] = game_norm(row.get("game") or "")
    row["side_n"] = norm_side(row.get("side") or "", row.get("market_type") or "moneyline")
    row["number_n"] = "" if row.get("market_type") == "moneyline" else norm_number(row.get("number") or "")
    row["venue_n"] = (row.get("venue") or "").strip()
    store.append(row)


def load_local_settlements() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(RAW.glob("*gemini.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        sport = payload.get("sport") or sport_from_name(path.name)
        game = payload.get("game") or ""
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            title = event.get("title") or game
            for contract in event.get("contracts") or []:
                if not isinstance(contract, dict):
                    continue
                status = str(contract.get("status") or "").lower()
                side_res = str(contract.get("resolutionSide") or "").lower()
                if status not in ("settled", "closed") and side_res not in ("yes", "no"):
                    continue
                if side_res not in ("yes", "no"):
                    continue
                symbol = str(contract.get("instrumentSymbol") or contract.get("ticker") or "")
                strike = contract.get("strike") if isinstance(contract.get("strike"), dict) else {}
                kind = market_type_from(symbol, str(event.get("ticker") or ""), str(strike.get("type") or ""), str(title or ""))
                if kind is None and strike.get("type") in ("moneyline", "spread", "total"):
                    kind = strike["type"]
                if kind is None:
                    kind = "moneyline"
                number = strike.get("value") if kind != "moneyline" else ""
                add_settlement(rows, {
                    "source": "gemini_local",
                    "venue": "Gemini",
                    "sport": sport,
                    "game": title or game,
                    "market_type": kind,
                    "side": contract.get("label") or contract.get("abbreviatedName") or "",
                    "number": number,
                    "result": side_res,
                    "ticker": symbol,
                    "occurrence": contract.get("resolvedAt") or "",
                })
    for path in sorted(RAW.glob("*kalshi.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        sport = payload.get("sport") or sport_from_name(path.name)
        game = payload.get("game") or ""
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            for contract in event.get("contracts") or []:
                if not isinstance(contract, dict):
                    continue
                result = str(contract.get("result") or "").lower()
                if result not in ("yes", "no"):
                    continue
                ticker = str(contract.get("ticker") or "")
                kind = market_type_from(ticker, str(event.get("event_ticker") or ""), str(contract.get("title") or ""))
                if kind is None:
                    continue
                number = contract.get("floor_strike")
                add_settlement(rows, {
                    "source": "kalshi_local",
                    "venue": "Kalshi",
                    "sport": sport,
                    "game": game or event.get("title") or "",
                    "market_type": kind,
                    "side": contract.get("yes_sub_title") or contract.get("title") or "",
                    "number": number,
                    "result": result,
                    "ticker": ticker,
                    "occurrence": contract.get("occurrence_datetime") or "",
                })
    n_poly = 0
    poly_path = RAW / "polymarket_us_markets.jsonl"
    if poly_path.is_file():
        with poly_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                closed = rec.get("closed") is True
                status = str(rec.get("status") or "") + " " + str(rec.get("ep3Status") or "")
                settled = closed or "SETTLED" in status.upper() or "RESOLVED" in status.upper()
                if not settled:
                    continue
                prices = rec.get("outcomePrices")
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except json.JSONDecodeError:
                        prices = None
                outcomes = rec.get("outcomes")
                if isinstance(outcomes, str):
                    try:
                        outcomes = json.loads(outcomes)
                    except json.JSONDecodeError:
                        outcomes = None
                result = None
                if isinstance(prices, list) and isinstance(outcomes, list) and len(prices) == len(outcomes):
                    mapped = {str(o).lower(): as_float(p) for o, p in zip(outcomes, prices)}
                    yes = mapped.get("yes")
                    if yes is not None and yes >= 0.99:
                        result = "yes"
                    elif yes is not None and yes <= 0.01:
                        result = "no"
                if result is None:
                    continue
                kind = str(rec.get("marketType") or rec.get("sportsMarketType") or "moneyline").lower()
                if "spread" in kind:
                    kind = "spread"
                elif "total" in kind:
                    kind = "total"
                else:
                    kind = "moneyline"
                game = rec.get("event_title") or rec.get("question") or rec.get("title") or ""
                add_settlement(rows, {
                    "source": "polymarket_local",
                    "venue": "Polymarket",
                    "sport": str(rec.get("category") or ""),
                    "game": game,
                    "market_type": kind,
                    "side": rec.get("title") or rec.get("titleShort") or "",
                    "number": rec.get("line") or "",
                    "result": result,
                    "ticker": rec.get("slug") or "",
                    "occurrence": rec.get("gameStartTime") or rec.get("endDate") or "",
                })
                n_poly += 1
    print(f"local settlements {len(rows)} (polymarket closed with 0/1 prices {n_poly})", flush=True)
    return rows


def collect_series() -> list[str]:
    found = set(EXTRA_SERIES)
    for path in RAW.glob("*kalshi.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for event in (payload or {}).get("events") or []:
            ticker = str((event or {}).get("event_ticker") or "")
            series = ticker.split("-", 1)[0]
            if series.startswith("KX"):
                found.add(series)
    tennis = RAW / "polymarket_tennis_matches.json"
    if tennis.is_file():
        try:
            payload = json.loads(tennis.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        for match in payload.get("matches") or []:
            series = str(match.get("series") or "")
            if series:
                found.add(series)
            ticker = str(match.get("event_ticker") or "")
            if ticker:
                found.add(ticker.split("-", 1)[0])
    return sorted(found)


def ticker_in_window(ticker: str) -> bool:
    return any(tok in (ticker or "") for tok in DATE_TOKENS)


def kalshi_events_by_status(series: str, status: str, pages: int = 4) -> list[dict]:
    out = []
    cursor = ""
    older = 0
    for _ in range(pages):
        query = {"series_ticker": series, "status": status, "limit": "200"}
        if cursor:
            query["cursor"] = cursor
        payload = http_get("https://api.elections.kalshi.com/trade-api/v2/events?" + urllib.parse.urlencode(query))
        if not isinstance(payload, dict):
            break
        batch = payload.get("events") or []
        if not isinstance(batch, list) or not batch:
            break
        for event in batch:
            if not isinstance(event, dict):
                continue
            ticker = str(event.get("event_ticker") or "")
            if ticker_in_window(ticker):
                out.append(event)
                older = 0
            else:
                older += 1
        cursor = str(payload.get("cursor") or "")
        if not cursor or older >= 80:
            break
    return out


def kalshi_event_markets(event_ticker: str) -> list[dict]:
    payload = http_get(
        "https://api.elections.kalshi.com/trade-api/v2/markets?"
        + urllib.parse.urlencode({"event_ticker": event_ticker, "limit": "200"})
    )
    if payload is None:
        time.sleep(0.4)
        payload = http_get(
            "https://api.elections.kalshi.com/trade-api/v2/markets?"
            + urllib.parse.urlencode({"event_ticker": event_ticker, "limit": "200"})
        )
    if not isinstance(payload, dict):
        return []
    return [m for m in (payload.get("markets") or []) if isinstance(m, dict)]


def sport_from_series(series: str) -> str:
    s = series.upper()
    if "ATP" in s or "WTA" in s or "TENNIS" in s:
        return "tennis"
    if "NCAAF" in s:
        return "college football"
    if "NFL" in s:
        return "pro football"
    if "NHL" in s:
        return "pro hockey"
    if "MLB" in s:
        return "pro baseball"
    if "WNBA" in s:
        return "wnba"
    if "NBA" in s:
        return "pro basketball"
    if "UCL" in s or "EPL" in s or "LIGA" in s or "MLS" in s or "SOCCER" in s:
        return "soccer"
    if "NCAAMB" in s:
        return "college basketball"
    return ""


def fetch_kalshi_settlements() -> list[dict]:
    series_list = collect_series()
    print(f"kalshi series {len(series_list)}", flush=True)
    events = []
    seen = set()
    for series in series_list:
        batch = kalshi_events_by_status(series, "settled") + kalshi_events_by_status(series, "closed")
        print(f"  {series} settled/closed-in-window {len(batch)}", flush=True)
        for event in batch:
            ticker = str(event.get("event_ticker") or "")
            if ticker and ticker not in seen:
                seen.add(ticker)
                events.append(event)
        time.sleep(0.05)
    tennis = RAW / "polymarket_tennis_matches.json"
    if tennis.is_file():
        try:
            payload = json.loads(tennis.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        for match in payload.get("matches") or []:
            ticker = str(match.get("event_ticker") or "")
            if ticker and ticker not in seen:
                seen.add(ticker)
                events.append({"event_ticker": ticker, "title": match.get("title") or "", "series": match.get("series") or ""})
    print(f"fetching kalshi markets for {len(events)} events", flush=True)
    rows: list[dict] = []

    def one(event: dict) -> list[dict]:
        ticker = str(event.get("event_ticker") or "")
        title = event.get("title") or event.get("sub_title") or ""
        series = str(event.get("series") or ticker.split("-", 1)[0])
        sport = sport_from_series(series)
        found = []
        for market in kalshi_event_markets(ticker):
            result = str(market.get("result") or "").lower()
            if result not in ("yes", "no"):
                continue
            mticker = str(market.get("ticker") or "")
            kind = market_type_from(mticker, ticker, str(market.get("title") or ""))
            if kind is None:
                continue
            number = market.get("floor_strike")
            if number is None and kind != "moneyline":
                number = norm_number(str(market.get("yes_sub_title") or market.get("title") or ""))
            found.append({
                "source": "kalshi_api",
                "venue": "Kalshi",
                "sport": sport,
                "game": title,
                "market_type": kind,
                "side": market.get("yes_sub_title") or market.get("title") or "",
                "number": number,
                "result": result,
                "ticker": mticker,
                "occurrence": market.get("occurrence_datetime") or market.get("expected_expiration_time") or "",
            })
        return found

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(one, event) for event in events]
        done = 0
        empty = 0
        for fut in as_completed(futs):
            batch = fut.result() or []
            if not batch:
                empty += 1
            for item in batch:
                add_settlement(rows, item)
            done += 1
            if done % 50 == 0:
                print(f"  kalshi markets {done}/{len(events)} settlements {len(rows)} empty={empty}", flush=True)
    print(f"kalshi api settlements {len(rows)}", flush=True)
    return rows


def fetch_gemini_refresh() -> list[dict]:
    urls = []
    seen = set()
    for path in RAW.glob("*gemini.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sport = payload.get("sport") or sport_from_name(path.name)
        game = payload.get("game") or ""
        for event in payload.get("events") or []:
            url = str((event or {}).get("url") or "")
            ticker = str((event or {}).get("ticker") or "")
            if not url and ticker:
                url = "https://api.gemini.com/v1/prediction-markets/events/" + urllib.parse.quote(ticker, safe="")
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append((url, sport, game))
    print(f"refreshing {len(urls)} gemini events", flush=True)
    rows: list[dict] = []

    def one(item):
        url, sport, game = item
        payload = http_get(url)
        if not isinstance(payload, dict):
            return []
        title = payload.get("title") or game
        contracts = payload.get("contracts")
        if not isinstance(contracts, list) and isinstance(payload.get("event"), dict):
            contracts = payload["event"].get("contracts")
            title = title or payload["event"].get("title") or game
        found = []
        for contract in contracts or []:
            if not isinstance(contract, dict):
                continue
            side_res = str(contract.get("resolutionSide") or "").lower()
            if side_res not in ("yes", "no"):
                continue
            symbol = str(contract.get("instrumentSymbol") or contract.get("ticker") or "")
            strike = contract.get("strike") if isinstance(contract.get("strike"), dict) else {}
            kind = market_type_from(symbol, str(payload.get("ticker") or ""), str(strike.get("type") or ""), str(title or ""))
            if kind is None and strike.get("type") in ("moneyline", "spread", "total"):
                kind = strike["type"]
            if kind is None:
                kind = "moneyline"
            number = strike.get("value") if kind != "moneyline" else ""
            found.append({
                "source": "gemini_api",
                "venue": "Gemini",
                "sport": sport,
                "game": title or game,
                "market_type": kind,
                "side": contract.get("label") or contract.get("abbreviatedName") or "",
                "number": number,
                "result": side_res,
                "ticker": symbol,
                "occurrence": contract.get("resolvedAt") or payload.get("startTime") or "",
            })
        return found

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(one, item) for item in urls]
        for fut in as_completed(futs):
            for item in fut.result() or []:
                add_settlement(rows, item)
    print(f"gemini api settlements {len(rows)}", flush=True)
    return rows


def build_index(rows: list[dict]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        venue = (row.get("venue_n") or "").lower()
        game = row.get("game_n") or ""
        kind = row.get("market_type") or ""
        number = row.get("number_n") or ""
        sport = (row.get("sport") or "").lower()
        for alias in side_keys(row.get("side") or "", sport) or [row.get("side_n") or ""]:
            if not alias:
                continue
            index[f"{venue}|{game}|{kind}|{alias}|{number}"].append(i)
            index[f"*|{game}|{kind}|{alias}|{number}"].append(i)
            index[f"{venue}|{sport}|{kind}|{alias}|{number}"].append(i)
            index[f"*|{sport}|{kind}|{alias}|{number}"].append(i)
    return index


def pick_result(cands: list[dict]) -> tuple[str, str, str] | None:
    if not cands:
        return None
    results = {(r.get("result") or "", r.get("source") or "", r.get("ticker") or "") for r in cands}
    yesno = {r[0] for r in results if r[0] in ("yes", "no")}
    if yesno == {"yes"} or yesno == {"no"}:
        row = cands[0]
        return row["result"], row.get("source") or "", row.get("ticker") or ""
    return None


def lookup(cross: dict, settlements: list[dict], index: dict[str, list[int]]) -> tuple[str, str, str] | None:
    venue = (cross.get("venue") or "").strip()
    game = game_norm(cross.get("game") or "")
    kind = cross.get("market_type") or ""
    number = "" if kind == "moneyline" else norm_number(cross.get("number") or "")
    sport = (cross.get("sport") or "").lower()
    aliases = side_keys(cross.get("side") or cross.get("side_key") or "", sport)
    keys = []
    for alias in aliases:
        keys.extend([
            f"{venue.lower()}|{game}|{kind}|{alias}|{number}",
            f"*|{game}|{kind}|{alias}|{number}",
        ])
    seen = set()
    cands = []
    for key in keys:
        for i in index.get(key) or []:
            if i in seen:
                continue
            seen.add(i)
            row = settlements[i]
            if venue and venue.lower() not in ("novig",) and (row.get("venue_n") or "").lower() != venue.lower():
                # Prefer same venue; still keep as fallback below.
                continue
            cands.append(row)
    picked = pick_result(cands)
    if picked:
        return picked
    # Same-game any venue (Novig, or a missing venue snapshot).
    cands = []
    seen = set()
    for alias in aliases:
        for key in (f"*|{game}|{kind}|{alias}|{number}",):
            for i in index.get(key) or []:
                if i in seen:
                    continue
                seen.add(i)
                cands.append(settlements[i])
    picked = pick_result(cands)
    if picked:
        source = picked[1] + "+same-game"
        return picked[0], source, picked[2]
    # Tennis last-name fallback already in aliases. Sport+side if unique game.
    cands = []
    seen = set()
    for alias in aliases:
        for i in index.get(f"*|{sport}|{kind}|{alias}|{number}") or []:
            if i in seen:
                continue
            seen.add(i)
            row = settlements[i]
            if game and row.get("game_n") and not _games_overlap(game, row["game_n"]):
                continue
            cands.append(row)
    return pick_result(cands)


def _games_overlap(a: str, b: str) -> bool:
    def parts(text: str) -> list[set[str]]:
        chunks = re.split(r"\s+vs\.?\s+|\s+v\s+", text)
        out = []
        for chunk in chunks:
            toks = {t for t in re.findall(r"[a-z0-9]+", chunk) if t not in STOP and len(t) > 1}
            if toks:
                out.append(toks)
        return out
    pa, pb = parts(a), parts(b)
    if len(pa) == 2 and len(pb) == 2:
        direct = bool(pa[0] & pb[0]) and bool(pa[1] & pb[1])
        crossed = bool(pa[0] & pb[1]) and bool(pa[1] & pb[0])
        return direct or crossed
    return bool(set().union(*pa) & set().union(*pb)) if pa and pb else False


def attach_results(crosses: list[dict], last_map: dict, settlements: list[dict], index: dict) -> None:
    for cross in crosses:
        last = last_map.get(cross["key"]) or {}
        last_px = as_float(last.get("price"))
        cross["last_price"] = last_px
        cross["last_seen"] = last.get("seen_at") or ""
        if last.get("game_start") and not cross.get("game_start"):
            cross["game_start"] = last["game_start"]
            timing, mins, bucket = timing_bucket(parse_dt(cross.get("cross_time")), parse_dt(cross.get("game_start")))
            cross["timing"] = timing
            cross["minutes_into_game"] = mins
            cross["during_bucket"] = bucket if timing == "during" else timing
        official = lookup(cross, settlements, index)
        if official:
            result, source, ticker = official
            cross["official"] = "win" if result == "yes" else "loss"
            cross["official_source"] = source
            cross["official_ticker"] = ticker
        else:
            cross["official"] = "pending"
            cross["official_source"] = ""
            cross["official_ticker"] = ""
        if last_px is not None and 0.99 <= last_px < 1.0:
            cross["proxy"] = "win"
        elif last_px is not None and 0.0 < last_px <= 0.01:
            cross["proxy"] = "loss"
        else:
            cross["proxy"] = "unknown"


def bucket_rows(crosses: list[dict], result_field: str, group: tuple[str, ...], settled_only: bool) -> list[dict]:
    bags: dict[tuple, dict] = {}
    for row in crosses:
        result = row.get(result_field)
        if settled_only and result not in ("win", "loss"):
            continue
        key = tuple(row.get(k) or "" for k in group)
        bag = bags.get(key)
        if bag is None:
            bag = {k: row.get(k) or "" for k in group}
            bag.update({"n": 0, "wins": 0, "losses": 0, "pending": 0, "unknown": 0})
            bags[key] = bag
        bag["n"] += 1
        if result == "win":
            bag["wins"] += 1
        elif result == "loss":
            bag["losses"] += 1
        elif result == "pending":
            bag["pending"] += 1
        else:
            bag["unknown"] += 1
    out = []
    for bag in bags.values():
        settled = bag["wins"] + bag["losses"]
        bag["settled"] = settled
        bag["win_pct"] = pct(bag["wins"], settled)
        bag["note"] = tiny_note(settled)
        out.append(bag)
    out.sort(key=lambda r: (-(r["settled"]), r.get(group[0], ""), str(r.get(group[-1], ""))))
    return out


def kind_mix_note(rows: list[dict]) -> str:
    uniq: dict[str, dict] = {}
    for row in rows:
        uniq[row.get("key") or ""] = row
    contracts = [r for k, r in uniq.items() if k]
    n = len(contracts)
    ml = sum(1 for r in contracts if (r.get("market_type") or "") == "moneyline")
    spread = sum(1 for r in contracts if (r.get("market_type") or "") == "spread")
    total = sum(1 for r in contracts if (r.get("market_type") or "") == "total")
    other = n - ml - spread - total
    hits = len(rows)
    return (
        f"{n:,} distinct (game, side, venue) contracts ({hits:,} band hits): {ml:,} moneyline, "
        f"{spread:,} spread, {total:,} total, {other:,} other."
    )


def with_pending_from(source_rows: list[dict], rows: list[dict], group: tuple[str, ...]) -> list[dict]:
    pending_map: dict[tuple, int] = {}
    for row in source_rows:
        key = tuple(row.get(k) or "" for k in group)
        pending_map[key] = pending_map.get(key, 0) + (1 if row.get("official") == "pending" else 0)
    out = []
    for row in rows:
        key = tuple(row.get(k) or "" for k in group)
        item = dict(row)
        item["pending"] = pending_map.get(key, 0)
        out.append(item)
    return out


def fill_decade_rows(rows: list[dict], include_leftover: bool = True) -> list[dict]:
    have = {r.get("band"): r for r in rows}
    labels = list(DECADE_LABELS)
    if include_leftover:
        labels.append(LEFTOVER_LABEL)
    out = []
    for lab in labels:
        if lab in have:
            item = dict(have[lab])
            if lab == LEFTOVER_LABEL:
                extra = "leftover union of prices below 0.30; overlaps 00–09 / 10–19 / 20–29"
                item["note"] = (item.get("note") + "; " if item.get("note") else "") + extra
            out.append(item)
            continue
        out.append({
            "band": lab,
            "settled": 0,
            "wins": 0,
            "losses": 0,
            "win_pct": "",
            "pending": 0,
            "n": 0,
            "note": "no settled rows" if lab != LEFTOVER_LABEL else (
                "no settled rows; leftover union of prices below 0.30; overlaps 00–09 / 10–19 / 20–29"
            ),
        })
    return out


def decade_tables_html(d_first: list[dict], d_open: list[dict]) -> str:
    metric_headers = [
        ("Band", "text"), ("Settled N", "num"), ("Wins", "num"), ("Losses", "num"),
        ("Win %", "num"), ("Pending (excluded)", "num"), ("Note", "text"),
    ]
    fields = ["band", "settled", "wins", "losses", "win_pct", "pending", "note"]
    money_f = [r for r in d_first if r.get("market_type") == "moneyline"]
    money_o = [r for r in d_open if r.get("market_type") == "moneyline"]
    first_all = fill_decade_rows(with_pending_from(d_first, bucket_rows(d_first, "official", ("band",), True), ("band",)))
    first_ml = fill_decade_rows(with_pending_from(money_f, bucket_rows(money_f, "official", ("band",), True), ("band",)))
    open_all = fill_decade_rows(with_pending_from(d_open, bucket_rows(d_open, "official", ("band",), True), ("band",)))
    open_ml = fill_decade_rows(with_pending_from(money_o, bucket_rows(money_o, "official", ("band",), True), ("band",)))
    first_sport = with_pending_from(
        money_f, bucket_rows(money_f, "official", ("band", "sport"), True), ("band", "sport")
    )
    first_sport.sort(key=lambda r: (DECADE_ORDER.get(r.get("band") or "", 99), r.get("sport") or ""))
    mix_f = kind_mix_note(d_first)
    mix_o = kind_mix_note(d_open)
    mix_f_ml = kind_mix_note(money_f)
    mix_o_ml = kind_mix_note(money_o)
    return f"""
<h2 id="decade-bands">Decade implied-odds bands (new)</h2>
<div class="callout">
<h3>Definition</h3>
<p>Independent of hysteresis and of “first print above a bar.” For each (game, side, venue): look at Yes prices in time order. Assign the side to band 30–39 on the first print with 0.30 ≤ price &lt; 0.40; 40–49 on first print 0.40 ≤ price &lt; 0.50; … 90–99 on first 0.90 ≤ price &lt; 1.00. Also 00–09, 10–19, 20–29 when a print lands there, plus a leftover 00–29 row for the first print below 0.30 (that leftover overlaps the three low decades; it is not a fourth disjoint bucket).</p>
<p>A side can appear in <strong>multiple</strong> bands over the game. Opens 0.32 then later 0.51 counts in 30–39 <em>and</em> 50–59. It counts in 40–49 only if a Yes print actually sat in 0.40 ≤ price &lt; 0.50. A jump skips the unprinted decade.</p>
<p><strong>Table 1 — first print in each band:</strong> one row per (game, side, venue, decade) at the first tick inside that decade. Same side can sit in several decades.</p>
<p><strong>Table 2 — opener only:</strong> first print of the entire series only. A side that opens at 0.72 is only 70–79, not 30–39. Do not mix the two tables.</p>
<p>Win = official Kalshi/Gemini settlement of that named side, same as the parent study. Pending markets are shown and excluded from win %. Moneyline is primary. Spreads and totals are in their own “all market types” table so they are not mixed into the moneyline win percent. Short live window 17–20 Oct 2026. Research only. Not gold. No KEEP.</p>
</div>
<p class="note">{esc(mix_f)} {esc(mix_f_ml)} Exact $0.00 and $1.00 Yes prints are skipped (empty book after settlement).</p>

<h3>Table 1 — first print in each band, moneyline only (primary)</h3>
<p class="note">Win % after the side has printed at least once in that decade. Same (game, side, venue) can appear in several rows. Click column headers to sort. These bands are not hysteresis.</p>
{table(metric_headers, first_ml, fields)}

<h3>Table 1b — first print in each band, all market types (spreads mixed in here)</h3>
<p class="note">Moneyline + spread + total. Win on a spread or total means that contract settled Yes, not that the team won the game. {esc(mix_f)}</p>
{table(metric_headers, first_all, fields)}

<h3>Table 1c — first print in each band, moneyline, by sport</h3>
{table([("Band", "text"), ("Sport", "text")] + metric_headers[1:], first_sport, ["band", "sport"] + fields[1:])}

<h3>Table 2 — opener only, moneyline only (primary)</h3>
<p class="note">Each (game, side, venue) is in exactly one disjoint decade (plus leftover 00–29 if the opener was below 0.30). An opener at 0.72 is only 70–79. {esc(mix_o_ml)}</p>
{table(metric_headers, open_ml, fields)}

<h3>Table 2b — opener only, all market types (spreads mixed in here)</h3>
<p class="note">{esc(mix_o)}</p>
{table(metric_headers, open_all, fields)}
"""


def table(headers: list[tuple[str, str]], rows: list[dict], fields: list[str]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = []
        for i, field in enumerate(fields):
            num = headers[i][1] == "num"
            cells.append(td(row.get(field, ""), num))
        body.append("<tr>" + "".join(cells) + "</tr>")
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def fmt_px(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def write_html(
    stream: dict,
    h_rows: list[dict],
    s_rows: list[dict],
    d_first: list[dict],
    d_open: list[dict],
    settle_n: dict,
    now: str,
) -> None:
    money_h = [r for r in h_rows if r.get("market_type") == "moneyline"]
    money_s = [r for r in s_rows if r.get("market_type") == "moneyline"]
    overall = bucket_rows(h_rows, "official", ("band",), True)
    overall_ml = bucket_rows(money_h, "official", ("band",), True)
    by_sport = bucket_rows(h_rows, "official", ("band", "sport"), True)
    by_venue = bucket_rows(h_rows, "official", ("band", "venue"), True)
    by_timing = bucket_rows(h_rows, "official", ("band", "timing"), True)
    by_sport_thr = bucket_rows(h_rows, "official", ("sport", "band"), True)
    by_hour = bucket_rows(h_rows, "official", ("band", "during_bucket"), True)
    by_kind = bucket_rows(h_rows, "official", ("band", "market_type"), True)
    simple_over = bucket_rows(s_rows, "official", ("band",), True)
    simple_ml = bucket_rows(money_s, "official", ("band",), True)
    proxy_over = bucket_rows(h_rows, "proxy", ("band",), True)
    proxy_ml = bucket_rows(money_h, "proxy", ("band",), True)

    def highlight(rows):
        return [r for r in rows if r.get("band") == "55→60"]

    detail_src = [r for r in h_rows if r.get("band") == "55→60"]
    detail_src.sort(key=lambda r: r.get("cross_time") or "", reverse=True)
    detail_src = detail_src[:400]
    detail_rows = []
    for r in detail_src:
        detail_rows.append({
            "sport": r.get("sport"),
            "game": r.get("game"),
            "side": r.get("side"),
            "venue": r.get("venue"),
            "market_type": r.get("market_type"),
            "number": r.get("number"),
            "cross_time": r.get("cross_time"),
            "game_start": r.get("game_start"),
            "timing": r.get("timing"),
            "minutes_into_game": r.get("minutes_into_game"),
            "during_bucket": r.get("during_bucket"),
            "phase_feed": r.get("phase_feed"),
            "first_below": fmt_px(r.get("first_below")),
            "first_above": fmt_px(r.get("first_above")),
            "official": r.get("official"),
            "official_source": r.get("official_source"),
            "proxy": r.get("proxy"),
            "last_price": fmt_px(r.get("last_price")),
        })

    pending_n = sum(1 for r in h_rows if r.get("official") == "pending")
    settled_n = sum(1 for r in h_rows if r.get("official") in ("win", "loss"))
    ml55 = next((r for r in overall_ml if r["band"] == "55→60"), None)
    all55 = next((r for r in overall if r["band"] == "55→60"), None)

    metric_headers = [
        ("Band", "text"), ("Settled N", "num"), ("Wins", "num"), ("Losses", "num"),
        ("Win %", "num"), ("Pending (excluded)", "num"), ("Note", "text"),
    ]

    def metric_fields(extra: list[str] | None = None):
        cols = extra or []
        return cols + ["settled", "wins", "losses", "win_pct", "pending", "note"]

    def with_pending(rows, group):
        # Recompute pending from full set so the column is visible even though
        # win% uses settled only.
        pending_map = {}
        for row in h_rows:
            key = tuple(row.get(k) or "" for k in group)
            pending_map[key] = pending_map.get(key, 0) + (1 if row.get("official") == "pending" else 0)
        out = []
        for row in rows:
            key = tuple(row.get(k) or "" for k in group)
            item = dict(row)
            item["pending"] = pending_map.get(key, 0)
            out.append(item)
        return out

    overall_show = with_pending(overall, ("band",))
    overall_ml_show = with_pending(overall_ml, ("band",))
    sport_show = with_pending(by_sport, ("band", "sport"))
    venue_show = with_pending(by_venue, ("band", "venue"))
    timing_show = with_pending(by_timing, ("band", "timing"))
    hour_show = with_pending(by_hour, ("band", "during_bucket"))
    kind_show = with_pending(by_kind, ("band", "market_type"))
    sport_thr_show = with_pending(by_sport_thr, ("sport", "band"))

    simple_headers = metric_headers
    simple_show = []
    pending_s = {}
    for row in s_rows:
        key = row.get("band") or ""
        pending_s[key] = pending_s.get(key, 0) + (1 if row.get("official") == "pending" else 0)
    for row in simple_over:
        item = dict(row)
        item["pending"] = pending_s.get(row["band"], 0)
        simple_show.append(item)
    simple_ml_show = []
    pending_sml = {}
    for row in money_s:
        key = row.get("band") or ""
        pending_sml[key] = pending_sml.get(key, 0) + (1 if row.get("official") == "pending" else 0)
    for row in simple_ml:
        item = dict(row)
        item["pending"] = pending_sml.get(row["band"], 0)
        simple_ml_show.append(item)

    def proxy_show(rows):
        out = []
        for row in rows:
            item = dict(row)
            item["pending"] = item.get("unknown") or 0
            out.append(item)
        return out

    headline_ml = (
        f"{ml55['win_pct']}% ({ml55['wins']} wins / {ml55['settled']} settled)"
        if ml55 and ml55["settled"]
        else "not enough official settlements"
    )
    headline_all = (
        f"{all55['win_pct']}% ({all55['wins']} wins / {all55['settled']} settled)"
        if all55 and all55["settled"]
        else "not enough official settlements"
    )

    sports_txt = ", ".join(f"{k} ({v} contracts)" for k, v in sorted(stream["sports"].items(), key=lambda kv: -kv[1]))
    venues_txt = ", ".join(f"{k} ({v})" for k, v in sorted(stream["venues"].items(), key=lambda kv: -kv[1]))
    decade_html = decade_tables_html(d_first, d_open)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Odds cross win rates</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; max-width: none; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.hl {{ background: #fef9c3; padding: 10px 12px; border: 1px solid #eab308; margin: 12px 0; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>When implied odds cross a bar, how often that side wins</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders.</p>
<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<p>{esc(ASKED_ROI)} See <a href="odds_cross_no_roi_60_70_20261020.html">No-bet ROI 60→70</a>.</p>
<p>{esc(ASKED_DECADE)}</p>
<p>Follow-up: tennis moneyline win rate by decade at match start and 24 hours before, not first print. See <a href="tennis_decade_at_start_20261020.html">Tennis odds at start</a>.</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
<p>Hysteresis (the hysteresis tables below) is the strict version of your first example: the Yes price must print <em>under</em> the floor, then later print <em>over</em> the bar. Simple first-cross tables only require the first print above a single bar, even if the side was never a dog.</p>
<p>{esc(PLAIN_DECADE)}</p>
<p>Moneyline is who wins the game. A spread is a points handicap. A total is over/under combined points. Win on a spread or total means that contract settled Yes, not that the team won the game.</p>
</div>

<div class="hl">
<p><strong>Headline, 55→60, moneyline only, official settlements:</strong> {esc(headline_ml)}.</p>
<p><strong>Same band, every market type (moneyline + spread + total):</strong> {esc(headline_all)}.</p>
<p>If a 60% print were “really” a 70% winner, the moneyline 55→60 row would need to sit near 70% with a large settled N. This sample is a short live window, not a multi-year book, so do not treat any row as a KEEP.</p>
<p>Decade bands (new, not hysteresis): moneyline win % by first print in 30–39, 40–49, … is in <a href="#decade-bands">the decade tables</a>. Research only. Not gold. No KEEP.</p>
</div>

<h2>Sample and honesty</h2>
<p>Price history is <code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw/price_memory.jsonl</code>. Yes ticks used: {stream['n_yes']:,} of {stream['n_lines']:,} lines. Distinct Yes contracts: {stream['n_keys']:,}. First quote {esc(stream['seen_min'])}. Last quote {esc(stream['seen_max'])}.</p>
<p>This feed is a short October 2026 live window (about 17–20 Oct). There is no in-sample / out-of-sample split to report: almost every first-cross is after 2024-01-01, and the tape does not go back years. Thresholds were fixed before looking at win rates. This page does not retune bands on these tables and does not name a KEEP or DISMISS.</p>
<p>Sports in the Yes book: {esc(sports_txt)}. Venues: {esc(venues_txt)}. Only the named side’s Yes price is used. No-ask rows are not inverted into a second Yes.</p>
<p>Official settlements attached: Kalshi public <code>result</code> (yes/no) {settle_n.get('kalshi', 0):,}; Gemini <code>resolutionSide</code> {settle_n.get('gemini', 0):,}; Polymarket US closed 0/1 prices {settle_n.get('polymarket', 0):,}. Unique settlement rows after merge: {settle_n.get('total', 0):,}. Hysteresis crosses with an official win or loss: {settled_n:,}. Still pending (excluded from win %): {pending_n:,}.</p>
<p>Novig is a quote venue, not a settlement venue. A Novig cross uses the same game/side/market on Kalshi or Gemini when that official result exists, and the source is tagged <code>same-game</code>.</p>
<p>Click column headers to sort. Swipe sideways to see more columns. Numeric columns are right-aligned. Tiny N is called out; do not read a 100% row on five games as a 70% law.</p>

{decade_html}

<h2>Hysteresis up-cross, official settlements, all market types</h2>
<p class="note">Must print strictly below the floor, then later strictly above the bar. First qualifying cross only. Win % = wins / (wins + losses). Pending is shown and excluded.</p>
{table(metric_headers, overall_show, ["band"] + metric_fields())}

<h2>Hysteresis, moneyline only (who wins the game)</h2>
{table(metric_headers, overall_ml_show, ["band"] + metric_fields())}

<h2>By sport</h2>
{table([("Band", "text"), ("Sport", "text")] + metric_headers[1:], sport_show, ["band", "sport"] + metric_fields())}

<h2>By venue</h2>
{table([("Band", "text"), ("Venue", "text")] + metric_headers[1:], venue_show, ["band", "venue"] + metric_fields())}

<h2>Before listed start vs during (at or after start)</h2>
<p class="note">Before = cross timestamp earlier than catalog game start. During = at or after start. Unknown = start missing (common on tennis when the feed never stored a commence time). During includes after the final whistle if the start is known; the next table splits during by minutes after start.</p>
{table([("Band", "text"), ("Timing", "text")] + metric_headers[1:], timing_show, ["band", "timing"] + metric_fields())}

<h2>Minutes after listed start (during only, plus before/unknown)</h2>
<p class="note">Buckets: before; 0–15 minutes; 15–60 minutes; 60 minutes and later; unknown. The 55→60 during rows are the closest answer to “when a game is on.”</p>
{table([("Band", "text"), ("When", "text")] + metric_headers[1:], hour_show, ["band", "during_bucket"] + metric_fields())}

<h2>Sport × threshold</h2>
{table([("Sport", "text"), ("Band", "text")] + metric_headers[1:], sport_thr_show, ["sport", "band"] + metric_fields())}

<h2>Market type (moneyline vs spread vs total)</h2>
{table([("Band", "text"), ("Market", "text")] + metric_headers[1:], kind_show, ["band", "market_type"] + metric_fields())}

<h2>Simple first print above a bar (no hysteresis)</h2>
<p class="note">Counts the first Yes print strictly above 40, 45, 50, 55, 60, 65, 70, or 80 percent. An opener at 0.72 counts as first-print-above every bar it already clears (40 through 70), not 80; it is not a 60-only tag. This is not the “was under, then over” test.</p>
<h3>All market types</h3>
{table(simple_headers, simple_show, ["band"] + metric_fields())}
<h3>Moneyline only</h3>
{table(simple_headers, simple_ml_show, ["band"] + metric_fields())}

<h2>Proxy: last Yes print ≥ 0.99 as win, ≤ 0.01 as loss</h2>
<p class="note"><strong>This is not official settlement.</strong> It is the last remembered Yes price on that contract, counting 0.99 through 0.999 as a proxy win and 0.001 through 0.01 as a proxy loss. Exact $0.00 and $1.00 are left out: after Kalshi finalizes, both sides often show a Yes ask of $1.00 with a $0.00 bid (an empty book), which is not a last trade. A 0.99 print during a live game can still reverse. Use this table only when official results are missing.</p>
<h3>Hysteresis, all market types, proxy</h3>
{table(metric_headers, proxy_show(proxy_over), ["band"] + metric_fields())}
<h3>Hysteresis, moneyline only, proxy</h3>
{table(metric_headers, proxy_show(proxy_ml), ["band"] + metric_fields())}

<h2>55→60 event detail (newest 400)</h2>
<p class="note">One row per (game, side, venue) at the first 55→60 hysteresis cross. Official is win/loss/pending. Proxy is last-print only.</p>
{table(
    [
        ("Sport", "text"), ("Game", "text"), ("Side", "text"), ("Venue", "text"),
        ("Market", "text"), ("Number", "num"), ("Cross time", "date"), ("Game start", "date"),
        ("Before/during", "text"), ("Minutes in", "num"), ("During bucket", "text"),
        ("Feed phase", "text"), ("First price below", "num"), ("First price above", "num"),
        ("Official", "text"), ("Official source", "text"), ("Proxy last-print", "text"),
        ("Last Yes", "num"),
    ],
    detail_rows,
    [
        "sport", "game", "side", "venue", "market_type", "number", "cross_time", "game_start",
        "timing", "minutes_into_game", "during_bucket", "phase_feed", "first_below", "first_above",
        "official", "official_source", "proxy", "last_price",
    ],
)}

<h2>How a cross is counted</h2>
<ul>
<li>Unit is (game, side, venue, threshold). The first qualifying tick wins; later ticks on the same contract are ignored.</li>
<li>Decade bands are a separate count. First-in-band: first Yes print inside 0.30 ≤ p &lt; 0.40 (etc.). Opener-only: first Yes print of the whole series. A side may sit in several first-in-band decades; opener-only is one disjoint decade.</li>
<li>Hysteresis 55→60: some Yes print &lt; 0.55, and a later Yes print &gt; 0.60.</li>
<li>Price is the Yes ask stored in price memory, 0–1 dollars = implied percent. Exact 0.00 and 1.00 prints are skipped (Kalshi empty book after settlement).</li>
<li>A first print above the bar of 0.995 or higher is not counted as a cross. That is usually the empty $1 ask, not a live 60% print.</li>
<li>Game start is the feed’s <code>game_start</code> when present, else unknown. Before vs during is cross timestamp versus that start, not the feed’s typical-length “after” flag.</li>
<li>A market with no official result is pending and is not in win %.</li>
</ul>
<p class="note">Acronyms: ATP is Association of Tennis Professionals. NHL is National Hockey League. NFL is National Football League. MLB is Major League Baseball. NBA is National Basketball Association. WTA is Women’s Tennis Association.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    dest_dir = Path(r"G:\My Drive\paul_experiments\prediction_market_arb_exhaustive_20261017")
    if dest_dir.parent.exists() or Path("G:/").exists():
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / PAGE.name
            shutil.copy2(PAGE, dest)
            print(f"copied {dest}", flush=True)
        except OSError as exc:
            print(f"G: copy skipped: {exc}", flush=True)
    else:
        print("G: not present, skip copy", flush=True)


def drop_empty_book_crosses(crosses: list[dict]) -> list[dict]:
    """Drop crosses whose first print above the bar is a $1 empty ask."""
    kept = []
    for row in crosses:
        above = as_float(row.get("first_above"))
        if above is None or above >= 0.995:
            continue
        kept.append(row)
    return kept


def load_stream_cache() -> dict | None:
    if not CROSSES_FULL.is_file():
        return None
    try:
        data = json.loads(CROSSES_FULL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "h_crosses" not in data or "last_map" not in data:
        return None
    print(f"reusing streamed crosses {CROSSES_FULL}", flush=True)
    return data


def save_stream_cache(stream: dict) -> None:
    payload = {
        "n_lines": stream["n_lines"],
        "n_yes": stream["n_yes"],
        "n_keys": stream["n_keys"],
        "seen_min": stream["seen_min"],
        "seen_max": stream["seen_max"],
        "sports": stream["sports"],
        "venues": stream["venues"],
        "h_crosses": stream["h_crosses"],
        "s_crosses": stream["s_crosses"],
        "last_map": stream["last_map"],
    }
    CROSSES_FULL.write_text(json.dumps(payload), encoding="utf-8")
    print(f"cached crosses {CROSSES_FULL}", flush=True)


def _print_decade_ml(label: str, rows: list[dict]) -> None:
    money = [r for r in rows if r.get("market_type") == "moneyline"]
    bags = fill_decade_rows(bucket_rows(money, "official", ("band",), True))
    print(f"\n{label}", flush=True)
    print("band\tN\twins\twin%", flush=True)
    for row in bags:
        print(
            f"{row['band']}\t{row['settled']}\t{row['wins']}\t{row['win_pct']}",
            flush=True,
        )


def main() -> None:
    now = datetime.now(ET).isoformat()
    reuse = "--skip-stream" in sys.argv
    skip_fetch = "--skip-fetch" in sys.argv
    skip_decade = "--skip-decade-stream" in sys.argv
    stream = load_stream_cache() if reuse else None
    if stream is None:
        stream = stream_crosses()
        save_stream_cache(stream)
    stream["h_crosses"] = drop_empty_book_crosses(stream["h_crosses"])
    stream["s_crosses"] = drop_empty_book_crosses(stream["s_crosses"])
    print(f"after dropping $1 empty-book crosses h={len(stream['h_crosses'])} s={len(stream['s_crosses'])}", flush=True)
    decade = load_decade_cache() if skip_decade else None
    if decade is None:
        decade = stream_decade_bands()
        save_decade_cache(decade)
    if skip_fetch and SETTLE_CACHE.is_file():
        local = []
        kalshi = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
        gemini = []
        print(f"reusing settlements {len(kalshi)}", flush=True)
    else:
        local = load_local_settlements()
        kalshi = fetch_kalshi_settlements()
        gemini = fetch_gemini_refresh()
    settlements = []
    seen = set()
    for row in local + kalshi + gemini:
        sig = (
            row.get("venue_n"), row.get("game_n"), row.get("market_type"),
            row.get("side_n"), row.get("number_n"), row.get("result"), row.get("ticker"),
        )
        if sig in seen:
            continue
        seen.add(sig)
        settlements.append(row)
    index = build_index(settlements)
    attach_results(stream["h_crosses"], stream["last_map"], settlements, index)
    attach_results(stream["s_crosses"], stream["last_map"], settlements, index)
    attach_results(decade["first_in_band"], stream["last_map"], settlements, index)
    attach_results(decade["opener"], stream["last_map"], settlements, index)
    # Backfill start from settlement occurrence when feed start is missing.
    occ = {}
    for row in settlements:
        if row.get("occurrence") and row.get("game_n"):
            occ.setdefault(row["game_n"], row["occurrence"])
    all_cross = (
        stream["h_crosses"] + stream["s_crosses"] + decade["first_in_band"] + decade["opener"]
    )
    for cross in all_cross:
        if cross.get("game_start"):
            continue
        occ_raw = occ.get(game_norm(cross.get("game") or ""))
        start = parse_dt(occ_raw)
        if start is None:
            continue
        cross["game_start"] = iso(start)
        timing, mins, bucket = timing_bucket(parse_dt(cross.get("cross_time")), start)
        cross["timing"] = timing
        cross["minutes_into_game"] = mins
        cross["during_bucket"] = bucket if timing == "during" else timing
    settle_n = {
        "kalshi": sum(1 for r in settlements if r.get("venue") == "Kalshi"),
        "gemini": sum(1 for r in settlements if r.get("venue") == "Gemini"),
        "polymarket": sum(1 for r in settlements if r.get("venue") == "Polymarket"),
        "total": len(settlements),
    }
    CROSSES_CACHE.write_text(json.dumps({
        "written_at": now,
        "stream": {k: stream[k] for k in ("n_lines", "n_yes", "n_keys", "seen_min", "seen_max", "sports", "venues")},
        "settle_n": settle_n,
        "h_n": len(stream["h_crosses"]),
        "s_n": len(stream["s_crosses"]),
        "decade_first_n": len(decade["first_in_band"]),
        "decade_opener_n": len(decade["opener"]),
    }, indent=2), encoding="utf-8")
    if not skip_fetch:
        SETTLE_CACHE.write_text(json.dumps(settlements, indent=2), encoding="utf-8")
    write_html(
        stream, stream["h_crosses"], stream["s_crosses"],
        decade["first_in_band"], decade["opener"], settle_n, now,
    )
    ml = [r for r in stream["h_crosses"] if r.get("band") == "55→60" and r.get("market_type") == "moneyline"]
    settled = [r for r in ml if r.get("official") in ("win", "loss")]
    wins = sum(1 for r in settled if r["official"] == "win")
    print(f"55->60 moneyline official {wins}/{len(settled)} = {pct(wins, len(settled))}% pending={sum(1 for r in ml if r.get('official')=='pending')}", flush=True)
    from collections import Counter
    print("55->60 ml sport", Counter((r.get("sport"), r.get("official")) for r in ml), flush=True)
    print("55->60 ml source", Counter(r.get("official_source") for r in settled), flush=True)
    print("55->60 ml venue", Counter((r.get("venue"), r.get("official")) for r in ml), flush=True)
    print("tennis settlements", sum(1 for r in settlements if r.get("sport") == "tennis"), flush=True)
    _print_decade_ml("DECADE moneyline first-in-band", decade["first_in_band"])
    _print_decade_ml("DECADE moneyline opener-only", decade["opener"])


if __name__ == "__main__":
    main()
