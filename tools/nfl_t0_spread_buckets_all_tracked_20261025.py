"""All tracked NFL T0 spread buckets — tape + catalog, not fills.

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not start a second live_strategy_b.py. Does not sell. Does not change live D.
Does not write sports_queue. Does not read orders.jsonl / FILLED / system=spread_t0.
Not gold. Not DailyRun.

Universe: every pro football / NFL (National Football League) series in local
price_memory + catalog that has a Type A spread book (wins-by-n / cover),
whether or not we sent D. T0 = first trusted kickoff. Two grains: (1) one line
per game closest to 50¢ among two-sided unique favorites (live D analog),
(2) all wins-by-n lines with a T0 Yes. Hero table is win% by T0 bucket, not
the old four-row with-fee P&L. Open games stay out of win%.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
from odds_cross_winrate_20261020 import build_index, game_norm
from prediction_paths import RAW_DIR as RAW
import t0_all_games_stats as t0
from nfl_t0_type_a_collect import (
    BAND_50_59_ID,
    BAND_51_69_ID,
    BAND_60_69_ID,
    BAND_OLD_COMBINED_ID,
    BAND_UF_ID,
    DECILE_10_29_ID,
    DECILE_20_39_ID,
    GAME_OVER,
    WINPCT_HEADERS,
    WINPCT_ORDER,
    band_edge_counts,
    band_primary_row,
    bucket_winpct,
    build_every_decile_payload,
    build_nfl_cover_index,
    cover_yes_known,
    decile_hero_rows,
    decile_verdict,
    in_old_50_69_neighborhood,
    is_sunday_book,
    load_nfl_settlements,
    occ_map_prefer_listed,
    overlay_cover_settlement,
    pick_fee_primary_line,
    score_t0_yes,
    score_t0_yes_band,
    unique_fav_one_per_game_band,
    winpct_row,
    in_51_69,
    in_old_50_59,
    in_old_60_69,
)
from t0_fav_lt90_baseline_20261024 import (
    fmt_ann,
    fmt_num,
    fmt_pct,
    html_table,
    quality,
)
from write_t0_band_from_stay_above import documented_leg_fee
from nfl_t0_spread_buckets_20261025 import (
    ALL_ID,
    BUCKETS,
    COMPARE_HEADERS,
    D_BAND_ID,
    PRIMARY_HEADERS,
    YES_LO,
    _in_bucket,
    book_trade,
    bucket_of,
    compare_row,
    format_money,
    in_d_band,
    is_nfl,
    is_spread,
    is_unique_fav,
    pick_one_per_game,
    pick_primary_line,
    primary_row,
    sample_note,
    stream_nfl_spread_sides,
    trades_for,
    trusted_two_sided,
    void_count,
)

ET = ZoneInfo("America/New_York")
PARENT = (
    ROOT / "drive" / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
)
PAGE = PARENT / "nfl_t0_spread_buckets_all_tracked_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/"
    "nfl_t0_spread_buckets_all_tracked_20261025.html"
)
OLD_PAGE = "nfl_t0_spread_buckets_20261025.html"
ALL_LINES_ID = "all two-sided lines"
TINY_N = 8
SMALL_N = 20
QUEUE_PATH = RAW / "sports_queue.json"
RESULTS_PATH = RAW / "pro_football_results.jsonl"

TODAY_ET = "2026-10-25"
WINDOW_LABELS = {
    "13:00": "1pm ET first window",
    "16:05": "4:05pm ET",
    "16:25": "4:25pm ET",
    "20:20": "8:20pm ET",
}
WINDOW_ORDER = [
    "1pm ET first window",
    "4:05pm ET",
    "4:25pm ET",
    "8:20pm ET",
]

ASKED_BUY_NO = (
    "what if we flip it and what if we bet against each of these? for example "
    "what if we buy a No contract for every decile for NFL games. It would seem "
    "to me that we might make money on betting no on anything that starts out "
    "in the 10-29 decile buckets, since they only win 4.5 and 9.2 percent of "
    "the time. can you run these numbers and report back?"
)
PLAIN_BUY_NO = (
    "We buy the other side of the same National Football League (NFL) Type A "
    "cover at first trusted kickoff (T0): team A wins by N or team B wins by N. "
    "If a Yes that opened at 10–19 or 20–29 cents rarely hits, the No ticket "
    "wins the rest — but that No usually costs most of a dollar (about 71–90 "
    "cents), plus the documented taker fee. A 90-cent No that wins 95% of the "
    "time can still lose money after fees; the table shows win percent and "
    "dollars so that cannot hide. Same settled rows as the Yes table, 1 "
    "contract. Kalshi house No cash = 1 − Yes-wire (buy side = ask). "
    "Polymarket BUY_SHORT No cash = 1 − Yes-price. Gemini / Novig on this tape "
    "use the same 1 − T0 Yes; Novig stays out of dollars when the fee is "
    "unknown — not treated as free. Fees are charged on each ticket, so Yes "
    "dollars and No dollars are not exact negatives of each other. Kansas "
    "City–Seattle enters dollars only if that cover has a result; still-open "
    "stays out. Research only. Did not turn live D NFL on, did not send, did "
    "not sell, did not start a second B, did not bump stake."
)
ASKED_DECILE = (
    "thanks, can you extend this to every decile?. i suspect 20-39 are also "
    "winners. sjow me"
)
PLAIN_DECILE = (
    "This is every National Football League (NFL) Type A cover-Yes we watched "
    "at kickoff — team A wins by N or team B wins by N — including dogs we did "
    "not bet, because live D still skips NFL. Totals and team totals are out. "
    "Each 10-cent bucket is a half-open interval: 20-29 means first trusted Yes "
    "from 20 cents up to but not including 30 cents ([0.20, 0.30)). 20-39 is "
    "20-29 plus 30-39, shown as those two rows plus a combined 20-39 row. "
    "Hypothetical: buy 1 contract of that cover-Yes at the T0 ask plus "
    "documented taker fees (Kalshi / Gemini / Polymarket). Novig is omitted "
    "from dollars when the fee is unknown — not treated as free. Kansas "
    "City–Seattle and any still-open line stay out of the dollars. Unique-fav "
    "one-per-game (the live D analog, always above 50 cents) is a labeled "
    "secondary so it cannot mix into this bankroll. Tiny N does not turn live "
    "D NFL on, does not send, does not sell, does not start a second B, does "
    "not bump stake."
)
ASKED_51_69 = (
    "thanks. so what is the final PnL if we take any spread in NFL that is "
    "51-69 at T0?"
)
PLAIN_51_69 = (
    "Hypothetical only — not a live order. Buy 1 contract of every National "
    "Football League (NFL) Type A spread (team A wins by N or team B wins by N "
    "/ cover-Yes) whose first trusted kickoff Yes sat between 51 cents and 69 "
    "cents, inclusive. That is every wins-by-n line we have a T0 Yes for in "
    "that band, including games we did not bet. Totals and team totals are "
    "out. Exact 50¢ is out (he said 51–69, so the floor is 0.51). Kansas "
    "City–Seattle stays out of the dollars if that 8:20pm ET game is still "
    "open. Fees are the documented house taker fees (Kalshi / Gemini / "
    "Polymarket). Novig is omitted when the fee schedule is unknown — not "
    "treated as free. Tiny N does not turn live D NFL on, does not send, "
    "does not sell, does not start a second B, does not bump stake."
)
ASKED = (
    "He thought this was a history of ALL games including those we did NOT bet "
    "on. The primary table is still N=4 / live D band N=3 — same size as before "
    "today. “how did we go through an entire day and not gather more useful "
    "data?” “I want data. collect it. analyze it, let's make some money from "
    "it. what is this report? it's nonsense. explain everything but only the "
    "stuff i really care about. what are the odds that a spread in the NFL for "
    "type A ( team A wins by N or team B wins by N) are the winners when they "
    "start T0 in bucket A) 90+, B) 80-89, etc. come on/ let's see it”"
)
PLAIN = (
    "This is every National Football League (NFL) Type A spread we watched at "
    "T0 (first trusted kickoff): team A wins by N or team B wins by N (cover). "
    "Not totals. Not team totals. Includes games we did not bet, because live D "
    "still skips NFL. The number you care about is win percent by T0 price "
    "bucket — how often that cover-Yes settled YES when it opened in >90, "
    "80-89, 70-79, 60-69, 50-59. Two grains, labeled so they cannot mix: one "
    "line per game (the unique favorite closest to 50¢, the live D pick analog) "
    "and all wins-by-n lines we actually have a T0 Yes for. Sunday-only and "
    "all-days sit in separate tables. Open games (Kansas City–Seattle 8:20 if "
    "still live) are listed below, not in win%. Dollars are with documented "
    "fees when we can size 1 contract at the T0 ask; win% does not need fees. "
    "Tiny N still does not wire D NFL. Research only."
)
_WINS_BY_RE = re.compile(
    r"\s*(?:wins by (?:more than|over)\s+[\d.]+(?:\s+points?)?)\s*$",
    re.I,
)

# Lower rank wins when a game has mixed books.
STATUS_RANK = {
    "settled unique-fav T0": 0,
    "settled cover-Yes (not unique-fav)": 1,
    "unsettled": 2,
    "void": 3,
    "50-50": 4,
    "no post-T0": 5,
    "one-sided": 6,
    "clock hid match": 7,
    "no T0 quotes": 8,
    "no clock": 9,
    "no documented fee": 10,
    "catalog only — no ticks": 11,
}


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def listed_et_parts(raw: str) -> tuple[str, str]:
    """Return (YYYY-MM-DD, HH:MM) in ET when the listed clock is parseable."""
    text = str(raw or "").strip()
    if not text:
        return "", ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text, ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        local = dt.astimezone(ET)
        return local.date().isoformat(), local.strftime("%H:%M")
    except ValueError:
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text):
            return text[:10], text[11:16]
        return text[:10] if len(text) >= 10 else text, ""


def is_today_slate(listed: str, today: str = TODAY_ET) -> bool:
    text = str(listed or "").strip()
    if text.startswith(today):
        return True
    date, _hm = listed_et_parts(text)
    return date == today


def kickoff_window_label(listed: str, today: str = TODAY_ET) -> str:
    date, hm = listed_et_parts(listed)
    if str(listed or "").startswith(today) and not date:
        date = today
    if date != today:
        return ""
    if not hm:
        return "Sunday listed, clock missing"
    return WINDOW_LABELS.get(hm, f"{hm} ET")


def d_missed_1pm(listed: str, today: str = TODAY_ET) -> bool:
    date, hm = listed_et_parts(listed)
    if str(listed or "").startswith(today) and not date:
        date = today
        if len(str(listed)) >= 16:
            hm = hm or str(listed)[11:16]
    return date == today and hm == "13:00"


def play_state(listed: str, *, settled: bool, catalog_only: bool, now: datetime | None = None) -> str:
    if settled:
        return "settled"
    now = now or datetime.now(ET)
    text = str(listed or "").strip()
    try:
        kick = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if kick.tzinfo is None:
            kick = kick.replace(tzinfo=ET)
        kick = kick.astimezone(ET)
    except ValueError:
        if catalog_only:
            return "catalog only — clock unparsed"
        return "OPEN on this tape — clock unparsed"
    if now < kick:
        return "not kicked off yet"
    if catalog_only:
        return "kickoff passed — still no ticks"
    return "OPEN (kickoff passed, not settled)"


def sunday_games(games: list[dict], today: str = TODAY_ET) -> list[dict]:
    return [g for g in games if is_today_slate(g.get("listed") or "", today)]


def _window_rank(label: str) -> tuple:
    try:
        return (0, WINDOW_ORDER.index(label))
    except ValueError:
        return (1, label)


def catalog_title(row: dict) -> str:
    return (
        str(row.get("title_kalshi") or "").strip()
        or str(row.get("title_gemini") or "").strip()
        or str(row.get("game") or "").strip()
        or str(row.get("game_name") or "").strip()
        or " vs ".join(str(c) for c in (row.get("codes") or []) if c)
    )


def catalog_has_spread(row: dict) -> bool:
    kalshi = row.get("kalshi") if isinstance(row.get("kalshi"), dict) else {}
    gemini = row.get("gemini") if isinstance(row.get("gemini"), dict) else {}
    if kalshi.get("spread") or gemini.get("spread"):
        return True
    markets = " ".join(
        str(x) for x in (
            row.get("kalshi_markets") or [],
            row.get("gemini_markets") or [],
        )
    ).lower()
    if "spread" in markets:
        return True
    closest = row.get("closest") if isinstance(row.get("closest"), dict) else {}
    return "spread" in str(closest.get("market_type") or "").lower()


def load_catalog_nfl_spread() -> list[dict]:
    """Saved catalog NFL games that list a spread sibling. Read-only."""
    by_game: dict[str, dict] = {}

    def add(row: dict, source: str) -> None:
        if not isinstance(row, dict):
            return
        if not catalog_has_spread(row):
            return
        title = catalog_title(row)
        if not title:
            return
        key = game_norm(title)
        if not key:
            return
        listed = str(row.get("listed_start") or row.get("startTime") or row.get("game_date") or "")
        prev = by_game.get(key)
        if prev is None:
            by_game[key] = {
                "game": title,
                "game_n": key,
                "listed_start": listed,
                "date": str(row.get("date") or row.get("game_date") or ""),
                "source": source,
                "codes": row.get("codes") or [],
            }
            return
        if listed and not prev.get("listed_start"):
            prev["listed_start"] = listed
        if len(title) > len(prev.get("game") or ""):
            prev["game"] = title

    if QUEUE_PATH.is_file():
        try:
            blob = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = {}
        for sport_row in blob.get("sports") or []:
            sport = str(sport_row.get("sport") or "")
            if not is_nfl(sport):
                continue
            for row in sport_row.get("matched") or []:
                add(row, "sports_queue.json")

    if RESULTS_PATH.is_file():
        try:
            with RESULTS_PATH.open(encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        rec = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not is_nfl(rec.get("sport")):
                        continue
                    add(rec, "pro_football_results.jsonl")
        except OSError:
            pass
    return sorted(by_game.values(), key=lambda r: (r.get("date") or "", r.get("game") or ""))


def overlay_catalog_starts(books: list[dict], catalog: list[dict]) -> int:
    """Fill empty listed clocks from catalog. Does not change the T0 helper."""
    by_n = {row["game_n"]: row for row in catalog}
    n = 0
    for book in books:
        if book.get("listed_raw"):
            continue
        hit = by_n.get(str(book.get("game_n") or ""))
        if not hit:
            continue
        listed = hit.get("listed_start") or ""
        if not listed:
            continue
        book["listed_raw"] = listed
        n += 1
    return n


def path_is_no_post(book: dict) -> bool:
    path = book.get("fav_path") or {}
    if not book.get("fav"):
        return False
    if path.get("empty"):
        return True
    return str(path.get("path_status") or "") == "no_post_t0_path"


def book_status(book: dict) -> str:
    skip = str(book.get("skip") or "")
    if skip == "clock_hides_match":
        return "clock hid match"
    if skip == "no_trusted_clock":
        return "no clock"
    if skip == "no_t0_quotes":
        return "no T0 quotes"
    if skip == "t0_50_50":
        return "50-50"
    if not book.get("two_sided"):
        return "one-sided"
    if not trusted_two_sided(book):
        return "no clock" if not skip else skip.replace("_", " ")
    if book.get("void"):
        return "void"
    if cover_yes_known(book):
        if book.get("fav") and is_unique_fav(score_t0_yes(book)):
            return "settled unique-fav T0"
        return "settled cover-Yes (not unique-fav)"
    if not book.get("settled"):
        if path_is_no_post(book) and is_unique_fav(book.get("t0_fav")):
            return "no post-T0"
        return "unsettled"
    if not book.get("fav") or not is_unique_fav(book.get("t0_fav")):
        return "50-50"
    if documented_leg_fee(str(book.get("venue") or ""), book.get("t0_fav")) is None:
        return "no documented fee"
    return "settled unique-fav T0"


def game_status(books: list[dict], *, catalog_row: dict | None = None) -> dict:
    """One status per game. P&L-eligible books win over skip reasons."""
    title = ""
    listed = ""
    if catalog_row:
        title = catalog_row.get("game") or ""
        listed = catalog_row.get("listed_start") or catalog_row.get("date") or ""
    if not books:
        return {
            "game": title,
            "game_n": (catalog_row or {}).get("game_n") or game_norm(title),
            "status": "catalog only — no ticks" if catalog_row else "no clock",
            "n_books": 0,
            "n_two_sided": 0,
            "n_trusted": 0,
            "listed": listed,
            "in_pnl": False,
            "pending": False,
            "settled_cover": False,
            "catalog_only": bool(catalog_row),
        }
    reasons = [book_status(b) for b in books]
    best = min(reasons, key=lambda r: STATUS_RANK.get(r, 99))
    for book in books:
        if len(str(book.get("game") or "")) > len(title):
            title = book.get("game") or title
        if book.get("listed_raw") and not listed:
            listed = book.get("listed_raw") or ""
        if book.get("clock") and (not listed or listed < str(book.get("clock"))):
            listed = listed or book.get("clock") or ""
    n_two = sum(1 for b in books if b.get("two_sided"))
    n_trusted = sum(1 for b in books if trusted_two_sided(b))
    return {
        "game": title,
        "game_n": str(books[0].get("game_n") or game_norm(title)),
        "status": best,
        "n_books": len(books),
        "n_two_sided": n_two,
        "n_trusted": n_trusted,
        "listed": listed,
        "in_pnl": best == "settled unique-fav T0",
        "pending": best == "unsettled",
        "settled_cover": best in {
            "settled unique-fav T0",
            "settled cover-Yes (not unique-fav)",
        },
        "catalog_only": False,
        "reasons": dict(sorted({r: reasons.count(r) for r in set(reasons)}.items())),
    }


def score_arm(trades: list[dict], *, arm_id: str, label: str, n_void: int, grain: str) -> dict:
    q = quality(trades, arm_id=arm_id, label=label, grain=grain)
    q["n_void"] = n_void
    q["total_fees"] = sum(float(t.get("fee") or 0) for t in trades)
    q["note"] = sample_note(int(q.get("n") or 0))
    return q


def bucket_arms(books: list[dict], voids: list[dict], *, grain: str, prefix: str) -> dict:
    by_bucket: dict[str, list[dict]] = {label: [] for label, *_ in BUCKETS}
    for book in books:
        by_bucket.setdefault(bucket_of(book.get("t0_fav")), []).append(book)
    d_books = [b for b in books if in_d_band(b.get("t0_fav"))]
    recs = {}
    for label, lo, hi, how in BUCKETS:
        recs[label] = score_arm(
            trades_for(by_bucket.get(label) or [], f"{prefix}:{label}"),
            arm_id=f"{prefix}:{label}",
            label=label,
            n_void=void_count(voids, lambda px, lo=lo, hi=hi, how=how: _in_bucket(px, lo, hi, how)),
            grain=grain,
        )
    recs[D_BAND_ID] = score_arm(
        trades_for(d_books, f"{prefix}:d_band"),
        arm_id=f"{prefix}:d_band",
        label=D_BAND_ID,
        n_void=void_count(voids, in_d_band),
        grain=grain,
    )
    recs[ALL_ID] = score_arm(
        trades_for(books, f"{prefix}:all_unique_fav"),
        arm_id=f"{prefix}:all_unique_fav",
        label=ALL_ID,
        n_void=len(voids),
        grain=grain,
    )
    return recs


def load_tracked_books(*, fetch: bool = True) -> tuple[list[dict], list[dict], dict]:
    print(
        "loading NFL Type A settlements (cache + local dumps"
        + (" + Kalshi pull" if fetch else " + saved overlay, no Kalshi pull")
        + ")",
        flush=True,
    )
    settlements, settle_meta = load_nfl_settlements(fetch=fetch)
    index = build_index(settlements)
    cover_index = build_nfl_cover_index(settlements)
    print(f"settlements {len(settlements)} cover-index {len(cover_index)}", flush=True)
    sides, meta = stream_nfl_spread_sides()
    books = t0.pair_books(sides)
    catalog = load_catalog_nfl_spread()
    n_overlay = overlay_catalog_starts(books, catalog)
    occ_map = occ_map_prefer_listed(catalog, settlements)
    print(
        f"paired {len(books)} NFL spread venue-game books; "
        f"catalog spread games {len(catalog)}; listed overlay {n_overlay}; "
        f"listed clocks {len(occ_map)}",
        flush=True,
    )
    now = datetime.now(ET)
    for i, book in enumerate(books):
        t0.settle_book(book, settlements, index)
        t0.score_book(book, occ_map)
        overlay_cover_settlement(book, cover_index, now=now)
        if book.get("fav") and cover_yes_known(book) and book.get("fav_won") is None:
            fav = book.get("fav")
            if fav == "a":
                book["fav_won"] = book.get("off_a") == "win"
            elif fav == "b":
                book["fav_won"] = book.get("off_b") == "win"
        if (i + 1) % 200 == 0:
            print(f"  scored {i + 1}/{len(books)}", flush=True)
    meta["n_settlements"] = len(settlements)
    meta["n_books"] = len(books)
    meta["n_catalog"] = len(catalog)
    meta["n_listed_overlay"] = n_overlay
    meta["settle"] = settle_meta
    return books, catalog, meta


def classify_inventory(books: list[dict]) -> dict:
    """Keep every NFL Type A spread book. Win% uses settled cover-Yes with T0."""
    skips: dict[str, int] = defaultdict(int)
    scored = []
    all_lines = []
    voids = []
    pending = []
    fifty = []
    no_fee = []
    no_post = []
    trusted = []
    for book in books:
        if not is_nfl(book.get("sport")) or not is_spread(book.get("kind")):
            continue
        status = book_status(book)
        skips[status] += 1
        if trusted_two_sided(book):
            trusted.append(book)
        if path_is_no_post(book):
            no_post.append(book)
        if status == "settled unique-fav T0":
            scored.append(book)
            all_lines.append(book)
        elif status == "settled cover-Yes (not unique-fav)":
            all_lines.append(book)
        elif status == "void":
            voids.append(book)
        elif status in {"unsettled", "no post-T0"}:
            pending.append(book)
        elif status == "50-50":
            fifty.append(book)
        elif status == "no documented fee":
            no_fee.append(book)
            if cover_yes_known(book):
                all_lines.append(book)
                if book.get("fav") and is_unique_fav(score_t0_yes(book)):
                    scored.append(book)
    return {
        "scored": scored,
        "all_lines": all_lines,
        "voids": voids,
        "pending": pending,
        "fifty": fifty,
        "no_fee": no_fee,
        "no_post": no_post,
        "trusted": trusted,
        "skips": dict(skips),
    }


def inventory_games(books: list[dict], catalog: list[dict]) -> list[dict]:
    bags: dict[str, list[dict]] = defaultdict(list)
    for book in books:
        if not is_nfl(book.get("sport")) or not is_spread(book.get("kind")):
            continue
        bags[str(book.get("game_n") or "")].append(book)
    cat_by_n = {row["game_n"]: row for row in catalog}
    rows = []
    seen = set()
    for game_n, group in bags.items():
        if not game_n:
            continue
        seen.add(game_n)
        rows.append(game_status(group, catalog_row=cat_by_n.get(game_n)))
    for game_n, cat in cat_by_n.items():
        if game_n in seen:
            continue
        rows.append(game_status([], catalog_row=cat))
    rows.sort(key=lambda r: (STATUS_RANK.get(r["status"], 99), r.get("game") or ""))
    return rows


def short_team_name(raw: str) -> str:
    """Drop 'wins by more than N points' so the cell is the team, not the ticker."""
    text = str(raw or "").strip()
    if not text:
        return ""
    return _WINS_BY_RE.sub("", text).strip() or text


def _px(value):
    if value is None:
        return None
    return float(value)


def yes_no_view(book: dict) -> dict:
    """Two teams' cover-Yes (sorted by name) plus fav Yes/No of one contract.

    T0 Yes A / T0 Yes B on the old table were those two cover-Yeses, not
    Yes+No of one contract. Team 1 / Team 2 follow side_a / side_b (name
    sort from pair_books). T0 fav No is the live No ask if present, else 1 − Yes.
    """
    number = str(book.get("number") or "").strip()
    team1 = short_team_name(str(book.get("side_a") or ""))
    team2 = short_team_name(str(book.get("side_b") or ""))
    team1_yes = _px(book.get("t0_a"))
    team2_yes = _px(book.get("t0_b"))
    fav = str(book.get("fav") or "")
    fav_name = short_team_name(str(book.get("fav_name") or "").strip())
    t0_yes = book.get("t0_fav")
    if t0_yes is None and fav == "a":
        t0_yes = book.get("t0_a")
    elif t0_yes is None and fav == "b":
        t0_yes = book.get("t0_b")
    if fav == "a":
        other_name = team2
        other_yes = team2_yes
        if not fav_name:
            fav_name = team1
    elif fav == "b":
        other_name = team1
        other_yes = team1_yes
        if not fav_name:
            fav_name = team2
    else:
        other_name = team2
        other_yes = team2_yes
        if not fav_name:
            fav_name = team1
        if t0_yes is None:
            t0_yes = book.get("t0_a")
    live_no = book.get("t0_no")
    if live_no is not None:
        t0_no = float(live_no)
        no_src = "live No ask"
    elif t0_yes is not None:
        t0_no = 1.0 - float(t0_yes)
        no_src = "1 − Yes"
    else:
        t0_no = None
        no_src = ""
    yes_no = None
    if t0_yes is not None and t0_no is not None:
        yes_no = float(t0_yes) + float(t0_no)
    if fav_name and number:
        market = f"{fav_name} wins by >{number}"
    elif fav_name:
        market = f"{fav_name} covers"
    else:
        market = number or "spread"
    return {
        "market": market,
        "t0_yes": None if t0_yes is None else float(t0_yes),
        "t0_no": t0_no,
        "no_src": no_src,
        "yes_no": yes_no,
        "other_name": other_name or "—",
        "other_yes": None if other_yes is None else float(other_yes),
        "fav_name": fav_name,
        "number": number,
        "team1": team1,
        "team2": team2,
        "team1_yes": team1_yes,
        "team2_yes": team2_yes,
    }


def _fmt_px(value) -> str:
    return fmt_num(value, 3) if value is not None else "—"


def t0_price_row(book: dict) -> list[str]:
    view = yes_no_view(book)
    return [
        esc(book.get("game") or ""),
        esc(view["team1"] or "—"),
        _fmt_px(view["team1_yes"]),
        esc(view["team2"] or "—"),
        _fmt_px(view["team2_yes"]),
        esc(view["market"]),
        _fmt_px(view["t0_yes"]),
        _fmt_px(view["t0_no"]),
        esc(view["no_src"] or "—"),
        _fmt_px(view["yes_no"]),
        esc(view["number"] or ""),
        esc(book.get("venue") or ""),
        esc(bucket_of(book.get("t0_fav")) if book.get("t0_fav") is not None else ""),
        "yes" if book.get("two_sided") else "no",
        "yes" if book.get("settled") else "no",
        "win" if book.get("fav_won") else ("—" if book.get("fav_won") is None else "loss"),
        esc(book.get("t0_source") or ""),
        esc(book_status(book)),
    ]


T0_PRICE_HEADERS = [
    ("Game", "text"),
    ("Team 1", "text"),
    ("Cover Yes team 1", "num"),
    ("Team 2", "text"),
    ("Cover Yes team 2", "num"),
    ("Market (fav cover Yes)", "text"),
    ("T0 fav Yes", "num"),
    ("T0 fav No", "num"),
    ("No source", "text"),
    ("Fav Yes+No (same contract)", "num"),
    ("Line", "text"),
    ("Venue", "text"),
    ("Bucket", "text"),
    ("Two-sided", "text"),
    ("Settled", "text"),
    ("Fav won", "text"),
    ("T0 source", "text"),
    ("Status", "text"),
]

BAND_OPEN_HEADERS = [
    ("Game", "text"),
    ("Line", "text"),
    ("T0 Yes", "num"),
    ("Venue", "text"),
    ("Listed / clock", "text"),
    ("Why out of PnL", "text"),
]

BAND_51_69_HEADERS = [
    ("Band / grain", "text"),
    ("N", "num"),
    ("Wins", "num"),
    ("Win %", "num"),
    ("With-fee PnL $", "num"),
    ("Mean $", "num"),
    ("Total fees $", "num"),
    ("N_void", "num"),
    ("N_fee", "num"),
    ("Note", "text"),
]
DECILE_HEADERS = BAND_51_69_HEADERS
NO_DECILE_HEADERS = [
    ("Band / grain", "text"),
    ("N", "num"),
    ("No wins (Yes lost)", "num"),
    ("No win %", "num"),
    ("With-fee PnL $", "num"),
    ("Mean $", "num"),
    ("Total fees $", "num"),
    ("N_void", "num"),
    ("N_fee", "num"),
    ("Note", "text"),
]


def band_open_why(book: dict, *, now: datetime | None = None) -> str:
    """Say whether a 51-69 line is still live, not yet kicked, or missing a result."""
    now = now or datetime.now(ET)
    listed = str(book.get("listed_raw") or book.get("clock") or "")
    venue = str(book.get("venue") or "")
    fee_missing = documented_leg_fee(venue, score_t0_yes(book)) is None
    fee_bit = f"; {venue or 'unknown'} fee unknown" if fee_missing else ""
    try:
        kick = datetime.fromisoformat(listed.replace("Z", "+00:00"))
        if kick.tzinfo is None:
            kick = kick.replace(tzinfo=ET)
        kick = kick.astimezone(ET)
    except ValueError:
        return "still open — excluded from PnL" + fee_bit
    if now < kick:
        return "not kicked off yet — excluded from PnL" + fee_bit
    if now < kick + GAME_OVER:
        return "still live — excluded from PnL" + fee_bit
    return "kickoff passed, no cover result on this line — excluded from PnL" + fee_bit


def summarize_open_band(open_books: list[dict], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(ET)
    live, future, missing = [], [], []
    for book in open_books:
        why = band_open_why(book, now=now)
        if why.startswith("still live"):
            live.append(book)
        elif why.startswith("not kicked"):
            future.append(book)
        else:
            missing.append(book)
    live_games = sorted({str(b.get("game") or "") for b in live})
    return {
        "n_live": len(live),
        "n_future": len(future),
        "n_missing": len(missing),
        "live_games": live_games,
        "live": live,
        "future": future,
        "missing": missing,
    }


def band_open_rows(open_books: list[dict], no_fee_books: list[dict]) -> list[list[str]]:
    rows = []
    now = datetime.now(ET)
    for book in sorted(
        open_books,
        key=lambda b: (str(b.get("game") or ""), str(b.get("number") or "")),
    ):
        px = score_t0_yes(book)
        rows.append([
            esc(book.get("game") or ""),
            esc(book.get("number") or ""),
            f"{float(px):.3f}" if px is not None else "—",
            esc(book.get("venue") or ""),
            esc(book.get("listed_raw") or book.get("clock") or ""),
            esc(band_open_why(book, now=now)),
        ])
    for book in sorted(
        no_fee_books,
        key=lambda b: (str(b.get("game") or ""), str(b.get("number") or "")),
    ):
        px = score_t0_yes(book)
        rows.append([
            esc(book.get("game") or ""),
            esc(book.get("number") or ""),
            f"{float(px):.3f}" if px is not None else "—",
            esc(book.get("venue") or ""),
            esc(book.get("listed_raw") or book.get("clock") or ""),
            "no documented fee (not treated as zero) — in win% N, out of $",
        ])
    if not rows:
        rows = [["none", "—", "—", "—", "—", "no open 51–69 lines and no fee holes"]]
    return rows


TICKET_HEADERS = [
    ("Game", "text"),
    ("Team 1", "text"),
    ("Cover Yes team 1", "num"),
    ("Team 2", "text"),
    ("Cover Yes team 2", "num"),
    ("Market (fav cover Yes)", "text"),
    ("T0 fav Yes", "num"),
    ("T0 fav No", "num"),
    ("No source", "text"),
    ("Fav Yes+No (same contract)", "num"),
    ("Venue", "text"),
    ("Bucket", "text"),
    ("In D band", "text"),
    ("Won", "text"),
    ("Fee $", "num"),
    ("With-fee PnL $", "num"),
    ("T0 date", "date"),
    ("T0 source", "text"),
    ("Lines on game", "num"),
]

# Glossary — T0 Yes A / T0 Yes B. A/B are two teams' cover-Yes, not Yes+No.
YES_AB_GLOSSARY = (
    "T0 Yes A / T0 Yes B = the two teams' Yes asks on that spread line "
    "(e.g. Arizona wins by more than 1.5 vs LA wins by more than 1.5), "
    "sorted by team name, at first trusted kickoff. Not Yes and No of one "
    "contract — not Yes plus No of one contract. Yes+No of one line is a "
    "different pair (fav cover Yes and fav cover No ≈ 1 − Yes). A/B are two "
    "teams' cover-Yes, not Yes+No. Adding them is a middle: if the winner "
    "covers by 1 (or the game ties), neither side wins by more than the line "
    "and both Yes lose."
)

SKIP_HEADERS = [
    ("Game", "text"),
    ("Status", "text"),
    ("N books", "num"),
    ("N two-sided", "num"),
    ("N trusted T0", "num"),
    ("Listed / clock", "text"),
    ("In P&L", "text"),
]

STATUS_COUNT_HEADERS = [
    ("Status", "text"),
    ("N games", "num"),
    ("In P&L?", "text"),
]


def nfl_type_a_books(books: list[dict]) -> list[dict]:
    """Type A only — wins-by-n / cover. Totals and team totals stay out."""
    return [
        b for b in books
        if is_nfl(b.get("sport")) and is_spread(b.get("kind"))
    ]


def build_51_69_payload(books: list[dict]) -> dict:
    """All-lines Type A T0 Yes in [0.51, 0.69]. Open excluded from PnL."""
    type_a = nfl_type_a_books(books)
    all_days = score_t0_yes_band(type_a, label=BAND_51_69_ID, grain="all-lines")
    sunday_src = [b for b in type_a if is_sunday_book(b, TODAY_ET)]
    sunday = score_t0_yes_band(
        sunday_src, label=f"{BAND_51_69_ID} Sunday", grain="all-lines Sunday"
    )
    # One venue per line on the old 50-69 neighborhood, then split so rows add.
    hood = pick_fee_primary_line(
        [b for b in type_a if in_old_50_69_neighborhood(score_t0_yes(b))]
    )
    split_50 = score_t0_yes_band(
        hood, label=BAND_50_59_ID, pred=in_old_50_59, pick=False
    )
    split_60 = score_t0_yes_band(
        hood, label=BAND_60_69_ID, pred=in_old_60_69, pick=False
    )
    old_combined = score_t0_yes_band(
        hood, label=BAND_OLD_COMBINED_ID, pred=in_old_50_69_neighborhood, pick=False
    )
    sunday_hood = pick_fee_primary_line(
        [b for b in sunday_src if in_old_50_69_neighborhood(score_t0_yes(b))]
    )
    sunday_50 = score_t0_yes_band(
        sunday_hood, label=f"{BAND_50_59_ID} Sunday", pred=in_old_50_59, pick=False
    )
    sunday_60 = score_t0_yes_band(
        sunday_hood, label=f"{BAND_60_69_ID} Sunday", pred=in_old_60_69, pick=False
    )
    uf = unique_fav_one_per_game_band(type_a, label=BAND_UF_ID)
    uf_sun = unique_fav_one_per_game_band(sunday_src, label=f"{BAND_UF_ID} Sunday")
    edges = band_edge_counts(pick_primary_line(type_a) if type_a else [])
    open_summary = summarize_open_band(all_days.get("open_books") or [])
    return {
        "all_days": all_days,
        "sunday": sunday,
        "split_50_59": split_50,
        "split_60_69": split_60,
        "old_combined": old_combined,
        "sunday_50_59": sunday_50,
        "sunday_60_69": sunday_60,
        "unique_fav": uf,
        "unique_fav_sunday": uf_sun,
        "edges": edges,
        "open_summary": open_summary,
        "n_type_a": len(type_a),
        "n_type_a_sunday": len(sunday_src),
        "n_in_band_raw": sum(1 for b in type_a if in_51_69(score_t0_yes(b))),
    }


def build_payload(*, fetch: bool = True) -> dict:
    books, catalog, meta = load_tracked_books(fetch=fetch)
    bags = classify_inventory(books)
    scored = bags["scored"]
    all_line_raw = bags["all_lines"]
    line_books = pick_primary_line(scored)
    match_books = pick_one_per_game(line_books)
    all_line_books = pick_primary_line(all_line_raw) if all_line_raw else []
    void_lines = pick_primary_line(bags["voids"])
    void_matches = pick_one_per_game(void_lines) if void_lines else []
    pending_lines = pick_primary_line(bags["pending"])
    pending_matches = pick_one_per_game(pending_lines) if pending_lines else []
    trusted_lines = pick_primary_line(bags["trusted"])

    match_recs = bucket_arms(match_books, void_matches, grain="match", prefix="match")
    line_recs = bucket_arms(line_books, void_lines, grain="line", prefix="line")
    match_win = bucket_winpct(match_books, prefix="unique-fav")
    line_win = bucket_winpct(all_line_books, prefix="all-lines")
    sunday_match = [b for b in match_books if is_sunday_book(b, TODAY_ET)]
    sunday_lines = [b for b in all_line_books if is_sunday_book(b, TODAY_ET)]
    sunday_match_win = bucket_winpct(sunday_match, prefix="sunday-unique-fav")
    sunday_line_win = bucket_winpct(sunday_lines, prefix="sunday-all-lines")
    games = inventory_games(books, catalog)
    n_tracked = len(games)
    n_pnl_games = sum(1 for g in games if g.get("in_pnl"))
    n_settled_games = sum(1 for g in games if g.get("settled_cover") or g.get("in_pnl"))
    n_pending_games = sum(1 for g in games if g.get("pending") or g["status"] == "catalog only — no ticks")
    n_skipped = n_tracked - n_pnl_games
    status_counts: dict[str, int] = defaultdict(int)
    for g in games:
        status_counts[g["status"]] += 1

    t0_dates = sorted({
        t.get("entry_date") for t in (match_recs[ALL_ID].get("trades") or []) if t.get("entry_date")
    })
    band_51_69 = build_51_69_payload(books)
    every_decile = build_every_decile_payload(
        nfl_type_a_books(books), sunday_date=TODAY_ET
    )
    return {
        "written_at": iso_now(),
        "meta": meta,
        "bags": {
            "n_raw_books": len(books),
            "n_scored_venue": len(scored),
            "n_all_line_raw": len(all_line_raw),
            "n_lines": len(line_books),
            "n_all_line_books": len(all_line_books),
            "n_match": len(match_books),
            "n_sunday_match": len(sunday_match),
            "n_sunday_lines": len(sunday_lines),
            "n_void_venue": len(bags["voids"]),
            "n_void_match": len(void_matches),
            "n_pending_books": len(bags["pending"]),
            "n_pending_lines": len(pending_lines),
            "n_pending_match": len(pending_matches),
            "n_fifty": len(bags["fifty"]),
            "n_no_fee": len(bags["no_fee"]),
            "n_no_post": len(bags["no_post"]),
            "n_trusted": len(bags["trusted"]),
            "n_trusted_lines": len(trusted_lines),
            "n_catalog": len(catalog),
            "n_tracked_games": n_tracked,
            "n_pnl_games": n_pnl_games,
            "n_settled_games": n_settled_games,
            "n_pending_games": n_pending_games,
            "n_skipped_games": n_skipped,
            "skips": bags["skips"],
            "status_counts": dict(status_counts),
            "t0_dates": t0_dates,
        },
        "match_recs": match_recs,
        "line_recs": line_recs,
        "match_win": match_win,
        "line_win": line_win,
        "sunday_match_win": sunday_match_win,
        "sunday_line_win": sunday_line_win,
        "match_books": match_books,
        "line_books": line_books,
        "all_line_books": all_line_books,
        "sunday_match": sunday_match,
        "sunday_lines": sunday_lines,
        "trusted_lines": trusted_lines,
        "pending_matches": pending_matches,
        "games": games,
        "catalog": catalog,
        "band_51_69": band_51_69,
        "every_decile": every_decile,
    }


def skip_count_rows(counts: dict[str, int]) -> list[list[str]]:
    rows = []
    for status, n in sorted(counts.items(), key=lambda kv: (STATUS_RANK.get(kv[0], 99), kv[0])):
        rows.append([
            esc(status),
            str(n),
            "yes" if status == "settled unique-fav T0" else "no",
        ])
    if not rows:
        rows = [["—", "0", "no"]]
    return rows


def game_rows(games: list[dict]) -> list[list[str]]:
    rows = []
    for g in games:
        rows.append([
            esc(g.get("game") or ""),
            esc(g.get("status") or ""),
            str(g.get("n_books") or 0),
            str(g.get("n_two_sided") or 0),
            str(g.get("n_trusted") or 0),
            esc(g.get("listed") or ""),
            "yes" if g.get("in_pnl") else "no",
        ])
    if not rows:
        rows = [["—", "none tracked", "0", "0", "0", "—", "no"]]
    return rows


def pending_rows(games: list[dict], pending_matches: list[dict]) -> list[list[str]]:
    by_n = {str(b.get("game_n") or ""): b for b in pending_matches}
    rows = []
    for g in games:
        if not (g.get("pending") or g["status"] in {"catalog only — no ticks", "no post-T0", "unsettled"}):
            continue
        book = by_n.get(str(g.get("game_n") or ""))
        view = yes_no_view(book) if book else {}
        rows.append([
            esc(g.get("game") or ""),
            esc(g.get("status") or ""),
            esc(view.get("team1") or "—"),
            _fmt_px(view.get("team1_yes")),
            esc(view.get("team2") or "—"),
            _fmt_px(view.get("team2_yes")),
            esc(view.get("market") or (book or {}).get("number") or "—"),
            _fmt_px(view.get("t0_yes")),
            _fmt_px(view.get("t0_no")),
            esc(view.get("no_src") or "—"),
            _fmt_px(view.get("yes_no")),
            esc((book or {}).get("venue") or ""),
            esc(g.get("listed") or ""),
        ])
    if not rows:
        rows = [["—"] * 13]
        rows[0][1] = "none pending"
    return rows


PENDING_HEADERS = [
    ("Game", "text"),
    ("Status", "text"),
    ("Team 1", "text"),
    ("Cover Yes team 1", "num"),
    ("Team 2", "text"),
    ("Cover Yes team 2", "num"),
    ("Market (fav cover Yes)", "text"),
    ("T0 fav Yes", "num"),
    ("T0 fav No", "num"),
    ("No source", "text"),
    ("Fav Yes+No (same contract)", "num"),
    ("Venue", "text"),
    ("Listed / clock", "text"),
]

SUNDAY_WINDOW_HEADERS = [
    ("Kickoff window", "text"),
    ("N games", "num"),
    ("With ticks", "num"),
    ("Catalog-only", "num"),
    ("Trusted T0", "num"),
    ("Settled (in win%)", "num"),
]

SUNDAY_GAME_HEADERS = [
    ("Game", "text"),
    ("Kickoff window", "text"),
    ("Listed / clock", "text"),
    ("Play state", "text"),
    ("Status", "text"),
    ("Ticks?", "text"),
    ("N books", "num"),
    ("N two-sided", "num"),
    ("N trusted T0", "num"),
    ("D 1pm miss?", "text"),
    ("In unique-fav win%", "text"),
    ("Settled cover", "text"),
    ("Team 1", "text"),
    ("Cover Yes team 1", "num"),
    ("Team 2", "text"),
    ("Cover Yes team 2", "num"),
    ("Market (fav cover Yes)", "text"),
    ("T0 fav Yes", "num"),
    ("T0 fav No", "num"),
    ("Venue", "text"),
]


def sunday_window_rows(games: list[dict], today: str = TODAY_ET) -> list[list[str]]:
    bags: dict[str, list[dict]] = defaultdict(list)
    for game in sunday_games(games, today):
        label = kickoff_window_label(game.get("listed") or "", today) or "Sunday listed, clock missing"
        bags[label].append(game)
    rows = []
    for window, group in sorted(bags.items(), key=lambda kv: _window_rank(kv[0])):
        catalog_only = sum(
            1 for g in group
            if g.get("catalog_only") or g.get("status") == "catalog only — no ticks"
        )
        with_ticks = sum(
            1 for g in group
            if not (g.get("catalog_only") or g.get("status") == "catalog only — no ticks")
            and int(g.get("n_books") or 0) > 0
        )
        trusted = sum(1 for g in group if int(g.get("n_trusted") or 0) > 0)
        settled = sum(1 for g in group if g.get("settled_cover") or g.get("in_pnl"))
        rows.append([
            esc(window),
            str(len(group)),
            str(with_ticks),
            str(catalog_only),
            str(trusted),
            str(settled),
        ])
    if not rows:
        rows = [["none on this tape", "0", "0", "0", "0", "0"]]
    return rows


def sunday_game_rows(
    games: list[dict],
    pending_matches: list[dict],
    *,
    today: str = TODAY_ET,
    now: datetime | None = None,
    extra_books: list[dict] | None = None,
) -> list[list[str]]:
    now = now or datetime.now(ET)
    by_n: dict[str, dict] = {}
    for book in list(pending_matches) + list(extra_books or []):
        key = str(book.get("game_n") or "")
        if key and key not in by_n:
            by_n[key] = book
    rows = []
    ordered = sorted(
        sunday_games(games, today),
        key=lambda g: (
            _window_rank(kickoff_window_label(g.get("listed") or "", today) or "zz"),
            g.get("game") or "",
        ),
    )
    for g in ordered:
        listed = str(g.get("listed") or "")
        catalog_only = bool(
            g.get("catalog_only") or g.get("status") == "catalog only — no ticks"
        )
        has_ticks = (not catalog_only) and int(g.get("n_books") or 0) > 0
        book = by_n.get(str(g.get("game_n") or ""))
        view = yes_no_view(book) if book else {}
        miss = d_missed_1pm(listed, today)
        rows.append([
            esc(g.get("game") or ""),
            esc(kickoff_window_label(listed, today) or "—"),
            esc(listed),
            esc(play_state(
                listed,
                settled=bool(g.get("settled_cover") or g.get("in_pnl")),
                catalog_only=catalog_only,
                now=now,
            )),
            esc(g.get("status") or ""),
            "ticks" if has_ticks else ("catalog only" if catalog_only else "no ticks"),
            str(g.get("n_books") or 0),
            str(g.get("n_two_sided") or 0),
            str(g.get("n_trusted") or 0),
            "yes — D pid froze in REST hydration" if miss else "no",
            "yes" if g.get("in_pnl") else "no",
            "yes" if g.get("settled_cover") else "no",
            esc(view.get("team1") or "—"),
            _fmt_px(view.get("team1_yes")),
            esc(view.get("team2") or "—"),
            _fmt_px(view.get("team2_yes")),
            esc(view.get("market") or (book or {}).get("number") or "—"),
            _fmt_px(view.get("t0_yes")),
            _fmt_px(view.get("t0_no")),
            esc((book or {}).get("venue") or ""),
        ])
    if not rows:
        rows = [["—"] * len(SUNDAY_GAME_HEADERS)]
        rows[0][1] = "no Sunday Oct 25 games on this tape"
    return rows


def ticket_row(book: dict, trade: dict) -> list[str]:
    view = yes_no_view(book)
    return [
        esc(trade.get("game") or book.get("game") or ""),
        esc(view["team1"] or "—"),
        _fmt_px(view["team1_yes"]),
        esc(view["team2"] or "—"),
        _fmt_px(view["team2_yes"]),
        esc(view["market"]),
        _fmt_px(view["t0_yes"]),
        _fmt_px(view["t0_no"]),
        esc(view["no_src"] or "—"),
        _fmt_px(view["yes_no"]),
        esc(trade.get("venue") or book.get("venue") or ""),
        esc(trade.get("bucket") or ""),
        "yes" if in_d_band(trade.get("t0_fav")) else "no",
        "win" if trade.get("won") else "loss",
        format_money(trade.get("fee")),
        format_money(trade.get("pnl_d")),
        esc(trade.get("entry_date") or ""),
        esc(trade.get("t0_source") or book.get("t0_source") or ""),
        str(trade.get("n_lines") or book.get("_n_lines") or 1),
    ]


def _book_lookup(books: list[dict]) -> dict[tuple, dict]:
    out = {}
    for book in books:
        key = (
            str(book.get("game_n") or ""),
            str(book.get("number") or ""),
            str(book.get("venue") or ""),
            str(book.get("_side_letter") or ""),
        )
        out[key] = book
    return out


def ticket_rows(trades: list[dict], books: list[dict]) -> list[list[str]]:
    lookup = _book_lookup(books)
    rows = []
    for trade in sorted(
        trades,
        key=lambda t: (t.get("entry_date") or "", t.get("game") or "", t.get("number") or ""),
    ):
        key = (
            str(trade.get("game_n") or ""),
            str(trade.get("number") or ""),
            str(trade.get("venue") or ""),
            str(trade.get("_side_letter") or ""),
        )
        book = lookup.get(key) or {
            "fav_name": trade.get("fav_name"),
            "number": trade.get("number"),
            "t0_fav": trade.get("t0_fav"),
            "t0_a": trade.get("t0_a"),
            "t0_b": trade.get("t0_b"),
            "side_a": trade.get("side_a"),
            "side_b": trade.get("side_b"),
            "fav": trade.get("fav"),
            "game": trade.get("game"),
            "venue": trade.get("venue"),
        }
        rows.append(ticket_row(book, trade))
    if not rows:
        rows = [["—"] * len(TICKET_HEADERS)]
    return rows


def write_html(payload: dict) -> Path:
    match_recs = payload["match_recs"]
    line_recs = payload["line_recs"]
    bags = payload["bags"]
    meta = payload["meta"]
    games = payload["games"]
    d_q = match_recs[D_BAND_ID]
    all_q = match_recs[ALL_ID]
    line_all = line_recs[ALL_ID]
    primary_order = [label for label, *_ in BUCKETS] + [D_BAND_ID, ALL_ID]
    match_primary = [primary_row(match_recs[key]) for key in primary_order]
    line_primary = [primary_row(line_recs[key]) for key in primary_order]
    match_compare = [compare_row(match_recs[key], d_q if key != D_BAND_ID else None) for key in primary_order]
    line_compare = [compare_row(line_recs[key], line_recs[D_BAND_ID] if key != D_BAND_ID else None) for key in primary_order]
    match_trades = ticket_rows(all_q.get("trades") or [], payload.get("match_books") or [])
    line_trades = ticket_rows(line_all.get("trades") or [], payload.get("line_books") or [])
    t0_rows = [t0_price_row(b) for b in sorted(
        payload.get("trusted_lines") or [],
        key=lambda b: (str(b.get("game") or ""), str(b.get("number") or "")),
    )]
    if not t0_rows:
        t0_rows = [["—"] * len(T0_PRICE_HEADERS)]
    dates = bags.get("t0_dates") or []
    date_txt = ", ".join(dates) if dates else "none settled"
    n_all = int(all_q.get("n") or 0)
    n_d = int(d_q.get("n") or 0)
    n_lines = int(line_all.get("n") or 0)
    n_tracked = int(bags.get("n_tracked_games") or 0)
    n_skip = int(bags.get("n_skipped_games") or 0)
    today_games = sunday_games(games)
    n_today = len(today_games)
    n_today_ticks = sum(
        1 for g in today_games
        if not (g.get("catalog_only") or g.get("status") == "catalog only — no ticks")
        and int(g.get("n_books") or 0) > 0
    )
    n_today_catalog = sum(
        1 for g in today_games
        if g.get("catalog_only") or g.get("status") == "catalog only — no ticks"
    )
    n_today_trusted = sum(1 for g in today_games if int(g.get("n_trusted") or 0) > 0)
    n_today_1pm = sum(1 for g in today_games if d_missed_1pm(g.get("listed") or ""))
    n_today_1pm_ticks = sum(
        1 for g in today_games
        if d_missed_1pm(g.get("listed") or "")
        and not (g.get("catalog_only") or g.get("status") == "catalog only — no ticks")
        and int(g.get("n_books") or 0) > 0
    )
    today_match_trades = [
        t for t in (all_q.get("trades") or []) if str(t.get("entry_date") or "") == TODAY_ET
    ]
    today_line_trades = [
        t for t in (line_all.get("trades") or []) if str(t.get("entry_date") or "") == TODAY_ET
    ]
    today_match_n = len(today_match_trades)
    today_line_n = len(today_line_trades)
    today_match_pnl = sum(float(t.get("pnl_d") or 0) for t in today_match_trades)
    today_line_pnl = sum(float(t.get("pnl_d") or 0) for t in today_line_trades)
    match_win = payload.get("match_win") or {}
    line_win = payload.get("line_win") or {}
    sunday_match_win = payload.get("sunday_match_win") or {}
    sunday_line_win = payload.get("sunday_line_win") or {}
    n_win_match = int((match_win.get(ALL_ID) or {}).get("n") or 0)
    n_win_line = int((line_win.get(ALL_ID) or {}).get("n") or 0)
    n_sun_match = int((sunday_match_win.get(ALL_ID) or {}).get("n") or 0)
    n_sun_line = int((sunday_line_win.get(ALL_ID) or {}).get("n") or 0)
    n_today_settled = sum(1 for g in today_games if g.get("settled_cover") or g.get("in_pnl"))
    n_today_open = sum(
        1 for g in today_games
        if not (g.get("settled_cover") or g.get("in_pnl"))
        and not (g.get("catalog_only") or g.get("status") == "catalog only — no ticks")
    )
    today_pnl_txt = (
        f"Sunday unique-fav win% N={n_sun_match} (entered the bucket table); "
        f"all-lines Type A N={n_sun_line}. Sunday games settled={n_today_settled}, "
        f"still open={n_today_open}."
    )
    tiny = n_win_match < SMALL_N
    tiny_banner = (
        f"<strong>Win% is the table.</strong> Tracked NFL Type A games: {n_tracked}. "
        f"Unique-fav one-per-game settled N={n_win_match}. All wins-by-n lines N={n_win_line}. "
        f"Live D band unique-fav N={int((match_win.get(D_BAND_ID) or {}).get('n') or 0)}. "
        f"Sunday Oct 25: {n_today} games ({n_today_ticks} with ticks, {n_today_settled} settled, "
        f"{n_today_open} still open). {today_pnl_txt} Tiny N still does not wire D NFL."
        if tiny or n_win_match == 0 else
        f"Tracked NFL games {n_tracked}. Unique-fav N={n_win_match}. All-lines N={n_win_line}. "
        f"Sunday settled {n_today_settled}. Still research only. Did not turn D NFL on."
    )
    skip_bits = ", ".join(
        f"{k}={v}" for k, v in sorted((bags.get("skips") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    ) or "none"
    settle_meta = (meta.get("settle") or {}) if isinstance(meta.get("settle"), dict) else {}
    why_n4 = (
        "The 6:26pm rebuild listed 11 Sunday games but left the primary bucket table as "
        "Oct 18–19 settled unique-fav P&amp;L only (N=4, +$0.09) because Sunday was still "
        "OPEN on SETTLE_CACHE. That cache’s Kalshi date window stops at 26OCT21, so Oct 25 "
        "official results never entered even after afternoon games finalized in local "
        f"nfl_*_kalshi.json dumps. This rebuild loads those dumps plus a Kalshi pull "
        f"(cache={esc(settle_meta.get('n_cache'))} local={esc(settle_meta.get('n_local'))} "
        f"fetched={esc(settle_meta.get('n_fetched'))} merged={esc(settle_meta.get('n_merged'))}). "
        "Middles (both cover-Yes lose) now count as losses, not as “still open.” "
        "The old four-row $0.09 table is no longer the hero."
    )
    def _win_table(recs: dict) -> str:
        rows = [winpct_row(recs[key], display=key) for key in WINPCT_ORDER if key in recs]
        return html_table(WINPCT_HEADERS, rows)
    extra_sun = list(payload.get("match_books") or []) + list(payload.get("all_line_books") or [])
    band = payload.get("band_51_69") or {}
    all_days_51 = band.get("all_days") or {}
    sunday_51 = band.get("sunday") or {}
    split_50 = band.get("split_50_59") or {}
    split_60 = band.get("split_60_69") or {}
    old_comb = band.get("old_combined") or {}
    sun_50 = band.get("sunday_50_59") or {}
    sun_60 = band.get("sunday_60_69") or {}
    uf_51 = band.get("unique_fav") or {}
    uf_sun = band.get("unique_fav_sunday") or {}
    edges = band.get("edges") or {}
    n_51 = int(all_days_51.get("n") or 0)
    n_51_sun = int(sunday_51.get("n") or 0)
    pnl_51 = all_days_51.get("pnl_sum")
    pnl_51_sun = sunday_51.get("pnl_sum")
    wr_51 = all_days_51.get("win_pct")
    wr_51_sun = sunday_51.get("win_pct")
    n_fee_51 = int(all_days_51.get("n_fee") or 0)
    n_open_51 = int(all_days_51.get("n_open") or 0)
    n_void_51 = int(all_days_51.get("n_void") or 0)
    n_nofee_51 = int(all_days_51.get("n_no_fee") or 0)
    open_sum = band.get("open_summary") or summarize_open_band(
        list(all_days_51.get("open_books") or [])
    )
    live_names = ", ".join(open_sum.get("live_games") or []) or "none"
    open_txt = (
        f"{n_open_51} lines out of $. Still live: {live_names} "
        f"(N={int(open_sum.get('n_live') or 0)}). "
        f"Not kicked off yet: {int(open_sum.get('n_future') or 0)}. "
        f"Kickoff passed with no cover result on this line "
        f"(often Novig-only): {int(open_sum.get('n_missing') or 0)}."
    )
    band_rows_all = [
        band_primary_row(all_days_51),
        band_primary_row(split_50),
        band_primary_row(split_60),
        band_primary_row(old_comb),
        band_primary_row(uf_51),
    ]
    band_rows_sun = [
        band_primary_row(sunday_51),
        band_primary_row(sun_50),
        band_primary_row(sun_60),
        band_primary_row(uf_sun),
    ]
    band_tickets = ticket_rows(
        all_days_51.get("trades") or [],
        all_days_51.get("books") or [],
    )
    sun_tickets = ticket_rows(
        sunday_51.get("trades") or [],
        sunday_51.get("books") or [],
    )
    open_band_rows = band_open_rows(
        list(all_days_51.get("open_books") or []),
        list(all_days_51.get("no_fee_books") or []),
    )
    hero_51 = (
        f"All-days all-lines Type A T0 Yes 0.51–0.69: N={n_51}, "
        f"wins={int(all_days_51.get('n_win') or 0)}, "
        f"win%={fmt_pct(wr_51) if n_51 else '—'}, "
        f"with-fee PnL {format_money(pnl_51) if n_fee_51 else '—'} "
        f"(N_fee={n_fee_51}, mean {format_money(all_days_51.get('mean')) if n_fee_51 else '—'}, "
        f"fees {format_money(all_days_51.get('total_fees')) if n_fee_51 else '—'}, "
        f"voids={n_void_51}). Sunday-only: N={n_51_sun}, "
        f"win%={fmt_pct(wr_51_sun) if n_51_sun else '—'}, "
        f"with-fee {format_money(pnl_51_sun) if int(sunday_51.get('n_fee') or 0) else '—'}. "
        f"{esc(open_txt)} "
        f"Settled fee holes N={n_nofee_51} (Novig omitted from $, not treated as free). "
        f"Did not wire D NFL."
    )
    edge_txt = (
        f"Exact T0=0.50 on the all-lines tape: {int(edges.get('n_exact_50') or 0)} "
        f"(dropped from 51–69). Prices in (0.50, 0.51): "
        f"{int(edges.get('n_between_50_51') or 0)}. Prices in (0.69, 0.70) that sit "
        f"in old 60-69 but not 51–69: {int(edges.get('n_between_69_70') or 0)}. "
        f"Old 50-59+60-69 combined N={int(old_comb.get('n') or 0)} vs 51–69 N={n_51}."
    )
    decile = payload.get("every_decile") or {}
    d_all = decile.get("all_days") or {}
    d_sun = decile.get("sunday") or {}
    d_all_no = decile.get("all_days_no") or {}
    d_sun_no = decile.get("sunday_no") or {}
    d_uf = decile.get("unique_fav") or {}
    d_uf_sun = decile.get("unique_fav_sunday") or {}
    rec10 = d_all.get("10-19") or {}
    rec20 = d_all.get("20-29") or {}
    rec30 = d_all.get("30-39") or {}
    rec1029 = d_all.get("10-29") or {}
    rec2039 = d_all.get("20-39") or {}
    rec20s = d_sun.get("20-29") or {}
    rec30s = d_sun.get("30-39") or {}
    rec2039s = d_sun.get("20-39") or {}
    rec10n = d_all_no.get("10-19") or {}
    rec20n = d_all_no.get("20-29") or {}
    rec1029n = d_all_no.get("10-29") or {}
    rec2039n = d_all_no.get("20-39") or {}
    rec10ns = d_sun_no.get("10-19") or {}
    rec20ns = d_sun_no.get("20-29") or {}
    rec1029ns = d_sun_no.get("10-29") or {}
    rec2039ns = d_sun_no.get("20-39") or {}
    verdict_all = decile_verdict(rec2039)
    verdict_sun = decile_verdict(rec2039s)
    verdict_10_29_no = decile_verdict(rec1029n)
    verdict_10_19_no = decile_verdict(rec10n)
    verdict_20_29_no = decile_verdict(rec20n)
    verdict_10_29_no_sun = decile_verdict(rec1029ns)
    decile_rows_all = decile_hero_rows(d_all)
    decile_rows_sun = decile_hero_rows(d_sun)
    decile_rows_all_no = decile_hero_rows(d_all_no)
    decile_rows_sun_no = decile_hero_rows(d_sun_no)
    uf_rows_all = decile_hero_rows(d_uf)
    uf_rows_sun = decile_hero_rows(d_uf_sun)
    tickets_2039 = ticket_rows(rec2039.get("trades") or [], rec2039.get("books") or [])
    tickets_2039_sun = ticket_rows(rec2039s.get("trades") or [], rec2039s.get("books") or [])
    open_2039_rows = band_open_rows(
        list(rec2039.get("open_books") or []),
        list(rec2039.get("no_fee_books") or []),
    )
    open_all_rec = d_all.get("all") or {}
    open_all_sum = summarize_open_band(list(open_all_rec.get("open_books") or []))
    live_all = ", ".join(open_all_sum.get("live_games") or []) or "none"
    open_all_txt = (
        f"All-decile open out of $: {int(open_all_rec.get('n_open') or 0)} sides. "
        f"Still live: {live_all} (N={int(open_all_sum.get('n_live') or 0)}). "
        f"Not kicked off yet: {int(open_all_sum.get('n_future') or 0)}. "
        f"Kickoff passed with no cover result: {int(open_all_sum.get('n_missing') or 0)}. "
        f"20-39 open N={int(rec2039.get('n_open') or 0)}. "
        f"Settled 20-39 fee holes N={int(rec2039.get('n_no_fee') or 0)} "
        f"(Novig omitted from $, not treated as free)."
    )
    def _px_line(rec: dict) -> str:
        n = int(rec.get("n") or 0)
        n_fee = int(rec.get("n_fee") or 0)
        return (
            f"N={n}, wins={int(rec.get('n_win') or 0)}, "
            f"win%={fmt_pct(rec.get('win_pct')) if n else '—'}, "
            f"with-fee {format_money(rec.get('pnl_sum')) if n_fee else '—'} "
            f"(N_fee={n_fee}, mean {format_money(rec.get('mean')) if n_fee else '—'}, "
            f"fees {format_money(rec.get('total_fees')) if n_fee else '—'}, "
            f"voids={int(rec.get('n_void') or 0)})"
        )
    def _no_line(rec: dict) -> str:
        n = int(rec.get("n") or 0)
        n_fee = int(rec.get("n_fee") or 0)
        return (
            f"N={n}, No wins={int(rec.get('n_win') or 0)}, "
            f"No win%={fmt_pct(rec.get('win_pct')) if n else '—'}, "
            f"with-fee {format_money(rec.get('pnl_sum')) if n_fee else '—'} "
            f"(N_fee={n_fee}, mean {format_money(rec.get('mean')) if n_fee else '—'}, "
            f"fees {format_money(rec.get('total_fees')) if n_fee else '—'}, "
            f"voids={int(rec.get('n_void') or 0)})"
        )
    tickets_1029_no = ticket_rows(
        rec1029n.get("trades") or [], rec1029n.get("books") or []
    )
    tickets_1029_no_sun = ticket_rows(
        rec1029ns.get("trades") or [], rec1029ns.get("books") or []
    )
    hero_no = (
        f"Buy No 10-19 all-days: {_no_line(rec10n)}. {verdict_10_19_no} "
        f"Buy No 20-29: {_no_line(rec20n)}. {verdict_20_29_no} "
        f"Buy No 10-29 combined: {_no_line(rec1029n)}. {verdict_10_29_no} "
        f"Sunday Buy No 10-29: {_no_line(rec1029ns)}. {verdict_10_29_no_sun} "
        f"Same rows as Yes (N match is "
        f"{'yes' if decile.get('same_rows_yes_no') else 'NO'}). "
        f"Yes+$ and No+$ are not exact negatives — each ticket pays its own "
        f"taker fee. {esc(open_all_txt)} Did not wire D NFL."
    )
    hero_decile = (
        f"20-39 combined all-days: {_px_line(rec2039)}. {verdict_all} "
        f"20-29: {_px_line(rec20)}. 30-39: {_px_line(rec30)}. "
        f"10-29 Yes: {_px_line(rec1029)}. "
        f"Sunday 20-39: {_px_line(rec2039s)}. {verdict_sun} "
        f"{esc(open_all_txt)} Did not wire D NFL."
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>NFL Type A T0 Yes + Buy No every decile — all tracked</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>NFL Type A T0 Yes and Buy No every decile — all tracked games</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. Live D is
<strong>on except NFL</strong> (<code>d_skip_nfl_gathering</code>). Did not turn D NFL
on. Did not send. Did not sell. Did not start a second
<code>live_strategy_b.py</code>. Did not write <code>sports_queue</code>.
Did not read <code>orders.jsonl</code>. Did not overwrite
<code>spread_two_yes_not_a_lock</code>. Did not bump stake.</p>
<p class="banner">{hero_no}</p>
<p class="banner">{hero_decile}</p>
<p class="banner">{tiny_banner}</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED_BUY_NO)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN_BUY_NO)}</p>
</div>

<h2>Buy No — every T0 Yes decile (all days)</h2>
<p class="note">Hero table. Same National Football League (NFL) Type A
wins-by-n tape as the Yes table below: every cover we watched at first trusted
kickoff (T0), including dogs we did not bet, settled only, 1 contract. For each
row we buy <strong>No</strong> on that same cover. T0 No cash = 1 − T0 Yes
(Kalshi house No / Polymarket BUY_SHORT; Gemini on this tape is the same
1 − Yes). Documented taker fee on the No cash. Novig omitted from dollars when
the fee is unknown — not treated as free. A 10–19 Yes (win% often under 5) is a
80–90¢ No. <strong>{esc(DECILE_10_29_ID)}</strong> sits under 20-29;
<strong>{esc(DECILE_20_39_ID)}</strong> sits under 30-39. Yes+$ and No+$ are the
flip of the same rows; fees make them not exact negatives of each other. Open
games stay out of dollars. Click column headers to sort. Swipe sideways to see
more columns.</p>
<p class="note">Buy No 10-19: {_no_line(rec10n)}. {esc(verdict_10_19_no)}
Buy No 20-29: {_no_line(rec20n)}. {esc(verdict_20_29_no)}
Buy No 10-29 combined: {_no_line(rec1029n)}. {esc(verdict_10_29_no)}
Buy No 20-39: {_no_line(rec2039n)}. Same-row N as Yes is
{"yes" if decile.get("same_rows_yes_no") else "NO — check explode/pick"}.
10-19 N + 20-29 N = 10-29 N is
{"yes" if decile.get("adds_10_29") else "NO"}.</p>
{html_table(NO_DECILE_HEADERS, decile_rows_all_no, total=True)}

<h2>Buy No — Sunday Oct 25 only</h2>
<p class="note">Same Buy No grain, Sunday kickoffs only. Kansas City–Seattle
is in the dollars if that cover has a result; still-open stays out.</p>
<p class="note">Sunday Buy No 10-19: {_no_line(rec10ns)}. 20-29:
{_no_line(rec20ns)}. 10-29 combined: {_no_line(rec1029ns)}.
{esc(verdict_10_29_no_sun)} 20-39: {_no_line(rec2039ns)}.</p>
{html_table(NO_DECILE_HEADERS, decile_rows_sun_no, total=True)}

<h2>Buy No 10-29 tickets (all days, with-fee)</h2>
<p class="note">One row per settled all-lines Type A cover whose T0 Yes sat in
[0.10, 0.30). PnL is the No ticket. N_fee={esc(int(rec1029n.get("n_fee") or 0))}.
Won = No won (Yes lost). Click column headers to sort.</p>
{html_table(TICKET_HEADERS, tickets_1029_no)}

<h2>Buy No 10-29 tickets (Sunday only, with-fee)</h2>
<p class="note">Sunday subset of the 10-29 No table.
N_fee={esc(int(rec1029ns.get("n_fee") or 0))}.</p>
{html_table(TICKET_HEADERS, tickets_1029_no_sun)}

<div class="callout">
<h2>What you asked (earlier — every Yes decile)</h2>
<p>{esc(ASKED_DECILE)}</p>
</div>
<div class="callout">
<h2>In plain English (every Yes decile)</h2>
<p>{esc(PLAIN_DECILE)}</p>
</div>

<h2>Every T0 Yes decile — all-lines Type A cover-Yes (all days)</h2>
<p class="note">Hero table. Every National Football League (NFL) Type A
wins-by-n cover-Yes we watched at first trusted kickoff, including dogs we did
not bet. One venue per game+line+side (documented-fee venue preferred). Size 1
contract at the T0 ask + documented taker fee. Intervals are half-open
<code>[0.20, 0.30)</code> etc; 90-100 is <code>[0.90, 1.00]</code> / 90+.
<strong>{esc(DECILE_10_29_ID)}</strong> sits under 20-29.
<strong>{esc(DECILE_20_39_ID)}</strong> sits under 30-39 so
the split is visible. Open games (Kansas City–Seattle if still live) are out of
the dollars. Totals / team totals are out. Unique-fav one-per-game is a labeled
secondary below — do not add it to this bankroll. Click column headers to sort.
Swipe sideways to see more columns.</p>
<p class="note">10-19 all-days: {_px_line(rec10)}. 20-29: {_px_line(rec20)}.
10-29 combined: {_px_line(rec1029)}. 30-39: {_px_line(rec30)}.
20-39 combined: {_px_line(rec2039)}. {esc(verdict_all)} Decades add:
20-29 N + 30-39 N = 20-39 N is
{"yes" if decile.get("adds_20_39") else "NO — check explode/pick"};
10-19 N + 20-29 N = 10-29 N is
{"yes" if decile.get("adds_10_29") else "NO"}.</p>
{html_table(DECILE_HEADERS, decile_rows_all, total=True)}

<h2>Every T0 Yes decile — Sunday Oct 25 only</h2>
<p class="note">Same all-lines Type A cover-Yes grain, Sunday kickoffs only.
Kansas City–Seattle is out if still open.</p>
<p class="note">Sunday 20-29: {_px_line(rec20s)}. 30-39: {_px_line(rec30s)}.
20-39 combined: {_px_line(rec2039s)}. {esc(verdict_sun)}</p>
{html_table(DECILE_HEADERS, decile_rows_sun, total=True)}

<h2>Unique-fav one-per-game (secondary) — every decile, all days</h2>
<p class="note">Live D analog: one unique favorite cover-Yes per game, closest
to 50¢, Yes &gt; 50¢. Empty below 50¢ by construction. Do not add this to the
all-lines hero bankroll.</p>
{html_table(DECILE_HEADERS, uf_rows_all, total=True)}

<h2>Unique-fav one-per-game (secondary) — Sunday only</h2>
<p class="note">Same unique-fav grain, Sunday kickoffs only. Empty below 50¢
by construction.</p>
{html_table(DECILE_HEADERS, uf_rows_sun, total=True)}

<h2>20-39 lines still open or missing a documented fee</h2>
<p class="note">These 20-39 rows are not in the with-fee dollar total. Win%
includes no-fee settled lines and excludes still-open lines. {esc(open_all_txt)}</p>
{html_table(BAND_OPEN_HEADERS, open_2039_rows)}

<h2>20-39 tickets (all days, with-fee)</h2>
<p class="note">One row per settled all-lines Type A cover-Yes in [0.20, 0.40)
with a documented fee. N_fee={esc(int(rec2039.get("n_fee") or 0))}. Click
column headers to sort.</p>
{html_table(TICKET_HEADERS, tickets_2039)}

<h2>20-39 tickets (Sunday only, with-fee)</h2>
<p class="note">Sunday subset of the 20-39 table. N_fee={esc(int(rec2039s.get("n_fee") or 0))}.</p>
{html_table(TICKET_HEADERS, tickets_2039_sun)}

<div class="callout">
<h2>What you asked (earlier — 51–69)</h2>
<p>{esc(ASKED_51_69)}</p>
</div>
<div class="callout">
<h2>In plain English (51–69)</h2>
<p>{esc(PLAIN_51_69)}</p>
</div>

<h2>Prior ask — any Type A spread T0 Yes 0.51–0.69 (favorite grain)</h2>
<p class="note">Kept as a labeled secondary. This grain is the favorite / only
T0 Yes in [0.51, 0.69] inclusive — not the exploded dog+fav cover-Yes tape
above. Unique-fav one-per-game is also secondary. Click column headers to sort.</p>
<p class="note">{esc(edge_txt)}</p>
<p class="banner">{hero_51}</p>
{html_table(BAND_51_69_HEADERS, band_rows_all)}

<h2>Sunday Oct 25 only — same 51–69 hypothetical</h2>
<p class="note">Same favorite-grain 51–69, Sunday kickoffs only. Kansas
City–Seattle is out if still open.</p>
{html_table(BAND_51_69_HEADERS, band_rows_sun)}

<h2>51–69 lines still open or missing a documented fee</h2>
<p class="note">These rows are not in the 51–69 with-fee dollar total. Win% includes
no-fee settled lines and excludes still-open lines.</p>
{html_table(BAND_OPEN_HEADERS, open_band_rows)}

<h2>51–69 tickets (all days, with-fee)</h2>
<p class="note">One row per settled all-lines Type A contract in 0.51–0.69 with
a documented fee. N_fee={esc(n_fee_51)}. Click column headers to sort.</p>
{html_table(TICKET_HEADERS, band_tickets)}

<h2>51–69 tickets (Sunday only, with-fee)</h2>
<p class="note">Sunday subset of the table above. N_fee={esc(int(sunday_51.get("n_fee") or 0))}.</p>
{html_table(TICKET_HEADERS, sun_tickets)}

<div class="callout">
<h2>What you asked (earlier — bucket win% tape)</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English (bucket tape)</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Paul note</h2>
<p><strong>HOLD</strong> live D NFL. Buy No 10-29 all-days: {esc(verdict_10_29_no)}
Buy No 10-19: {esc(verdict_10_19_no)} Buy No 20-29: {esc(verdict_20_29_no)}
20-39 Yes all-days: {esc(verdict_all)} Sunday 20-39 Yes: {esc(verdict_sun)} {why_n4}
IS N=0 — every T0 on this tape is 2026 (after 2024-01-01). Annualized rate of return
(Ann ROR) omitted on same-day holds. Tiny N does not wire D NFL.</p>

<h2>Type A win% by T0 bucket — unique-fav, one line per game (all days)</h2>
<p class="note">Type A = traditional spread: team A wins by N or team B wins by N
(cover). One line per game: the unique cover-Yes closer to 50¢ (live D pick analog).
Winner = that cover-Yes settled YES. Click column headers to sort. N={esc(n_win_match)}.
Live D band N={esc(int((match_win.get(D_BAND_ID) or {}).get("n") or 0))}. Dollars use
documented fees on a 1-contract T0 ask when the fee is known; win% does not need fees.
Do not mix this table with all-lines.</p>
{_win_table(match_win)}

<h2>Type A win% by T0 bucket — unique-fav, Sunday Oct 25 only</h2>
<p class="note">Same unique-fav grain, Sunday kickoffs only. Open games are not in
this win%. N={esc(n_sun_match)}.</p>
{_win_table(sunday_match_win)}

<h2>Type A win% by T0 bucket — all wins-by-n lines (all days)</h2>
<p class="note">Every Type A line we have a T0 Yes for (one venue per game+line).
Not the same as one-per-game. Do not add this N to the unique-fav bankroll.
N={esc(n_win_line)}.</p>
{_win_table(line_win)}

<h2>Type A win% by T0 bucket — all wins-by-n lines, Sunday only</h2>
<p class="note">Sunday Oct 25 all-lines grain. N={esc(n_sun_line)}.</p>
{_win_table(sunday_line_win)}

<h2>Glossary — T0 Yes A / T0 Yes B</h2>
<p class="note">{esc(YES_AB_GLOSSARY)}</p>
<p class="note">The lock-shaped pair is <strong>Yes LA wins by &gt;1.5</strong> plus
<strong>No LA wins by &gt;1.5</strong> on the same settlement. Adding 0.41 + 0.50 = 0.91 is not a 0.91 lock. The lock bot does not send both Yeses as a lock. Pair key is
(kind, side, number): Yes on one venue + No on the other for the same team
covering the same line. Indiana/Michigan-style same-line two-Yes is not a
lock candidate.</p>

<h2>Freeze</h2>
<ul>
<li><strong>Universe:</strong> every pro football / NFL series in local
<code>price_memory</code> and catalog (<code>sports_queue.json</code> +
<code>pro_football_results.jsonl</code>) that has a spread book. Totals and
moneyline are out. College football is out. Fills are out.</li>
<li><strong>T0:</strong> first trusted kickoff — Kalshi/Gemini occurrence, else
listed/feed with seconds=00. Same helper as <code>t0_all_games_stats.py</code>.
Not tape-resume. Not first-competitive-without-a-clock.</li>
<li><strong>Favorite:</strong> higher T0 Yes ask, unique, Yes ask &gt; 0.50. Skip 50-50
from P&amp;L; keep them on the skip / T0-price tables.</li>
<li><strong>Grain 1 (match):</strong> one line per game, closest T0 favorite Yes to 50¢
among two-sided unique-fav lines (live D).</li>
<li><strong>Grain 2 (line):</strong> all two-sided unique-fav spread lines (one venue
per line: cheapest documented-fee Yes, then Kalshi &gt; Gemini &gt; Polymarket &gt; Novig).
First-class table, not a footnote.</li>
<li><strong>Trade:</strong> buy 1 Yes on the spread favorite at the T0 ask, taker,
documented fees in, hold to official settlement. Win: $1 − ask − fee. Loss: −ask − fee.</li>
<li><strong>Fees:</strong> Kalshi 0.07×p×(1−p) to $0.0001; Gemini same formula rounded
up to a cent; Polymarket 0.0695×p×(1−p) banker's cent. Novig omitted (no documented
coefficient — not treated as zero-fee).</li>
<li><strong>Buckets:</strong> living-dashboard decades. &gt;90 is strictly above 90¢.
0.90 sits in 80-89 and is <em>not</em> in live D (D is exclusive of 0.50 and 0.90).</li>
<li><strong>Pending / skips:</strong> listed, not in P&amp;L. No silent drop to 4.</li>
<li><strong>Yes vs No:</strong> Cover Yes team 1 / Cover Yes team 2 are the two
teams’ cover-Yes asks, sorted by name (the old unlabeled A/B). T0 fav Yes /
T0 fav No is the lock-shaped pair on the favorite’s contract (live No ask,
else 1 − Yes). Fav Yes+No is that pair. Do not add the two cover-Yeses as a lock.</li>
<li><strong>Live D:</strong> NFL / pro football skipped (<code>d_skip_nfl_gathering</code>).
systems.json D stays on. CFB unchanged. This page still scores the NFL tape.
Did not turn D NFL on.</li>
<li><strong>Sunday Oct 25 first set:</strong> listed kickoff date {esc(TODAY_ET)}
in ET. First window ~1pm ET; later Sunday windows stay on this table if they
are already on the tape. Monday and later catalog games stay in the all-tracked
tables, not this first-set block.</li>
<li><strong>Every-decile hypothetical:</strong> explode each Type A line into
cover-Yes sides (dog and favorite). T0 Yes decades are half-open
<code>[0.00, 0.10)</code> … <code>[0.80, 0.90)</code>; 90-100 is
<code>[0.90, 1.00]</code> / 90+. 20-39 is <code>[0.20, 0.40)</code> =
20-29 + 30-39. Exact 0.50 sits in 50-59 under this convention. All-lines
Type A only. Unique-fav one-per-game is secondary (empty below 50¢).
Did not wire D NFL from any decade.</li>
<li><strong>51–69 hypothetical (prior ask):</strong> favorite / only T0 Yes in
[0.51, 0.69] inclusive. Exact 0.50 is out. Old 50-59 is &gt;0.50 and &lt;0.60;
old 60-69 is ≥0.60 and &lt;0.70. Not the exploded dog tape. Did not wire D NFL
from this band.</li>
</ul>

<h2>Sunday Oct 25 first set (1pm ET + later kickoffs on the tape)</h2>
<p class="note">National Football League (NFL) games listed Sunday {esc(TODAY_ET)}
ET. First window is ~1pm ET. Later windows (4:05pm, 4:25pm, 8:20pm) are included
when already on the tape. Includes games we tracked but did not bet. Click
column headers to sort. Open games stay out of win%.</p>
<p class="banner">Sunday first set: <strong>{esc(n_today)}</strong> games,
<strong>{esc(n_today_ticks)}</strong> with ticks,
<strong>{esc(n_today_settled)}</strong> settled into buckets,
<strong>{esc(n_today_open)}</strong> still open,
<strong>{esc(n_today_catalog)}</strong> catalog-only,
<strong>{esc(n_today_trusted)}</strong> with a trusted T0 quote.
1pm ET window: {esc(n_today_1pm)} games, {esc(n_today_1pm_ticks)} with ticks
after the miss. {today_pnl_txt} Live D missed the 1pm window earlier today
because pid froze in REST hydration. Live D still skips NFL. Did not turn D
NFL on. Did not send.</p>
{html_table(SUNDAY_WINDOW_HEADERS, sunday_window_rows(games))}
{html_table(SUNDAY_GAME_HEADERS, sunday_game_rows(games, payload.get("pending_matches") or [], extra_books=extra_sun))}

<h2>Tracked NFL games vs settled vs skipped</h2>
<p class="note">One row per unique NFL game that has a spread book on the tape or
catalog. Click column headers to sort. Settled unique-fav games are the P&amp;L
denominator for grain 1. Everything else stays here.</p>
{html_table(STATUS_COUNT_HEADERS, skip_count_rows(bags.get("status_counts") or {{}}))}
{html_table(SKIP_HEADERS, game_rows(games))}

<h2>Pending games (not in P&amp;L)</h2>
<p class="note">Today’s / future catalog slate and tape games without an official
settlement. Listed only. Caption: A/B are two teams’ cover-Yes, not Yes+No.</p>
{html_table(PENDING_HEADERS, pending_rows(games, payload.get("pending_matches") or []))}

<h2>With-fee $ (secondary) — unique-fav one-per-game</h2>
<p class="note">Same unique-fav grain as the win% table, dollars only when the
fee is documented. Not the hero. N={esc(n_all)}. Live D band N={esc(n_d)}.</p>
{html_table(PRIMARY_HEADERS, match_primary)}

<h2>With-fee $ (secondary) — unique-fav all-lines</h2>
<p class="note">Do not add this row to the one-per-game bankroll. N={esc(n_lines)}.</p>
{html_table(PRIMARY_HEADERS, line_primary)}

<h2>Canonical compare — one-per-game buckets vs live D band</h2>
<p class="note">Control is the live D band on the same one-line-per-game NFL book.
Deltas vs that row. Ann ROR omitted when the hold is same-day. IS N=0. Do not
KEEP from this ranking — selection bias, tiny N.</p>
{html_table(COMPARE_HEADERS, match_compare)}

<h2>Canonical compare — all-lines buckets vs all-lines D band</h2>
<p class="note">Control is favorite Yes in (0.50, 0.90) on the all-lines grain.
Do not mix with the one-per-game bankroll.</p>
{html_table(COMPARE_HEADERS, line_compare)}

<h2>T0 spread prices — every trusted two-sided line</h2>
<div class="callout">
<h2>What T0 Yes A / T0 Yes B meant</h2>
<p>{esc(YES_AB_GLOSSARY)}</p>
<p>Headers on this table are <strong>Cover Yes team 1</strong> / <strong>Cover Yes
team 2</strong> (with a name column for each) plus <strong>T0 fav Yes</strong> /
<strong>T0 fav No</strong>. A/B are two teams’ cover-Yes, not Yes+No.</p>
</div>
<p class="note">One venue per (game, line). Includes 50-50 and pending. This is
the T0 price tape, not fills. Book-level skip mix: {esc(skip_bits)}. Click
column headers to sort. Caption: A/B are two teams’ cover-Yes, not Yes+No.
Cover Yes team 1 / Cover Yes team 2 are those two Yes asks, sorted by team name,
at first trusted kickoff. T0 fav Yes / T0 fav No is the lock-shaped pair on the
favorite’s contract (live No ask or 1 − Yes).</p>
{html_table(T0_PRICE_HEADERS, t0_rows)}

<h2>One-per-game tickets (P&amp;L)</h2>
<p class="note">Settled unique-fav NFL spreads under the all-unique-fav rule.
Simulated buy is still one Yes. Cover Yes team 1 / team 2 are the two teams’
cover-Yes, not Yes+No. Fav Yes+No is the same-contract pair. Live D would have
taken only In D band = yes (and live D now skips NFL). Click column headers to
sort.</p>
{html_table(TICKET_HEADERS, match_trades)}

<h2>All-lines tickets (P&amp;L)</h2>
<p class="note">Every settled unique-fav two-sided line. Same fees. Not additive
with the one-per-game table.</p>
{html_table(TICKET_HEADERS, line_trades)}

<h2>Inventory</h2>
<ul>
<li>Tracked NFL games with a spread book: <strong>{esc(n_tracked)}</strong>
(tape ∪ catalog). Catalog spread games: {esc(bags.get("n_catalog"))}.</li>
<li>Unique-fav win% N={esc(n_win_match)} (Sunday {esc(n_sun_match)}). All-lines
Type A win% N={esc(n_win_line)} (Sunday {esc(n_sun_line)}). Live D band unique-fav:
{esc(int((match_win.get(D_BAND_ID) or {}).get("n") or 0))}.</li>
<li>With-fee unique-fav one-per-game N={esc(n_all)}. All-lines unique-fav $ N=
{esc(n_lines)}.</li>
<li>Venue-game books paired: {esc(bags.get("n_raw_books"))}. Trusted two-sided
venue-books: {esc(bags.get("n_trusted"))}. After one venue per line:
{esc(bags.get("n_trusted_lines"))}.</li>
<li>Pending games: {esc(bags.get("n_pending_games"))}. 50-50 venue-books:
{esc(bags.get("n_fifty"))}. No documented fee: {esc(bags.get("n_no_fee"))}.
No post-T0 path books: {esc(bags.get("n_no_post"))}.</li>
<li>Settled T0 dates: {esc(date_txt)}.</li>
<li>Sunday Oct 25 first set: {esc(n_today)} games, {esc(n_today_ticks)} with
ticks, {esc(n_today_catalog)} catalog-only. Sunday unique-fav one-per-game N=
{esc(today_match_n)}; all-lines N={esc(today_line_n)}.</li>
<li>Tape Yes ticks: {esc(meta.get("seen_min") or "—")} through
{esc(meta.get("seen_max") or "—")}. Streamed {esc(meta.get("n_lines"))}
pro-football lines, {esc(meta.get("n_yes"))} spread Yes ticks.</li>
</ul>

<p class="tiny">Generator: <code>tools/nfl_t0_spread_buckets_all_tracked_20261025.py</code>.
Tick scan: <code>nfl_t0_spread_buckets_20261025.stream_nfl_spread_sides</code>
(no orders.jsonl). T0 / settlement: <code>tools/t0_all_games_stats.py</code>.
Fees: <code>write_t0_band_from_stay_above.documented_leg_fee</code>. Tests:
<code>tools/test_nfl_t0_spread_buckets_all_tracked_20261025.py</code>.
Written {esc(payload.get("written_at"))} ET. file:// {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PARENT.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def main() -> int:
    fetch = "--no-fetch" not in sys.argv
    print("scoring ALL tracked NFL T0 spreads (tape + catalog, not fills)", flush=True)
    payload = build_payload(fetch=fetch)
    path = write_html(payload)
    bags = payload["bags"]
    all_q = payload["match_recs"][ALL_ID]
    line_q = payload["line_recs"][ALL_ID]
    d_q = payload["match_recs"][D_BAND_ID]
    mw = payload.get("match_win") or {}
    lw = payload.get("line_win") or {}
    sm = payload.get("sunday_match_win") or {}
    sl = payload.get("sunday_line_win") or {}
    band = payload.get("band_51_69") or {}
    a51 = band.get("all_days") or {}
    s51 = band.get("sunday") or {}
    print(
        f"tracked_games={bags['n_tracked_games']} unique_fav_winN={mw.get(ALL_ID, {}).get('n')} "
        f"win%={mw.get(ALL_ID, {}).get('win_pct')} sunday_unique={sm.get(ALL_ID, {}).get('n')} "
        f"all_lines_winN={lw.get(ALL_ID, {}).get('n')} sunday_lines={sl.get(ALL_ID, {}).get('n')} "
        f"fee_match={all_q['n']} pnl={all_q['pnl_sum']:.4f} D-band={d_q['n']} wrote {path}",
        flush=True,
    )
    print(
        f"51-69 all-lines N={a51.get('n')} wins={a51.get('n_win')} win%={a51.get('win_pct')} "
        f"with_fee={a51.get('pnl_sum')} n_fee={a51.get('n_fee')} mean={a51.get('mean')} "
        f"fees={a51.get('total_fees')} voids={a51.get('n_void')} open={a51.get('n_open')} "
        f"sunday N={s51.get('n')} with_fee={s51.get('pnl_sum')}",
        flush=True,
    )
    dec = payload.get("every_decile") or {}
    d_all = dec.get("all_days") or {}
    d_sun = dec.get("sunday") or {}
    d_no = dec.get("all_days_no") or {}
    d_no_sun = dec.get("sunday_no") or {}
    r20 = d_all.get("20-29") or {}
    r30 = d_all.get("30-39") or {}
    r39 = d_all.get("20-39") or {}
    s39 = d_sun.get("20-39") or {}
    n10 = d_no.get("10-19") or {}
    n20 = d_no.get("20-29") or {}
    n1029 = d_no.get("10-29") or {}
    n39 = d_no.get("20-39") or {}
    ns1029 = d_no_sun.get("10-29") or {}
    print(
        f"20-29 N={r20.get('n')} win%={r20.get('win_pct')} $={r20.get('pnl_sum')} "
        f"30-39 N={r30.get('n')} win%={r30.get('win_pct')} $={r30.get('pnl_sum')} "
        f"20-39 N={r39.get('n')} win%={r39.get('win_pct')} $={r39.get('pnl_sum')} "
        f"n_fee={r39.get('n_fee')} sunday N={s39.get('n')} $={s39.get('pnl_sum')} "
        f"adds={dec.get('adds_20_39')}",
        flush=True,
    )
    print(
        f"BuyNo 10-19 N={n10.get('n')} NoWin%={n10.get('win_pct')} $={n10.get('pnl_sum')} "
        f"20-29 N={n20.get('n')} NoWin%={n20.get('win_pct')} $={n20.get('pnl_sum')} "
        f"10-29 N={n1029.get('n')} NoWin%={n1029.get('win_pct')} $={n1029.get('pnl_sum')} "
        f"n_fee={n1029.get('n_fee')} 20-39 No $={n39.get('pnl_sum')} "
        f"sunday 10-29 No $={ns1029.get('pnl_sum')} "
        f"same_rows={dec.get('same_rows_yes_no')} adds_10_29={dec.get('adds_10_29')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
