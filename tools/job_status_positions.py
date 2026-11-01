"""Venue-open tickets for the job_status Positions table.

Open now and Positions share one open-set (open_count_sync.open_set_tickets):
Kalshi qty >= 1, Polymarket GET qty > 0, plus Poly house-open confirms from
activities / this-order cumQuantity / ledger FILLED when the positions GET is
empty and the market is still open. Resolved / expired / final / void never
join Open or Positions, even with confirm qty ≥ 1 (empty after settle is
normal). Same for Kalshi closed tickers. Empty Poly GET must not hide a
confirmed fill on an OPEN market (Namigata 0.32, Guajardo 0.19). House cap is
still 1 slot per game; fractional qty may display. House watches tag the
system (B tennis crossover). Gemini and Novig fill-history are not a
positions book. A venue ticket with no intent stays sys=unknown.

Does not place, cancel, or flatten orders. Does not print secrets. Does not
start a second live_strategy_b.py. Research-candidate live. Not gold. Not
DailyRun.
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from prediction_paths import DRIVE_STAMP as STAMP, ONE_LEG_WATCH, RAW_DIR as RAW, ROOT, ensure_dirs

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import kalshi_ticker_decode as ktd  # noqa: E402
import order_types  # noqa: E402
import report_page_extras  # noqa: E402

ET = ZoneInfo("America/New_York")
FRESH_SEC = 120
CACHE_PATH = RAW / "job_status_positions_cache.json"
ORDERS = RAW / "orders.jsonl"
POSITIONS_PULL = RAW / "kalshi_positions_pull.json"
STAMP_PAGE = STAMP / "job_status_positions_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/job_status.html"
)
STAMP_FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/job_status_positions_20261024.html"
)
WATCH = {
    "tennis_crossover": RAW / "strategy_b_watch.json",
    "cfb_favorite": RAW / "cfb_favorite_watch.json",
    "spread_t0": RAW / "spread_t0_watch.json",
    "tennis_t0_dog": RAW / "tennis_t0_dog_watch.json",
    "tennis_t0_spread": RAW / "tennis_t0_spread_watch.json",
    "soccer_t0_total": RAW / "soccer_t0_total_watch.json",
}
LETTER = {
    "lock": "A",
    "tennis_crossover": "B",
    "cfb_favorite": "C",
    "spread_t0": "D",
    "tennis_t0_dog": "E",
    "tennis_t0_spread": "F",
    "soccer_t0_total": "G",
}
DISPLAY = {
    "lock": "Lock gap",
    "tennis_crossover": "Tennis crossover",
    "cfb_favorite": "College football favorite",
    "spread_t0": "T0 spreads",
    "tennis_t0_dog": "Tennis T0 dog",
    "tennis_t0_spread": "Tennis spread",
    "soccer_t0_total": "Soccer total",
}
VENUE_LABEL = {
    "kalshi": "Kalshi",
    "gemini": "Gemini",
    "polymarket": "Polymarket US",
    "novig": "Novig",
}
ASKED = (
    "On job_status.html, below Systems, a table Positions: live open orders for each "
    "system. Columns: sys/name, sport, game, bets, plus anything helpful. How much we "
    "are currently up or down, and a sum footer so he knows the total on open orders. "
    "Right now an order pops on a venue and he cannot tell which system it belongs to."
)
PLAIN = (
    "When a sportsbook still shows a ticket we bought, this table names which of the "
    "four systems owns it, what game and line it is, and whether that open ticket is "
    "ahead or behind right now. The bottom row adds those open profits and losses. "
    "A ticket the house does not recognize still appears as unknown, so a stray fill "
    "is visible. Open now is the count of these rows by system, including a Polymarket "
    "fill the positions list forgot. We did not sell anything."
)

POSITIONS_CAPTION = (
    "Open now is the count of Positions rows by system. Same open-set: Kalshi qty ≥ 1, "
    "Polymarket qty > 0, plus Poly confirm / activities / cumQuantity / ledger FILLED "
    "when the positions GET is empty and the market is still open. Resolved, expired, "
    "final, or void never count as open — empty after settle is normal. Same for Kalshi "
    "closed tickers. Click headers to sort. Swipe sideways."
)

CENT = Decimal("0.01")
FOUR = Decimal("0.0001")
ONE = Decimal("1")


def iso_now() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")


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


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{_esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data


def _dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _parse_dt(raw: str):
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def et_text(raw: str) -> str:
    when = _parse_dt(raw)
    if when is None:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=ET)
    return when.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S ET")


def money(value: Decimal | None, places: Decimal = FOUR) -> str:
    if value is None:
        return "—"
    number = value.quantize(places, rounding=ROUND_HALF_UP)
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number)}"


def kalshi_fee(price: Decimal) -> Decimal:
    raw = Decimal("0.07") * price * (ONE - price)
    if raw < 0:
        raw = Decimal("0")
    return raw.quantize(FOUR, rounding=ROUND_HALF_UP)


def _px(value) -> Decimal | None:
    number = _dec(value)
    if number is None:
        return None
    if number > 1:
        if number <= 100:
            number = number / Decimal("100")
        else:
            return None
    if number < 0 or number > 1:
        return None
    return number


def market_from_ticker(ticker: str) -> tuple[str, str]:
    text = str(ticker or "").upper()
    if "TEAMTOTAL" in text or re.search(r"[-_]TT([-_]|$)", text):
        return "team_total", "team total"
    if "SPREAD" in text:
        return "spread", "spread"
    if "TOTAL" in text or re.search(r"[-_]T([-_]|$)", text):
        return "total", "total"
    return "moneyline", "ML"


def sport_from_ticker(ticker: str) -> str:
    text = str(ticker or "").upper()
    low = str(ticker or "").lower()
    if "NCAAF" in text or "CFB" in text or low.startswith("aec-ncaaf") or low.startswith("aec-cfb"):
        return "college football"
    if "NFL" in text or "KXNFL" in text or low.startswith("aec-nfl"):
        return "pro football"
    tennis_tags = ("ATP", "WTA", "UTR", "CHALLENGER", "ITF")
    tennis_slugs = ("aec-atp", "aec-wta", "aec-itf", "aec-challenger", "aec-utr")
    if any(tag in text for tag in tennis_tags) or any(low.startswith(p) for p in tennis_slugs):
        return "tennis"
    if "NBA" in text:
        return "pro basketball"
    if "MLB" in text:
        return "pro baseball"
    if "NHL" in text:
        return "pro hockey"
    return ""


_NFL_CODE_ALIAS = {"WSH": "WAS", "JAC": "JAX", "LAR": "LA"}


def is_nfl_moneyline(ident: str) -> bool:
    """True for NFL winner markets (KXNFLGAME / aec-nfl), not spreads or totals."""
    text = str(ident or "").strip()
    if not text:
        return False
    up = text.upper()
    low = text.lower()
    if "SPREAD" in up or "TOTAL" in up:
        return False
    return low.startswith("aec-nfl") or up.startswith("KXNFLGAME")


def nfl_fixture_key(ident: str) -> str:
    """Sorted NFL team codes for a moneyline ticker/slug, e.g. PHI-WAS. Empty if not NFL ML."""
    text = str(ident or "").strip()
    if not text:
        return ""
    up = text.upper()
    low = text.lower()
    if "SPREAD" in up or "TOTAL" in up:
        return ""
    match = re.search(r"aec-nfl-([a-z]{2,4})-([a-z]{2,4})-", low)
    if match:
        codes = [_NFL_CODE_ALIAS.get(c.upper(), c.upper()) for c in match.groups()]
        return "-".join(sorted(codes))
    if not up.startswith("KXNFLGAME"):
        return ""
    decoded = ktd.decode_kalshi_ticker(text)
    if decoded.kind == "moneyline" and decoded.away_code and decoded.home_code:
        codes = [
            _NFL_CODE_ALIAS.get(decoded.away_code.upper(), decoded.away_code.upper()),
            _NFL_CODE_ALIAS.get(decoded.home_code.upper(), decoded.home_code.upper()),
        ]
        return "-".join(sorted(codes))
    return ""


def parse_ticker_game(ticker: str) -> tuple[str, str, str]:
    """Best-effort Kalshi ticker → (game_codes, side_code, line)."""
    decoded = ktd.decode_kalshi_ticker(ticker)
    if decoded.kind:
        return decoded.game_short or decoded.game, decoded.yes_code, decoded.line_raw
    text = str(ticker or "")
    parts = text.split("-")
    if len(parts) < 3:
        return "", "", ""
    mid = parts[-2]
    side = parts[-1]
    match = re.match(r"(\d{2}[A-Za-z]{3}\d{2})([A-Za-z0-9]+)$", mid)
    teams = match.group(2) if match else mid
    line = ""
    side_code = side
    digits = re.search(r"(\d+)$", side)
    if digits and not side[-1:].isalpha():
        line = digits.group(1)
        side_code = side[: digits.start()]
    if len(teams) >= 6 and len(teams) % 2 == 0:
        half = len(teams) // 2
        game = f"{teams[:half]} vs {teams[half:]}"
    else:
        game = teams
    return game, side_code, line


def system_from_bet_key(key: str) -> str:
    text = str(key or "")
    head = text.split("\t", 1)[0].strip().lower()
    if head in {"cfb-favorite", "cfb_favorite"}:
        return "cfb_favorite"
    if head in {"spread-t0", "spread_t0"}:
        return "spread_t0"
    if head in {"tennis-t0-dog", "tennis_t0_dog"}:
        return "tennis_t0_dog"
    if head in {"tennis-t0-spread", "tennis_t0_spread"}:
        return "tennis_t0_spread"
    if head in {"soccer-t0-total", "soccer_t0_total"}:
        return "soccer_t0_total"
    if head in {"tennis-b", "tennis_crossover", "tennis-crossover"}:
        return "tennis_crossover"
    if head in {"lock"}:
        return "lock"
    return ""


def _sid_letter(sid: str) -> str:
    return LETTER.get(sid, "") or "unknown"


def _sid_name(sid: str) -> str:
    if sid in DISPLAY:
        return DISPLAY[sid]
    return "unknown"


def intent_from_watch_row(sid: str, row: dict) -> dict:
    last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
    tape = row.get("_tape") if isinstance(row.get("_tape"), dict) else {}
    t0 = row.get("t0_yes") if isinstance(row.get("t0_yes"), dict) else {}
    inst = str(
        row.get("instrument")
        or last.get("instrument")
        or tape.get("instrument")
        or ""
    )
    venue = str(row.get("venue") or last.get("venue") or tape.get("venue") or "").lower()
    kind = str(row.get("kind") or row.get("market_type") or "moneyline")
    side_label = str(row.get("dog") or row.get("fav") or row.get("side") or row.get("side_label") or "")
    pay = str(tape.get("side") or last.get("side") or "yes").lower()
    if pay not in {"yes", "no"}:
        pay = "yes"
    entry = _px(last.get("pay") or row.get("dog_ask") or row.get("fav_ask") or last.get("limit_price"))
    opened = str(last.get("time") or row.get("opened_at") or "")
    number = str(row.get("number") or "")
    extra = []
    if inst:
        extra.append((venue or "kalshi", inst))
    for slot in t0.values():
        if isinstance(slot, dict) and slot.get("instrument"):
            extra.append((str(slot.get("venue") or venue or "").lower(), str(slot.get("instrument"))))
    if tape.get("instrument"):
        extra.append((str(tape.get("venue") or venue).lower(), str(tape.get("instrument"))))
    return {
        "sid": sid,
        "letter": _sid_letter(sid),
        "name": _sid_name(sid),
        "sport": str(row.get("sport") or ""),
        "game": str(row.get("game") or row.get("key") or ""),
        "key": str(row.get("key") or ""),
        "kind": kind,
        "number": number,
        "side_label": side_label,
        "pay": pay,
        "venue": venue,
        "instrument": inst,
        "entry": entry,
        "opened_at": opened,
        "instruments": extra,
    }


def load_watch_intent() -> dict[tuple[str, str], dict]:
    found: dict[tuple[str, str], dict] = {}
    for sid, path in WATCH.items():
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        for row in data.get("matches") or []:
            if not isinstance(row, dict):
                continue
            info = intent_from_watch_row(sid, row)
            for shop, ident in info.get("instruments") or []:
                if shop and ident:
                    found.setdefault((shop, ident), info)
            if info.get("instrument"):
                found.setdefault((info.get("venue") or "kalshi", info["instrument"]), info)
    return found


def load_order_intent() -> dict[tuple[str, str], dict]:
    found: dict[tuple[str, str], dict] = {}
    if not ORDERS.exists():
        return found
    try:
        lines = ORDERS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        event = str(row.get("event") or "")
        if event not in {"sent", "filled"}:
            continue
        ident = str(row.get("instrument") or "")
        venue = str(row.get("venue") or "").lower()
        if not ident or not venue:
            continue
        # Filled rows are often qty/price only. Kitchen labels live on the sent row.
        if event == "filled" and not str(
            row.get("game") or row.get("side_label") or row.get("player") or ""
        ).strip():
            continue
        key = (venue, ident)
        if key in found:
            continue
        sid = str(row.get("system") or "") or system_from_bet_key(str(row.get("bet_key") or ""))
        if not sid:
            bet = str(row.get("bet_key") or "")
            if bet.startswith("tennis-b"):
                sid = "tennis_crossover"
            elif "\t" in bet and not bet.startswith(("cfb-", "spread-", "tennis-")):
                sid = "lock"
        if not sid:
            continue
        found[key] = {
            "sid": sid,
            "letter": _sid_letter(sid),
            "name": _sid_name(sid),
            "sport": str(row.get("sport") or ""),
            "game": str(row.get("game") or ""),
            "key": str(row.get("bet_key") or ""),
            "kind": str(row.get("market_type") or row.get("kind") or ""),
            "number": str(row.get("number") or ""),
            "side_label": str(
                row.get("side_label") or row.get("player") or ""
            ),
            "pay": str(row.get("side") or "yes").lower(),
            "venue": venue,
            "instrument": ident,
            "entry": _px(row.get("limit_price") or row.get("quote_price") or row.get("price")),
            "opened_at": str(row.get("sent_at") or row.get("filled_at") or row.get("compared_at") or ""),
        }
    return found


def load_lock_intent() -> dict[tuple[str, str], dict]:
    found: dict[tuple[str, str], dict] = {}
    data = _load_json(ONE_LEG_WATCH)
    watches = []
    if isinstance(data, dict):
        watches = data.get("watches") or []
    elif isinstance(data, list):
        watches = data
    for row in watches:
        if not isinstance(row, dict):
            continue
        if str(row.get("bet_key") or "").startswith("tennis-b"):
            continue
        info = {
            "sid": "lock",
            "letter": "A",
            "name": DISPLAY["lock"],
            "sport": str(row.get("sport") or ""),
            "game": str(row.get("game") or ""),
            "key": str(row.get("bet_key") or ""),
            "kind": str(row.get("market_type") or "moneyline"),
            "number": str(row.get("number") or ""),
            "side_label": str(row.get("claim_side") or ""),
            "pay": str(row.get("filled_side") or "yes").lower(),
            "venue": str(row.get("filled_venue") or "").lower(),
            "instrument": str(row.get("filled_instrument") or ""),
            "entry": _px(row.get("fill_px")),
            "opened_at": str(row.get("started_at") or ""),
            "lock_pair": True,
        }
        for shop, ident, pay, label in (
            (row.get("filled_venue"), row.get("filled_instrument"), row.get("filled_side"), row.get("claim_side")),
            (row.get("missed_venue"), row.get("missed_instrument"), row.get("missed_side"), row.get("claim_side")),
        ):
            shop_s = str(shop or "").lower()
            ident_s = str(ident or "")
            if not shop_s or not ident_s:
                continue
            slot = dict(info)
            slot["venue"] = shop_s
            slot["instrument"] = ident_s
            slot["pay"] = str(pay or "yes").lower()
            slot["side_label"] = str(label or "")
            found.setdefault((shop_s, ident_s), slot)
        venues = row.get("venues") if isinstance(row.get("venues"), dict) else {}
        for shop, blob in venues.items():
            if not isinstance(blob, dict):
                continue
            ident_s = str(blob.get("instrument") or "")
            shop_s = str(shop or "").lower()
            if ident_s and shop_s:
                found.setdefault((shop_s, ident_s), info)
    return found


def load_intent_index() -> dict[tuple[str, str], dict]:
    """Watch files beat orders.jsonl beat leftover lock watches. No ticker guess for sys."""
    found: dict[tuple[str, str], dict] = {}
    for blob in (load_lock_intent(), load_order_intent(), load_watch_intent()):
        for key, info in blob.items():
            found[key] = info
    return found


def overlay_kalshi_fields(tickets: list[dict]) -> list[dict]:
    payload = _load_json(POSITIONS_PULL)
    body = (payload or {}).get("body") if isinstance(payload, dict) else None
    by = {}
    if isinstance(body, dict):
        for item in body.get("market_positions") or []:
            if isinstance(item, dict) and item.get("ticker"):
                by[str(item["ticker"])] = item
    out = []
    for row in tickets:
        item = dict(row)
        extra = by.get(str(item.get("ticker") or "")) or {}
        if extra:
            if not item.get("fees"):
                item["fees"] = extra.get("fees_paid_dollars") or ""
            if not item.get("exposure"):
                item["exposure"] = extra.get("market_exposure_dollars") or ""
            if not item.get("last_updated"):
                item["last_updated"] = extra.get("last_updated_ts") or ""
            signed = _dec(extra.get("position_fp") or extra.get("position"))
            if signed is not None:
                # Positive position_fp is Yes. Negative is No.
                item["pay"] = "yes" if signed >= 0 else "no"
            if signed is not None and not item.get("qty"):
                item["qty"] = format(abs(signed), "f")
        out.append(item)
    return out


def venue_tickets(
    snapshot: dict | None,
    *,
    watches: dict | None = None,
    tape: dict | None = None,
    now=None,
) -> tuple[list[dict], list[str]]:
    """Same open-set as Open now. Skip Gemini/Novig fill-history."""
    import open_count_sync as ocs

    warnings: list[str] = []
    snap = snapshot if isinstance(snapshot, dict) else {}
    tickets = ocs.open_set_tickets(snap, watches=watches, tape=tape, now=now)
    kalshi_ok = bool(snap.get("kalshi_ok"))
    poly_ok = bool(snap.get("poly_ok"))
    if kalshi_ok:
        tickets = overlay_kalshi_fields(tickets)
    elif snap:
        warnings.append("Kalshi positions GET failed; last good Kalshi rows kept if cached.")
    if not poly_ok and snap:
        warnings.append("Polymarket US positions GET failed; last good Poly rows kept if cached.")
    for shop, flag, note_bit in (
        ("gemini", "gemini_ok", "history fill, not a positions book"),
        ("novig", "novig_ok", "fills list, not a positions book"),
    ):
        if not snap.get(flag):
            continue
        for row in snap.get(shop) or []:
            if not isinstance(row, dict):
                continue
            if note_bit in str(row.get("note") or ""):
                continue
            qty = _qty(row.get("qty"))
            if qty < 1:
                continue
            tickets.append(
                {
                    "venue": shop,
                    "ticker": str(row.get("ticker") or ""),
                    "title": str(row.get("title") or row.get("ticker") or ""),
                    "qty": format(qty, "f"),
                    "pay": str(row.get("side") or "yes").lower() or "yes",
                    "fees": "",
                    "exposure": "",
                    "last_updated": "",
                }
            )
    return tickets, warnings


def _decode_ticket_display(
    ident: str,
    *,
    game: str,
    kind: str,
    number: str,
    market_label: str,
    side_label: str,
    pay: str,
    title: str = "",
) -> tuple[str, str, str, str, str, str]:
    """Upgrade ticker/yes-no labels to team names and Over/Under. Tennis MATCH unchanged."""
    title_s = "" if ktd.looks_like_ticker(title) else str(title or "")
    if not title_s:
        title_s = ktd.cached_title(ident)
    if ktd.is_yes_no_token(side_label):
        pay = side_label.lower()
        side_label = ""
    pay = pay if pay in {"yes", "no"} else "yes"
    decoded = ktd.decode_kalshi_ticker(ident, title=title_s, pay=pay)
    if not decoded.kind:
        return game, kind, number, market_label, side_label, pay
    kind = decoded.kind or kind
    if decoded.line_raw and not str(number or "").strip():
        number = decoded.line_raw
    generic_market = str(market_label or "") in {"", "spread", "total", "ML", "moneyline", "team_total"}
    if ktd.looks_like_ticker(game) or not str(game or "").strip() or str(game).strip() == ident:
        game = decoded.game or game
        market_label = decoded.market or market_label
    elif decoded.game and " vs " in str(game) and len(str(game).split()) <= 5:
        # "PHI vs WAS" / "BSU vs WSU" → full names when we have them.
        left, _, right = str(game).partition(" vs ")
        if left.strip().upper() in {decoded.away_code, decoded.home_code} or right.strip().upper() in {
            decoded.away_code,
            decoded.home_code,
        }:
            game = decoded.game
            if generic_market:
                market_label = decoded.market or market_label
    if not side_label or ktd.is_yes_no_token(side_label) or side_label.upper() == decoded.yes_code:
        side_label = ktd.bet_for_who(decoded, pay) or decoded.yes_name or side_label
    if kind == "moneyline":
        number = number if str(number or "").strip() else ""
    return game, kind, number, market_label, side_label, pay


def attach_intent(ticket: dict, intent: dict[tuple[str, str], dict]) -> dict:
    venue = str(ticket.get("venue") or "").lower()
    ident = str(ticket.get("ticker") or "")
    info = intent.get((venue, ident))
    kind, market_label = market_from_ticker(ident)
    game_guess, side_code, line = parse_ticker_game(ident)
    number = line
    title = str(ticket.get("title") or "")
    if info:
        kind = str(info.get("kind") or kind) or kind
        number = str(info.get("number") or number)
        sid = str(info.get("sid") or ticket.get("sid") or "")
        letter = str(info.get("letter") or ticket.get("letter") or _sid_letter(sid))
        name = str(info.get("name") or _sid_name(sid))
        sport = str(info.get("sport") or ticket.get("sport") or sport_from_ticker(ident))
        game = str(info.get("game") or ticket.get("game") or ticket.get("title") or game_guess or ident)
        side_label = str(info.get("side_label") or side_code)
        pay = str(ticket.get("pay") or info.get("pay") or "yes").lower()
        entry = info.get("entry")
        opened = str(info.get("opened_at") or ticket.get("last_updated") or "")
        lock_pair = bool(info.get("lock_pair")) or sid == "lock"
    elif str(ticket.get("sid") or ticket.get("letter") or "") not in {"", "unknown"}:
        sid = str(ticket.get("sid") or "")
        letter = str(ticket.get("letter") or _sid_letter(sid) or "unknown")
        if not sid:
            sid = {"A": "lock", "B": "tennis_crossover", "C": "cfb_favorite", "D": "spread_t0", "E": "tennis_t0_dog", "F": "tennis_t0_spread"}.get(letter, "")
        name = _sid_name(sid)
        sport = str(ticket.get("sport") or sport_from_ticker(ident))
        game = str(ticket.get("game") or ticket.get("title") or game_guess or ident)
        side_label = side_code
        pay = str(ticket.get("pay") or "yes").lower()
        entry = _px(ticket.get("entry"))
        opened = str(ticket.get("last_updated") or "")
        lock_pair = sid == "lock"
    else:
        sid = ""
        letter = "unknown"
        name = "unknown"
        sport = sport_from_ticker(ident)
        game = game_guess or str(ticket.get("title") or ident)
        side_label = side_code
        pay = str(ticket.get("pay") or "yes").lower()
        entry = _px(ticket.get("entry"))
        opened = str(ticket.get("last_updated") or "")
        lock_pair = False
        if is_nfl_moneyline(ident):
            sid = "lock"
            letter = "A"
            name = DISPLAY["lock"]
            lock_pair = True
    if entry is None:
        entry = _px(ticket.get("entry"))
    game, kind, number, market_label, side_label, pay = _decode_ticket_display(
        ident,
        game=game,
        kind=kind,
        number=number,
        market_label=market_label,
        side_label=side_label,
        pay=pay,
        title=title,
    )
    poly_game = _poly_nfl_game(ident)
    if poly_game:
        game = poly_game
        sport = "pro football"
        if str(letter or "") in {"", "unknown", "B"} and is_nfl_moneyline(ident):
            sid = "lock"
            letter = "A"
            name = DISPLAY["lock"]
            lock_pair = True
        if not kind or kind.lower() in {"ml", "moneyline"}:
            kind = "moneyline"
        if not market_label or market_label.lower() in {"", "ml", "moneyline"}:
            market_label = "ML"
        side_label = _nfl_full_name(side_label) or side_label
        if not side_label:
            title_l = str(title or game).casefold()
            match = re.match(r"aec-nfl-([a-z]{2,3})-([a-z]{2,3})-", str(ident or "").lower())
            if match:
                first = ktd.NFL_TEAMS.get(match.group(1).upper()) or ""
                second = ktd.NFL_TEAMS.get(match.group(2).upper()) or ""
                if first and first.casefold().split()[-1] in title_l:
                    side_label = first
                elif second and second.casefold().split()[-1] in title_l:
                    side_label = second
                elif pay == "yes":
                    side_label = first
    if kind == "moneyline" and not ktd.is_sports_ticker(ident):
        market_label = "ML"
        number = ""
    elif kind == "moneyline" and not market_label:
        market_label = "moneyline"
        number = ""
    elif kind == "spread" and (not market_label or market_label == "spread"):
        market_label = f"spread {number}".strip() if number else "spread"
    elif kind == "total" and (not market_label or market_label == "total"):
        market_label = f"total {number}".strip() if number else "total"
    exposure = _dec(ticket.get("exposure"))
    fees = _dec(ticket.get("fees"))
    qty = _qty(ticket.get("qty"))
    if entry is None and exposure is not None and qty:
        entry = exposure / qty
    if fees is None and entry is not None and venue == "kalshi":
        fees = kalshi_fee(entry) * qty
    cost = None
    if exposure is not None:
        cost = exposure + (fees or Decimal("0"))
    elif entry is not None:
        cost = entry * qty + (fees or Decimal("0"))
    held = et_text(opened) or et_text(str(ticket.get("last_updated") or ""))
    return {
        "sid": sid or "unknown",
        "letter": letter,
        "name": name,
        "sport": sport,
        "game": game,
        "kind": kind,
        "number": number,
        "market": market_label,
        "side_label": side_label,
        "pay": pay if pay in {"yes", "no"} else "yes",
        "venue": venue,
        "venue_label": VENUE_LABEL.get(venue, venue or ""),
        "ticker": ident,
        "qty": qty,
        "entry": entry,
        "fees": fees,
        "cost": cost,
        "exposure": exposure,
        "opened_at": opened,
        "held": held,
        "lock_pair": lock_pair,
        "mark": None,
        "mark_src": "",
        "pnl": None,
    }


def group_key(row: dict) -> tuple:
    letter = str(row.get("letter") or "unknown")
    game = " ".join(str(row.get("game") or "").lower().split())
    kind = str(row.get("kind") or "")
    number = str(row.get("number") or "")
    if letter == "unknown":
        return (letter, game, kind, number, str(row.get("venue") or ""), str(row.get("ticker") or ""))
    return (letter, game, kind, number)


def bet_text(row: dict) -> str:
    ident = str(row.get("ticker") or "")
    pay = str(row.get("pay") or "yes").lower()
    side = str(row.get("side_label") or "").strip()
    if ktd.is_yes_no_token(side):
        pay = side.lower()
        side = ""
    entry = row.get("entry")
    px = format(entry.quantize(FOUR), "f") if isinstance(entry, Decimal) else ""
    venue = str(row.get("venue_label") or row.get("venue") or "")
    if ktd.is_sports_ticker(ident):
        title = "" if ktd.looks_like_ticker(str(row.get("title") or "")) else str(row.get("title") or "")
        if not title:
            title = ktd.cached_title(ident)
        decoded = ktd.decode_kalshi_ticker(ident, title=title, pay=pay)
        phrase = ktd.kitchen_clear(decoded, pay)
        bits = [phrase] if phrase else (["No"] if pay == "no" else ["Yes"])
    else:
        yn = "No" if pay == "no" else "Yes"
        bits = [yn]
        if side:
            bits.append(side)
    if px:
        bits.append(px)
    if venue:
        bits.append(venue)
    return " ".join(bits)


def merge_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for row in rows:
        key = group_key(row)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)
    out = []
    for key in order:
        legs = grouped[key]
        first = dict(legs[0])
        first["legs"] = legs
        first["bets"] = "; ".join(bet_text(leg) for leg in legs)
        venues = []
        for leg in legs:
            label = str(leg.get("venue_label") or "")
            if label and label not in venues:
                venues.append(label)
        first["venue_label"] = "; ".join(venues)
        qtys = [format(leg["qty"].normalize(), "f") if isinstance(leg.get("qty"), Decimal) else str(leg.get("qty") or "") for leg in legs]
        first["qty_text"] = qtys[0] if len(set(qtys)) == 1 else "; ".join(qtys)
        costs = [leg.get("cost") for leg in legs if leg.get("cost") is not None]
        first["cost"] = sum(costs, Decimal("0")) if len(costs) == len(legs) else first.get("cost")
        entries = []
        for leg in legs:
            if leg.get("entry") is None:
                continue
            text = format(leg["entry"].quantize(FOUR), "f")
            if leg.get("fees") is not None:
                text += f" + {format(leg['fees'].quantize(FOUR), 'f')} fee"
            entries.append(text)
        first["entry_text"] = "; ".join(entries) if entries else "—"
        helds = [leg.get("held") for leg in legs if leg.get("held")]
        first["held"] = helds[0] if helds else ""
        out.append(first)
    return out


def _nfl_full_name(token: str) -> str:
    text = str(token or "").strip()
    if not text:
        return ""
    up = text.upper()
    if up in ktd.NFL_TEAMS:
        return ktd.NFL_TEAMS[up]
    low = text.casefold()
    for name in ktd.NFL_TEAMS.values():
        n = name.casefold()
        if n == low or n.endswith(" " + low) or low == n.split()[-1]:
            return name
    return text


def _poly_nfl_game(ident: str) -> str:
    text = str(ident or "").lower()
    match = re.match(r"aec-nfl-([a-z]{2,3})-([a-z]{2,3})-\d{4}-\d{2}-\d{2}$", text)
    if not match:
        return ""
    left = ktd.NFL_TEAMS.get(match.group(1).upper())
    right = ktd.NFL_TEAMS.get(match.group(2).upper())
    if left and right:
        return f"{left} vs {right}"
    return ""


def _who_pays_for_leg(leg: dict) -> str:
    ident = str(leg.get("ticker") or "")
    pay = str(leg.get("pay") or "yes").lower()
    if ktd.is_sports_ticker(ident):
        title = "" if ktd.looks_like_ticker(str(leg.get("title") or "")) else str(leg.get("title") or "")
        decoded = ktd.decode_kalshi_ticker(ident, title=title, pay=pay)
        return ktd.pays_if_label(decoded, pay)
    who = _nfl_full_name(str(leg.get("side_label") or "").strip())
    if not who:
        return ""
    low = who.casefold()
    if low.endswith(" win") or low.endswith(" cover") or low in {"over", "under"}:
        return who
    kind = str(leg.get("kind") or leg.get("market") or "").lower()
    if "spread" in kind:
        return f"{who} cover"
    if "total" in kind:
        return who
    return f"{who} win"


def pair_nfl_lock_tickets(rows: list[dict]) -> None:
    """Same NFL ML fixture on two shops is one A lock-gap pair. Display only."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        ident = str(row.get("ticker") or row.get("instrument") or "")
        inferred = sport_from_ticker(ident)
        if inferred == "pro football":
            row["sport"] = "pro football"
        key = nfl_fixture_key(ident)
        if key:
            groups.setdefault(key, []).append(row)
    for group in groups.values():
        letters = {str(r.get("letter") or r.get("system") or "") for r in group}
        venues = {str(r.get("venue") or "").lower() for r in group}
        if "A" not in letters and not ({"kalshi", "polymarket"} <= venues):
            continue
        for row in group:
            ident = str(row.get("ticker") or row.get("instrument") or "")
            if not is_nfl_moneyline(ident):
                continue
            row["sport"] = "pro football"
            row["letter"] = "A"
            row["sid"] = "lock"
            row["name"] = DISPLAY["lock"]
            row["lock_pair"] = True
            if "system" in row:
                row["system"] = "A"
            row["open_type"] = order_types.open_now_type("A")


def stamp_open_labels(rows: list[dict], watches: dict | None = None) -> None:
    """Type + who-$1-pays on each Positions / Open now row."""
    b_matches = []
    if isinstance(watches, dict):
        blob = watches.get("tennis_crossover") or {}
        if isinstance(blob, dict):
            b_matches = list(blob.get("matches") or [])
    for row in rows:
        letter = str(row.get("letter") or "")
        step = ""
        cross_fill = ""
        stage = ""
        if letter == "B":
            game = str(row.get("game") or "").casefold()
            for match in b_matches:
                if not isinstance(match, dict):
                    continue
                if str(match.get("game") or "").casefold() == game:
                    stage = str(match.get("stage") or "")
                    cross_fill = str(match.get("cross_fill") or "")
                    last = match.get("last_order") if isinstance(match.get("last_order"), dict) else {}
                    step = str(last.get("step") or "")
                    break
        row["open_type"] = order_types.open_now_type(
            letter, step=step, cross_fill=cross_fill, stage=stage
        )
        pays = []
        for leg in row.get("legs") or [row]:
            label = _who_pays_for_leg(leg)
            if label and label not in pays:
                pays.append(label)
        row["who_pays"] = "; ".join(pays)
    flag_mismatched_lock_pairs(rows)


def tape_mismatch_idents() -> set[str]:
    """Instruments on a sent A pair whose legs are not the same settlement.

    Novig is not a positions book, so the Kalshi team-total ticket still needs
    this tape lookup. Display only. Does not sell.
    """
    import price_memory

    groups: dict[str, dict] = {}
    if not ORDERS.exists():
        return set()
    try:
        with ORDERS.open(encoding="utf-8") as handle:
            for line in handle:
                if "sent" not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("event") != "sent":
                    continue
                ident = str(row.get("instrument") or row.get("ticker") or "")
                if not ident:
                    continue
                key = str(row.get("bet_key") or "") or "\t".join(
                    str(row.get(k) or "") for k in ("game", "sport", "sent_at")
                )
                slot = groups.setdefault(key, {"idents": [], "extras": []})
                slot["idents"].append(ident)
                parts = key.split("\t")
                if len(parts) >= 4:
                    slot["extras"].append(parts[3])
                slot["extras"].append(str(row.get("market_type") or ""))
    except OSError:
        return set()
    bad: set[str] = set()
    for slot in groups.values():
        kinds = price_memory.settlement_kinds(*slot["idents"], *slot["extras"])
        if len(kinds) > 1:
            bad.update(slot["idents"])
    return bad


def flag_mismatched_lock_pairs(rows: list[dict]) -> None:
    """Open now: team-vs-game (or mixed kinds) on one A game is not a lock.

    Display only. Does not sell or flatten.
    """
    tape_bad = tape_mismatch_idents()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("letter") or "") != "A":
            continue
        idents = [str(row.get("ticker") or row.get("instrument") or "")]
        idents.extend(str(t) for t in (row.get("tickers") or []) if t)
        if any(ident in tape_bad for ident in idents if ident):
            row["open_type"] = "not a lock (two directional)"
            row["lock_pair"] = False


def apply_quotes(rows: list[dict], quotes: dict[tuple[str, str], dict] | None) -> None:
    quotes = quotes or {}
    for row in rows:
        pnls = []
        marks = []
        missing = False
        for leg in row.get("legs") or [row]:
            q = quotes.get((str(leg.get("venue") or "").lower(), str(leg.get("ticker") or "")))
            if not q or q.get("mark") is None:
                missing = True
                continue
            mark = _px(q.get("mark"))
            if mark is None:
                missing = True
                continue
            pay = str(leg.get("pay") or "yes").lower()
            if pay == "no" and q.get("mark_no") is not None:
                mark = _px(q.get("mark_no")) or mark
            elif pay == "no" and q.get("yes_mid") is not None:
                yes_mid = _px(q.get("yes_mid"))
                mark = (ONE - yes_mid) if yes_mid is not None else mark
            leg["mark"] = mark
            leg["mark_src"] = str(q.get("src") or "")
            cost = leg.get("cost")
            qty = leg.get("qty") if isinstance(leg.get("qty"), Decimal) else _qty(leg.get("qty"))
            if cost is None or mark is None:
                missing = True
                continue
            pnl = mark * qty - cost
            leg["pnl"] = pnl
            pnls.append(pnl)
            label = "mid" if q.get("src") in {"memory-mid", "rest-mid"} or q.get("kind") == "mid" else (
                "bid" if q.get("kind") == "bid" else ""
            )
            marks.append(f"{format(mark.quantize(FOUR), 'f')}{(' ' + label) if label else ''}")
        if missing or len(pnls) != len(row.get("legs") or [row]):
            row["pnl"] = None
            row["mark_text"] = "—"
        else:
            row["pnl"] = sum(pnls, Decimal("0"))
            row["mark_text"] = "; ".join(marks)
        if not row.get("mark_text"):
            row["mark_text"] = "—"


def memory_quotes(rows: list[dict], last: dict | None = None, now: datetime | None = None) -> dict[tuple[str, str], dict]:
    if last is None:
        try:
            import price_memory

            last = price_memory.load_last()
        except Exception:
            last = {}
    now = now or datetime.now(ET)
    found: dict[tuple[str, str], dict] = {}
    if not isinstance(last, dict):
        return found
    for row in rows:
        for leg in row.get("legs") or [row]:
            venue = str(leg.get("venue") or "")
            ident = str(leg.get("ticker") or "")
            if not ident:
                continue
            want_venue = VENUE_LABEL.get(venue, venue)
            want_pay = str(leg.get("pay") or "yes").lower()
            game = str(leg.get("game") or "").lower()
            kind = str(leg.get("kind") or "")
            side = str(leg.get("side_label") or "").lower()
            tokens = [t for t in re.split(r"[^a-z0-9]+", game) if len(t) >= 3]
            best = None
            best_dt = None
            for item in last.values():
                if not isinstance(item, dict):
                    continue
                if str(item.get("venue") or "") != want_venue:
                    continue
                if str(item.get("pay") or "").lower() != want_pay:
                    continue
                if kind and str(item.get("market_type") or "") not in {kind, ""}:
                    if str(item.get("market_type") or "") != kind:
                        continue
                seen = _parse_dt(str(item.get("seen_at") or ""))
                if seen is None:
                    continue
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=ET)
                if abs((now - seen).total_seconds()) > FRESH_SEC:
                    continue
                g = str(item.get("game") or "").lower()
                s = str(item.get("side") or "").lower()
                hit = False
                if side and (side in s or s in side):
                    hit = True
                if tokens and sum(1 for t in tokens if t in g) >= min(2, len(tokens)):
                    hit = True
                if ident.lower() in g:
                    hit = True
                if not hit:
                    continue
                if best_dt is None or seen > best_dt:
                    best = item
                    best_dt = seen
            if best is not None:
                mark = _px(best.get("price"))
                if mark is not None:
                    found[(venue, ident)] = {
                        "mark": mark,
                        "src": "memory",
                        "kind": "ask" if want_pay == "yes" else "bid",
                    }
    return found


def _http_get(url: str, timeout: float = 12.0) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "stockresearch-job-status-positions"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, body
    except Exception as exc:
        return 0, type(exc).__name__


def rest_kalshi_mark(ticker: str) -> dict | None:
    url = (
        "https://api.elections.kalshi.com/trade-api/v2/markets/"
        + urllib.parse.quote(ticker, safe="")
    )
    status, body = _http_get(url)
    if status != 200:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    market = payload.get("market") if isinstance(payload, dict) else None
    if not isinstance(market, dict):
        market = payload if isinstance(payload, dict) else {}
    bid = _px(market.get("yes_bid_dollars") or market.get("yes_bid"))
    ask = _px(market.get("yes_ask_dollars") or market.get("yes_ask"))
    last = _px(market.get("last_price_dollars") or market.get("last_price"))
    mark = None
    kind = ""
    src = "rest"
    if bid is not None and ask is not None:
        mark = (bid + ask) / Decimal("2")
        kind = "mid"
        src = "rest-mid"
    elif bid is not None:
        mark = bid
        kind = "bid"
        src = "rest-bid"
    elif ask is not None:
        mark = ask
        kind = "ask"
        src = "rest-ask"
    elif last is not None:
        mark = last
        kind = "last"
        src = "rest-last"
    if mark is None:
        return None
    yes_sub = str(market.get("yes_sub_title") or market.get("title") or "")
    if ticker and yes_sub and not ktd.looks_like_ticker(yes_sub):
        try:
            cache = ktd.load_title_cache()
            prev = cache.get(ticker) if isinstance(cache.get(ticker), dict) else {}
            cache[ticker] = {**(prev or {}), "title": yes_sub, "yes_sub_title": str(market.get("yes_sub_title") or "")}
            ktd.save_title_cache(cache)
        except Exception:
            pass
    return {
        "mark": mark,
        "yes_bid": bid,
        "yes_ask": ask,
        "yes_mid": mark if kind == "mid" else ((bid + ask) / Decimal("2") if bid is not None and ask is not None else None),
        "src": src,
        "kind": kind,
        "title": yes_sub,
    }


def rest_polymarket_mark(slug: str) -> dict | None:
    try:
        import polymarket_us_live

        url = polymarket_us_live.GATEWAY + "/v1/markets/" + urllib.parse.quote(slug, safe="")
    except Exception:
        url = "https://gateway.polymarket.us/v1/markets/" + urllib.parse.quote(slug, safe="")
    status, body = _http_get(url)
    if status != 200:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    bid = _px(payload.get("yes_bid") or payload.get("bestBid"))
    ask = _px(payload.get("yes_ask") or payload.get("bestAsk"))
    mark = None
    kind = ""
    src = "rest"
    if bid is not None and ask is not None:
        mark = (bid + ask) / Decimal("2")
        kind = "mid"
        src = "rest-mid"
    elif bid is not None:
        mark = bid
        kind = "bid"
        src = "rest-bid"
    elif ask is not None:
        mark = ask
        kind = "ask"
        src = "rest-ask"
    if mark is None:
        return None
    return {"mark": mark, "yes_bid": bid, "yes_ask": ask, "src": src, "kind": kind}


def fetch_marks(rows: list[dict], *, memory: dict | None = None, rest: bool = True) -> dict[tuple[str, str], dict]:
    quotes = memory_quotes(rows, last=memory)
    if not rest:
        return quotes
    for row in rows:
        for leg in row.get("legs") or [row]:
            key = (str(leg.get("venue") or "").lower(), str(leg.get("ticker") or ""))
            if key in quotes or not key[1]:
                continue
            try:
                if key[0] == "kalshi":
                    got = rest_kalshi_mark(key[1])
                elif key[0] == "polymarket":
                    got = rest_polymarket_mark(key[1])
                else:
                    got = None
            except Exception:
                got = None
            if got:
                quotes[key] = got
    return quotes


def footer_from_rows(rows: list[dict]) -> dict:
    priced = [row for row in rows if row.get("pnl") is not None]
    skipped = len(rows) - len(priced)
    total = sum((row["pnl"] for row in priced), Decimal("0")) if priced else None
    if not rows:
        total = Decimal("0")
    elif not priced:
        total = None
    return {
        "n": len(rows),
        "priced": len(priced),
        "skipped": skipped,
        "pnl": total,
        "pnl_text": money(total) if total is not None else "—",
        "count_text": f"{len(rows)} row{'s' if len(rows) != 1 else ''}",
    }


def open_now_from_rows(rows: list[dict] | None) -> dict[str, int]:
    """Open now is the count of Positions rows by system letter."""
    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for row in rows or []:
        letter = str(row.get("letter") or "")
        if letter in counts:
            counts[letter] += 1
    return counts


def empty_bundle(*, warning: str = "") -> dict:
    notes = [warning] if warning else []
    return {
        "rows": [],
        "warnings": notes,
        "footer": footer_from_rows([]),
        "open_now": {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0},
        "used_cache": False,
        "pulled_at": iso_now(),
    }


def serializable_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        item = {
            "letter": row.get("letter"),
            "name": row.get("name"),
            "sport": row.get("sport"),
            "game": row.get("game"),
            "market": row.get("market"),
            "bets": row.get("bets"),
            "open_type": row.get("open_type") or "",
            "who_pays": row.get("who_pays") or "",
            "venue_label": row.get("venue_label"),
            "qty_text": row.get("qty_text"),
            "entry_text": row.get("entry_text"),
            "mark_text": row.get("mark_text"),
            "pnl_text": money(row.get("pnl")) if row.get("pnl") is not None else "—",
            "pnl": format(row["pnl"], "f") if row.get("pnl") is not None else None,
            "held": row.get("held") or "",
            "sid": row.get("sid"),
            "tickers": [str(leg.get("ticker") or "") for leg in (row.get("legs") or [row])],
        }
        out.append(item)
    return out


def save_cache(bundle: dict) -> None:
    payload = {
        "pulled_at": bundle.get("pulled_at") or iso_now(),
        "rows": serializable_rows(bundle.get("rows") or []),
        "footer": {
            "n": (bundle.get("footer") or {}).get("n", 0),
            "pnl": None
            if (bundle.get("footer") or {}).get("pnl") is None
            else format((bundle.get("footer") or {})["pnl"], "f"),
            "skipped": (bundle.get("footer") or {}).get("skipped", 0),
        },
        "warnings": bundle.get("warnings") or [],
    }
    try:
        _dump_json(CACHE_PATH, payload)
    except OSError:
        pass


def load_cache() -> dict | None:
    data = _load_json(CACHE_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return None
    rows = []
    for item in data["rows"]:
        if not isinstance(item, dict):
            continue
        pnl = _dec(item.get("pnl"))
        rows.append(
            {
                **item,
                "pnl": pnl,
                "mark_text": item.get("mark_text") or "—",
                "entry_text": item.get("entry_text") or "—",
                "qty_text": item.get("qty_text") or "",
                "legs": [{"ticker": t} for t in (item.get("tickers") or [])],
            }
        )
    footer = footer_from_rows(rows)
    return {
        "rows": rows,
        "warnings": list(data.get("warnings") or []),
        "footer": footer,
        "open_now": open_now_from_rows(rows),
        "used_cache": True,
        "pulled_at": str(data.get("pulled_at") or ""),
    }


def _fill_sports_titles(rows: list[dict], *, fetch: bool = False) -> None:
    """If an open Kalshi sports row still has no market title, fetch once and cache."""
    if not fetch:
        return
    cache = ktd.load_title_cache()
    for row in rows:
        for leg in row.get("legs") or [row]:
            ident = str(leg.get("ticker") or "")
            if not ktd.is_sports_ticker(ident):
                continue
            title = ktd.cached_title(ident, cache)
            if title:
                decoded = ktd.decode_kalshi_ticker(ident, title=title, pay=str(leg.get("pay") or "yes"))
                if decoded.kind == "spread" and decoded.line:
                    if ktd.is_yes_no_token(str(leg.get("side_label") or "")) or not str(leg.get("side_label") or "").strip():
                        leg["side_label"] = ktd.bet_for_who(decoded, str(leg.get("pay") or "yes"))
                    if str(leg.get("market") or "").lower() in {"", "spread"} or ktd.looks_like_ticker(str(row.get("game") or "")):
                        leg["market"] = decoded.market
                        row["market"] = decoded.market
                continue
            title, cache = ktd.title_for(ident, cache=cache, fetch=True)
            if not title:
                continue
            decoded = ktd.decode_kalshi_ticker(ident, title=title, pay=str(leg.get("pay") or "yes"))
            if decoded.game and (
                ktd.looks_like_ticker(str(row.get("game") or "")) or not str(row.get("game") or "").strip()
            ):
                row["game"] = decoded.game
                leg["game"] = decoded.game
            if decoded.market:
                leg["market"] = decoded.market
                row["market"] = decoded.market
            if decoded.kind and (
                ktd.is_yes_no_token(str(leg.get("side_label") or "")) or not str(leg.get("side_label") or "").strip()
            ):
                leg["side_label"] = ktd.bet_for_who(decoded, str(leg.get("pay") or "yes"))
    for row in rows:
        legs = row.get("legs") or [row]
        row["bets"] = "; ".join(bet_text(leg) for leg in legs)


def build_rows(
    snapshot: dict | None,
    *,
    intent: dict[tuple[str, str], dict] | None = None,
    quotes: dict[tuple[str, str], dict] | None = None,
    fetch_quotes: bool = False,
    fetch_titles: bool | None = None,
    watches: dict | None = None,
    tape: dict | None = None,
    now=None,
) -> dict:
    """Join the shared open-set to intent and optional marks. No live orders."""
    if fetch_titles is None:
        fetch_titles = fetch_quotes
    warnings: list[str] = []
    snap = snapshot if isinstance(snapshot, dict) else {}
    tickets, warn = venue_tickets(snap, watches=watches, tape=tape, now=now)
    warnings.extend(warn)
    kalshi_ok = bool(snap.get("kalshi_ok"))
    poly_ok = bool(snap.get("poly_ok"))
    if not snap:
        cached = load_cache()
        if cached:
            cached["warnings"] = ["Venue snapshot missing; showing last good Positions rows."] + list(
                cached.get("warnings") or []
            )
            return cached
        return empty_bundle(warning="No venue snapshot; Positions empty.")
    if not kalshi_ok and not poly_ok:
        cached = load_cache()
        if cached:
            cached["warnings"] = warnings + ["Both venue position GETs failed; last good rows."] + list(
                cached.get("warnings") or []
            )
            return cached
        return empty_bundle(warning="; ".join(warnings) or "Venue position GETs failed.")
    if not kalshi_ok or not poly_ok:
        cached = load_cache()
        if cached:
            keep_venues = set()
            if kalshi_ok:
                keep_venues.add("kalshi")
            if poly_ok:
                keep_venues.add("polymarket")
            live_keys = {
                (str(t.get("venue") or ""), str(t.get("ticker") or ""))
                for t in tickets
            }
            for item in cached.get("rows") or []:
                for ticker in item.get("tickers") or []:
                    venue = "kalshi" if str(ticker).startswith("KX") else "polymarket"
                    if venue in keep_venues:
                        continue
                    key = (venue, str(ticker))
                    if key in live_keys:
                        continue
                    # Failed venue: keep last good ticket for that shop only.
                    tickets.append(
                        {
                            "venue": venue,
                            "ticker": str(ticker),
                            "title": str(item.get("game") or ticker),
                            "qty": str(item.get("qty_text") or "1"),
                            "pay": "yes",
                            "from_cache": True,
                        }
                    )
                    live_keys.add(key)
            warnings.append("One venue book failed; mixed live rows with last good rows for the failed shop.")
    intent = intent if intent is not None else load_intent_index()
    tagged = [attach_intent(ticket, intent) for ticket in tickets]
    try:
        pair_nfl_lock_tickets(tagged)
    except Exception:
        pass
    rows = merge_rows(tagged)
    try:
        _fill_sports_titles(rows, fetch=bool(fetch_titles))
    except Exception:
        pass
    if quotes is not None:
        apply_quotes(rows, quotes)
    elif fetch_quotes:
        try:
            apply_quotes(rows, fetch_marks(rows, rest=True))
        except Exception as exc:
            warnings.append(f"Mark fetch {type(exc).__name__}; Open P&L shown as —.")
            apply_quotes(rows, {})
    else:
        apply_quotes(rows, {})
    try:
        stamp_open_labels(rows, watches)
    except Exception:
        pass
    skipped = sum(1 for row in rows if row.get("pnl") is None)
    if skipped:
        warnings.append(
            f"{skipped} row{'s' if skipped != 1 else ''} excluded from the Open P&L sum (no quote)."
        )
    bundle = {
        "rows": rows,
        "warnings": warnings,
        "footer": footer_from_rows(rows),
        "open_now": open_now_from_rows(rows),
        "used_cache": False,
        "pulled_at": iso_now(),
        "venue_ok": bool(kalshi_ok or poly_ok),
    }
    return bundle


def bundle_from_snapshot(snapshot: dict | None, *, fetch_quotes: bool = True) -> dict:
    try:
        import open_count_sync as ocs

        watches = {sid: ocs.load_watch(sid) for sid in ocs.WATCH}
        tape = ocs.load_tape_index()
        bundle = build_rows(
            snapshot,
            fetch_quotes=fetch_quotes,
            watches=watches,
            tape=tape,
        )
        if bundle.get("venue_ok"):
            save_cache(bundle)
        return bundle
    except Exception as exc:
        cached = load_cache()
        if cached:
            cached["warnings"] = [f"Positions build {type(exc).__name__}; last good rows."] + list(
                cached.get("warnings") or []
            )
            return cached
        return empty_bundle(warning=f"Positions build {type(exc).__name__}.")


def render_table(bundle: dict | None, *, caption: str | None = None) -> str:
    bundle = bundle if isinstance(bundle, dict) else empty_bundle()
    rows = bundle.get("rows") or []
    footer = bundle.get("footer") or footer_from_rows(rows)
    headers = [
        ("Sys", "text"),
        ("Name", "text"),
        ("Type", "text"),
        ("Sport", "text"),
        ("Game", "text"),
        ("Market", "text"),
        ("Bets", "text"),
        ("Who $1 pays", "text"),
        ("Venue", "text"),
        ("Qty", "num"),
        ("Entry", "text"),
        ("Mark", "text"),
        ("Open P&L $", "num"),
        ("Held since ET", "date"),
    ]
    head = "".join(_th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        pnl = row.get("pnl")
        pnl_text = money(pnl) if pnl is not None else (row.get("pnl_text") or "—")
        cells = [
            row.get("letter") or "unknown",
            row.get("name") or "unknown",
            row.get("open_type") or order_types.open_now_type(str(row.get("letter") or "")),
            row.get("sport") or "",
            row.get("game") or "",
            row.get("market") or "",
            row.get("bets") or "",
            row.get("who_pays") or "",
            row.get("venue_label") or "",
            row.get("qty_text") or "",
            row.get("entry_text") or "—",
            row.get("mark_text") or "—",
            pnl_text,
            row.get("held") or "",
        ]
        tds = "".join(f"<td>{_esc(cell)}</td>" for cell in cells)
        body.append(f"<tr>{tds}</tr>")
    foot_cells = [
        footer.get("count_text") or "0 rows",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        footer.get("pnl_text") or "—",
        "",
    ]
    foot = "<tr class=\"total-row\">" + "".join(f"<td>{_esc(cell)}</td>" for cell in foot_cells) + "</tr>"
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    note = caption or POSITIONS_CAPTION
    warns = bundle.get("warnings") or []
    warn_html = ""
    if warns:
        warn_html = '<p class="note">' + _esc(" ".join(str(w) for w in warns if w)) + "</p>"
    return (
        "<h2>Positions</h2>"
        f'<p class="note">{_esc(note)}</p>'
        f"{warn_html}"
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}{foot}</tbody>"
        "</table></div>"
    )


def write_stamp(bundle: dict, *, pids: dict | None = None) -> Path:
    ensure_dirs()
    rows = bundle.get("rows") or []
    footer = bundle.get("footer") or footer_from_rows(rows)
    mapped = [row for row in rows if str(row.get("letter") or "") in {"C", "D", "A", "B", "E"}]
    unknown = [row for row in rows if str(row.get("letter") or "") == "unknown"]
    pid_bits = ", ".join(f"{k} {v}" for k, v in (pids or {}).items()) or "unchanged (status rewrite only)"
    table = render_table(
        bundle,
        caption=(
            "T0 is the listed start (the first second of the game). ML is moneyline "
            "(who wins). " + POSITIONS_CAPTION
        ),
    )
    named = ", ".join(
        f"{row.get('letter')} {row.get('game')} {row.get('market')}"
        for row in rows
    ) or "none"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>job_status Positions — 24 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note, .tiny {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>job_status Positions</h1>
<p class="note">Written {_esc(bundle.get("pulled_at") or iso_now())}. Research-candidate live. Not gold. Not DailyRun. Did not sell tickets. Did not start a second Tennis crossover.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{_esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{_esc(PLAIN)}</p>
</div>
<p>Live page: <a href="job_status.html">job_status.html</a>. This stamp is the research note. Open P&amp;L is mark-to-market versus entry (fees in when the venue reported them). A missing quote is an em-dash and is left out of the footer sum.</p>
<p class="note">{footer.get("count_text")}; footer Open P&amp;L { _esc(footer.get("pnl_text") or "—") }. Named now: {_esc(named)}. Unknown tickets: {len(unknown)}. Mapped C/D/A/B: {len(mapped)}.</p>
{table}
<p class="tiny">Live PIDs { _esc(pid_bits) }. Venue positions are truth; house watches only tag the system. File URL {_esc(STAMP_FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP_PAGE.parent.mkdir(parents=True, exist_ok=True)
    STAMP_PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return STAMP_PAGE


def current_pids() -> dict:
    try:
        import prediction_systems as ps

        jobs = ps.classify_jobs()
        out = {}
        for sid, label in (
            ("cfb_favorite", "C"),
            ("spread_t0", "D"),
            ("tennis_crossover", "B"),
            ("tennis_t0_dog", "E"),
            ("tennis_t0_spread", "F"),
        ):
            pids = ps.pids_for(sid, jobs)
            out[label] = pids[0] if pids else "—"
        sup = (jobs.get("supervisor") or [None])[0]
        out["A supervisor"] = sup["pid"] if isinstance(sup, dict) and sup.get("pid") else "—"
        return out
    except Exception:
        return {}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_dirs()
    snap = None
    try:
        import open_count_sync

        snap = open_count_sync.venue_snapshot()
    except Exception as exc:
        print(f"venue snapshot {type(exc).__name__}", file=sys.stderr)
    bundle = bundle_from_snapshot(snap, fetch_quotes=True)
    if "stamp" in argv or not argv:
        pids = current_pids()
        path = write_stamp(bundle, pids=pids)
        print(path)
    footer = bundle.get("footer") or {}
    print(f"rows {footer.get('n', 0)} pnl {footer.get('pnl_text')}")
    for row in bundle.get("rows") or []:
        print(
            f"{row.get('letter')} {row.get('game')} {row.get('market')} "
            f"{row.get('bets')} pnl={money(row.get('pnl')) if row.get('pnl') is not None else '—'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
