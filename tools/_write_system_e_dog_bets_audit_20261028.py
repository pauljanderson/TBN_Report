"""Audit System E tennis T0 dog fills on 2026-10-28. Research only.

Does not place, cancel, or sell. Does not retune 11–49. Does not start a
second Tennis crossover (B). Does not touch hist/. Does not rename Kalshi
overlay tickers. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import kalshi_ticker_decode as ktd
import live_tennis_t0_dog as e
import prediction_systems as systems
import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from t0_all_games_stats import table

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "system_e_dog_bets_audit_20261028.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/system_e_dog_bets_audit_20261028.html"
)
DAY = datetime(2026, 10, 28, tzinfo=ET)
ASKED = (
    "Paul: analyze System E Tennis T0 dog fills. Not all make sense. Do not "
    "retune 11–49. Do not start second B. Quoted dashboard rows 2026-10-28 ET: "
    "(1) 11:30 E Djokovic vs Humbert Poly Yes Novak Djokovic 0.55 fee 0.02 = 0.57 "
    "settled win +$0.43; (2) 11:09 E Yaneva vs Selekhmeteva Poly No Oksana "
    "Selekhmeteva 0.40 fee 0.02 = 0.42 settled loss −$0.42; (3) 10:39 E Djokovic vs "
    "Humbert Poly No Ugo Humbert 0.30 fee 0.01 = 0.31 settled loss −$0.31; "
    "(4) 10:38 E Musetti vs Tiafoe Kalshi No Lorenzo Musetti 0.51 fee 0.0175 = 0.5275 "
    "settled loss −$0.53; (5) 09:41 E Musetti vs Tiafoe Kalshi Yes Lorenzo Musetti "
    "0.43 fee 0.0172 = 0.4472 settled win +$0.55; (6) 09:39 E Tabur vs Romano Poly "
    "No Filippo Romano 0.29 fee 0.01 = 0.30 settled win +$0.70. Intended: Yes on the "
    "underdog at T0 ask in 11–49¢. List every E send that should not have fired."
)
PLAIN = (
    "System E is supposed to buy one cheap tennis underdog at first serve: Yes, "
    "price 11 through 49 cents, hold until the match is over. Several kitchen rows "
    "look like we bought the favorite (Djokovic at 55¢) or bet “No” on a name. "
    "We checked the live sender, the order tape, and the leftover-lock watcher. "
    "The real T0 dog tickets were Yes on the cheaper player at a legal price. "
    "The weird 51¢ and 55¢ rows are a different bot (leftover lock hedge) that "
    "reattached to E’s ticket. Kitchen “No {player}” on Polymarket is usually a "
    "label: Polymarket BUY_SHORT on that player pays when they win, so it is Yes "
    "that player. We did not change the 11–49 band and did not patch live E."
)
QUOTED_IDS = {
    "DCFWP54G11TB": 1,
    "DCFK7M0G11MM": 2,
    "DCF5J93G11MM": 3,
    "01a182f3-52f8-72fc-aac8-f260aa203891": 4,
    "01a182be-cda8-7252-b003-5928592c38e4": 5,
    "DCEA1H9G11N6": 6,
}
def load_dash_by_oid() -> dict[str, dict]:
    cache = load_json(RAW / "dashboard_cache.json")
    out: dict[str, dict] = {}
    for row in cache.get("today_rows") or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("order_id") or "")
        if oid:
            out[oid] = row
    return out


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value), quote=True)


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def parse_et(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def on_day(stamp: datetime | None) -> bool:
    if stamp is None:
        return False
    local = stamp.astimezone(ET)
    return local.date() == DAY.date()


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data


def game_names(title: str) -> list[str]:
    text = " ".join(
        str(title or "").replace(" vs. ", " vs ").replace(" @ ", " vs ").split()
    )
    for tail in (" Round of 16", " Round of 32", " Quarterfinal", " Semifinal", " Final"):
        if text.endswith(tail):
            text = text[: -len(tail)]
    if " vs " not in text.lower():
        return []
    left, right = text.split(" vs ", 1)
    names = [left.strip(" ."), right.strip(" .")]
    return [n for n in names if n]


def other_name(who: str, title: str) -> str:
    names = game_names(title)
    if not who or len(names) < 2:
        return names[1] if len(names) > 1 else ""
    want = who.lower()
    for name in names:
        if name.lower() == want:
            continue
        last = name.split()[-1].lower()
        if last and last in want:
            continue
        if want in name.lower() or name.lower() in want:
            continue
        return name
    for name in names:
        if name.split()[-1].lower() != (who.split()[-1].lower() if who else ""):
            return name
    return ""


def yes_player_phrase(row: dict) -> str:
    """If this seat pays $1 when P wins → Yes P. Does not change send side.

    E T0 Polymarket BUY_SHORT names the dog (short player) and pays if they win.
    A leftover watch No on the same ticker as an E Yes is a true No (hedge).
    """
    venue = str(row.get("venue") or "").lower()
    book = str(row.get("side") or "").lower()
    player = str(row.get("side_label") or row.get("player") or "").strip()
    game = str(row.get("game") or "")
    inst = str(row.get("instrument") or "")
    step = str(row.get("step") or "")
    if venue == "kalshi" and ktd.is_sports_ticker(inst):
        decoded = ktd.decode_kalshi_ticker(inst, title=game or row.get("title") or "", pay=book)
        who = ktd.bet_for_who(decoded, book)
        return f"Yes {who}" if who else (ktd.kitchen_phrase(decoded, book) or "Yes")
    if venue == "polymarket":
        if book == "yes" and player:
            return f"Yes {player}"
        if book == "no" and player:
            if step == "watch":
                opp = other_name(player, game)
                return f"Yes {opp}" if opp else f"No {player}"
            return f"Yes {player}"
    if book in {"yes", "no"} and player:
        return f"{book.capitalize()} {player}"
    return player or "—"


def in_band_txt(px) -> str:
    value = _dec(px)
    if value is None:
        return "unknown"
    return "yes" if systems.in_dog_band(value) else "no"


def dog_or_fav(who: str, dog: str, cash) -> str:
    px = _dec(cash)
    who_l = (who or "").lower()
    dog_l = (dog or "").lower()
    if who and dog and (who_l == dog_l or who_l in dog_l or dog_l in who_l):
        return "dog"
    if px is not None and px >= Decimal("0.50"):
        return "favorite / ≥50¢"
    if who and dog:
        return "favorite (other name)"
    return "—"


def b_note(title: str, b_watch: dict) -> str:
    if e.b_holds_match(title, sport="tennis", b_status=b_watch):
        return "B holds (E should skip)"
    want = " ".join(str(title or "").lower().split())
    for row in b_watch.get("skipped") or []:
        if not isinstance(row, dict):
            continue
        game = " ".join(str(row.get("game") or "").lower().split())
        if game != want:
            continue
        reason = str(row.get("reason") or "")
        if "t0_allin_c_over_105" in reason:
            return "B skipped C>1.05 (E allowed)"
        return f"B skipped ({reason})"
    return "B did not hold"


def classify_row(row: dict, match: dict | None, dash_by_oid: dict | None = None) -> dict:
    step = str(row.get("step") or "")
    house = _dec(row.get("house_cash") or row.get("wire") or row.get("quote_price"))
    after = _dec(row.get("after_fee"))
    dog = str((match or {}).get("dog") or "")
    t0_when = str((match or {}).get("t0_when") or "")
    t0_src = str((match or {}).get("t0_src") or "")
    dog_ask = _dec((match or {}).get("dog_ask") or (match or {}).get("fav_ask"))
    dash_row = (dash_by_oid or {}).get(str(row.get("order_id") or ""), {})
    kitchen = str(dash_row.get("side") or "") or str(row.get("side_label") or "")
    dash_outcome = str(dash_row.get("outcome") or "")
    dash_pnl = str(dash_row.get("pnl") or "")
    labeled = dict(row)
    if not str(labeled.get("side_label") or "").strip() and kitchen:
        bits = kitchen.split(" ", 1)
        if len(bits) == 2 and bits[0] in {"Yes", "No"}:
            labeled["side_label"] = bits[1]
    yes_phrase = yes_player_phrase(labeled)
    book = str(row.get("side") or "").lower()
    filled = _dec(row.get("confirm_qty") or row.get("tape_qty") or row.get("size")) or Decimal("0")
    is_e_t0 = step == "e-t0"
    is_watch = step == "watch"
    who_yes = yes_phrase[4:] if yes_phrase.startswith("Yes ") else kitchen
    role = dog_or_fav(who_yes, dog, house)
    band_px = house if is_e_t0 else house
    legal_e = False
    illegal_why = ""
    if is_watch:
        illegal_why = "leftover-watch hedge on E bet_key; not an E T0 send"
    elif not is_e_t0:
        illegal_why = f"step {step or '(blank)'} is not e-t0"
    elif filled < 1 and str(row.get("confirm_qty") or "0") in {"0", "0.0", ""}:
        if house is not None and systems.in_dog_band(house):
            illegal_why = ""
        else:
            illegal_why = "e-t0 miss"
    elif house is None or not systems.in_dog_band(house):
        illegal_why = f"house cash {house} not in 11–49¢"
    elif role.startswith("favorite"):
        illegal_why = "Yes on favorite / ≥50¢"
    else:
        legal_e = True
    quoted = QUOTED_IDS.get(str(row.get("order_id") or ""))
    return {
        "quoted": quoted,
        "when": str(row.get("sent_at") or ""),
        "game": str(row.get("game") or (match or {}).get("game") or ""),
        "venue": str(row.get("venue") or ""),
        "step": step or "—",
        "book": book or "—",
        "kitchen": kitchen or f"{book.capitalize()} {row.get('side_label') or ''}".strip(),
        "yes_player": yes_phrase,
        "dog": dog or "—",
        "role": role,
        "house": house,
        "yes_wire": _dec(row.get("wire")),
        "fee": _dec(row.get("fee")),
        "after": after,
        "limit": _dec(row.get("limit_price")),
        "in_band": in_band_txt(band_px),
        "t0_when": t0_when,
        "t0_src": t0_src,
        "dog_ask": dog_ask,
        "legal": "legal E dog" if legal_e and filled >= 1 else (
            "legal E attempt (no fill)" if is_e_t0 and not illegal_why and filled < 1
            else ("illegal under freeze" if illegal_why else "—")
        ),
        "why": illegal_why or (
            "Yes dog in 11–49¢ at trusted T0; Poly BUY_SHORT is Yes that player"
            if is_e_t0 and book == "no"
            else "Yes dog in 11–49¢ at trusted T0"
            if is_e_t0
            else ""
        ),
        "pnl": dash_pnl,
        "outcome": dash_outcome,
        "order_id": str(row.get("order_id") or ""),
        "instrument": str(row.get("instrument") or ""),
        "filled": filled >= 1,
        "is_e_t0": is_e_t0,
        "is_watch": is_watch,
        "bet_key": str(row.get("bet_key") or ""),
    }


def load_orders() -> list[dict]:
    path = RAW / "orders.jsonl"
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or "tennis-t0-dog" not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("event") != "sent":
                continue
            if "tennis-t0-dog" not in str(row.get("bet_key") or ""):
                continue
            if on_day(parse_et(row.get("sent_at"))):
                out.append(row)
    out.sort(key=lambda r: str(r.get("sent_at") or ""))
    return out


def leftover_summary() -> dict[str, dict]:
    path = RAW / "leftover_watch_stats.jsonl"
    by_key: dict[str, dict] = defaultdict(lambda: {
        "ticks": 0,
        "buyable": 0,
        "filled": 0,
        "last": "",
        "last_event": "",
        "max_other": "",
        "origin": "",
        "filled_side": "",
        "opposite": "",
    })
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if "tennis-t0-dog" not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            key = str(row.get("bet_key") or "")
            if not key.startswith("tennis-t0-dog"):
                continue
            blob = by_key[key]
            blob["ticks"] += 1
            blob["last"] = str(row.get("seen_at") or blob["last"])
            blob["last_event"] = str(row.get("event") or blob["last_event"])
            blob["max_other"] = str(row.get("max_other_price") or blob["max_other"])
            blob["origin"] = str(row.get("origin_venue") or blob["origin"])
            blob["filled_side"] = str(row.get("filled_side") or blob["filled_side"])
            blob["opposite"] = str(row.get("opposite_side") or blob["opposite"])
            if row.get("event") == "buyable_send":
                blob["buyable"] += 1
            if row.get("event") == "ioc_filled":
                blob["filled"] += 1
    return by_key


def money(value) -> str:
    px = _dec(value)
    if px is None:
        return "—"
    return format(px, "f")


def main() -> int:
    now = datetime.now(ET)
    now_s = now.strftime("%Y-%m-%d %H:%M:%S ET")
    watch = load_json(RAW / "tennis_t0_dog_watch.json")
    b_watch = load_json(RAW / "strategy_b_watch.json")
    matches = {
        str(row.get("key") or ""): row
        for row in (watch.get("matches") or [])
        if isinstance(row, dict)
    }
    by_game = {
        " ".join(str(row.get("game") or "").lower().split()): row
        for row in matches.values()
    }
    orders = load_orders()
    leftover = leftover_summary()
    dash_by_oid = load_dash_by_oid()
    classified = []
    for row in orders:
        key = str(row.get("bet_key") or "")
        parts = key.split("\t")
        match_key = parts[1] if len(parts) > 1 else ""
        match = matches.get(match_key)
        if match is None:
            game = " ".join(str(row.get("game") or "").lower().split())
            match = by_game.get(game)
        classified.append(classify_row(row, match, dash_by_oid))

    table_rows = []
    for item in classified:
        quoted = f"#{item['quoted']}" if item["quoted"] else "extra"
        fill = "yes" if item["filled"] else "no"
        table_rows.append([
            esc(quoted),
            esc((parse_et(item["when"]) or DAY).strftime("%H:%M:%S")),
            esc(item["game"]),
            esc(item["venue"]),
            esc(item["step"]),
            esc(item["book"]),
            esc(item["kitchen"]),
            esc(item["yes_player"]),
            esc(item["dog"]),
            esc(item["role"]),
            esc(money(item["house"])),
            esc(money(item["limit"])),
            esc(money(item["fee"])),
            esc(money(item["after"])),
            esc(item["in_band"]),
            esc(item["t0_src"] or "—"),
            esc((parse_et(item["t0_when"]) or None).strftime("%H:%M:%S") if parse_et(item["t0_when"]) else "—"),
            esc(fill),
            esc(item["outcome"] or ("open" if item["filled"] and not item["outcome"] else "miss" if not item["filled"] else "—")),
            esc(item["pnl"] or "—"),
            esc(item["legal"]),
            esc(item["why"]),
            esc(item["order_id"]),
        ])

    freeze = table(
        [("Knob", "text"), ("Freeze", "text")],
        [
            ["Universe", "Tennis moneyline underdog only. Unique cheaper player. tennis_rows, not sports_queue."],
            ["Band", "DOG_LO=0.10 exclusive, DOG_HI=0.50 exclusive → 11¢ through 49¢. Not retuned."],
            ["T0", "15 seconds before trusted start through T0_GRACE=300 after."],
            ["Overlap", "Skip if B holds, except B skipped t0_allin_c_over_105."],
            ["Hold", "Hold to settle. No flatten, no 50-cross, no favorite dip, no both-Yes."],
            ["Size", "1 contract, stake $1, max_open 2 (open games, not two tickets on one game)."],
            ["Venue", "Cheapest Yes of Kalshi, Gemini, Polymarket, Novig; Kalshi wins ties."],
        ],
    )

    headers = [
        ("Quoted", "text"),
        ("When ET", "date"),
        ("Match", "text"),
        ("Venue", "text"),
        ("Step", "text"),
        ("Book side", "text"),
        ("Kitchen label", "text"),
        ("Yes-player (pays $1 if they win)", "text"),
        ("E dog at send", "text"),
        ("Dog or fav", "text"),
        ("House cash", "num"),
        ("Limit posted", "num"),
        ("Fee", "num"),
        ("After fee", "num"),
        ("In 11–49", "text"),
        ("T0 clock src", "text"),
        ("Trusted T0", "date"),
        ("Filled", "text"),
        ("Outcome", "text"),
        ("P&L", "text"),
        ("Under freeze", "text"),
        ("Why", "text"),
        ("Order id", "text"),
    ]
    sends_table = table(headers, table_rows)

    quoted_walk = []
    for item in classified:
        if not item["quoted"]:
            continue
        quoted_walk.append(item)
    quoted_walk.sort(key=lambda r: r["quoted"] or 99)

    game_bits = defaultdict(list)
    for item in classified:
        game_bits[item["game"]].append(item)

    leftover_rows = []
    for key, blob in sorted(leftover.items()):
        parts = key.split("\t")
        match = matches.get(parts[1] if len(parts) > 1 else "", {})
        leftover_rows.append([
            esc(match.get("game") or parts[1] if len(parts) > 1 else key),
            esc(blob["origin"] or "—"),
            esc(blob["filled_side"] or "—"),
            esc(blob["opposite"] or "—"),
            esc(blob["max_other"] or "—"),
            esc(str(blob["ticks"])),
            esc(str(blob["buyable"])),
            esc(str(blob["filled"])),
            esc(blob["last_event"] or "—"),
            esc(blob["last"] or "—"),
        ])
    leftover_table = table(
        [
            ("Match", "text"),
            ("Origin venue", "text"),
            ("E filled book", "text"),
            ("Watch hunts", "text"),
            ("Max other ¢", "num"),
            ("Watch ticks", "num"),
            ("Buyable sends", "num"),
            ("IOC filled", "num"),
            ("Last event", "text"),
            ("Last seen", "date"),
        ],
        leftover_rows,
    ) if leftover_rows else "<p class=\"note\">No leftover_watch_stats rows on tennis-t0-dog keys.</p>"

    open_e = [
        row for row in (watch.get("matches") or [])
        if isinstance(row, dict) and str(row.get("stage") or "") in {"filled", "waiting_t0"}
    ]
    open_txt = ", ".join(
        f"{row.get('game')} ({row.get('stage')} {row.get('dog')} @{row.get('dog_ask')})"
        for row in open_e
    ) or "(none)"

    illegal = [x for x in classified if x["legal"] == "illegal under freeze"]
    legal_fills = [x for x in classified if x["legal"] == "legal E dog"]
    legal_miss = [x for x in classified if x["legal"].startswith("legal E attempt")]

    facts = table(
        [("Check", "text"), ("Value", "text")],
        [
            ["E on / max_open / stake", f"on / {watch.get('max_open')} / ${watch.get('stake_usd')}"],
            ["E pid / last send", f"{watch.get('pid')} / {watch.get('last_send')}"],
            ["Today tennis-t0-dog sent rows", str(len(classified))],
            ["Quoted dashboard six", "all six are on the tape"],
            ["Legal E T0 dog fills", str(len(legal_fills))],
            ["Legal E T0 attempts with no fill", str(len(legal_miss))],
            ["Sends that should not have fired under the freeze", str(len(illegal))],
            ["Patched live E?", "No. Analysis only. Band and sender unchanged."],
            ["Second B started?", "No."],
            ["11–49 retuned?", "No."],
            ["Open E tickets now", open_txt],
        ],
    )

    walk_html = []
    walks = [
        (
            "Tabur vs Romano (quoted #6, 09:39)",
            "E bought the underdog. Kitchen says “No Filippo Romano 29¢.” "
            "The Polymarket ticket is BUY_SHORT named Romano: that seat pays $1 if Romano wins, "
            "so Yes-player is Yes Filippo Romano at 29¢ (after fee 30¢). Romano was the unique "
            "cheaper Yes (dog_ask 0.28, send 0.29). In band. One T0 send. Romano won; +$0.70. "
            "This does make sense as a dog. Leftover watch opened on the complementary Yes "
            "(Tabur) with max other 67¢; Tabur’s ask stayed ~72¢ so that hedge never filled.",
        ),
        (
            "Musetti vs Tiafoe (quoted #5 then #4)",
            "First ticket (09:41) is the real E send: Kalshi Yes Lorenzo Musetti 43¢, in band, "
            "Musetti was the dog. Makes sense. Musetti won; +$0.55. About an hour later (10:38) "
            "leftover watch bought Kalshi No Musetti at 51¢ house cash (out of band, favorite-side). "
            "That is Yes Tiafoe at 51¢, not a second T0 dog. E’s consider_game already marks the "
            "match filled, so E did not T0 twice. max_open 2 is two games, not two tickets on one "
            "game. Clock was listed/feed 09:40, send 09:41 — not a Parks-style early T0. The 51¢ "
            "No should not have fired under the E freeze.",
        ),
        (
            "Djokovic vs Humbert (quoted #3 then #1)",
            "10:39 E T0: Polymarket BUY_SHORT named Humbert, house 30¢. Kitchen “No Ugo Humbert.” "
            "Yes-player is Yes Ugo Humbert at 30¢. Humbert was the unique cheaper Yes (dog_ask 0.29). "
            "Legal dog. Humbert lost; −$0.31. 11:30 leftover watch bought Polymarket Yes Novak "
            "Djokovic at 55¢ (favorite, out of band). That is the complementary long on the same "
            "market, turning E’s directional dog into a Yes+Yes lock. Combined P&amp;L −$0.31 + $0.43 "
            "= +$0.12, which is lock vig, not a second underdog. The 55¢ favorite should not have "
            "fired under the E freeze. T0 clock listed/feed 10:40, first send 10:39:50 — in the 15s "
            "lead. Not skip-if-B (B did not hold this match).",
        ),
        (
            "Yaneva vs Selekhmeteva (quoted #2 + extra leftover)",
            "11:09 E T0: Polymarket BUY_SHORT named Selekhmeteva, house 40¢. Kitchen “No Oksana "
            "Selekhmeteva.” Yes-player is Yes Oksana Selekhmeteva at 40¢. She was the dog. Legal. "
            "She lost; −$0.42. 13:55 leftover watch bought Yes Elizara Yaneva at 54¢ (favorite). "
            "Same leftover bug as Djokovic. Combined −$0.42 + $0.44 = +$0.02. T0 listed/feed 11:05, "
            "send 11:09 — inside the 300-second grace, not a second T0 and not Parks-early.",
        ),
        (
            "Fritz vs Hijikata (extra)",
            "13:59 E T0: Polymarket BUY_SHORT named Hijikata, house 13¢. Yes Rinky Hijikata, the "
            "dog, in band. B had not absorbed this match (B later skipped “missed T0 window”). "
            "Legal E dog. Hijikata lost; −$0.14. Leftover tried Yes Fritz at 84¢ and missed (confirm 0).",
        ),
        (
            "Guillen Meza vs Hernandez (extra)",
            "14:39 E T0: Polymarket BUY_SHORT named Hernandez, house 38¢. Yes Alex Hernandez, dog, "
            "in band. B skipped this match for t0_allin_c_over_105, which is the freeze exception "
            "that lets E still send. Legal. Leftover later bought Yes Guillen Meza at 57¢ — illegal "
            "as E, leftover hedge.",
        ),
        (
            "Hurkacz vs Rune (extra)",
            "16:03 E T0: Polymarket BUY_SHORT named Rune, house 38¢. Kitchen “No Holger Rune.” "
            "Yes-player is Yes Holger Rune, the dog, in band. Legal. At 17:10 leftover watch bought "
            "Yes Hubert Hurkacz at 57¢ (favorite, out of band) — same illegal hedge as Djokovic.",
        ),
        (
            "Mikovic-Palomar vs Corwin-Overmyer (extra miss)",
            "17:00 E T0: Polymarket BUY_SHORT named Corwin-Overmyer, quoted 47¢ in band. HTTP 200 "
            "confirm 0 — no fill. Legal attempt. E cancelled. Not an illegal send.",
        ),
        (
            "Giovannini vs Leme Da Silva (extra)",
            "17:02 E T0: Polymarket BUY_LONG Yes Nauhany Leme Da Silva 34¢. Here the dog is the "
            "long-named player, so the tape side is yes (not BUY_SHORT). Legal dog. At 17:15 leftover "
            "watch bought complementary No Nauhany / Yes Giovannini at 59¢ house — a Yes+No lock "
            "on the dog, not a second underdog. Illegal under the E freeze.",
        ),
    ]
    for title, body in walks:
        walk_html.append(f"<h3>{esc(title)}</h3><p>{body}</p>")

    rec = table(
        [("Option", "text"), ("What it does", "text"), ("Recommend?", "text")],
        [
            [
                "Fix leftover: skip directional E/C/D in _register_send_fill_watch",
                "Stop opening a lock leftover watch after an E fill. The comment already says "
                "“Do not leftover-watch a directional dog.” The function never checks "
                "_DIRECTIONAL_SYSTEMS. That is why 55¢ Djokovic / 51¢ No Musetti / 54¢ Yaneva fired "
                "on tennis-t0-dog keys with step=watch.",
                "Yes. Unambiguous. Tests-gated. This is not an E band retune. Did not patch this job.",
            ],
            [
                "Fix kitchen labels: Poly BUY_SHORT tennis = Yes {that player}",
                "Dashboard “No Romano / No Humbert / No Selekhmeteva” are Yes-dog seats. Share the "
                "Yes-player rule (Poly BUY_SHORT pays when that player wins). Do not invert Kalshi "
                "overlay work a sibling may be doing; extend tennis_t0_dog kind into "
                "_poly_short_is_yes_opponent.",
                "Yes, display only. Did not patch; sibling may be renaming Kalshi overlay tickers.",
            ],
            [
                "Stamp leftover watch as system A, not E",
                "Kitchen type “only lock underdog T0” on a 55¢ favorite is wrong. step=watch should "
                "not inherit E’s letter just because it reused the bet_key.",
                "Yes, after leftover skip. Otherwise leftover should not exist on E keys.",
            ],
            [
                "Stop sending No-favorite / 55¢ inside live_tennis_t0_dog.py",
                "E’s plan_send / dog_line_snapshot already require unique dog Yes in (0.10, 0.50) "
                "and send_yes uses that Yes. The 55¢ did not go through that path.",
                "No. Would not have blocked today’s illegal rows. Do not retune 11–49.",
            ],
            [
                "Reload E now",
                "Reload does not drop leftover watches already open on E bet_keys. Open tickets "
                "(Rune, Leme Da Silva) can still be hedged until leftover skip is patched.",
                "No reload this job. Patch leftover first if Paul wants the live leak stopped.",
            ],
        ],
    )

    illegal_list = "".join(
        f"<li><strong>{esc((parse_et(x['when']) or DAY).strftime('%H:%M'))}</strong> "
        f"{esc(x['game'])} {esc(x['venue'])} kitchen {esc(x['kitchen'])} house "
        f"{esc(money(x['house']))} — {esc(x['why'])} (id {esc(x['order_id'])})</li>"
        for x in illegal
    ) or "<li>None.</li>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>System E tennis T0 dog fills audit 28 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
h3 {{ margin: 1rem 0 0.4rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>System E tennis T0 dog fills — 28 Oct 2026 audit</h1>
<p class="note">Written {esc(now_s)}. Research-candidate live. Not gold. Not DailyRun.
Did not sell, did not retune 11–49, did not start a second B, did not touch <code>hist/</code>,
did not revert Kalshi overlay ticker renaming, did not patch live E send.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{PLAIN}</p></div>

<h2>Verdict</h2>
{facts}
<p class="note">Of the six quoted kitchen rows: <strong>#5 Musetti Yes 43¢, #6 Romano 29¢, #3 Humbert 30¢, #2 Selekhmeteva 40¢ are legal E dogs</strong>
(the last three are Yes that player; kitchen “No” is a Polymarket BUY_SHORT label).
<strong>#1 Djokovic Yes 55¢ and #4 Musetti No 51¢ are illegal under the E freeze</strong> — leftover-lock hedges on E’s bet_key, not T0 dog sends.
E did not fire twice on those games. in_dog_band ran on the dog Yes, not the 55¢ favorite.</p>

<h2>Freeze (unchanged)</h2>
{freeze}

<h2>Every tennis-t0-dog send today</h2>
<p class="note">Click column headers to sort. House cash is what we paid. Limit posted on Polymarket BUY_SHORT is 1 − house (the long Yes). Swipe sideways to see more columns.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{sends_table}

<h2>Sends that should not have fired under the freeze</h2>
<ul>{illegal_list}</ul>
<p class="note">Root cause is not <code>in_dog_band</code> on the wrong E price. E’s
<code>live_tennis_t0_dog.plan_send</code> / <code>live_t0_yes.dog_line_snapshot</code> pick the unique cheaper Yes,
require <code>DOG_LO &lt; ask &lt; DOG_HI</code>, and send that Yes. After the fill,
<code>live_lock_orders._register_send_fill_watch</code> opens a leftover watch on the same
<code>tennis-t0-dog</code> bet_key and later IOCs the opposite book (favorite Yes, or Kalshi No).
Those posts use <code>step=watch</code> and inherit E on the kitchen because of the bet_key.
The module comment says “Do not leftover-watch a directional dog.” The skip list is only
strategy B, flatten, and lock hard/easy — not E.</p>

<h2>Walk each game</h2>
{''.join(walk_html)}

<h2>Why two tickets on one game?</h2>
<p>Not skip-if-B (B did not hold Djokovic/Musetti). Not max_open 2 (that cap is open games).
Not E T0 twice (<code>consider_game</code> returns already handled once stage is filled).
Not a Parks-style early occurrence clock (these T0 sources are listed/feed, sends sit in the
15s-before through 300s-after window). It is leftover watch hedging E.</p>
<p>Poly “No X” rows on E T0 are not betting the favorite to lose. They are BUY_SHORT seats that
pay when X wins, at X’s Yes price. Tabur 29¢ No Romano is Yes Romano at 29¢ and <strong>does</strong>
make sense as a dog. Musetti Yes 43¢ makes sense if Musetti was the dog — he was.</p>

<h2>Leftover watch on E keys today</h2>
{leftover_table}

<h2>Options and recommendation</h2>
{rec}
<p class="note"><strong>Recommendation:</strong> keep E’s 11–49 sender as-is. Patch leftover so
directional E/C/D fills do not open a watch (tests-gated). Separately, kitchen-label Polymarket
BUY_SHORT tennis as Yes {{that player}}. Do not treat 55¢ Djokovic as an E band bug.</p>

<p class="tiny">Sources: <code>orders.jsonl</code> tennis-t0-dog sent rows 2026-10-28 ET,
<code>tennis_t0_dog_watch.json</code>, <code>tennis_t0_dog.log</code>,
<code>leftover_watch_stats.jsonl</code>, <code>strategy_b_watch.json</code>,
<code>dashboard_cache.json</code> kitchen labels/P&amp;L,
<code>tools/live_tennis_t0_dog.py</code>, <code>tools/live_t0_yes.py</code>,
<code>tools/live_lock_orders.py</code> <code>_register_send_fill_watch</code>,
<code>tools/prediction_systems.py</code> <code>in_dog_band</code> / <code>pick_dog_primary</code>.
File URL {esc(FILE_URL)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    summary = {
        "n_sends": len(classified),
        "legal_fills": [x["order_id"] for x in legal_fills],
        "illegal": [(x["order_id"], x["game"], x["kitchen"], str(x["house"])) for x in illegal],
        "quoted_legal": [x["quoted"] for x in classified if x["quoted"] and x["legal"] == "legal E dog"],
        "quoted_illegal": [x["quoted"] for x in classified if x["quoted"] and x["legal"] == "illegal under freeze"],
        "patched": False,
    }
    print(json.dumps(summary, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
