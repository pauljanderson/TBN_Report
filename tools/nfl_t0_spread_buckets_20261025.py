"""NFL / pro football T0 spread favorite buckets — with-fee P&L.

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not start a second live_strategy_b.py. Does not sell. Does not change live D.
Does not write sports_queue. Not gold. Not DailyRun.

Universe: this tape's pro football two-sided spreads with trusted T0 (same clock
as live D / write_t0_* / t0_all_games_stats). One line per game: closest T0
favorite Yes to 50¢ among two-sided unique favorites. Buy 1 Yes on that
favorite, taker, documented fees in, hold to settlement.
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
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
from compare_format import format_money, format_money_delta
from price_memory import iter_tick_lines, load_last
from odds_cross_winrate_20261020 import as_float, build_index, game_norm
import t0_all_games_stats as t0
from t0_fav_lt90_baseline_20261024 import (
    VENUE_RANK,
    fav_yes_pnl,
    fmt_ann,
    fmt_num,
    fmt_pct,
    html_table,
    quality,
)
from write_t0_band_from_stay_above import documented_leg_fee

ET = ZoneInfo("America/New_York")
PARENT = (
    ROOT / "drive" / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
)
PAGE = PARENT / "nfl_t0_spread_buckets_20261025.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/nfl_t0_spread_buckets_20261025.html"
)
IS_CUT = "2024-01-01"
YES_LO = 0.50
YES_HI = 0.90
TINY_N = 8
SMALL_N = 20
DOC_FEE_VENUES = {"Kalshi", "Gemini", "Polymarket"}
NFL_SPORTS = {"pro football", "nfl"}
BUCKETS = (
    (">90", 0.90, 1.01, "gt"),
    ("80-89", 0.80, 0.90, "ge_lt"),
    ("70-79", 0.70, 0.80, "ge_lt"),
    ("60-69", 0.60, 0.70, "ge_lt"),
    ("50-59", 0.50, 0.60, "gt_lt"),
)
D_BAND_ID = "(0.50, 0.90) live D"
ALL_ID = "all unique fav"

ASKED = (
    "Test for pro football: historical breakdown for each bucket for T0 spread "
    "(>90, 80-89, etc.). He wants with-fee P&L."
)
PLAIN = (
    "T0 is the first trusted kickoff price — a real listed or venue start clock, "
    "not a random first tick after we started watching. A bucket is how expensive "
    "the spread favorite was at that first price: a 0.82 Yes means the market "
    "wanted 82 cents for the side it liked to cover the line. Live D already buys "
    "one spread per game when that favorite sits between 50 and 90 cents, not "
    "including the edges. This page keeps D’s one-line-per-game pick (the "
    "two-sided line closest to 50 cents) and asks whether those NFL tickets made "
    "money after fees if we bought one Yes and held to the official result. "
    "This tape is only the October 2026 collection — a few NFL Sundays, last "
    "matched games around October 22. Empty buckets are empty. Research only. "
    "Not gold. Not DailyRun. Paul asked after seeing live D (selection bias). "
    "Do not change live D from this page."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def norm_sport(value) -> str:
    sport = " ".join(str(value or "").lower().split())
    if sport in {"nfl", "pro football"}:
        return "pro football"
    return sport


def is_nfl(value) -> bool:
    return norm_sport(value) in {"pro football"} or str(value or "").strip().lower() in NFL_SPORTS


def is_spread(value) -> bool:
    return str(value or "").strip().lower() in {"spread", "spreads"}


def in_d_band(px) -> bool:
    if px is None:
        return False
    return YES_LO + 1e-12 < float(px) < YES_HI - 1e-12


def is_unique_fav(px) -> bool:
    if px is None:
        return False
    return float(px) > YES_LO + 1e-12


def bucket_of(px) -> str:
    """Same disjoint decades as living t0_all_games_stats. 0.90 sits in 80-89."""
    return t0.bucket_of(None if px is None else float(px))


def sample_note(n: int) -> str:
    if n <= 0:
        return "N=0 — no settled rows in this bucket on this tape"
    if n < TINY_N:
        return "tiny N — do not change live D"
    if n < SMALL_N:
        return "small sample"
    return ""


def stream_nfl_spread_sides() -> tuple[dict[tuple, dict], dict]:
    """Pro football + spread Yes only. Same pairing keys as t0_all_games_stats."""
    sides: dict[tuple, dict] = {}
    n_lines = 0
    n_yes = 0
    seen_min = ""
    seen_max = ""
    sports: dict[str, int] = defaultdict(int)
    kinds: dict[str, int] = defaultdict(int)
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
        if not is_spread(kind):
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
            sports[sport] += 1
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
        if seen:
            if not seen_min or seen < seen_min:
                seen_min = seen
            if not seen_max or seen > seen_max:
                seen_max = seen
    n_overlay = overlay_nfl_spread(sides)
    print(
        f"stream done nfl-spread lines={n_lines} yes={n_yes} sides={len(sides)} "
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
        "sports": dict(sports),
        "kinds": dict(kinds),
    }


def overlay_nfl_spread(sides: dict[tuple, dict]) -> int:
    """Reuse last-Yes overlay, keep only pro football spreads."""
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
        if not is_spread(kind):
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


def trusted_two_sided(book: dict) -> bool:
    if book.get("skip"):
        return False
    if not book.get("two_sided"):
        return False
    if book.get("t0_a") is None or book.get("t0_b") is None or book.get("t0_ts") is None:
        return False
    return True


def pick_primary_line(books: list[dict]) -> list[dict]:
    """One venue per (game, spread number). Cheapest documented-fee Yes, then Kalshi rank."""
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for book in books:
        key = (
            str(book.get("game_n") or book.get("game") or ""),
            str(book.get("number") or ""),
        )
        bags[key].append(book)
    out = []
    for _key, group in bags.items():
        group = sorted(
            group,
            key=lambda b: (
                float(b.get("t0_fav") or 9),
                VENUE_RANK.get(str(b.get("venue") or ""), 9),
                str(b.get("venue") or ""),
            ),
        )
        chosen = dict(group[0])
        chosen["_n_venues"] = len(group)
        chosen["_grain"] = "line"
        out.append(chosen)
    return out


def pick_one_per_game(books: list[dict]) -> list[dict]:
    """Same as live D: one two-sided line per game, closest T0 favorite Yes to 50¢."""
    bags: dict[str, list[dict]] = defaultdict(list)
    for book in books:
        bags[str(book.get("game_n") or book.get("game") or "")].append(book)
    out = []
    for _key, group in bags.items():
        group = sorted(
            group,
            key=lambda b: (
                abs(float(b.get("t0_fav")) - YES_LO),
                str(b.get("number") or ""),
                VENUE_RANK.get(str(b.get("venue") or ""), 9),
            ),
        )
        chosen = dict(group[0])
        chosen["_n_lines"] = len(group)
        chosen["_grain"] = "match"
        out.append(chosen)
    return out


def book_trade(book: dict, arm_id: str) -> dict | None:
    t0_fav = book.get("t0_fav")
    if not is_unique_fav(t0_fav):
        return None
    venue = str(book.get("venue") or "")
    fee = documented_leg_fee(venue, t0_fav)
    if fee is None:
        return None
    won = bool(book.get("fav_won"))
    pnl = fav_yes_pnl(t0_fav, fee, won=won)
    cost = Decimal(str(t0_fav)) + Decimal(str(fee))
    pnl_pct = (float(pnl) / float(cost) * 100.0) if cost > 0 else None
    t0_ts = book.get("t0_ts")
    end_ts = book.get("end_ts") or t0_ts
    days = 0.0
    opened = closed = None
    if t0_ts is not None:
        opened = datetime.fromtimestamp(int(t0_ts), ET)
        if end_ts is not None:
            closed = datetime.fromtimestamp(int(end_ts), ET)
            days = max(0.0, (int(end_ts) - int(t0_ts)) / 86400.0)
        else:
            closed = opened
    return {
        "arm": arm_id,
        "sport": "pro football",
        "kind": "spread",
        "venue": venue,
        "game": book.get("game") or "",
        "game_n": book.get("game_n") or "",
        "number": book.get("number") or "",
        "fav_name": book.get("fav_name") or "",
        "t0_fav": float(t0_fav),
        "bucket": bucket_of(t0_fav),
        "fee": float(fee),
        "fee_known": True,
        "cost": float(cost),
        "won": won,
        "pnl_d": float(pnl),
        "pnl": pnl_pct,
        "days": days,
        "opened": opened,
        "closed": closed,
        "entry_date": opened.date().isoformat() if opened else "",
        "be": float(cost),
        "grain": book.get("_grain") or "match",
        "two_sided": True,
        "t0_source": book.get("t0_source") or "",
        "t0_label": book.get("t0_label") or "",
        "n_lines": book.get("_n_lines") or 1,
        "n_venues": book.get("_n_venues") or 1,
    }


def trades_for(books: list[dict], arm_id: str) -> list[dict]:
    out = []
    for book in books:
        trade = book_trade(book, arm_id)
        if trade is not None:
            out.append(trade)
    return out


def void_count(voids: list[dict], pred) -> int:
    return sum(1 for book in voids if pred(book.get("t0_fav")))


def score_arm(trades: list[dict], *, arm_id: str, label: str, n_void: int) -> dict:
    q = quality(trades, arm_id=arm_id, label=label, grain="match")
    q["n_void"] = n_void
    q["total_fees"] = sum(float(t.get("fee") or 0) for t in trades)
    q["note"] = sample_note(int(q.get("n") or 0))
    return q


def primary_row(q: dict) -> list[str]:
    n = int(q.get("n") or 0)
    return [
        esc(q.get("arm") or q.get("arm_id") or ""),
        str(n),
        str(q.get("n_win") or 0),
        fmt_pct(q.get("win_pct")) if n else "—",
        format_money(q.get("pnl_sum")) if n else "—",
        format_money(q.get("mean")) if n else "—",
        format_money(q.get("total_fees")) if n else "—",
        str(q.get("n_void") or 0),
        esc(q.get("note") or ""),
    ]


def compare_row(q: dict, control: dict | None) -> list[str]:
    def dlt(key, fmt="num"):
        if control is None:
            return "—"
        a = q.get(key)
        b = control.get(key)
        if a is None or b is None:
            return "—"
        got = float(a) - float(b)
        if fmt == "money":
            return format_money_delta(got)
        if fmt == "pct":
            return f"{got:+.1f}"
        return f"{got:+.2f}"

    ann_full = q["ann_note"] if q.get("ann_note") else fmt_ann(q.get("ann_ror"))
    ann_is = q.get("is_note") or fmt_ann(q.get("ann_ror_is"))
    ann_oos = q["ann_note"] if q.get("ann_note") else fmt_ann(q.get("ann_ror_oos"))
    return [
        esc(q.get("arm") or q.get("arm_id") or ""),
        esc(q.get("grain") or "match"),
        str(q.get("n") or 0),
        str(q.get("n_win") or 0),
        fmt_pct(q.get("win_pct")),
        format_money(q.get("pnl_sum")),
        format_money(q.get("mean")),
        format_money(q.get("total_fees")),
        fmt_num(q.get("avg_pnl_pct")),
        fmt_num(q.get("avg_pnl_pct_wo_max")),
        format_money(q.get("avg_win")),
        format_money(q.get("avg_loss")),
        fmt_num(q.get("pf")),
        format_money(q.get("expectancy")),
        fmt_num(q.get("avg_days"), 3),
        fmt_num(q.get("capital_days"), 2),
        format_money(q.get("max_dd_d")),
        fmt_pct(q.get("max_dd")),
        fmt_num(q.get("calmar")),
        fmt_num(q.get("sharpe")),
        esc(ann_full),
        esc(ann_is),
        esc(ann_oos),
        str(q.get("n_is") or 0),
        str(q.get("n_oos") or 0),
        dlt("win_pct", "pct"),
        dlt("mean", "money"),
        dlt("avg_pnl_pct"),
        dlt("pf"),
        dlt("total_fees", "money"),
    ]


PRIMARY_HEADERS = [
    ("Bucket", "text"),
    ("N", "num"),
    ("Wins", "num"),
    ("Win %", "num"),
    ("With-fee PnL $", "num"),
    ("Mean $", "num"),
    ("Total fees $", "num"),
    ("N_void", "num"),
    ("Note", "text"),
]

COMPARE_HEADERS = [
    ("Arm", "text"),
    ("Grain", "text"),
    ("N", "num"),
    ("Wins", "num"),
    ("Win %", "num"),
    ("With-fee PnL $", "num"),
    ("Mean $", "num"),
    ("Total fees $", "num"),
    ("Avg PnL %", "num"),
    ("AVG_PNL_PCT_WO_MAX", "num"),
    ("Avg win $", "num"),
    ("Avg loss $", "num"),
    ("Profit factor", "num"),
    ("Expectancy $", "num"),
    ("Avg days held", "num"),
    ("Capital days", "num"),
    ("Max DD $", "num"),
    ("Max DD %", "num"),
    ("Calmar", "num"),
    ("Sharpe", "num"),
    ("Ann ROR full", "text"),
    ("Ann ROR IS", "text"),
    ("Ann ROR OOS", "text"),
    ("N IS", "num"),
    ("N OOS", "num"),
    ("Δ Win % vs D-band", "num"),
    ("Δ Mean $ vs D-band", "num"),
    ("Δ Avg PnL % vs D-band", "num"),
    ("Δ PF vs D-band", "num"),
    ("Δ Total fees vs D-band", "num"),
]

TRADE_HEADERS = [
    ("Game", "text"),
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
    ("T0 source", "text"),
    ("Lines on game", "num"),
]


def trade_row(trade: dict) -> list[str]:
    return [
        esc(trade.get("game") or ""),
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
        esc(trade.get("t0_source") or ""),
        str(trade.get("n_lines") or 1),
    ]


def load_nfl_spread_books() -> tuple[list[dict], dict]:
    print("loading settlements", flush=True)
    settlements = t0.load_settlement_rows()
    occ_map = t0.start_lookup_from_settlements(settlements)
    index = build_index(settlements)
    print(f"settlements {len(settlements)} occurrence clocks {len(occ_map)}", flush=True)
    sides, meta = stream_nfl_spread_sides()
    books = t0.pair_books(sides)
    print(f"paired {len(books)} NFL spread venue-game books", flush=True)
    for i, book in enumerate(books):
        t0.settle_book(book, settlements, index)
        t0.score_book(book, occ_map)
        if (i + 1) % 200 == 0:
            print(f"  scored {i + 1}/{len(books)}", flush=True)
    meta["n_settlements"] = len(settlements)
    meta["n_books"] = len(books)
    return books, meta


def classify_books(books: list[dict]) -> dict:
    skips: dict[str, int] = defaultdict(int)
    two_sided = []
    voids = []
    pending = []
    fifty = []
    no_fee = []
    for book in books:
        if not is_nfl(book.get("sport")) or not is_spread(book.get("kind")):
            continue
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
        if not book.get("settled"):
            pending.append(book)
            continue
        if not book.get("fav") or not is_unique_fav(book.get("t0_fav")):
            fifty.append(book)
            continue
        if documented_leg_fee(str(book.get("venue") or ""), book.get("t0_fav")) is None:
            no_fee.append(book)
            continue
        two_sided.append(book)
    return {
        "scored": two_sided,
        "voids": voids,
        "pending": pending,
        "fifty": fifty,
        "no_fee": no_fee,
        "skips": dict(skips),
    }


def build_payload() -> dict:
    books, meta = load_nfl_spread_books()
    bags = classify_books(books)
    scored = bags["scored"]
    line_books = pick_primary_line(scored)
    match_books = pick_one_per_game(line_books)
    void_lines = pick_primary_line(bags["voids"])
    void_matches = pick_one_per_game(void_lines) if void_lines else []

    by_bucket: dict[str, list[dict]] = {label: [] for label, *_ in BUCKETS}
    for book in match_books:
        by_bucket.setdefault(bucket_of(book.get("t0_fav")), []).append(book)
    d_books = [b for b in match_books if in_d_band(b.get("t0_fav"))]

    void_by_bucket = {label: void_count(void_matches, lambda px, lo=lo, hi=hi, how=how: _in_bucket(px, lo, hi, how))
                      for label, lo, hi, how in BUCKETS}
    void_d = void_count(void_matches, in_d_band)
    void_all = len(void_matches)

    recs = {}
    for label, lo, hi, how in BUCKETS:
        recs[label] = score_arm(
            trades_for(by_bucket.get(label) or [], label),
            arm_id=label,
            label=label,
            n_void=void_by_bucket.get(label) or 0,
        )
    recs[D_BAND_ID] = score_arm(
        trades_for(d_books, "d_band"),
        arm_id="d_band",
        label=D_BAND_ID,
        n_void=void_d,
    )
    recs[ALL_ID] = score_arm(
        trades_for(match_books, "all_unique_fav"),
        arm_id="all_unique_fav",
        label=ALL_ID,
        n_void=void_all,
    )
    all_line_trades = trades_for(line_books, "all_lines")
    recs["all_lines"] = score_arm(
        all_line_trades,
        arm_id="all_lines",
        label="all two-sided lines (footnote grain)",
        n_void=len(void_lines),
    )
    recs["all_lines"]["grain"] = "line"

    t0_dates = sorted({t.get("entry_date") for t in recs[ALL_ID]["trades"] if t.get("entry_date")})
    return {
        "written_at": iso_now(),
        "meta": meta,
        "bags": {
            "n_raw_books": len(books),
            "n_scored_venue": len(scored),
            "n_lines": len(line_books),
            "n_match": len(match_books),
            "n_void_venue": len(bags["voids"]),
            "n_void_match": void_all,
            "n_pending": len(bags["pending"]),
            "n_fifty": len(bags["fifty"]),
            "n_no_fee": len(bags["no_fee"]),
            "skips": bags["skips"],
            "t0_dates": t0_dates,
        },
        "recs": recs,
        "match_books": match_books,
        "d_books": d_books,
    }


def _in_bucket(px, lo, hi, how) -> bool:
    if px is None:
        return False
    p = float(px)
    if how == "gt":
        return p > lo + 1e-12
    if how == "gt_lt":
        return p > lo + 1e-12 and p < hi - 1e-12
    return p >= lo - 1e-12 and p < hi - 1e-12


def write_html(payload: dict) -> Path:
    recs = payload["recs"]
    bags = payload["bags"]
    meta = payload["meta"]
    d_q = recs[D_BAND_ID]
    all_q = recs[ALL_ID]
    all_lines = recs["all_lines"]
    primary_order = [label for label, *_ in BUCKETS] + [D_BAND_ID, ALL_ID]
    primary_rows = [primary_row(recs[key]) for key in primary_order]
    compare_rows = [compare_row(recs[key], d_q if key != D_BAND_ID else None) for key in primary_order]
    trade_rows = [trade_row(t) for t in sorted(
        all_q.get("trades") or [],
        key=lambda t: (t.get("entry_date") or "", t.get("game") or "", t.get("number") or ""),
    )]
    if not trade_rows:
        trade_rows = [["—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", "—"]]
    dates = bags.get("t0_dates") or []
    date_txt = ", ".join(dates) if dates else "none settled"
    n_all = int(all_q.get("n") or 0)
    n_d = int(d_q.get("n") or 0)
    n_lines = int(all_lines.get("n") or 0)
    line_note = (
        f"All two-sided unique-fav lines (one venue per line) N={n_lines}. "
        f"One-per-game N={n_all}. "
    )
    if n_lines == n_all:
        line_note += "Same N — no extra lines after the closest-to-50¢ pick."
    else:
        line_note += (
            f"N differs by {n_lines - n_all} extra line(s). Headline grain is one per game "
            "to match live D. Do not add the all-lines row to the one-per-game bankroll."
        )
    tiny = n_all < SMALL_N
    tiny_banner = (
        f"<strong>Tiny-N warning.</strong> NFL T0 spread N total = {n_all} settled "
        f"one-line-per-game unique favorites on this tape ({date_txt}). "
        f"Live D band N = {n_d}. This is a few NFL Sundays, not a season. "
        "HOLD on changing live D."
        if tiny or n_all == 0 else
        f"NFL T0 spread N total = {n_all}. Live D band N = {n_d}. Still research only."
    )
    skip_bits = ", ".join(f"{k}={v}" for k, v in sorted((bags.get("skips") or {}).items())) or "none"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>NFL T0 spread buckets</title>
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
<h1>NFL T0 spread buckets — with-fee P&amp;L</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. HOLD on changing live D.
Paul asked after seeing D (selection bias). Did not start a second
<code>live_strategy_b.py</code>. Did not sell. Did not write <code>sports_queue</code>.</p>
<p class="banner">{tiny_banner}</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Paul note</h2>
<p><strong>HOLD</strong> on changing live D. Live D is one spread per game, any sport,
favorite Yes in (0.50, 0.90). This page is NFL only, same T0 and one-line pick,
with-fee size-1 Yes held to settle. {esc(sample_note(n_all))}. IS N=0 — every T0
on this tape is 2026 (after 2024-01-01), so the whole book is out-of-sample.
Annualized rate of return (Ann ROR) is omitted when average hold is same-day
(NFL spreads settle the same Sunday). House formula only; do not invent a
second one. Quality over N. Empty buckets are empty — we did not invent
seasons we did not collect.</p>

<h2>Freeze</h2>
<ul>
<li><strong>Universe:</strong> pro football / NFL two-sided spreads on this tape. Totals and moneyline are out. College football is out.</li>
<li><strong>T0:</strong> first trusted kickoff price — Kalshi/Gemini occurrence, else listed/feed with seconds=00. Same as <code>t0_all_games_stats.py</code> / live D. Not tape-resume. Not first-competitive-without-a-clock.</li>
<li><strong>Favorite:</strong> higher T0 Yes ask on that venue book, unique, Yes ask &gt; 0.50. Skip 50-50.</li>
<li><strong>Line:</strong> one per game, closest T0 favorite Yes to 50¢ among two-sided unique-fav lines (live D). Primary venue per line is cheapest documented-fee Yes, then Kalshi &gt; Gemini &gt; Polymarket &gt; Novig.</li>
<li><strong>Trade:</strong> buy 1 Yes on the spread favorite at the T0 ask, taker, documented fees in, hold to official settlement. Win: $1 − ask − fee. Loss: −ask − fee.</li>
<li><strong>Fees:</strong> Kalshi 0.07×p×(1−p) to $0.0001; Gemini same formula rounded up to a cent; Polymarket 0.0695×p×(1−p) banker's cent. Novig omitted (no documented coefficient — not treated as zero-fee).</li>
<li><strong>Buckets:</strong> living-dashboard decades. &gt;90 is strictly above 90¢. 0.90 sits in 80-89 and is <em>not</em> in live D (D is exclusive of 0.50 and 0.90).</li>
<li><strong>Voids / 50-50 / pushes:</strong> out of the P&amp;L denominator. N_void is shown. Pending games (today’s slate) are not settled.</li>
<li><strong>Grain:</strong> headline is one game. All-lines N is a footnote only.</li>
</ul>

<h2>Primary — with-fee P&amp;L by bucket</h2>
<p class="note">Size 1 contract. Click column headers to sort. {esc(line_note)}</p>
{html_table(PRIMARY_HEADERS, primary_rows)}

<h2>Canonical compare — buckets vs live D band</h2>
<p class="note">Control is the live D band row: T0 favorite Yes in (0.50, 0.90) on the same
one-line-per-game NFL book. Deltas are vs that row. Ann ROR is omitted when the
hold is same-day. IS N=0. Do not KEEP from this ranking — selection bias, tiny N.</p>
{html_table(COMPARE_HEADERS, compare_rows)}

<h2>Inventory on this tape</h2>
<ul>
<li>NFL spread venue-game books paired: {esc(bags.get("n_raw_books"))}.</li>
<li>Settled two-sided trusted-T0 unique-fav with a documented fee: {esc(bags.get("n_scored_venue"))} venue-lines; {esc(bags.get("n_lines"))} after one venue per line; <strong>{esc(bags.get("n_match"))} one-per-game</strong>.</li>
<li>Live D band one-per-game N: {esc(n_d)}.</li>
<li>All unique fav one-per-game N: {esc(n_all)}. All-lines N: {esc(n_lines)}.</li>
<li>N_void (one-per-game): {esc(bags.get("n_void_match"))}. 50-50 skipped: {esc(bags.get("n_fifty"))}. Pending / not settled: {esc(bags.get("n_pending"))}. No documented fee: {esc(bags.get("n_no_fee"))}.</li>
<li>Trusted-T0 skip reasons (not in P&amp;L): {esc(skip_bits)}.</li>
<li>Settled T0 dates: {esc(date_txt)}.</li>
<li>Tape Yes ticks: {esc(meta.get("seen_min") or "—")} through {esc(meta.get("seen_max") or "—")}. Streamed {esc(meta.get("n_lines"))} pro-football lines, {esc(meta.get("n_yes"))} spread Yes ticks.</li>
</ul>

<h2>One-per-game tickets</h2>
<p class="note">Every settled unique-fav NFL spread we would have bought under the
all-unique-fav rule. Live D would have taken only the rows marked In D band = yes.</p>
{html_table(TRADE_HEADERS, trade_rows)}

<p class="tiny">Generator: <code>tools/nfl_t0_spread_buckets_20261025.py</code>.
T0 / settlement: <code>tools/t0_all_games_stats.py</code>. Fees:
<code>write_t0_band_from_stay_above.documented_leg_fee</code>. Live D line pick:
<code>prediction_systems.pick_spread_line</code>. Tests:
<code>tools/test_nfl_t0_spread_buckets_20261025.py</code>.
Written {esc(payload.get("written_at"))} ET. file:// {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PARENT.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def main() -> int:
    print("scoring NFL T0 spreads (this tape only)", flush=True)
    payload = build_payload()
    path = write_html(payload)
    all_q = payload["recs"][ALL_ID]
    d_q = payload["recs"][D_BAND_ID]
    print(
        f"NFL T0 spread N total={all_q['n']} pnl={all_q['pnl_sum']:.4f} "
        f"D-band N={d_q['n']} pnl={d_q['pnl_sum']:.4f} wrote {path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
