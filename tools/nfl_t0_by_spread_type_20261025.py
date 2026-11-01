"""NFL T0 buckets split by market type — tape + catalog, not fills.

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not start a second live_strategy_b.py. Does not sell. Does not change live D.
Does not write the sibling all-tracked spread page. Does not read orders.jsonl /
FILLED / system=spread_t0. Not gold. Not DailyRun.

Types: spread (team wins by n), total (combined points), team total (one team
scores over n). One closest-to-50¢ unique-fav line per game within each type.
Live D still sends traditional spread only; leftover max slots go to the next
game. HOLD that live band.
"""
from __future__ import annotations

import html as html_mod
import json
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
from odds_cross_winrate_20261020 import as_float, build_index, game_norm
from prediction_paths import RAW_DIR as RAW
from price_memory import iter_tick_lines, load_last, market_type_from
import t0_all_games_stats as t0
from t0_fav_lt90_baseline_20261024 import html_table
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
    in_d_band,
    is_nfl,
    is_unique_fav,
    pick_one_per_game,
    primary_row,
    sample_note,
    score_arm,
    trusted_two_sided,
    void_count,
)
from nfl_t0_spread_buckets_all_tracked_20261025 import (
    TODAY_ET,
    d_missed_1pm,
    is_today_slate,
    kickoff_window_label,
)
from nfl_t0_type_a_collect import (
    WINPCT_HEADERS,
    WINPCT_ORDER,
    bucket_winpct,
    build_nfl_cover_index,
    cover_yes_known,
    is_sunday_book,
    load_nfl_settlements,
    occ_map_prefer_listed,
    overlay_cover_settlement,
    winpct_row,
)

ET = ZoneInfo("America/New_York")
PARENT = (
    ROOT / "drive" / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
)
PAGE = PARENT / "nfl_t0_by_spread_type_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/nfl_t0_by_spread_type_20261025.html"
)
QUEUE_PATH = RAW / "sports_queue.json"
RESULTS_PATH = RAW / "pro_football_results.jsonl"
TRACKED_TYPES = ("spread", "total", "team_total")
TYPE_LABEL = {
    "spread": "Spread — team wins by n",
    "total": "Total — combined points scored",
    "team_total": "Team total — team scores over n",
}
KALSHI_NAME = {
    "spread": "KXNFLSPREAD — Will TEAM win by over X.5 points?",
    "total": "KXNFLTOTAL — Will the combined score be over X.5?",
    "team_total": "KXNFLTEAMTOTAL — Will TEAM score over X.5 points?",
}
GEMINI_SUFFIX = {
    "spread": "-S (point spread, TEAM+LINE)",
    "total": "-T (combined over/under, O{LINE} / U{LINE})",
    "team_total": "-TT (one-team over, TEAMO{LINE})",
}

ASKED = (
    "When making T0 spread bets, cycle through different games until we hit max. "
    "Do not place all bets on a single game's many spread lines. Types: team wins "
    "by n (spread), total points scored (totals), team score over n (team total). "
    "Have we tracked those? Can we? Bucket analysis for NFL should include type. "
    "Same Sunday Oct 25 tape as the sibling all-tracked Type A win% page. Type A "
    "is wins-by-n / cover. Totals and team totals are appendix only. Do not show "
    "N=0 settled as if we gathered nothing today."
)
PLAIN = (
    "Type A is the traditional National Football League (NFL) spread: team A "
    "wins by N or team B wins by N (cover). That is the sibling page's hero and "
    "this page's spread section. A total is combined points. A team total is one "
    "team's points. Live D only buys Type A, one line per game, and still skips "
    "NFL. This rebuild loads Sunday settlements so the spread type is not stuck "
    "at N=0. Totals/team totals stay an appendix if ticks exist. T0 is first "
    "trusted kickoff. Tiny N does not wire D NFL. Research only."
)

STATUS_RANK = {
    "settled unique-fav T0": 0,
    "unsettled": 1,
    "void": 2,
    "50-50": 3,
    "no post-T0": 4,
    "one-sided": 5,
    "clock hid match": 6,
    "no T0 quotes": 7,
    "no clock": 8,
    "no documented fee": 9,
    "catalog only — no ticks": 10,
}


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def catalog_title(row: dict) -> str:
    return (
        str(row.get("title_kalshi") or "").strip()
        or str(row.get("title_gemini") or "").strip()
        or str(row.get("game") or "").strip()
        or " vs ".join(str(c) for c in (row.get("codes") or []) if c)
    )


def load_catalog_nfl() -> list[dict]:
    by_game: dict[str, dict] = {}

    def add(row: dict, source: str) -> None:
        if not isinstance(row, dict):
            return
        title = catalog_title(row)
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
            if not is_nfl(sport_row.get("sport")):
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
                    if is_nfl(rec.get("sport")):
                        add(rec, "pro_football_results.jsonl")
        except OSError:
            pass
    return sorted(by_game.values(), key=lambda r: (r.get("date") or "", r.get("game") or ""))


def team_total_number(side_key: str, number: str) -> str:
    team = " ".join(str(side_key or "").split())
    if team in {"over", "under"}:
        return number
    if team.endswith(" over") or team.endswith(" under"):
        team = team.rsplit(" ", 1)[0]
    team = team.strip()
    if team:
        return f"{team}:{number}" if number else team
    return number


def stream_nfl_type_sides() -> tuple[dict[tuple, dict], dict]:
    sides: dict[tuple, dict] = {}
    n_lines = 0
    n_yes = 0
    seen_min = ""
    seen_max = ""
    kinds: dict[str, int] = defaultdict(int)
    tickers: dict[str, int] = defaultdict(int)
    for line in iter_tick_lines(sport="pro football"):
        n_lines += 1
        if n_lines % 400000 == 0:
            print(f"  streamed {n_lines} NFL lines, yes sides {len(sides)} ticks {n_yes}", flush=True)
        if '"pay": "no"' in line or '"pay":"no"' in line:
            continue
        text = line.strip()
        if not text:
            continue
        try:
            rec = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if str(rec.get("pay") or "yes").lower() != "yes":
            continue
        if not is_nfl(rec.get("sport")):
            continue
        kind = str(rec.get("market_type") or "moneyline") or "moneyline"
        if kind not in TRACKED_TYPES:
            continue
        venue = str(rec.get("venue") or "")
        if venue not in t0.VENUES:
            continue
        price = as_float(rec.get("price"))
        if price is None or price <= 0.0 or price >= 1.0:
            continue
        seen = rec.get("seen_at") or ""
        ts = t0._ts(seen)
        if ts is None:
            continue
        sport = str(rec.get("sport") or "unknown")
        game = rec.get("game") or ""
        number = str(rec.get("number") or "")
        side_key = str(rec.get("side_key") or rec.get("side") or "").strip().lower()
        if kind == "team_total":
            number = team_total_number(side_key, number)
        if not game or not side_key:
            continue
        ident = (sport.lower(), game_norm(game), kind, venue, number, side_key)
        st = sides.get(ident)
        if st is None:
            st = {
                "sport": sport,
                "game": game,
                "kind": kind,
                "venue": venue,
                "number": number,
                "side": rec.get("side") or rec.get("side_label") or side_key,
                "side_key": side_key,
                "game_start": rec.get("game_start") or "",
                "ticks": [],
            }
            sides[ident] = st
            kinds[kind] += 1
        else:
            if rec.get("game_start") and not st.get("game_start"):
                st["game_start"] = rec.get("game_start") or ""
            if rec.get("game") and len(str(rec.get("game") or "")) > len(st.get("game") or ""):
                st["game"] = rec.get("game") or st["game"]
        if st["ticks"] and st["ticks"][-1][0] == ts:
            st["ticks"][-1] = (ts, price)
        else:
            st["ticks"].append((ts, price))
        n_yes += 1
        kinds[f"ticks:{kind}"] += 1
        if seen:
            if not seen_min or seen < seen_min:
                seen_min = seen
            if not seen_max or seen > seen_max:
                seen_max = seen
        blob = " ".join(
            str(rec.get(k) or "")
            for k in ("instrument", "ticker", "event_ticker", "symbol", "side", "side_label")
        )
        inferred = market_type_from(blob, kind)
        if inferred:
            tickers[inferred] += 1
    n_overlay = overlay_nfl_types(sides)
    print(
        f"stream done nfl-types lines={n_lines} yes={n_yes} sides={len(sides)} "
        f"overlay={n_overlay} seen {seen_min} .. {seen_max}",
        flush=True,
    )
    for st in sides.values():
        st["ticks"].sort(key=lambda row: row[0])
    return sides, {
        "n_lines": n_lines,
        "n_yes": n_yes,
        "n_sides": len(sides),
        "n_overlay": n_overlay,
        "seen_min": seen_min,
        "seen_max": seen_max,
        "kinds": dict(kinds),
        "tickers": dict(tickers),
    }


def overlay_nfl_types(sides: dict[tuple, dict]) -> int:
    try:
        stored = load_last()
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        return 0
    n_add = 0
    for _key, row in stored.items():
        if not isinstance(row, dict):
            continue
        if str(row.get("pay") or "yes").lower() != "yes":
            continue
        if not is_nfl(row.get("sport")):
            continue
        kind = str(row.get("market_type") or "moneyline") or "moneyline"
        if kind not in TRACKED_TYPES:
            continue
        venue = str(row.get("venue") or "")
        if venue not in t0.VENUES:
            continue
        price = as_float(row.get("price"))
        if price is None or price <= 0.0 or price >= 1.0:
            continue
        seen = row.get("seen_at") or ""
        ts = t0._ts(seen)
        if ts is None:
            continue
        sport = str(row.get("sport") or "unknown")
        game = row.get("game") or ""
        number = str(row.get("number") or "")
        side_key = str(row.get("side_key") or row.get("side") or "").strip().lower()
        if kind == "team_total":
            number = team_total_number(side_key, number)
        if not game or not side_key:
            continue
        ident = (sport.lower(), game_norm(game), kind, venue, number, side_key)
        st = sides.get(ident)
        if st is None:
            st = {
                "sport": sport,
                "game": game,
                "kind": kind,
                "venue": venue,
                "number": number,
                "side": row.get("side") or row.get("side_label") or side_key,
                "side_key": side_key,
                "game_start": row.get("game_start") or "",
                "ticks": [],
            }
            sides[ident] = st
        if row.get("game_start") and not st.get("game_start"):
            st["game_start"] = row.get("game_start") or ""
        if st["ticks"] and st["ticks"][-1][0] == ts:
            st["ticks"][-1] = (ts, price)
        elif not st["ticks"] or ts > st["ticks"][-1][0]:
            st["ticks"].append((ts, price))
            n_add += 1
    return n_add


def pick_primary_typed(books: list[dict]) -> list[dict]:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for book in books:
        key = (
            str(book.get("game_n") or book.get("game") or ""),
            str(book.get("kind") or ""),
            str(book.get("number") or ""),
        )
        bags[key].append(book)
    out = []
    rank = {"Kalshi": 0, "Gemini": 1, "Polymarket": 2, "Novig": 3}
    for _key, group in bags.items():
        group = sorted(
            group,
            key=lambda b: (
                float(b.get("t0_fav") or 9),
                rank.get(str(b.get("venue") or ""), 9),
                str(b.get("venue") or ""),
            ),
        )
        chosen = dict(group[0])
        chosen["_n_venues"] = len(group)
        chosen["_grain"] = "line"
        out.append(chosen)
    return out


def typed_trade(book: dict, arm_id: str) -> dict | None:
    trade = book_trade(book, arm_id)
    if trade is None:
        return None
    trade["kind"] = str(book.get("kind") or "")
    return trade


def trades_for(books: list[dict], arm_id: str) -> list[dict]:
    out = []
    for book in books:
        trade = typed_trade(book, arm_id)
        if trade is not None:
            out.append(trade)
    return out


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
        if book.get("fav") and is_unique_fav(book.get("t0_fav")):
            return "settled unique-fav T0"
        return "unsettled"
    if not book.get("settled"):
        return "unsettled"
    if not book.get("fav") or not is_unique_fav(book.get("t0_fav")):
        return "50-50"
    if documented_leg_fee(str(book.get("venue") or ""), book.get("t0_fav")) is None:
        return "no documented fee"
    return "settled unique-fav T0"


def classify_kind(books: list[dict], kind: str) -> dict:
    scored = []
    voids = []
    pending = []
    fifty = []
    no_fee = []
    skips: dict[str, int] = defaultdict(int)
    raw = [b for b in books if str(b.get("kind") or "") == kind]
    for book in raw:
        skip = book.get("skip") or ""
        if skip:
            skips[skip] += 1
            continue
        if not trusted_two_sided(book):
            skips["not_trusted_two_sided"] += 1
            continue
        if book.get("void"):
            voids.append(book)
            continue
        if cover_yes_known(book) and book.get("fav") and is_unique_fav(book.get("t0_fav")):
            scored.append(book)
            continue
        if not book.get("settled"):
            pending.append(book)
            continue
        if not book.get("fav") or not is_unique_fav(book.get("t0_fav")):
            fifty.append(book)
            continue
        if documented_leg_fee(str(book.get("venue") or ""), book.get("t0_fav")) is None:
            no_fee.append(book)
            continue
        scored.append(book)
    return {
        "raw": raw,
        "scored": scored,
        "voids": voids,
        "pending": pending,
        "fifty": fifty,
        "no_fee": no_fee,
        "skips": dict(skips),
    }


def skip_rows_for(kind: str, books: list[dict], catalog: list[dict]) -> list[list[str]]:
    bags: dict[str, list[dict]] = defaultdict(list)
    for book in books:
        if str(book.get("kind") or "") != kind:
            continue
        bags[str(book.get("game_n") or "")].append(book)
    seen = set()
    rows = []
    for game_n, group in bags.items():
        seen.add(game_n)
        statuses = [book_status(b) for b in group]
        best = min(statuses, key=lambda r: STATUS_RANK.get(r, 99))
        if best == "settled unique-fav T0":
            continue
        title = max((b.get("game") or "" for b in group), key=len)
        listed = next((b.get("listed_raw") or b.get("clock") or "" for b in group if b.get("listed_raw") or b.get("clock")), "")
        rows.append([esc(title), esc(kind), esc(best), str(len(group)), esc(listed[:22])])
    for cat in catalog:
        game_n = str(cat.get("game_n") or "")
        if game_n in seen:
            continue
        rows.append([
            esc(cat.get("game") or ""),
            esc(kind),
            "catalog only — no ticks",
            "0",
            esc((cat.get("listed_start") or cat.get("date") or "")[:22]),
        ])
    rows.sort(key=lambda r: (r[2], r[0]))
    if not rows:
        rows = [["—", esc(kind), "no skip rows", "0", "—"]]
    return rows


def score_kind(kind: str, bags: dict) -> dict:
    scored = bags["scored"]
    line_books = pick_primary_typed(scored)
    match_books = pick_one_per_game(line_books)
    void_lines = pick_primary_typed(bags["voids"])
    void_matches = pick_one_per_game(void_lines) if void_lines else []
    by_bucket: dict[str, list[dict]] = {label: [] for label, *_ in BUCKETS}
    for book in match_books:
        by_bucket.setdefault(bucket_of(book.get("t0_fav")), []).append(book)
    d_books = [b for b in match_books if in_d_band(b.get("t0_fav"))]
    recs = {}
    for label, lo, hi, how in BUCKETS:
        recs[label] = score_arm(
            trades_for(by_bucket.get(label) or [], label),
            arm_id=label,
            label=label,
            n_void=void_count(void_matches, lambda px, lo=lo, hi=hi, how=how: _in_bucket(px, lo, hi, how)),
        )
    recs[D_BAND_ID] = score_arm(
        trades_for(d_books, "d_band"),
        arm_id="d_band",
        label=D_BAND_ID,
        n_void=void_count(void_matches, in_d_band),
    )
    recs[ALL_ID] = score_arm(
        trades_for(match_books, "all_unique_fav"),
        arm_id="all_unique_fav",
        label=ALL_ID,
        n_void=len(void_matches),
    )
    return {
        "kind": kind,
        "recs": recs,
        "match_books": match_books,
        "d_books": d_books,
        "n_raw": len(bags["raw"]),
        "n_scored_venue": len(scored),
        "n_lines": len(line_books),
        "n_match": len(match_books),
        "n_void": len(void_matches),
        "n_pending": len(bags["pending"]),
        "n_fifty": len(bags["fifty"]),
        "n_no_fee": len(bags["no_fee"]),
        "skips": bags["skips"],
    }


SKIP_HEADERS = [
    ("Game", "text"),
    ("Type", "text"),
    ("Why no T0 P&L", "text"),
    ("Books", "num"),
    ("Listed / clock", "text"),
]
SUNDAY_KIND_HEADERS = [
    ("Game", "text"),
    ("Kickoff window", "text"),
    ("Type", "text"),
    ("Status", "text"),
    ("Books", "num"),
    ("Listed / clock", "text"),
    ("D 1pm miss?", "text"),
    ("In P&L", "text"),
]


def sunday_kind_rows(kind: str, skip_rows: list[list[str]], match_books: list[dict]) -> list[list[str]]:
    """Sunday Oct 25 first set for one type. Same tape as the sibling spread page."""
    seen = set()
    rows = []
    for book in match_books:
        listed = str(book.get("listed_raw") or book.get("clock") or "")
        if not is_today_slate(listed):
            continue
        game = str(book.get("game") or "")
        seen.add(game.lower())
        rows.append([
            esc(game),
            esc(kickoff_window_label(listed) or "—"),
            esc(kind),
            "settled unique-fav T0",
            str(book.get("_n_venues") or 1),
            esc(listed),
            "yes — D pid froze in REST hydration" if d_missed_1pm(listed) else "no",
            "yes",
        ])
    for row in skip_rows:
        if len(row) < 5:
            continue
        listed = str(row[4])
        # skip_rows cells are already escaped
        listed_raw = html_mod.unescape(listed)
        if not is_today_slate(listed_raw):
            continue
        game_raw = html_mod.unescape(str(row[0]))
        if game_raw.lower() in seen:
            continue
        rows.append([
            row[0],
            esc(kickoff_window_label(listed_raw) or "—"),
            row[1] if len(row) > 1 else esc(kind),
            row[2] if len(row) > 2 else "—",
            row[3] if len(row) > 3 else "0",
            row[4],
            "yes — D pid froze in REST hydration" if d_missed_1pm(listed_raw) else "no",
            "no",
        ])
    rows.sort(key=lambda r: (html_mod.unescape(str(r[1])), html_mod.unescape(str(r[0]))))
    if not rows:
        rows = [["—", "no Sunday Oct 25 rows", esc(kind), "—", "0", "—", "no", "no"]]
    return rows
TRADE_HEADERS = [
    ("Game", "text"),
    ("Type", "text"),
    ("Line", "text"),
    ("Fav", "text"),
    ("Venue", "text"),
    ("T0 Yes", "num"),
    ("Bucket", "text"),
    ("In D band", "text"),
    ("Won", "text"),
    ("Fee $", "num"),
    ("With-fee PnL $", "num"),
    ("T0 date", "date"),
]


def trade_row(trade: dict) -> list[str]:
    from compare_format import format_money
    from t0_fav_lt90_baseline_20261024 import fmt_num

    return [
        esc(trade.get("game") or ""),
        esc(trade.get("kind") or ""),
        esc(trade.get("number") or ""),
        esc(trade.get("fav_name") or ""),
        esc(trade.get("venue") or ""),
        fmt_num(trade.get("t0_fav"), 3),
        esc(trade.get("bucket") or ""),
        "yes" if in_d_band(trade.get("t0_fav")) else "no",
        "win" if trade.get("won") else "loss",
        format_money(trade.get("fee")),
        format_money(trade.get("pnl_d")),
        esc(trade.get("entry_date") or ""),
    ]


def ensure_queue_type_siblings() -> int:
    """Add missing Kalshi/Gemini type ticker fields. Does not drop ML/spread."""
    if not QUEUE_PATH.is_file():
        return 0
    try:
        blob = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    n = 0
    changed = False
    for sport_row in blob.get("sports") or []:
        if not is_nfl(sport_row.get("sport")):
            continue
        for row in sport_row.get("matched") or []:
            if not isinstance(row, dict):
                continue
            kalshi = row.setdefault("kalshi", {})
            gem = row.setdefault("gemini", {})
            game = str(kalshi.get("game") or "")
            if game and "KXNFLGAME" in game.upper():
                if not kalshi.get("spread"):
                    kalshi["spread"] = game.replace("KXNFLGAME", "KXNFLSPREAD", 1)
                    n += 1
                    changed = True
                if not kalshi.get("total"):
                    kalshi["total"] = game.replace("KXNFLGAME", "KXNFLTOTAL", 1)
                    n += 1
                    changed = True
                if not kalshi.get("team_total"):
                    kalshi["team_total"] = game.replace("KXNFLGAME", "KXNFLTEAMTOTAL", 1)
                    n += 1
                    changed = True
            for src, dst in (
                ("moneyline", "spread"),
                ("moneyline", "total"),
                ("moneyline", "team_total"),
                ("spread", "moneyline"),
                ("spread", "total"),
                ("spread", "team_total"),
                ("total", "moneyline"),
                ("total", "spread"),
                ("total", "team_total"),
            ):
                if gem.get(dst) or not gem.get(src):
                    continue
                ticker = str(gem.get(src) or "")
                up = ticker.upper()
                suffix = next((s for s in ("-TT", "-M", "-S", "-T") if up.endswith(s)), "")
                if not suffix:
                    continue
                stem = ticker[: -len(suffix)]
                want = {"moneyline": "-M", "spread": "-S", "total": "-T", "team_total": "-TT"}[dst]
                gem[dst] = stem + want
                n += 1
                changed = True
    if changed:
        tmp = QUEUE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
        tmp.replace(QUEUE_PATH)
    return n


def build_payload() -> dict:
    added = ensure_queue_type_siblings()
    print(f"queue type siblings added={added}", flush=True)
    catalog = load_catalog_nfl()
    print("loading NFL settlements (reuse overlay if the sibling already fetched)", flush=True)
    from nfl_t0_type_a_collect import OVERLAY_PATH
    settlements, settle_meta = load_nfl_settlements(fetch=not OVERLAY_PATH.is_file())
    index = build_index(settlements)
    cover_index = build_nfl_cover_index(settlements)
    occ_map = occ_map_prefer_listed(catalog, settlements)
    sides, meta = stream_nfl_type_sides()
    books = t0.pair_books(sides)
    print(f"paired {len(books)} NFL type venue-game books", flush=True)
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
    meta["queue_siblings_added"] = added
    meta["settle"] = settle_meta
    by_kind = {}
    for kind in TRACKED_TYPES:
        bags = classify_kind(books, kind)
        scored = score_kind(kind, bags)
        scored["skip_rows"] = skip_rows_for(kind, books, catalog)
        scored["win"] = bucket_winpct(scored.get("match_books") or [], prefix=f"{kind}-unique-fav")
        scored["sunday_win"] = bucket_winpct(
            [b for b in (scored.get("match_books") or []) if is_sunday_book(b, TODAY_ET)],
            prefix=f"{kind}-sunday",
        )
        by_kind[kind] = scored
    return {
        "written_at": iso_now(),
        "meta": meta,
        "by_kind": by_kind,
        "n_catalog": len(catalog),
    }


def kind_section(kind: str, block: dict) -> str:
    recs = block["recs"]
    d_q = recs[D_BAND_ID]
    all_q = recs[ALL_ID]
    primary_order = [label for label, *_ in BUCKETS] + [D_BAND_ID, ALL_ID]
    primary_rows = [primary_row(recs[key]) for key in primary_order]
    compare_rows = [compare_row(recs[key], d_q if key != D_BAND_ID else None) for key in primary_order]
    trades = sorted(
        all_q.get("trades") or [],
        key=lambda t: (t.get("entry_date") or "", t.get("game") or "", t.get("number") or ""),
    )
    trade_rows = [trade_row(t) for t in trades] or [["—"] * len(TRADE_HEADERS)]
    n_all = int(all_q.get("n") or 0)
    n_d = int(d_q.get("n") or 0)
    skip_bits = ", ".join(f"{k}={v}" for k, v in sorted((block.get("skips") or {}).items())) or "none"
    win = block.get("win") or {}
    sunday_win = block.get("sunday_win") or {}
    win_rows = [winpct_row(win[key], display=key) for key in WINPCT_ORDER if key in win]
    sun_rows = [winpct_row(sunday_win[key], display=key) for key in WINPCT_ORDER if key in sunday_win]
    win_block = ""
    if kind == "spread":
        win_block = f"""
<h3>Type A win% by T0 bucket (unique-fav, all days)</h3>
<p class="note">This is the same unique-fav grain as the sibling all-tracked page.
N={esc(int((win.get(ALL_ID) or {}).get("n") or 0))}. Sunday N=
{esc(int((sunday_win.get(ALL_ID) or {}).get("n") or 0))}. Totals/team totals stay
below as appendix. Did not turn D NFL on.</p>
{html_table(WINPCT_HEADERS, win_rows)}
<h3>Type A win% — Sunday Oct 25 only</h3>
{html_table(WINPCT_HEADERS, sun_rows)}
"""
    return f"""
<h2 id="{esc(kind)}">{esc(TYPE_LABEL[kind])}</h2>
<p class="note">Kalshi calls this <code>{esc(KALSHI_NAME[kind])}</code>.
Gemini event suffix {esc(GEMINI_SUFFIX[kind])}. One closest-to-50¢ unique-fav
line per game inside this type. Live D would only send the spread type.
Click column headers to sort.</p>
{win_block}
<p class="note">Settled unique-fav N={esc(n_all)}. Live D band N={esc(n_d)}.
Venue-lines {esc(block.get("n_scored_venue"))} → one venue {esc(block.get("n_lines"))}
→ one-per-game {esc(block.get("n_match"))}. Pending {esc(block.get("n_pending"))}.
Void {esc(block.get("n_void"))}. 50-50 {esc(block.get("n_fifty"))}.
No documented fee {esc(block.get("n_no_fee"))}. Tape skip reasons: {esc(skip_bits)}.
{esc(sample_note(n_all))}.</p>
<h3>With-fee P&amp;L by bucket</h3>
{html_table(PRIMARY_HEADERS, primary_rows)}
<h3>Canonical compare vs this type's (0.50, 0.90) band</h3>
<p class="note">Control is this type's live D band, not the spread-only live wire.
Ann ROR is omitted when hold is same-day. HOLD live D.</p>
{html_table(COMPARE_HEADERS, compare_rows)}
<h3>Skip — no trusted T0 P&amp;L</h3>
<p class="note">Games we tracked for this type that are not in the P&amp;L
denominator. Catalog-only rows mean we listed the game but have no ticks of
this type yet (team totals were not subscribed until this job).</p>
{html_table(SKIP_HEADERS, block.get("skip_rows") or [])}
<h3>Settled unique-fav tickets</h3>
{html_table(TRADE_HEADERS, trade_rows)}
"""


def write_html(payload: dict) -> Path:
    meta = payload["meta"]
    by_kind = payload["by_kind"]
    n_spread = int(by_kind["spread"]["recs"][ALL_ID].get("n") or 0)
    n_total = int(by_kind["total"]["recs"][ALL_ID].get("n") or 0)
    n_tt = int(by_kind["team_total"]["recs"][ALL_ID].get("n") or 0)
    n_spread_d = int(by_kind["spread"]["recs"][D_BAND_ID].get("n") or 0)
    ticks = meta.get("kinds") or {}
    sunday_bits = []
    sunday_tables = []
    for kind in TRACKED_TYPES:
        block = by_kind[kind]
        kind_trades = [
            t for t in (block["recs"][ALL_ID].get("trades") or [])
            if str(t.get("entry_date") or "") == TODAY_ET
        ]
        sunday_rows = sunday_kind_rows(
            kind,
            block.get("skip_rows") or [],
            block.get("match_books") or [],
        )
        n_sunday = sum(1 for r in sunday_rows if r[0] != "—")
        n_sunday_pnl = len(kind_trades)
        n_sunday_ticks = sum(
            1 for r in sunday_rows
            if html_mod.unescape(str(r[3])) != "catalog only — no ticks" and r[0] != "—"
        )
        n_sunday_cat = sum(
            1 for r in sunday_rows
            if html_mod.unescape(str(r[3])) == "catalog only — no ticks"
        )
        sunday_bits.append(
            f"{TYPE_LABEL[kind]}: {n_sunday} Sunday rows, {n_sunday_ticks} with ticks, "
            f"{n_sunday_cat} catalog-only, settled unique-fav N={n_sunday_pnl}"
        )
        sunday_tables.append(
            f"<h3>{esc(TYPE_LABEL[kind])}</h3>\n"
            + html_table(SUNDAY_KIND_HEADERS, sunday_rows)
        )
    sunday_summary = ". ".join(sunday_bits) + "."
    sunday_block = "\n".join(sunday_tables)
    sections = "".join(kind_section(kind, by_kind[kind]) for kind in TRACKED_TYPES)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>NFL T0 by type — spread / total / team total</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
h3 {{ margin: 1rem 0 0.4rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>NFL T0 buckets by type — spread / total / team total</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. HOLD live D
(one traditional spread per game, favorite Yes in (0.50, 0.90)). Did not start a
second <code>live_strategy_b.py</code>. Did not sell. Did not read fills. Did not
overwrite the sibling all-tracked spread page.</p>
<p class="banner">Type A (spread / wins-by-n) unique-fav N={esc(n_spread)}.
Totals {esc(n_total)}, team total {esc(n_tt)} are appendix. Spread live-D-band
N={esc(n_spread_d)}. Did not turn D NFL on. Tiny N still does not wire D NFL.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Paul note</h2>
<p><strong>HOLD</strong> live D. Cycle games, not lines: at most one T0 ticket
per kickoff, traditional spread (wins-by-n) when it qualifies, leftover
<code>max_open</code> slots go to the next game. Totals and team totals are on
this research page so we can see whether they were even on the tape. They are
not a live D send. IS N=0 — every T0 here is 2026. Annualized rate of return
(Ann ROR) is omitted when hold is same-day. House formula only.</p>

<h2>Have we tracked these? Can we?</h2>
<ul>
<li><strong>Spread (team wins by n).</strong> Yes since the Oct 17 tape. Kalshi
series <code>KXNFLSPREAD</code>. Gemini <code>-S</code>. Pollers already
synthesized GAME→SPREAD. This is live D.</li>
<li><strong>Total (combined points).</strong> Yes as a sibling: GAME→TOTAL /
<code>KXNFLTOTAL</code> / Gemini <code>-T</code>. Ticks on this tape:
{esc(ticks.get("ticks:total") or ticks.get("total") or 0)} Yes sides.
Novig lists TOTAL. Polymarket full-game totals exist when a twin is listed.</li>
<li><strong>Team total (team scores over n).</strong> Not subscribed until this
job. Kalshi series <code>KXNFLTEAMTOTAL</code> (example
<code>KXNFLTEAMTOTAL-26OCT22NECHI-CHI11</code> = Chicago over 10.5). Gemini
<code>-TT</code> (example <code>GEMI-NFL-…-NE-SEA-TT-NEO24</code>). Pollers now
add those siblings without dropping moneyline or spread. Polymarket has
<code>team_total</code> but lock matching still skips props. Novig's polled
<code>marketType</code> is MONEY / SPREAD / TOTAL only — no team-total enum on
the wire we read. Ticks on this tape before the sibling add:
{esc(ticks.get("ticks:team_total") or ticks.get("team_total") or 0)}.</li>
</ul>
<p class="note">Tape Yes ticks {esc(meta.get("seen_min") or "—")} through
{esc(meta.get("seen_max") or "—")}. Streamed {esc(meta.get("n_lines"))} pro-football
lines, {esc(meta.get("n_yes"))} typed Yes ticks, {esc(meta.get("n_sides"))} sides,
catalog NFL games {esc(payload.get("n_catalog"))}. Queue sibling fields added this
job: {esc(meta.get("queue_siblings_added"))}.</p>

<h2>Sunday Oct 25 first set (same tape as the sibling spread page)</h2>
<p class="note">National Football League (NFL) games listed Sunday {esc(TODAY_ET)}
ET. First window ~1pm ET; later Sunday kickoffs stay here if they are already on
the tape. Click column headers to sort. This is the by-type pair of
<code>nfl_t0_spread_buckets_all_tracked_20261025.html</code> — same Sunday
slate, split by spread / total / team total. Annualized rate of return (Ann ROR)
is omitted on same-day holds.</p>
<p class="banner">{esc(sunday_summary)} Live D missed the 1pm window earlier
today because pid froze in REST hydration
(<code>d_missed_nfl_t0_1300_20261025.html</code>). Live D still skips NFL
(<code>d_skip_nfl_gathering</code>). Did not turn D NFL on. Did not send.</p>
{sunday_block}

{sections}

<p class="tiny">Generator: <code>tools/nfl_t0_by_spread_type_20261025.py</code>.
Live D pick: <code>prediction_systems.pick_spread_line</code> (one spread, ignores
<code>--d-all-lines</code>). Siblings: <code>live_game_pollers.expand_sibling_tickers</code>.
Did not overwrite <code>nfl_t0_spread_buckets_all_tracked_20261025.html</code>.
Written {esc(payload.get("written_at"))} ET. file:// {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PARENT.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def main() -> int:
    print("scoring NFL T0 by type (spread / total / team total)", flush=True)
    payload = build_payload()
    path = write_html(payload)
    bits = []
    for kind in TRACKED_TYPES:
        q = payload["by_kind"][kind]["recs"][ALL_ID]
        bits.append(f"{kind} N={q.get('n')} pnl={float(q.get('pnl_sum') or 0):.4f}")
    print(f"wrote {path} " + " ".join(bits), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
