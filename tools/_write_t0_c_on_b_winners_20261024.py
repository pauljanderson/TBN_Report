"""T0 both-Yes C on settled Strategy B winners. Research report only.

Does not start live_strategy_b.py. Does not edit live knobs. Does not sell.
Does not commit. Does not print secrets.
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)
from write_orders_performance import last_name, same_player  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "t0_c_on_b_winners_20261024.html"
WATCH = RAW / "strategy_b_watch.json"
EXTRACT = RAW / "b_vs_lock_pnl_extract_20261023.json"
PRICE_LAST = RAW / "price_last.json"
UNDER_ONE = STAMP / "strategy_b_t0_under_one_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/t0_c_on_b_winners_20261024.html"
)
C_HI_PAUL = Decimal("1.01")
ONE = Decimal("1")
FOUR = Decimal("0.0001")
POLY_THETA = Decimal("0.0695")

ASKED = (
    "He made up $1.01. Check it against winning tennis crossover bets. What was "
    "the total starting % for both (T0 both Yes asks summed = C) on those winners?"
)
PLAIN = (
    "Strategy B, at the first trusted tennis start (T0), buys one Yes on each player. "
    "A Yes pays $1 if that person wins, so the two tickets always pay $1 together. "
    "C is those two Yes prices added up. Paul made up a $1.01 cap: do not send if C "
    "is above $1.01. This page does not change that live knob. It only scores C on "
    "settled B matches, especially the ones that made money after fees. B can still "
    "win when the original underdog later prints above 50¢ and the extra pair locks, "
    "even if the first pair was a bit over $1. N is small. Every settled B row is "
    "on the table. Research only, not gold, not DailyRun. Do not wire a new cap from "
    "this table — Paul asked after Namigata (selection bias)."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def d(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def money(value: Decimal | None, places: int = 4) -> str:
    if value is None:
        return ""
    q = Decimal("1").scaleb(-places)
    return format(value.quantize(q, rounding=ROUND_HALF_UP), "f")


def signed(value: Decimal | None) -> str:
    if value is None:
        return ""
    txt = money(value, 4)
    if value > 0:
        return "+" + txt
    return txt


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


def tokens(text: str) -> set[str]:
    parts = re.findall(r"[a-z0-9]+", str(text or "").lower())
    skip = {"vs", "v", "at", "wins", "win", "the", "de", "del", "van", "of", "and"}
    return {p for p in parts if len(p) >= 4 and p not in skip}


def games_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if same_player(a, b) and last_name(a) and last_name(a) == last_name(b):
        return True
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    hit = ta & tb
    if len(hit) >= 2:
        return True
    if len(hit) == 1 and (hit <= ta and hit <= tb) and min(len(ta), len(tb)) <= 2:
        return True
    return False


def wire_leg(row: dict | None) -> Decimal | None:
    if not isinstance(row, dict):
        return None
    return d(row.get("yes_ask")) or d(row.get("price"))


def filled_leg(row: dict | None) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("filled") is True:
        return True
    if d(row.get("fill_px")) is not None:
        return True
    q = d(row.get("fill_qty") or row.get("qty"))
    return q is not None and q > 0


def kalshi_fee(price: Decimal | None) -> Decimal:
    if price is None:
        return Decimal("0")
    raw = Decimal("0.07") * price * (ONE - price)
    if raw < 0:
        raw = Decimal("0")
    return raw.quantize(FOUR, rounding=ROUND_HALF_UP)


def estimate_fee(venue: str, price: Decimal | None, stored: Decimal | None) -> Decimal:
    if stored is not None and stored > 0:
        return stored
    venue = str(venue or "").lower()
    if price is None:
        return stored if stored is not None else Decimal("0")
    if venue == "kalshi":
        return kalshi_fee(price)
    spec = {"venue": venue, "fee_coefficient": POLY_THETA}
    fee = live_lock_orders.leg_fee(spec, price)
    if fee is None:
        return stored if stored is not None else Decimal("0")
    return fee


def yes_cash(row: dict | None, venue: str) -> tuple[Decimal | None, Decimal | None]:
    if not isinstance(row, dict):
        return None, None
    w = wire_leg(row)
    fill = d(row.get("fill_px"))
    fee_stored = d(row.get("fill_fee"))
    intent = str(row.get("intent") or "")
    cash = fill
    inverted = "BUY_SHORT" in intent
    if fill is not None and w is not None and abs((fill + w) - ONE) <= Decimal("0.02"):
        inverted = True
    if inverted or (fill is not None and w is not None and abs(fill - w) > Decimal("0.05")):
        cash = w
    if cash is None:
        cash = w
    fee = estimate_fee(venue, cash, fee_stored)
    return cash, fee


def parse_dt_et(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        if text.endswith("Z"):
            text = text.replace("Z", "+00:00")
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ET)
        return stamp.astimezone(ET).strftime("%Y-%m-%d %H:%M ET")
    except ValueError:
        return text[:19]


def load_extract_b() -> list[dict]:
    if not EXTRACT.is_file():
        return []
    data = json.loads(EXTRACT.read_text(encoding="utf-8"))
    rows = []
    for item in data.get("groups") or []:
        if item.get("system") != "B":
            continue
        rows.append(item)
    return rows


def token_score(a: str, b: str) -> int:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0
    return len(ta & tb)


def pair_extract(watch_games: list[str], rows: list[dict]) -> dict[str, dict]:
    """Each extract group attaches to at most one watch game (best token overlap)."""
    used: set[int] = set()
    out: dict[str, dict] = {}
    scored = []
    for gi, game in enumerate(watch_games):
        for ei, row in enumerate(rows):
            s = token_score(game, str(row.get("game") or ""))
            if s < 2:
                continue
            scored.append((-s, -len(tokens(str(row.get("game") or ""))), gi, ei))
    scored.sort()
    taken_games: set[int] = set()
    for _neg, _nlen, gi, ei in scored:
        if gi in taken_games or ei in used:
            continue
        taken_games.add(gi)
        used.add(ei)
        out[watch_games[gi]] = rows[ei]
    return out


def load_price_last() -> dict:
    if not PRICE_LAST.is_file():
        return {}
    try:
        raw = json.loads(PRICE_LAST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def last_yes(price_last: dict, game: str, player: str) -> Decimal | None:
    best = None
    best_at = ""
    want = last_name(player)
    gtok = tokens(game)
    for rec in price_last.values():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("pay") or rec.get("side_kind") or "").lower() not in {"yes", ""}:
            if str(rec.get("pay") or "").lower() == "no":
                continue
        if str(rec.get("pay") or "").lower() != "yes":
            continue
        rg = str(rec.get("game") or "")
        if gtok and len(gtok & tokens(rg)) < 1 and not games_match(game, rg):
            continue
        if not games_match(game, rg) and last_name(rg) != last_name(game):
            if not (gtok and len(gtok & tokens(rg)) >= 2):
                continue
        side = str(rec.get("side") or "")
        if want and not same_player(player, side) and last_name(side) != want:
            continue
        px = d(rec.get("price"))
        seen = str(rec.get("seen_at") or "")
        if px is None:
            continue
        if best is None or seen > best_at:
            best, best_at = px, seen
    return best


def outcome_from_prices(
    fav: str, dog: str, fav_px: Decimal | None, dog_px: Decimal | None
) -> str:
    if fav_px is None and dog_px is None:
        return ""
    if fav_px is not None and dog_px is not None:
        if Decimal("0.45") <= fav_px <= Decimal("0.55") and Decimal("0.45") <= dog_px <= Decimal("0.55"):
            return "void"
        if fav_px >= Decimal("0.90") and dog_px <= Decimal("0.15"):
            return "T0 favorite won"
        if dog_px >= Decimal("0.90") and fav_px <= Decimal("0.15"):
            return "T0 dog won"
    if fav_px is not None and fav_px >= Decimal("0.95"):
        return "T0 favorite won"
    if dog_px is not None and dog_px >= Decimal("0.95"):
        return "T0 dog won"
    return ""


def parse_under_one_live() -> dict:
    out = {"n": None, "min": None, "max": None, "valid": False, "note": ""}
    if not UNDER_ONE.is_file():
        out["note"] = "strategy_b_t0_under_one_20261024.html missing"
        return out
    text = UNDER_ONE.read_text(encoding="utf-8")
    m = re.search(
        r"Live B sent T0, Yes asks \(wire\)</td><td>(\d+)</td><td>\d+</td><td>\d+</td><td>\d+</td><td>([0-9.]+)</td><td>([0-9.]+)</td>",
        text,
    )
    if not m:
        out["note"] = "could not parse the 29-row min/max from the under-one page"
        return out
    out["n"] = int(m.group(1))
    out["min"] = d(m.group(2))
    out["max"] = d(m.group(3))
    out["valid"] = True
    written = re.search(r"Written ([^.<]+)", text)
    out["note"] = f"Page written {written.group(1).strip() if written else 'unknown'}."
    return out


def t0_favorite(a: dict, b: dict, match: dict) -> tuple[str, Decimal | None, str, Decimal | None]:
    wa, wb = wire_leg(a), wire_leg(b)
    pa = str(a.get("player") or match.get("fav_player") or "A")
    pb = str(b.get("player") or match.get("dog_player") or "B")
    if wa is None or wb is None:
        return pa, wa, pb, wb
    if wa >= wb:
        return pa, wa, pb, wb
    return pb, wb, pa, wa


def classify_bucket(pnl: Decimal | None, outcome: str, settled: bool) -> str:
    if outcome == "void" or (pnl is not None and outcome == "void"):
        if outcome == "void":
            return "void"
    if not settled:
        return "not settled"
    if outcome == "void":
        return "void"
    if pnl is None:
        return "settled unknown P&L"
    if pnl > 0:
        return "B net winner"
    if pnl < 0:
        return "B net loser"
    return "flat"


def build_rows() -> tuple[list[dict], dict]:
    watch = json.loads(WATCH.read_text(encoding="utf-8")) if WATCH.is_file() else {}
    extract_rows = load_extract_b()
    price_last = load_price_last()
    matches = [m for m in (watch.get("matches") or []) if isinstance(m, dict)]
    filled_games = []
    for item in matches:
        t0 = item.get("t0_yes") if isinstance(item.get("t0_yes"), dict) else {}
        a = t0.get("a") if isinstance(t0.get("a"), dict) else {}
        b = t0.get("b") if isinstance(t0.get("b"), dict) else {}
        if filled_leg(a) or filled_leg(b):
            filled_games.append(str(item.get("game") or ""))
    extract_map = pair_extract(filled_games, extract_rows)
    rows = []
    for item in matches:
        t0 = item.get("t0_yes") if isinstance(item.get("t0_yes"), dict) else {}
        a = t0.get("a") if isinstance(t0.get("a"), dict) else {}
        b = t0.get("b") if isinstance(t0.get("b"), dict) else {}
        if not filled_leg(a) and not filled_leg(b):
            continue
        venue = str(item.get("venue") or a.get("venue") or b.get("venue") or "")
        wa, fa = yes_cash(a, venue)
        wb, fb = yes_cash(b, venue)
        w_ask_a, w_ask_b = wire_leg(a), wire_leg(b)
        wire = None
        if w_ask_a is not None and w_ask_b is not None:
            wire = w_ask_a + w_ask_b
        all_in = None
        if wa is not None and wb is not None:
            all_in = wa + wb + (fa or Decimal("0")) + (fb or Decimal("0"))
        both = filled_leg(a) and filled_leg(b)
        fav_name, fav_yes, dog_name, dog_yes = t0_favorite(a, b, item)
        ext = extract_map.get(str(item.get("game") or ""))
        stage = str(item.get("stage") or "")
        note = str(item.get("note") or "")
        complete = "B complete" in note
        cross = d(item.get("cross_fill"))
        ext_n = int((ext or {}).get("n_tickets") or 0)
        ext_pay = d((ext or {}).get("payout")) if ext else None
        if ext_pay == Decimal("2") and ext_n >= 4:
            complete = True
        elif ext_pay == Decimal("2") and ext_n == 3 and cross is None:
            # Taverna-style: T0 both + extra dog, watch may still say postponed.
            cross = Decimal("0")
        postponed = stage == "postponed"
        open_stage = stage in {
            "waiting_t0",
            "t0_filled_waiting_50_cross",
            "waiting_cross",
            "waiting_fav_dip",
            "one_leg_miss",
        }
        extract_closed = bool(ext and str(ext.get("status") or "").startswith("closed"))
        extract_unknown = bool(ext and "unknown" in str(ext.get("status") or "").lower())
        voidish = "void" in note.lower() or "settlementPx 0.50" in note
        game = str(item.get("game") or "")
        if "guajardo" in game.lower() or "brain" in game.lower():
            voidish = True
        if "danilova" in game.lower():
            voidish = True
        settled = False
        settle_why = ""
        if extract_closed:
            settled = True
            settle_why = "venue-fill extract closed"
            if postponed:
                settle_why += " (watch still postponed)"
        elif stage in {"done", "absorbed"}:
            settled = True
            settle_why = f"watch stage {stage}"
        elif stage == "abandoned" and both:
            settled = True
            settle_why = "watch abandoned after T0 fills"
        elif voidish and both:
            settled = True
            settle_why = "void / 50¢ settlement"
        elif open_stage:
            settled = False
            settle_why = f"still open ({stage})"
        elif postponed:
            settled = False
            settle_why = "watch postponed; holdings stay"
        else:
            settle_why = f"stage {stage}"

        pnl = None
        pnl_src = ""
        if ext and ext.get("realized") not in (None, ""):
            pnl = d(ext.get("realized"))
            pnl_src = "b_vs_lock extract (venue fills + fees)"
        if voidish and "guajardo" in game.lower():
            pnl = Decimal("0.0245")
            pnl_src = "Guajardo autopsy: 50¢ settlement, net +$0.0245 with fees"
        if pnl is None and complete and both and all_in is not None and cross is not None:
            fav_pay = d((item.get("last_order") or {}).get("pay"))
            cross_fee = estimate_fee(venue, cross, d(item.get("cross_fee")))
            fav_fee = estimate_fee(venue, fav_pay, None) if fav_pay else Decimal("0")
            extra = (cross or Decimal("0")) + (fav_pay or Decimal("0")) + cross_fee + fav_fee
            pnl = Decimal("2") - all_in - extra
            pnl_src = "computed: $2 payout − T0 all-in − extra pair (Kalshi fee estimated when watch stored 0)"

        fav_px = last_yes(price_last, game, fav_name)
        dog_px = last_yes(price_last, game, dog_name)
        outcome = outcome_from_prices(fav_name, dog_name, fav_px, dog_px)
        if voidish:
            outcome = "void"
        if not outcome and extract_closed and d(ext.get("payout") or 0) == ONE and not complete and cross is None:
            # T0-only $1 payout does not name the tennis winner.
            outcome = ""
        if "fernandez" in game.lower():
            outcome = "T0 dog won"
        if "moutet" in game.lower() or ("paul" in game.lower() and "moutet" in str(item.get("fav_player") or item.get("dog_player") or game).lower()):
            if "moutet" in game.lower():
                outcome = "T0 favorite won"
        if "trungelliti" in game.lower() or "dodig" in game.lower():
            outcome = "T0 dog won"
        if "yastremska" in game.lower():
            outcome = "T0 favorite won"
        if extract_closed and ext and d(ext.get("payout")) == Decimal("2") and cross is not None and not complete:
            if "taverna" in game.lower() and "bueno" in game.lower():
                outcome = "T0 dog won"

        skip = None
        if wire is not None:
            skip = wire > C_HI_PAUL
        bucket = classify_bucket(pnl, outcome, settled)
        if outcome == "void":
            bucket = "void"
        elif not settled:
            bucket = "not settled"
        elif pnl is None:
            bucket = "settled unknown P&L"
        elif pnl > 0:
            bucket = "B net winner"
        elif pnl < 0:
            bucket = "B net loser"
        else:
            bucket = "flat"

        famous = ""
        low = game.lower()
        if "fernandez" in low:
            famous = "Fernandez / Alexandrova (textbook complete B)"
        elif "moutet" in low:
            famous = "Moutet / Paul (T0 loser; no 50-cross)"
        elif "trungelliti" in low or "dodig" in low:
            famous = "Trungelliti / Dodig (duplicate extra Dodig bug)"
        elif "guajardo" in low or "brain" in low:
            famous = "Guajardo / Brain (void 50¢)"
        elif "namigata" in low:
            famous = "Namigata (still open leftover; ask was after this)"

        rows.append(
            {
                "game": game,
                "stage": stage,
                "venue": venue,
                "t0_et": parse_dt_et(item.get("t0_when") or item.get("opened_at")),
                "opened": parse_dt_et(item.get("opened_at")),
                "fav": fav_name,
                "dog": dog_name,
                "fav_yes": fav_yes,
                "dog_yes": dog_yes,
                "wire": wire,
                "all_in": all_in,
                "both": both,
                "complete": complete,
                "cross": cross,
                "outcome": outcome or "unknown",
                "pnl": pnl,
                "pnl_src": pnl_src,
                "bucket": bucket,
                "settled": settled,
                "settle_why": settle_why,
                "skip_101": skip,
                "famous": famous,
                "note": note,
                "extract_status": str((ext or {}).get("status") or ""),
                "extract_payout": d((ext or {}).get("payout")) if ext else None,
                "watch_c": d(item.get("c")),
            }
        )
    rows.sort(key=lambda r: (r["t0_et"], r["game"]))
    meta = {
        "n_watch": len(matches),
        "updated": str(watch.get("updated_at") or ""),
        "currently_open": watch.get("currently_open"),
    }
    return rows, meta


def live_t0_stats(rows: list[dict]) -> dict:
    sent = [r for r in rows if r.get("wire") is not None]
    wires = [r["wire"] for r in sent]
    return {
        "n": len(wires),
        "min": min(wires) if wires else None,
        "max": max(wires) if wires else None,
        "both": sum(1 for r in rows if r.get("both")),
    }


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    rows, meta = build_rows()
    under = parse_under_one_live()
    live = live_t0_stats(rows)
    settled = [r for r in rows if r["settled"]]
    winners = [r for r in settled if r["bucket"] == "B net winner"]
    losers = [r for r in settled if r["bucket"] == "B net loser"]
    voids = [r for r in settled if r["bucket"] == "void"]
    unk = [r for r in settled if r["bucket"] == "settled unknown P&L"]
    openish = [r for r in rows if not r["settled"]]

    def counts(group: list[dict]) -> dict:
        wires = [r["wire"] for r in group if r.get("wire") is not None]
        return {
            "n": len(group),
            "le": sum(1 for c in wires if c <= C_HI_PAUL),
            "gt101": sum(1 for c in wires if c > C_HI_PAUL),
            "gt105": sum(1 for c in wires if c > Decimal("1.05")),
            "gt110": sum(1 for c in wires if c > Decimal("1.10")),
            "skip": sum(1 for r in group if r.get("skip_101")),
        }

    cw = counts(winners)
    headline_bits = []
    for r in winners:
        name = r["game"]
        if "fernandez" in name.lower():
            label = "Fernandez"
        elif "taverna" in name.lower() and "bueno" in name.lower():
            label = "Taverna/Bueno"
        elif "nakao" in name.lower():
            label = "Nakao"
        elif "broady" in name.lower():
            label = "Broady"
        elif "atmane" in name.lower() or "bellucci" in name.lower():
            label = "Atmane/Bellucci"
        elif "yastremska" in name.lower():
            label = "Yastremska"
        else:
            label = name.split(" vs")[0].split(" @")[0]
        headline_bits.append(f"{label} {money(r['wire'], 2)}x")
    skipped_winners = [r for r in winners if r.get("skip_101")]
    kept_winners = [r for r in winners if r.get("skip_101") is False]
    expensive_losers = [r for r in losers if r.get("skip_101")]

    def row_cells(r: dict) -> list[str]:
        skip_txt = ""
        if r.get("skip_101") is True:
            skip_txt = "yes — would skip"
        elif r.get("skip_101") is False:
            skip_txt = "no — would send"
        pair = "T0 both-Yes" if r["both"] else "first pair / one-leg"
        play = "complete B" if r["complete"] else ("T0 + 50-cross" if r["cross"] is not None else "T0 only")
        return [
            esc(r["game"]),
            esc(r["t0_et"]),
            esc(r["venue"]),
            esc(r["fav"]),
            esc(money(r["fav_yes"], 2)),
            esc(r["dog"]),
            esc(money(r["dog_yes"], 2)),
            esc(money(r["wire"], 4)),
            esc(money(r["all_in"], 4)),
            esc(r["outcome"]),
            esc(signed(r["pnl"])),
            esc(r["bucket"]),
            esc(skip_txt),
            esc(pair),
            esc(play),
            esc(r["famous"] or r["settle_why"]),
        ]

    headers = [
        ("Game", "text"),
        ("T0 ET", "date"),
        ("Venue", "text"),
        ("T0 favorite", "text"),
        ("Favorite Yes", "num"),
        ("T0 dog", "text"),
        ("Dog Yes", "num"),
        ("Wire C", "num"),
        ("All-in C", "num"),
        ("Outcome", "text"),
        ("B P&L with fees $", "num"),
        ("Split", "text"),
        ("C_HI=1.01 skip?", "text"),
        ("T0 pair", "text"),
        ("B path", "text"),
        ("Note", "text"),
    ]

    winner_txt = ", ".join(headline_bits) if headline_bits else "none with known +P&L"
    skip_names = ", ".join(
        f"{r['game']} C={money(r['wire'], 2)}" for r in skipped_winners
    ) or "none"
    under_line = (
        f"The under-one page still reports N={under['n']}, min wire C={money(under['min'], 2)}, "
        f"max={money(under['max'], 2)}. {under['note']}"
        if under.get("valid")
        else under.get("note") or ""
    )
    now_line = (
        f"Watch now (this pull): {live['n']} matches with a T0 fill and a wire C, "
        f"{live['both']} with both Yes filled. Min wire C={money(live['min'], 2)}, "
        f"max={money(live['max'], 2)}."
    )
    still_valid = (
        under.get("valid")
        and under.get("min") == live.get("min")
        and under.get("n") is not None
        and live["n"] >= under["n"]
    )
    valid_txt = (
        f"Min 1.01 / max 1.08 from that 29-row table is still the right band for the "
        f"original 29. Watch has grown to {live['n']} filled T0s; max is now {money(live['max'], 2)}."
        if under.get("valid")
        else under_line
    )

    win_pnl = sum((r["pnl"] or Decimal("0")) for r in winners)
    lose_pnl = sum((r["pnl"] or Decimal("0")) for r in losers)
    void_pnl = sum((r["pnl"] or Decimal("0")) for r in voids)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>T0 C on B winners — 2026-10-24</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.warn {{ background: #fef2f2; padding: 10px 12px; border: 1px solid #f87171; margin: 12px 0; }}
.ok {{ background: #f0fdf4; padding: 10px 12px; border: 1px solid #86efac; margin: 12px 0; }}
.hold {{ background: #fff7ed; padding: 10px 12px; border: 1px solid #fdba74; margin: 12px 0; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>T0 both-Yes C on settled Strategy B winners</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. Did not change live knobs. Did not start a second live_strategy_b.py. Did not sell. Click column headers to sort.</p>

<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hold">
<p><strong>HOLD on wiring C_HI from this table.</strong> Paul made up 1.01 after Namigata (T0 wire C=1.10, still open leftover). N is tiny. Picking 1.01 after seeing Namigata is selection bias. This job did not edit <code>live_strategy_b.py</code>.</p>
</div>

<div class="ok">
<h2>Headline — B net winners, T0 wire C</h2>
<p>{esc(winner_txt)}.</p>
<p>Winners with wire C ≤ 1.01: <strong>{cw['le']}</strong> of {cw['n']}. C &gt; 1.01: <strong>{cw['gt101']}</strong>. C &gt; 1.05: <strong>{cw['gt105']}</strong>. C &gt; 1.10: <strong>{cw['gt110']}</strong>.</p>
<p>Would C_HI=1.01 have skipped those winners? <strong>{esc(skip_names)}</strong>. Send rule is C ≤ 1.01, so C=1.01 still sends (Fernandez, Moutet, Yastremska, Nakao, Atmane).</p>
</div>

<h2>How to read C</h2>
<p>Wire C = T0 Yes ask on the favorite + T0 Yes ask on the dog. That is the number live B gates on, not the later watch <code>c</code> field (quotes overwrite after the match). All-in C adds documented taker fees. Kalshi watch often stored fill_fee 0; all-in then uses 0.07 × p × (1−p) to $0.0001, the same formula that matched Fernandez GET fees. Polymarket uses stored fill_fee (theta 0.0695). Favorite Yes is the higher T0 Yes, not the watch label (Broady was the 68¢ Yes even when the watch named Santillan favorite).</p>
<p>P&amp;L is the whole B book with fees, not “did the T0 favorite win.” Complete B (T0 both + 50-cross + favorite dip) pays about $2 either way. T0 only always pays $1, so C above $1 is a small locked loss. Extra dog without the dip is winner-dependent. Void/push settles near 50¢ (Guajardo).</p>

<h2>Split</h2>
{SWIPE_NOTE_HTML}
{table(
    [("Split", "text"), ("N", "num"), ("Total B P&L $", "num"), ("C ≤ 1.01", "num"), ("C > 1.01", "num"), ("C > 1.05", "num"), ("C > 1.10", "num"), ("1.01 would skip", "num")],
    [
        ["B net winner", str(cw["n"]), esc(signed(win_pnl)), str(cw["le"]), str(cw["gt101"]), str(cw["gt105"]), str(cw["gt110"]), str(cw["skip"])],
        ["B net loser", str(len(losers)), esc(signed(lose_pnl)), str(counts(losers)["le"]), str(counts(losers)["gt101"]), str(counts(losers)["gt105"]), str(counts(losers)["gt110"]), str(counts(losers)["skip"])],
        ["Void / 50¢", str(len(voids)), esc(signed(void_pnl)), str(counts(voids)["le"]), str(counts(voids)["gt101"]), str(counts(voids)["gt105"]), str(counts(voids)["gt110"]), str(counts(voids)["skip"])],
        ["Settled, P&L unknown", str(len(unk)), "", str(counts(unk)["le"]), str(counts(unk)["gt101"]), str(counts(unk)["gt105"]), str(counts(unk)["gt110"]), str(counts(unk)["skip"])],
    ],
    ["All settled B with a T0 pair", str(len(settled)), esc(signed(win_pnl + lose_pnl + void_pnl)), str(counts(settled)["le"]), str(counts(settled)["gt101"]), str(counts(settled)["gt105"]), str(counts(settled)["gt110"]), str(counts(settled)["skip"])],
)}
<p class="note">Taverna/Bueno: watch still says postponed; Kalshi fill extract closed it +$0.3809 with a $2 payout (T0 both + extra Taverna 56¢, dog won). Counted as settled because the venue book paid. Wolff/Webb: extract closed −$0.03 / $1 payout; watch still postponed — also counted. If those rain delays were not actually paid, drop them; the winner list without Taverna is still Fernandez, Nakao, Atmane/Bellucci, Broady, Yastremska.</p>

<h2>B net winners</h2>
<p class="note">Every settled B row with +P&amp;L after fees. Click headers to sort.</p>
{SWIPE_NOTE_HTML}
{table(headers, [row_cells(r) for r in winners], None)}
<p>Skipped by 1.01: {esc(skip_names)}. Kept (C ≤ 1.01): {esc(", ".join(f"{r['game']} {money(r['wire'], 2)}x" for r in kept_winners) or "none")}.</p>

<h2>B net losers</h2>
<p class="note">Includes Moutet T0 (−3.52¢, C=1.01, T0 favorite Paul won, no 50-cross) and Trungelliti (−$0.69, C=1.02, extra duplicate Dodig). Sohns−Walker complete B at C=1.08 is a <strong>loser</strong> (−$0.20): the extra pair paid $2 but T0 vig ate it. 1.01 would have skipped that loser, not a winner.</p>
{SWIPE_NOTE_HTML}
{table(headers, [row_cells(r) for r in losers], None)}

<h2>Void</h2>
<p class="note">Guajardo/Brain expired at 50¢. Not a tennis winner/loser. Danilova tape was marked void / not a venue holding on the orders ledger.</p>
{SWIPE_NOTE_HTML}
{table(headers, [row_cells(r) for r in voids] if voids else [["—", "", "", "", "", "", "", "", "", "none", "", "", "", "", "", ""]], None)}

<h2>Every settled B row</h2>
<p class="note">N={len(settled)}. Do not sample. Wire C from frozen T0 Yes asks. P&amp;L from the 23 Oct venue-fill extract when it closed the match; Yastremska and Guajardo are after that extract. Click headers to sort. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{table(headers, [row_cells(r) for r in settled], None)}

<h2>Famous ones</h2>
<ul>
<li><strong>Fernandez / Alexandrova:</strong> wire C=1.01 (0.75 + 0.26). Complete B. Fernandez (T0 dog) won. +$0.1937 with Kalshi fees. 1.01 would <em>not</em> skip.</li>
<li><strong>Moutet / Paul:</strong> wire C=1.01 (0.77 + 0.24). T0 only, no 50-cross. Paul (T0 favorite) won. B T0 −$0.0352. Lock leftover later is not B. 1.01 would <em>not</em> skip this loser.</li>
<li><strong>Trungelliti / Dodig:</strong> wire C=1.02 (0.61 + 0.41). Extra duplicate Dodig. Trungelliti (T0 dog) won. −$0.69. 1.01 <em>would</em> skip this loser.</li>
<li><strong>Guajardo / Brain:</strong> wire C=1.01. Void 50¢. About +$0.02 with fees. Not a winner/loser tennis payout.</li>
<li><strong>Yastremska / You:</strong> watch done, complete B, wire C=1.01. Yastremska (T0 favorite) last print $1. P&amp;L computed $2 − T0 all-in − extra pair with estimated Kalshi fees (watch stored fill_fee 0). 1.01 would <em>not</em> skip.</li>
<li><strong>Namigata:</strong> not settled. T0 wire C=1.10, one-leg leftover still open. This ask came after Namigata. Do not retune 1.01 from the winner table.</li>
</ul>

<h2>29 live T0 ask C (under-one page)</h2>
<p>{esc(under_line)} {esc(now_line)} {esc(valid_txt)}</p>
<p class="note">That page’s live-B wire buckets were 25 in (1.00, 1.01], 3 in (1.01, 1.05], 1 in (1.05, 1.20] (Sohns 1.08). None under $1.00. This score uses the same T0 Yes-ask C, not overwritten watch <code>c</code>.</p>

<h2>Not settled (shown so the book is complete)</h2>
<p class="note">Postponed holdings, still-open (Karim waiting_cross, Namigata one_leg_miss), abandoned with no T0 send. Not in the winner counts.</p>
{SWIPE_NOTE_HTML}
{table(headers, [row_cells(r) for r in openish], None)}

<h2>Freeze / what this is not</h2>
<ul>
<li>Research candidate only. Not gold. Not DailyRun.</li>
<li>Did not change C_HI, D, or stacking in this job. Did not fight another agent setting C_HI=1.01.</li>
<li>Did not start a second <code>live_strategy_b.py</code>. Did not sell. Did not wire GTC.</li>
<li>IS/OOS does not apply — these are live 21–24 Oct 2026 tickets, all after 2024-01-01.</li>
</ul>

<p class="note">Sources: <code>strategy_b_watch.json</code> T0 Yes ask/price; <code>b_vs_lock_pnl_extract_20261023.json</code> closed B groups (venue fills + fees); famous autopsies Fernandez, Moutet, Trungelliti, Guajardo; <code>price_last.json</code> for who printed $1; <code>strategy_b_t0_under_one_20261024.html</code> for the 29-row min/max. Watch updated {esc(meta.get('updated'))}. File URL {esc(FILE_URL)}. No secrets.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}")
    print("winners", winner_txt)
    print("skip", skip_names)
    print("settled", len(settled), "winners", len(winners), "losers", len(losers), "void", len(voids), "unk", len(unk))
    for r in settled:
        print(
            "ROW",
            r["bucket"],
            r["game"][:40],
            "C",
            r["wire"],
            "pnl",
            r["pnl"],
            r["outcome"],
            r["settle_why"][:40],
        )
    print("live_t0", live)
    print("under_one", under)
    print("FILE", FILE_URL)


if __name__ == "__main__":
    main()
