"""Collect NFL Type A (wins-by-n) settlements and score T0 cover-Yes.

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not start live_strategy_b.py. Does not write sports_queue. Does not change live D.
"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odds_cross_winrate_20261020 import (
    SETTLE_CACHE,
    add_settlement,
    game_norm,
    kalshi_event_markets,
    load_local_settlements,
    parse_dt,
)
from prediction_paths import RAW_DIR as RAW
from price_memory import market_type_from, norm_number, norm_side
import t0_all_games_stats as t0
from decimal import Decimal

from t0_fav_lt90_baseline_20261024 import VENUE_RANK, fav_yes_pnl, fmt_pct
from write_t0_band_from_stay_above import documented_leg_fee
from nfl_t0_spread_buckets_20261025 import (
    ALL_ID,
    BUCKETS,
    D_BAND_ID,
    book_trade,
    bucket_of,
    format_money,
    in_d_band,
    is_unique_fav,
    pick_one_per_game,
    sample_note,
)

ET = ZoneInfo("America/New_York")
OVERLAY_PATH = RAW / "nfl_t0_spread_settlements_20261025.json"
QUEUE_PATH = RAW / "sports_queue.json"
NFL_DATE_TOKS = (
    "26OCT18", "26OCT19", "26OCT20", "26OCT21", "26OCT22",
    "26OCT25", "26OCT26",
)
GAME_OVER = timedelta(hours=3, minutes=30)
ABSORB = 0.05
WINPCT_BUCKETS = BUCKETS + (("<50", 0.0, 0.50, "gt_lt_low"),)
WINPCT_ORDER = [label for label, *_ in WINPCT_BUCKETS] + ["50-50", "missing T0", D_BAND_ID, ALL_ID]
WINPCT_HEADERS = [
    ("Bucket", "text"),
    ("N", "num"),
    ("Wins", "num"),
    ("Win %", "num"),
    ("With-fee PnL $", "num"),
    ("N with fee", "num"),
    ("Note", "text"),
]


def ticker_in_nfl_window(ticker: str) -> bool:
    up = str(ticker or "").upper()
    return any(tok in up for tok in NFL_DATE_TOKS)


def collect_nfl_event_tickers() -> list[tuple[str, str]]:
    """Spread + game event tickers from local dumps and the catalog. Read-only on queue."""
    found: dict[str, str] = {}

    def add(ticker: str, game: str) -> None:
        ticker = str(ticker or "").strip()
        if not ticker:
            return
        up = ticker.upper()
        if "KXNFLSPREAD" not in up and "KXNFLGAME" not in up:
            return
        if not ticker_in_nfl_window(ticker):
            return
        prev = found.get(ticker) or ""
        if len(game) > len(prev):
            found[ticker] = game

    for path in sorted(RAW.glob("nfl_*_kalshi.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        game = str(payload.get("game") or "")
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            add(str(event.get("event_ticker") or ""), game or str(event.get("title") or ""))
    if QUEUE_PATH.is_file():
        try:
            blob = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = {}
        for sport_row in blob.get("sports") or []:
            for row in sport_row.get("matched") or []:
                if not isinstance(row, dict):
                    continue
                kalshi = row.get("kalshi") if isinstance(row.get("kalshi"), dict) else {}
                title = str(
                    row.get("title_kalshi") or row.get("game") or row.get("title") or ""
                )
                add(str(kalshi.get("spread") or ""), title)
                add(str(kalshi.get("game") or ""), title)
    return sorted(found.items())


def fetch_nfl_kalshi_results() -> list[dict]:
    """Public Kalshi markets for this tape's NFL spread/game events. Includes Oct 25."""
    items = collect_nfl_event_tickers()
    print(f"fetching Kalshi NFL events {len(items)}", flush=True)
    rows: list[dict] = []

    def one(item: tuple[str, str]) -> list[dict]:
        ticker, game = item
        found: list[dict] = []
        for market in kalshi_event_markets(ticker):
            result = str(market.get("result") or "").lower()
            if result not in ("yes", "no"):
                continue
            mticker = str(market.get("ticker") or "")
            kind = market_type_from(mticker, ticker, str(market.get("title") or ""))
            if kind is None:
                continue
            number = market.get("floor_strike")
            add_settlement(found, {
                "source": "kalshi_api_nfl",
                "venue": "Kalshi",
                "sport": "pro football",
                "game": game or market.get("title") or "",
                "market_type": kind,
                "side": market.get("yes_sub_title") or market.get("title") or "",
                "number": number,
                "result": result,
                "ticker": mticker,
                "occurrence": market.get("occurrence_datetime")
                or market.get("expected_expiration_time")
                or "",
            })
        return found

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(one, item) for item in items]
        done = 0
        for fut in as_completed(futs):
            for item in fut.result() or []:
                add_settlement(rows, item)
            done += 1
            if done % 10 == 0:
                print(f"  kalshi NFL {done}/{len(items)} settlements {len(rows)}", flush=True)
    print(f"kalshi NFL api settlements {len(rows)}", flush=True)
    return rows


def _sig(row: dict) -> tuple:
    return (
        row.get("venue_n") or row.get("venue"),
        row.get("game_n") or game_norm(row.get("game") or ""),
        row.get("market_type"),
        row.get("side_n") or "",
        row.get("number_n") or "",
        row.get("result"),
        row.get("ticker"),
    )


def merge_settlements(*bags: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    for bag in bags:
        for row in bag:
            if not isinstance(row, dict):
                continue
            if (row.get("result") or "").strip().lower() not in ("yes", "no"):
                continue
            sig = _sig(row)
            if sig in seen:
                continue
            seen.add(sig)
            out.append(row)
    return out


def load_nfl_settlements(*, fetch: bool = True) -> tuple[list[dict], dict]:
    """Cache (Oct 16–21 window) + local nfl_* dumps + a fresh Kalshi pull for Oct 22/25.

    The living odds_cross DATE_TOKENS stop at 26OCT21, so Sunday Oct 25 never entered
    SETTLE_CACHE. Local nfl_*_kalshi.json already has afternoon finalized spreads;
    this also re-fetches so 4pm/8:20 games are not stuck on a stale dump.
    """
    cache: list[dict] = []
    if SETTLE_CACHE.is_file():
        try:
            raw = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = []
        if isinstance(raw, list):
            cache = [r for r in raw if isinstance(r, dict)]
    local = [
        r for r in load_local_settlements()
        if str(r.get("sport") or "").lower() in {"pro football", "nfl", ""}
        or "nfl" in str(r.get("ticker") or "").lower()
        or "nfl" in str(r.get("game") or "").lower()
    ]
    fetched: list[dict] = []
    if fetch:
        fetched = fetch_nfl_kalshi_results()
        try:
            OVERLAY_PATH.write_text(json.dumps(fetched), encoding="utf-8")
        except OSError:
            pass
    elif OVERLAY_PATH.is_file():
        try:
            blob = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = []
        if isinstance(blob, list):
            fetched = [r for r in blob if isinstance(r, dict)]
    merged = merge_settlements(cache, local, fetched)
    meta = {
        "n_cache": len(cache),
        "n_local": len(local),
        "n_fetched": len(fetched),
        "n_merged": len(merged),
        "n_spread": sum(1 for r in merged if str(r.get("market_type") or "") == "spread"),
        "fetched": bool(fetch),
    }
    print(
        f"NFL settlements cache={meta['n_cache']} local={meta['n_local']} "
        f"fetched={meta['n_fetched']} merged={meta['n_merged']} "
        f"spread={meta['n_spread']}",
        flush=True,
    )
    return merged, meta


def occ_map_prefer_listed(catalog: list[dict], settlements: list[dict]) -> dict[str, datetime]:
    """Listed kickoff beats Kalshi expiration (often 20:00Z on a 1pm ET game)."""
    out: dict[str, datetime] = {}
    for row in catalog:
        listed = row.get("listed_start") or row.get("date") or ""
        dt = parse_dt(listed)
        if dt is None:
            continue
        dt = t0.to_et(dt)
        if not t0.is_scheduled_clock(dt):
            continue
        key = str(row.get("game_n") or game_norm(row.get("game") or ""))
        if key:
            out[key] = dt
    extra = t0.start_lookup_from_settlements(settlements)
    for key, dt in extra.items():
        if key not in out:
            out[key] = dt
    return out


def team_key(side: str) -> str:
    return norm_side(str(side or ""), "spread")


def build_nfl_cover_index(settlements: list[dict]) -> dict[tuple, dict]:
    """Match on (game_n, number, team) so 'wins by over' equals 'wins by more than'."""
    idx: dict[tuple, dict] = {}
    for row in settlements:
        if str(row.get("market_type") or "") != "spread":
            continue
        result = str(row.get("result") or "").lower()
        if result not in ("yes", "no"):
            continue
        game = row.get("game_n") or game_norm(row.get("game") or "")
        number = row.get("number_n") or norm_number(row.get("number") or "")
        team = row.get("side_n") or team_key(row.get("side") or "")
        if not game or not team:
            continue
        key = (game, number, team)
        prev = idx.get(key)
        if prev is None or str(prev.get("source") or "").endswith("local"):
            idx[key] = row
        # also index without number for last-resort
        idx.setdefault((game, "", team), row)
    return idx


def lookup_nfl_cover(book: dict, cover_index: dict[tuple, dict], letter: str) -> dict | None:
    game = str(book.get("game_n") or game_norm(book.get("game") or ""))
    number = norm_number(book.get("number") or "")
    side = book.get("side_a") if letter == "a" else book.get("side_b")
    team = team_key(side)
    if not game or not team:
        return None
    return cover_index.get((game, number, team)) or cover_index.get((game, "", team))


def absorbing_from_ticks(ticks: list) -> str | None:
    if not ticks:
        return None
    px = float(ticks[-1][1])
    if px >= 1.0 - ABSORB:
        return "win"
    if px <= ABSORB:
        return "loss"
    return None


def kick_dt(book: dict) -> datetime | None:
    raw = book.get("listed_raw") or book.get("clock") or ""
    dt = parse_dt(raw)
    return t0.to_et(dt) if dt is not None else None


def overlay_cover_settlement(
    book: dict,
    cover_index: dict[tuple, dict],
    *,
    now: datetime | None = None,
) -> None:
    """Fill pending cover-Yes from team+number index, then middles, then last-tick.

    Last-tick absorbing is only used after listed kickoff + 3.5 hours so a live
    8:20pm game cannot be marked settled from an in-game 0.99 print.
    """
    now = now or datetime.now(ET)
    for letter, off_key, src_key in (
        ("a", "off_a", "off_src_a"),
        ("b", "off_b", "off_src_b"),
    ):
        if book.get(off_key) in ("win", "loss"):
            continue
        hit = lookup_nfl_cover(book, cover_index, letter)
        if hit:
            book[off_key] = "win" if hit.get("result") == "yes" else "loss"
            book[src_key] = hit.get("source") or "nfl_cover_index"
            book["official_ticker_" + letter] = hit.get("ticker") or ""
    kick = kick_dt(book)
    over = bool(kick and now >= kick + GAME_OVER)
    if over:
        for letter, ticks, off_key, src_key in (
            ("a", book.get("yes_a") or [], "off_a", "off_src_a"),
            ("b", book.get("yes_b") or [], "off_b", "off_src_b"),
        ):
            if book.get(off_key) in ("win", "loss"):
                continue
            proxy = absorbing_from_ticks(ticks)
            if proxy:
                book[off_key] = proxy
                book[src_key] = "last-tick absorbing (kickoff + 3.5h)"
    off_a = book.get("off_a")
    off_b = book.get("off_b")
    a_known = off_a in ("win", "loss")
    b_known = off_b in ("win", "loss")
    if a_known and b_known:
        if off_a == "win" and off_b == "win":
            book["void"] = True
            book["settled"] = False
            book["middle"] = False
            book["winner"] = None
            return
        book["void"] = False
        book["middle"] = off_a == "loss" and off_b == "loss"
        if off_a == "win" and off_b != "win":
            book["winner"] = "a"
        elif off_b == "win" and off_a != "win":
            book["winner"] = "b"
        else:
            book["winner"] = None
        book["settled"] = True
    elif a_known or b_known:
        book["void"] = False
        book["middle"] = False
        if off_a == "win":
            book["winner"] = "a"
            book["settled"] = True
        elif off_b == "win":
            book["winner"] = "b"
            book["settled"] = True
        else:
            # one side lost, the other still pending — do not invent a winner
            book["settled"] = False
            book["one_side_known"] = True
    fav = book.get("fav") or ""
    if fav == "a" and a_known:
        book["fav_won"] = off_a == "win"
        book["cover_known"] = True
    elif fav == "b" and b_known:
        book["fav_won"] = off_b == "win"
        book["cover_known"] = True
    elif book.get("settled") and fav:
        book["fav_won"] = book.get("winner") == fav
        book["cover_known"] = True
    elif book.get("settled") and book.get("middle"):
        book["fav_won"] = False
        book["cover_known"] = True


def cover_yes_known(book: dict) -> bool:
    if book.get("void"):
        return False
    if book.get("cover_known"):
        return True
    fav = book.get("fav") or ""
    if fav == "a":
        return book.get("off_a") in ("win", "loss")
    if fav == "b":
        return book.get("off_b") in ("win", "loss")
    return bool(book.get("settled"))


def score_t0_yes(book: dict) -> float | None:
    """The Type A Yes we bucket: unique-fav if it exists, else the only T0 Yes."""
    if book.get("t0_fav") is not None:
        return float(book.get("t0_fav"))
    if book.get("t0_a") is not None and book.get("t0_b") is None:
        return float(book.get("t0_a"))
    if book.get("t0_b") is not None and book.get("t0_a") is None:
        return float(book.get("t0_b"))
    return None


def line_won(book: dict) -> bool | None:
    if not cover_yes_known(book):
        return None
    if book.get("fav_won") is not None:
        return bool(book.get("fav_won"))
    fav = book.get("fav") or ""
    if fav == "a":
        return book.get("off_a") == "win"
    if fav == "b":
        return book.get("off_b") == "win"
    if book.get("middle"):
        return False
    return book.get("winner") is not None


def winpct_note(n: int) -> str:
    if n <= 0:
        return "N=0 on this tape"
    if n < 8:
        return "tiny N — do not wire D NFL"
    if n < 20:
        return "small sample"
    return ""


def winpct_stats(books: list[dict], *, label: str) -> dict:
    n = len(books)
    n_win = sum(1 for b in books if line_won(b))
    wr = (100.0 * n_win / n) if n else None
    fee_trades = []
    for book in books:
        trade = book_trade(book, label)
        if trade is not None:
            fee_trades.append(trade)
    pnl = sum(float(t.get("pnl_d") or 0) for t in fee_trades) if fee_trades else None
    if n == 0:
        pnl = None
    return {
        "arm": label,
        "n": n,
        "n_win": n_win,
        "win_pct": wr,
        "pnl_sum": pnl,
        "n_fee": len(fee_trades),
        "note": winpct_note(n),
        "books": books,
        "trades": fee_trades,
    }


def bucket_winpct(books: list[dict], *, prefix: str) -> dict[str, dict]:
    by: dict[str, list[dict]] = {label: [] for label, *_ in WINPCT_BUCKETS}
    by["50-50"] = []
    by["missing T0"] = []
    for book in books:
        px = score_t0_yes(book)
        lab = bucket_of(px)
        if lab == "under-50":
            lab = "<50"
        by.setdefault(lab, []).append(book)
    recs = {}
    for label, *_ in WINPCT_BUCKETS:
        recs[label] = winpct_stats(by.get(label) or [], label=f"{prefix}:{label}")
    recs["50-50"] = winpct_stats(by.get("50-50") or [], label=f"{prefix}:50-50")
    recs["missing T0"] = winpct_stats(by.get("missing T0") or [], label=f"{prefix}:missing")
    recs[D_BAND_ID] = winpct_stats(
        [b for b in books if in_d_band(score_t0_yes(b))],
        label=f"{prefix}:d_band",
    )
    recs[ALL_ID] = winpct_stats(books, label=f"{prefix}:all")
    return recs


def winpct_row(q: dict, *, display: str | None = None) -> list[str]:
    n = int(q.get("n") or 0)
    pnl = q.get("pnl_sum")
    n_fee = int(q.get("n_fee") or 0)
    name = display if display is not None else str(q.get("arm") or "")
    if display is None and ":" in name:
        name = name.split(":", 1)[-1]
    return [
        name,
        str(n),
        str(q.get("n_win") or 0) if n else "0",
        fmt_pct(q.get("win_pct")) if n else "—",
        format_money(pnl) if n_fee else "—",
        str(n_fee),
        sample_note(n) if n else (q.get("note") or "N=0 on this tape"),
    ]


def is_sunday_book(book: dict, today: str = "2026-10-25") -> bool:
    listed = str(book.get("listed_raw") or book.get("clock") or "")
    if listed.startswith(today):
        return True
    dt = parse_dt(listed)
    if dt is None:
        return False
    return t0.to_et(dt).date().isoformat() == today


# Closed interval Paul asked: 51¢ through 69¢. Exact 0.50 is out.
BAND_51_69_LO = 0.51
BAND_51_69_HI = 0.69
BAND_51_69_ID = "T0 Yes 0.51–0.69"
BAND_50_59_ID = "50-59 (old: >0.50 and <0.60)"
BAND_60_69_ID = "60-69 (old: ≥0.60 and <0.70)"
BAND_OLD_COMBINED_ID = "50-59 + 60-69 (old decades)"
BAND_UF_ID = "51-69 unique-fav one-per-game (secondary)"


def in_closed_band(px, lo: float, hi: float) -> bool:
    if px is None:
        return False
    p = float(px)
    return p >= lo - 1e-12 and p <= hi + 1e-12


def in_51_69(px) -> bool:
    """T0 Yes in [0.51, 0.69] inclusive. Drops exact 0.50."""
    return in_closed_band(px, BAND_51_69_LO, BAND_51_69_HI)


def in_old_50_59(px) -> bool:
    """Living 50-59 decade: strictly above 50¢ and below 60¢."""
    if px is None:
        return False
    p = float(px)
    return p > 0.50 + 1e-12 and p < 0.60 - 1e-12


def in_old_60_69(px) -> bool:
    """Living 60-69 decade: 60¢ inclusive through just under 70¢."""
    if px is None:
        return False
    p = float(px)
    return p >= 0.60 - 1e-12 and p < 0.70 - 1e-12


def t0_yes_trade(book: dict, arm_id: str) -> dict | None:
    """1-contract taker Yes at T0 ask + documented fee. Unknown fee → None."""
    px = score_t0_yes(book)
    if px is None:
        return None
    won = line_won(book)
    if won is None:
        return None
    venue = str(book.get("venue") or "")
    fee = documented_leg_fee(venue, px)
    if fee is None:
        return None
    pnl = fav_yes_pnl(px, fee, won=won)
    cost = Decimal(str(px)) + Decimal(str(fee))
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
        "t0_fav": float(px),
        "t0_yes": float(px),
        "bucket": bucket_of(px),
        "fee": float(fee),
        "fee_known": True,
        "cost": float(cost),
        "won": bool(won),
        "pnl_d": float(pnl),
        "pnl": pnl_pct,
        "days": days,
        "opened": opened,
        "closed": closed,
        "entry_date": opened.date().isoformat() if opened else "",
        "be": float(cost),
        "grain": book.get("_grain") or "line",
        "two_sided": bool(book.get("two_sided")),
        "t0_source": book.get("t0_source") or "",
        "t0_label": book.get("t0_label") or "",
        "n_lines": book.get("_n_lines") or 1,
        "n_venues": book.get("_n_venues") or 1,
        "sunday": is_sunday_book(book),
        "one_sided": not bool(book.get("two_sided")),
        "_side_letter": str(book.get("_side_letter") or ""),
        "side_a": book.get("side_a"),
        "side_b": book.get("side_b"),
        "t0_a": book.get("t0_a"),
        "t0_b": book.get("t0_b"),
        "fav": book.get("fav"),
    }


def t0_no_cash(book: dict) -> float | None:
    """Venue-correct T0 No cash on the same cover as the Yes we bucketed.

    Kalshi house No = 1 − Yes-wire (buy side = ask). Polymarket BUY_SHORT No
    cash = 1 − Yes-price. Gemini / Novig on this tape are the same 1 − T0 Yes
    (the stream is Yes ticks; Novig still has no documented fee).
    """
    yes = score_t0_yes(book)
    if yes is None:
        return None
    cash = 1.0 - float(yes)
    if cash <= 0.0 or cash >= 1.0:
        return None
    return cash


def t0_no_won(book: dict) -> bool | None:
    """No wins when that cover-Yes lost (including middles: both Yes lose)."""
    yes = line_won(book)
    if yes is None:
        return None
    return not bool(yes)


def t0_no_trade(book: dict, arm_id: str) -> dict | None:
    """1-contract taker No at T0 No cash + documented fee. Unknown fee → None."""
    cash = t0_no_cash(book)
    if cash is None:
        return None
    won = t0_no_won(book)
    if won is None:
        return None
    venue = str(book.get("venue") or "")
    fee = documented_leg_fee(venue, cash)
    if fee is None:
        return None
    pnl = fav_yes_pnl(cash, fee, won=won)
    cost = Decimal(str(cash)) + Decimal(str(fee))
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
    yes = score_t0_yes(book)
    return {
        "arm": arm_id,
        "sport": "pro football",
        "kind": "spread",
        "venue": venue,
        "game": book.get("game") or "",
        "game_n": book.get("game_n") or "",
        "number": book.get("number") or "",
        "fav_name": book.get("fav_name") or "",
        "t0_fav": float(yes) if yes is not None else None,
        "t0_yes": float(yes) if yes is not None else None,
        "t0_no": float(cash),
        "side": "no",
        "bucket": bucket_of(yes) if yes is not None else "",
        "fee": float(fee),
        "fee_known": True,
        "cost": float(cost),
        "won": bool(won),
        "pnl_d": float(pnl),
        "pnl": pnl_pct,
        "days": days,
        "opened": opened,
        "closed": closed,
        "entry_date": opened.date().isoformat() if opened else "",
        "be": float(cost),
        "grain": book.get("_grain") or "line",
        "two_sided": bool(book.get("two_sided")),
        "t0_source": book.get("t0_source") or "",
        "t0_label": book.get("t0_label") or "",
        "n_lines": book.get("_n_lines") or 1,
        "n_venues": book.get("_n_venues") or 1,
        "sunday": is_sunday_book(book),
        "one_sided": not bool(book.get("two_sided")),
        "_side_letter": str(book.get("_side_letter") or ""),
        "side_a": book.get("side_a"),
        "side_b": book.get("side_b"),
        "t0_a": book.get("t0_a"),
        "t0_b": book.get("t0_b"),
        "fav": book.get("fav"),
    }


def pick_fee_primary_line(books: list[dict]) -> list[dict]:
    """One venue per (game, line, side). Documented-fee venue first, then cheaper Yes.

    Unexploded books have no _side_letter, so they still collapse to one venue
    per (game, line). Exploded cover-Yes sides keep both the dog and the favorite.
    """
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for book in books:
        key = (
            str(book.get("game_n") or book.get("game") or ""),
            str(book.get("number") or ""),
            str(book.get("_side_letter") or ""),
        )
        bags[key].append(book)
    out = []
    for _key, group in bags.items():
        group = sorted(
            group,
            key=lambda b: (
                0 if documented_leg_fee(
                    str(b.get("venue") or ""), score_t0_yes(b)
                ) is not None else 1,
                float(score_t0_yes(b) if score_t0_yes(b) is not None else 9),
                VENUE_RANK.get(str(b.get("venue") or ""), 9),
                str(b.get("venue") or ""),
            ),
        )
        chosen = dict(group[0])
        px = score_t0_yes(chosen)
        if chosen.get("t0_fav") is None and px is not None:
            chosen["t0_fav"] = px
        chosen["_n_venues"] = len(group)
        chosen["_grain"] = "line"
        chosen["_venues"] = sorted({str(b.get("venue") or "") for b in group})
        out.append(chosen)
    return out


def collect_t0_yes_band(books: list[dict], pred) -> dict:
    """Split Type A books whose scored T0 Yes matches pred. Open stays out of PnL."""
    settled: list[dict] = []
    voids: list[dict] = []
    open_books: list[dict] = []
    for book in books:
        px = score_t0_yes(book)
        if not pred(px):
            continue
        if book.get("void"):
            voids.append(book)
        elif cover_yes_known(book):
            settled.append(book)
        else:
            open_books.append(book)
    return {
        "settled": settled,
        "voids": voids,
        "open": open_books,
    }


def band_edge_counts(books: list[dict]) -> dict:
    """How 51-69 differs from old 50-59 + 60-69 decades."""
    n_exact_50 = 0
    n_between_50_51 = 0
    n_between_69_70 = 0
    n_old_combined = 0
    n_51_69 = 0
    for book in books:
        px = score_t0_yes(book)
        if px is None:
            continue
        p = float(px)
        if abs(p - 0.50) <= 1e-12:
            n_exact_50 += 1
        if 0.50 + 1e-12 < p < 0.51 - 1e-12:
            n_between_50_51 += 1
        if 0.69 + 1e-12 < p < 0.70 - 1e-12:
            n_between_69_70 += 1
        if in_old_50_59(p) or in_old_60_69(p):
            n_old_combined += 1
        if in_51_69(p):
            n_51_69 += 1
    return {
        "n_exact_50": n_exact_50,
        "n_between_50_51": n_between_50_51,
        "n_between_69_70": n_between_69_70,
        "n_old_combined": n_old_combined,
        "n_51_69": n_51_69,
    }


def in_old_50_69_neighborhood(px) -> bool:
    """Old 50-59 ∪ 60-69: (0.50, 0.70). Used so the decade split adds."""
    return in_old_50_59(px) or in_old_60_69(px)


def score_t0_yes_band(
    books: list[dict],
    *,
    label: str,
    grain: str = "all-lines",
    pred=in_51_69,
    pick: bool = True,
    trade_fn=None,
    won_fn=None,
) -> dict:
    """Settled 1-contract with-fee PnL on T0 Yes matching pred. Open excluded.

    trade_fn / won_fn swap in Buy No on the same rows (fees are not the exact
    negative of the Yes book).
    """
    trade_fn = trade_fn or t0_yes_trade
    won_fn = won_fn or line_won
    bags = collect_t0_yes_band(books, pred)
    def _line_key(b: dict) -> tuple:
        return (
            str(b.get("game_n") or b.get("game") or ""),
            str(b.get("number") or ""),
            str(b.get("_side_letter") or ""),
        )
    if pick:
        settled = pick_fee_primary_line(bags["settled"])
        voids = pick_fee_primary_line(bags["voids"])
        settled_keys = {_line_key(b) for b in settled}
        open_raw = [b for b in bags["open"] if _line_key(b) not in settled_keys]
        open_books = pick_fee_primary_line(open_raw)
    else:
        settled = list(bags["settled"])
        voids = list(bags["voids"])
        settled_keys = {_line_key(b) for b in settled}
        open_books = [b for b in bags["open"] if _line_key(b) not in settled_keys]
    n = len(settled)
    n_win = sum(1 for b in settled if won_fn(b))
    wr = (100.0 * n_win / n) if n else None
    trades = []
    no_fee = []
    for book in settled:
        trade = trade_fn(book, label)
        if trade is None:
            no_fee.append(book)
        else:
            trades.append(trade)
    n_fee = len(trades)
    pnls = [float(t.get("pnl_d") or 0) for t in trades]
    fees = [float(t.get("fee") or 0) for t in trades]
    pnl_sum = sum(pnls) if pnls else None
    mean_pnl = (sum(pnls) / n_fee) if n_fee else None
    total_fees = sum(fees) if fees else None
    n_one_sided = sum(1 for b in settled if not b.get("two_sided"))
    no_fee_venues = sorted({str(b.get("venue") or "") or "unknown" for b in no_fee})
    open_games = sorted({str(b.get("game") or b.get("game_n") or "") for b in open_books})
    note = sample_note(n)
    if n_fee < n:
        hole = ", ".join(no_fee_venues) or "unknown venue"
        extra = f"N_no_fee={n - n_fee} ({hole}) omitted from $ — not treated as zero-fee"
        note = f"{extra}. {note}".strip() if note else extra
    if n_one_sided:
        extra = f"includes {n_one_sided} one-sided T0 Yes"
        note = f"{extra}. {note}".strip() if note else extra
    if open_books:
        extra = f"open excluded N={len(open_books)} (not in $)"
        note = f"{extra}. {note}".strip() if note else extra
    if not note and n == 0:
        note = "N=0 — no settled Type A T0 Yes in this band"
    return {
        "arm": label,
        "grain": grain,
        "n": n,
        "n_win": n_win,
        "win_pct": wr,
        "pnl_sum": pnl_sum if n_fee else None,
        "mean": mean_pnl,
        "total_fees": total_fees if n_fee else None,
        "n_fee": n_fee,
        "n_no_fee": n - n_fee,
        "n_void": len(voids),
        "n_open": len(open_books),
        "n_one_sided": n_one_sided,
        "no_fee_venues": no_fee_venues,
        "open_games": open_games,
        "note": note,
        "books": settled,
        "voids": voids,
        "open_books": open_books,
        "no_fee_books": no_fee,
        "trades": trades,
    }


def unique_fav_one_per_game_band(books: list[dict], *, label: str) -> dict:
    """Secondary grain: unique-fav closest-to-50¢, one line per game, then 51-69."""
    settled = collect_t0_yes_band(books, lambda px: is_unique_fav(px)).get("settled") or []
    with_fav = []
    for book in settled:
        row = dict(book)
        px = score_t0_yes(row)
        if row.get("t0_fav") is None and px is not None:
            row["t0_fav"] = px
        if row.get("t0_fav") is not None:
            with_fav.append(row)
    matches = pick_one_per_game(with_fav) if with_fav else []
    return score_t0_yes_band(matches, label=label, grain="unique-fav one-per-game", pred=in_51_69)


def band_primary_row(q: dict) -> list[str]:
    n = int(q.get("n") or 0)
    n_fee = int(q.get("n_fee") or 0)
    return [
        str(q.get("arm") or ""),
        str(n),
        str(q.get("n_win") or 0) if n else "0",
        fmt_pct(q.get("win_pct")) if n else "—",
        format_money(q.get("pnl_sum")) if n_fee else "—",
        format_money(q.get("mean")) if n_fee else "—",
        format_money(q.get("total_fees")) if n_fee else "—",
        str(q.get("n_void") or 0),
        str(n_fee),
        str(q.get("note") or ""),
    ]


# Every T0 Yes decade. Half-open [lo, hi) except 90-100 which is 90+ ([0.90, 1.00]).
DECILE_SPECS = (
    ("0-9", 0.00, 0.10, "[0.00, 0.10)"),
    ("10-19", 0.10, 0.20, "[0.10, 0.20)"),
    ("20-29", 0.20, 0.30, "[0.20, 0.30)"),
    ("30-39", 0.30, 0.40, "[0.30, 0.40)"),
    ("40-49", 0.40, 0.50, "[0.40, 0.50)"),
    ("50-59", 0.50, 0.60, "[0.50, 0.60)"),
    ("60-69", 0.60, 0.70, "[0.60, 0.70)"),
    ("70-79", 0.70, 0.80, "[0.70, 0.80)"),
    ("80-89", 0.80, 0.90, "[0.80, 0.90)"),
    ("90-100", 0.90, None, "[0.90, 1.00] / 90+"),
)
DECILE_20_39_ID = "20-39 combined (20-29 + 30-39)"
DECILE_10_29_ID = "10-29 combined (10-19 + 20-29)"
DECILE_ALL_ID = "all Type A cover-Yes (sum of decades)"
DECILE_ALL_NO_ID = "all Type A cover-No (sum of decades)"
DECILE_UF_NOTE = "unique-fav one-per-game (secondary) — empty below 50¢ by construction"


def in_half_open(px, lo: float, hi: float) -> bool:
    """T0 Yes in [lo, hi)."""
    if px is None:
        return False
    p = float(px)
    return p >= lo - 1e-12 and p < hi - 1e-12


def in_90_100(px) -> bool:
    """T0 Yes in [0.90, 1.00] / 90+."""
    if px is None:
        return False
    return float(px) >= 0.90 - 1e-12


def in_20_39(px) -> bool:
    """T0 Yes in [0.20, 0.40) = 20-29 ∪ 30-39."""
    return in_half_open(px, 0.20, 0.40)


def in_20_29(px) -> bool:
    return in_half_open(px, 0.20, 0.30)


def in_10_19(px) -> bool:
    return in_half_open(px, 0.10, 0.20)


def in_10_29(px) -> bool:
    """T0 Yes in [0.10, 0.30) = 10-19 ∪ 20-29."""
    return in_half_open(px, 0.10, 0.30)


def in_30_39(px) -> bool:
    return in_half_open(px, 0.30, 0.40)


def decile_pred(lo: float, hi: float | None):
    if hi is None:
        return in_90_100
    return lambda px, _lo=lo, _hi=hi: in_half_open(px, _lo, _hi)


def decile_arm_label(short: str, interval: str, *, side: str = "yes") -> str:
    base = f"{short} {interval}"
    if side == "no":
        return f"Buy No {base}"
    return base


def explode_cover_yes_sides(books: list[dict]) -> list[dict]:
    """One row per Type A cover-Yes with a T0 ask, including dogs.

    A two-sided line Arizona 0.31 / Denver 0.64 becomes two tickets. Win is
    that side's cover-Yes settling YES. Parent void (both Yes) voids both sides.
    """
    out: list[dict] = []
    for book in books:
        letters = []
        if book.get("t0_a") is not None:
            letters.append("a")
        if book.get("t0_b") is not None:
            letters.append("b")
        if not letters:
            px = score_t0_yes(book)
            if px is None:
                continue
            row = dict(book)
            row["_side_letter"] = str(book.get("fav") or "fav")
            row["t0_fav"] = float(px)
            out.append(row)
            continue
        parent_void = bool(book.get("void"))
        for letter in letters:
            row = dict(book)
            px = float(book.get(f"t0_{letter}"))
            off = book.get(f"off_{letter}")
            name = book.get(f"side_{letter}") or letter
            row["_side_letter"] = letter
            row["t0_fav"] = px
            row["fav"] = letter
            row["fav_name"] = name
            row["two_sided"] = len(letters) == 2
            if parent_void:
                row["void"] = True
                row["settled"] = False
                row["cover_known"] = False
                row["fav_won"] = None
                row["middle"] = False
            elif off in ("win", "loss"):
                row["void"] = False
                row["cover_known"] = True
                row["settled"] = True
                row["fav_won"] = off == "win"
            else:
                row["cover_known"] = False
                row["settled"] = False
                row["fav_won"] = None
            out.append(row)
    return out


def score_decile_set(
    sides: list[dict],
    *,
    grain: str,
    suffix: str = "",
    side: str = "yes",
) -> dict:
    """Score every decade plus combined 10-29 and 20-39 on an already-picked tape.

    side='no' buys No on the same cover-Yes rows (pick=False so the venue stays
    the Yes primary).
    """
    is_no = side == "no"
    trade_fn = t0_no_trade if is_no else t0_yes_trade
    won_fn = t0_no_won if is_no else line_won
    extra = {"pick": False, "trade_fn": trade_fn, "won_fn": won_fn}
    recs: dict[str, dict] = {}
    order: list[str] = []
    for short, lo, hi, interval in DECILE_SPECS:
        label = decile_arm_label(short, interval, side=side) + suffix
        rec = score_t0_yes_band(
            sides, label=label, grain=grain, pred=decile_pred(lo, hi), **extra
        )
        recs[short] = rec
        order.append(short)
    rec_1029 = score_t0_yes_band(
        sides,
        label=(("Buy No " if is_no else "") + DECILE_10_29_ID + suffix),
        grain=grain,
        pred=in_10_29,
        **extra,
    )
    recs["10-29"] = rec_1029
    rec_2039 = score_t0_yes_band(
        sides,
        label=(("Buy No " if is_no else "") + DECILE_20_39_ID + suffix),
        grain=grain,
        pred=in_20_39,
        **extra,
    )
    recs["20-39"] = rec_2039
    all_label = (DECILE_ALL_NO_ID if is_no else DECILE_ALL_ID) + suffix
    rec_all = score_t0_yes_band(
        sides,
        label=all_label,
        grain=grain,
        pred=lambda px: px is not None,
        **extra,
    )
    recs["all"] = rec_all
    recs["_order"] = order
    recs["_side"] = side
    return recs


def unique_fav_decile_sides(sides: list[dict]) -> list[dict]:
    """Unique-fav cover-Yes (>50¢), one line per game closest to 50¢."""
    with_fav = []
    for book in sides:
        px = score_t0_yes(book)
        if not is_unique_fav(px):
            continue
        row = dict(book)
        if row.get("t0_fav") is None:
            row["t0_fav"] = float(px)
        with_fav.append(row)
    return pick_one_per_game(with_fav) if with_fav else []


def build_every_decile_payload(books: list[dict], *, sunday_date: str = "2026-10-25") -> dict:
    """All-lines Type A cover-Yes sides, every T0 Yes decade. Open out of $."""
    sides = explode_cover_yes_sides(books)
    picked = pick_fee_primary_line(sides)
    sunday_src = [b for b in picked if is_sunday_book(b, sunday_date)]
    all_days = score_decile_set(picked, grain="all-lines cover-Yes")
    sunday = score_decile_set(sunday_src, grain="all-lines Sunday", suffix=" Sunday")
    all_days_no = score_decile_set(
        picked, grain="all-lines cover-No", side="no"
    )
    sunday_no = score_decile_set(
        sunday_src, grain="all-lines Sunday", suffix=" Sunday", side="no"
    )
    uf_sides = unique_fav_decile_sides(picked)
    uf_sun_sides = unique_fav_decile_sides(sunday_src)
    uf = score_decile_set(uf_sides, grain="unique-fav one-per-game")
    uf_sun = score_decile_set(
        uf_sun_sides, grain="unique-fav one-per-game Sunday", suffix=" Sunday"
    )
    d20 = all_days.get("20-29") or {}
    d30 = all_days.get("30-39") or {}
    comb = all_days.get("20-39") or {}
    d10 = all_days.get("10-19") or {}
    comb1029 = all_days.get("10-29") or {}
    n20 = int(d20.get("n") or 0)
    n30 = int(d30.get("n") or 0)
    n_comb = int(comb.get("n") or 0)
    n10 = int(d10.get("n") or 0)
    n_1029 = int(comb1029.get("n") or 0)
    adds = n20 + n30 == n_comb
    adds_10_29 = n10 + n20 == n_1029
    n20_no = int((all_days_no.get("20-29") or {}).get("n") or 0)
    n10_no = int((all_days_no.get("10-19") or {}).get("n") or 0)
    n1029_no = int((all_days_no.get("10-29") or {}).get("n") or 0)
    same_rows = n20_no == n20 and n10_no == n10 and n1029_no == n_1029
    return {
        "n_raw_books": len(books),
        "n_sides": len(sides),
        "n_picked": len(picked),
        "n_sunday_picked": len(sunday_src),
        "all_days": all_days,
        "sunday": sunday,
        "all_days_no": all_days_no,
        "sunday_no": sunday_no,
        "unique_fav": uf,
        "unique_fav_sunday": uf_sun,
        "adds_20_39": adds,
        "adds_10_29": adds_10_29,
        "same_rows_yes_no": same_rows,
        "n_10_19": n10,
        "n_20_29": n20,
        "n_30_39": n30,
        "n_10_29": n_1029,
        "n_20_39": n_comb,
    }


def decile_hero_rows(
    recs: dict,
    *,
    include_combined: bool = True,
    include_10_29: bool = True,
) -> list[list[str]]:
    """Decade rows, combined 10-29 after 20-29, combined 20-39 after 30-39, total."""
    rows: list[list[str]] = []
    for short, _lo, _hi, _interval in DECILE_SPECS:
        rec = recs.get(short)
        if rec is None:
            continue
        rows.append(band_primary_row(rec))
        if include_10_29 and short == "20-29":
            comb1029 = recs.get("10-29")
            if comb1029 is not None:
                rows.append(band_primary_row(comb1029))
        if include_combined and short == "30-39":
            comb = recs.get("20-39")
            if comb is not None:
                rows.append(band_primary_row(comb))
    all_rec = recs.get("all")
    if all_rec is not None:
        rows.append(band_primary_row(all_rec))
    return rows


def decile_verdict(rec: dict) -> str:
    """Say whether the band won in dollars and win%, no hedge."""
    n = int(rec.get("n") or 0)
    n_fee = int(rec.get("n_fee") or 0)
    wr = rec.get("win_pct")
    pnl = rec.get("pnl_sum")
    wr_txt = fmt_pct(wr) if n else "—"
    pnl_txt = format_money(pnl) if n_fee else "—"
    if n == 0:
        return f"N=0 on this tape. Win% {wr_txt}. With-fee {pnl_txt}."
    if n_fee == 0:
        return (
            f"Win% {wr_txt} on N={n}, but no documented-fee tickets so dollars "
            f"are unknown (Novig omitted — not treated as free)."
        )
    won_dollars = pnl is not None and float(pnl) > 1e-12
    lost_dollars = pnl is not None and float(pnl) < -1e-12
    wr_vs_half = None if wr is None else (float(wr) > 50.0 + 1e-12)
    if won_dollars and wr_vs_half:
        return (
            f"Winners: win% {wr_txt} on N={n} and with-fee PnL {pnl_txt} "
            f"(N_fee={n_fee})."
        )
    if won_dollars and wr_vs_half is False:
        return (
            f"Winners in dollars, not on win%: win% {wr_txt} on N={n} is at or "
            f"under 50, but with-fee PnL {pnl_txt} (N_fee={n_fee}) because the "
            f"Yes was cheap."
        )
    if lost_dollars and wr_vs_half:
        return (
            f"Win% {wr_txt} on N={n} looks like a winner, but they lose after "
            f"fees: with-fee PnL {pnl_txt} (N_fee={n_fee})."
        )
    if lost_dollars:
        return (
            f"Not winners: win% {wr_txt} on N={n}, with-fee PnL {pnl_txt} "
            f"(N_fee={n_fee})."
        )
    return (
        f"Flat in dollars: win% {wr_txt} on N={n}, with-fee PnL {pnl_txt} "
        f"(N_fee={n_fee})."
    )
