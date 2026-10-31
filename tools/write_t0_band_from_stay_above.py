"""T0 both-Yes band vs stay-above-50 of the T0 favorite.

Research only. Companion decision table for Paul. Does not change live
C_HI=1.20 or D=0.25. Does not edit live_strategy_b.py. Does not place,
cancel, or amend orders. Does not print secrets. Does not start a second
Strategy B. Not gold. Not DailyRun. Not a GitHub Pages live report.

Grain is venue-game (and spread line): the same match on Kalshi and Gemini
is two rows. T0 is the first trusted serve (occurrence, else a scheduled
listed/feed clock with seconds=00). First-competitive / tape-resume T0s
are dropped. Favorite = higher T0 Yes ask.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from dense_inplay_yes_dip_20261021 import assign_actual_t0, attach_start_sources
from odds_cross_winrate_20261020 import (
    SETTLE_CACHE,
    add_settlement,
    as_float,
    attach_results,
    build_index,
    game_norm,
    parse_dt,
    pct,
    tiny_note,
)
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from price_memory import iter_tick_lines, to_et
from tennis_decade_at_start_20261020 import is_clocked_start, start_lookup_from

try:
    from polymarket_tennis_no_90plus_20261020 import load_catalog, load_poly_tennis_resolutions
except Exception:  # pragma: no cover - catalog is optional
    def load_catalog() -> list[dict]:
        return []

    def load_poly_tennis_resolutions() -> list[dict]:
        return []

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "t0_band_from_stay_above_20261024.html"
LIVING_PAGE = STAMP / "t0_all_games_stats.html"
CENT = Decimal("0.01")
ONE = Decimal("1")
POLY_THETA = Decimal("0.0695")
STAY_BAR = 0.50
TRUSTED_SOURCES = ("occurrence", "listed/feed", "listed")

FAV_BUCKETS = (
    (">90", 0.90, None),
    ("80-89", 0.80, 0.90),
    ("70-79", 0.70, 0.80),
    ("60-69", 0.60, 0.70),
    ("50-59", 0.50, 0.60),
    ("<50", None, 0.50),
)
FAV_CUMULATIVE = (
    (">80", 0.80),
    (">70", 0.70),
    (">60", 0.60),
)
C_BUCKETS = (
    ("<0.95", None, 0.95),
    ("0.95-0.99", 0.95, 1.00),
    ("1.00-1.04", 1.00, 1.05),
    ("1.05-1.09", 1.05, 1.10),
    ("1.10-1.14", 1.10, 1.15),
    ("1.15-1.20", 1.15, 1.2000001),
    (">1.20", 1.20, None),
)
MOUTET_C = "1.00-1.04"

ASKED = (
    "He may want to adjust the Strategy B T0 both-Yes band based on the percentage "
    "of games where the winner at T0 remains above 50% for the entirety of the game. "
    "He also confirmed: $1.20 is the \"don't pay too much vig\" cap (Moutet was 1.01 "
    "asks / 1.035 all-in). Kalshi fees can turn a 0.99 wire into over $1 all-in, so "
    "stacking must use all-in, not the wire."
)

PLAIN = (
    "T0 is the first trusted start price (first serve we trust: Kalshi/Gemini "
    "occurrence when clocked, else a listed start that lands on a real sports clock "
    "with seconds=00). The T0 favorite is whoever has the higher Yes ask at that "
    "open — the side the market is calling more likely. Stay-above-50 means that "
    "favorite's Yes never printed 50 cents or lower after T0 on a complete watch "
    "(we saw post-T0 ticks, and we did not lose while the last tick was still above 50). "
    "An empty tape after T0 is not stay-above. A last print at 80 cents plus an official "
    "loss is a missing crash, not stay-above. Stay-above is not the same as winning: a "
    "favorite can dip under 50 and still win. "
    "C is the two Yes asks added together (the vig, the house overround). Wire C "
    "is the asks only. All-in C adds documented taker fees (Kalshi 0.07×p×(1−p) "
    "to a ten-thousandth of a dollar; Gemini the same formula rounded up to a cent; "
    "Polymarket the standard 0.0695 coefficient to a banker's cent). Novig needs a "
    "per-market coefficient, so those rows stay wire-only. Live today still uses "
    "C_HI=1.20 as the vig cap and stacks another 1-contract both-Yes only while "
    "all-in is under $1. This page does not change those knobs. Research only. "
    "Not gold. Not DailyRun. The October 2026 tape is all out-of-sample versus the "
    "2024-01-01 holdout. Same-day contracts, so annualized rate of return is omitted."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def td(value) -> str:
    return f"<td>{esc('' if value is None else value)}</td>"


def html_table(headers: list[tuple[str, str]], rows: list[dict], fields: list[str]) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        klass = ' class="total-row"' if row.get("_total") else ""
        cells = "".join(td(row.get(field, "")) for field in fields)
        body.append(f"<tr{klass}>{cells}</tr>")
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f"<table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


_SHARED = False


def _shared_module():
    """Import living-dashboard metrics (tools/t0_all_games_stats.py)."""
    global _SHARED
    if _SHARED is not False:
        return _SHARED
    try:
        import t0_all_games_stats as mod
    except Exception:
        _SHARED = None
        return None
    _SHARED = mod
    return mod


def is_scheduled_sports_clock(dt: datetime | None) -> bool:
    """True for 15:10:00 lists. False for Polymarket feed stamps like 23:12:40Z."""
    if not isinstance(dt, datetime):
        return False
    return dt.second == 0 and dt.microsecond == 0


def in_lo_hi(value: float, lo: float | None, hi: float | None) -> bool:
    if lo is not None and value < lo - 1e-12:
        return False
    if hi is not None and value >= hi - 1e-12:
        return False
    return True


def favorite_yes_bucket(price: float | None) -> str:
    """Disjoint T0-favorite Yes bucket. >90 is 90 cents and up."""
    shared = _shared_module()
    fn = getattr(shared, "favorite_yes_bucket", None) if shared else None
    if callable(fn) and fn is not favorite_yes_bucket:
        try:
            return str(fn(price))
        except Exception:
            pass
    if price is None:
        return ""
    px = float(price)
    for label, lo, hi in FAV_BUCKETS:
        if in_lo_hi(px, lo, hi):
            return label
    return ""


def wire_c_bucket(cost: float | None) -> str:
    """Both-Yes sum C. 1.15-1.20 includes the live 1.20 cap. 1.00-1.04 is Moutet-like."""
    shared = _shared_module()
    fn = getattr(shared, "wire_c_bucket", None) if shared else None
    if callable(fn) and fn is not wire_c_bucket:
        try:
            return str(fn(cost))
        except Exception:
            pass
    if cost is None:
        return ""
    c = float(cost)
    for label, lo, hi in C_BUCKETS:
        if in_lo_hi(c, lo, hi):
            return label
    return ""


def stay_above_50(ticks: list[tuple[int, float]], t0_ts: int | None) -> bool:
    """True when the T0 favorite never prints ≤0.50 after T0.

    T0 itself is the start snapshot, not a fail. No later print is NOT
    stay-above (thin tape / incomplete path). A print of 0.50 after T0 fails.
    Settlement completeness (missing crash) is applied in score_pair.
    """
    shared = _shared_module()
    fn = getattr(shared, "classify_stay_above", None) if shared else None
    if callable(fn):
        try:
            got = fn(ticks, t0_ts, fav_won=None)
            return bool(got.get("stay_above"))
        except Exception:
            pass
    if t0_ts is None:
        return False
    n_post = 0
    for ts, px in ticks or []:
        if ts <= t0_ts:
            continue
        n_post += 1
        if float(px) <= STAY_BAR + 1e-12:
            return False
    return n_post > 0


def documented_leg_fee(venue: str, price) -> Decimal | None:
    """Documented one-contract taker fee. Missing schedule → None, not zero."""
    shared = _shared_module()
    fn = getattr(shared, "documented_leg_fee", None) if shared else None
    if callable(fn) and fn is not documented_leg_fee:
        try:
            got = fn(venue, price)
            return None if got is None else Decimal(str(got))
        except Exception:
            pass
    if price is None or price == "":
        return None
    try:
        p = Decimal(str(price))
    except Exception:
        return None
    if p <= 0 or p >= ONE:
        return None
    name = (venue or "").strip().lower()
    if name == "kalshi":
        raw = Decimal("0.07") * p * (ONE - p)
        if raw < 0:
            raw = Decimal("0")
        return raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if name == "gemini":
        raw = Decimal("0.07") * p * (ONE - p)
        if raw < 0:
            raw = Decimal("0")
        return raw.quantize(CENT, rounding=ROUND_CEILING)
    if name.startswith("polymarket"):
        exact = POLY_THETA * p * (ONE - p)
        return exact.quantize(CENT, rounding=ROUND_HALF_EVEN)
    return None


def all_in_c(venue: str, yes_a, yes_b) -> Decimal | None:
    """Wire asks plus documented taker fees. Unknown fee → None (not a zero-fee pretend)."""
    if yes_a is None or yes_b is None:
        return None
    fee_a = documented_leg_fee(venue, yes_a)
    fee_b = documented_leg_fee(venue, yes_b)
    if fee_a is None or fee_b is None:
        return None
    return Decimal(str(yes_a)) + Decimal(str(yes_b)) + fee_a + fee_b


def pair_has_trusted_t0(pair: dict) -> bool:
    """Keep occurrence or scheduled listed/feed. Drop tape-resume and first-competitive."""
    if pair.get("t0_a") is None or pair.get("t0_b") is None or pair.get("t0_ts") is None:
        return False
    src = str(pair.get("actual_source") or "")
    if src == "occurrence":
        return True
    if src in ("listed/feed", "listed"):
        dt = pair.get("listed_dt")
        if not isinstance(dt, datetime):
            dt = parse_dt(pair.get("actual_start") or pair.get("listed_start") or "")
        return is_scheduled_sports_clock(dt)
    return False


def assign_trusted_t0(pair: dict, start_lookup: dict) -> None:
    shared = _shared_module()
    fn = getattr(shared, "assign_trusted_t0", None) if shared else None
    if callable(fn) and fn is not assign_trusted_t0:
        try:
            fn(pair, start_lookup)
            return
        except Exception:
            pass
    attach_start_sources(pair, start_lookup)
    assign_actual_t0(pair, start_lookup)
    if pair_has_trusted_t0(pair):
        return
    pair["t0_a"] = None
    pair["t0_b"] = None
    pair["t0_ts"] = None
    pair["trusted_t0"] = False


def score_pair(pair: dict) -> dict | None:
    """One venue-game (or venue-game-spread-line) with trusted T0 + settlement."""
    t0_a = as_float(pair.get("t0_a"))
    t0_b = as_float(pair.get("t0_b"))
    t0_ts = pair.get("t0_ts")
    if t0_a is None or t0_b is None or t0_ts is None:
        return None
    if not pair.get("settled"):
        return None
    winner = pair.get("winner")
    if winner not in ("a", "b"):
        return None
    if t0_a >= t0_b:
        fav, dog = "a", "b"
        t0_fav, t0_dog = t0_a, t0_b
        fav_side = pair.get("side_a") or ""
        fav_ticks = pair.get("yes_a") or []
    else:
        fav, dog = "b", "a"
        t0_fav, t0_dog = t0_b, t0_a
        fav_side = pair.get("side_b") or ""
        fav_ticks = pair.get("yes_b") or []
    fav_won = winner == fav
    shared = _shared_module()
    classify = getattr(shared, "classify_stay_above", None) if shared else None
    cls = {}
    if callable(classify):
        try:
            cls = classify(fav_ticks, int(t0_ts), fav_won=fav_won) or {}
        except Exception:
            cls = {}
    if cls:
        stayed = bool(cls.get("stay_above"))
        post_n = int(cls.get("n_post") or 0)
    else:
        post_n = sum(1 for ts, _px in fav_ticks if ts > int(t0_ts))
        raw_stay = stay_above_50(fav_ticks, int(t0_ts))
        last_px = None
        for ts, px in fav_ticks or []:
            if ts > int(t0_ts):
                last_px = float(px)
        missing_crash = (not fav_won) and last_px is not None and last_px > STAY_BAR + 1e-12
        stay_lost = bool(raw_stay) and not fav_won
        stayed = bool(raw_stay) and not stay_lost
        cls = {
            "stay_above": stayed,
            "missing_crash": missing_crash,
            "stay_above_but_lost": stay_lost,
            "path_status": (
                "path_incomplete" if stay_lost or missing_crash
                else ("no_post_t0_path" if post_n == 0 else "watched")
            ),
            "n_post": post_n,
            "last_px": last_px,
            "raw_never_le50": raw_stay,
        }
    wire = t0_a + t0_b
    all_in = all_in_c(str(pair.get("venue") or ""), t0_a, t0_b)
    return {
        "sport": pair.get("sport") or "unknown",
        "game": pair.get("game") or "",
        "venue": pair.get("venue") or "",
        "market_type": pair.get("market_type") or "moneyline",
        "number": pair.get("number") or "",
        "fav_side": fav_side,
        "fav": fav,
        "dog": dog,
        "t0_fav": t0_fav,
        "t0_dog": t0_dog,
        "c_wire": wire,
        "c_all_in": float(all_in) if all_in is not None else None,
        "fav_bucket": favorite_yes_bucket(t0_fav),
        "c_bucket": wire_c_bucket(wire),
        "c_all_in_bucket": wire_c_bucket(float(all_in)) if all_in is not None else "",
        "stay_above": stayed,
        "fav_won": fav_won,
        "post_t0_n": post_n,
        "t0_source": pair.get("actual_source") or pair.get("t0_source") or "",
        "t0_label": pair.get("t0_label") or "",
        "path_status": cls.get("path_status") or "",
        "missing_crash": bool(cls.get("missing_crash")),
        "stay_above_but_lost": bool(cls.get("stay_above_but_lost")),
        "raw_never_le50": bool(cls.get("raw_never_le50")),
        "last_px": cls.get("last_px"),
        "two_sided": True,
        "t0_ts": int(t0_ts),
        "side_a": pair.get("side_a") or "",
        "side_b": pair.get("side_b") or "",
        "winner": winner,
        "listed_raw": pair.get("listed_raw") or pair.get("start") or "",
        "end_ts": pair.get("end_ts"),
        "game_n": pair.get("game_n") or "",
        "kind": pair.get("market_type") or pair.get("kind") or "moneyline",
    }


def rows_from_living_books(books: list[dict]) -> list[dict]:
    """Map living-dashboard scored books onto this page's row schema. No tape scan."""
    rows = []
    for book in books or []:
        if book.get("skip"):
            continue
        if not book.get("settled") or book.get("void"):
            continue
        if not book.get("fav"):
            continue
        t0_a = as_float(book.get("t0_a"))
        t0_b = as_float(book.get("t0_b"))
        t0_fav = as_float(book.get("t0_fav"))
        if t0_fav is None:
            continue
        path = book.get("fav_path") or {}
        fav = book.get("fav")
        dog = book.get("dog") or ""
        if fav == "a":
            t0_dog = t0_b
            fav_side = book.get("side_a") or ""
        else:
            t0_dog = t0_a
            fav_side = book.get("side_b") or ""
        wire = None
        if t0_a is not None and t0_b is not None:
            wire = t0_a + t0_b
        all_in = all_in_c(str(book.get("venue") or ""), t0_a, t0_b) if (
            t0_a is not None and t0_b is not None
        ) else None
        kind = book.get("kind") or book.get("market_type") or "moneyline"
        rows.append({
            "sport": book.get("sport") or "unknown",
            "game": book.get("game") or "",
            "game_n": book.get("game_n") or "",
            "venue": book.get("venue") or "",
            "market_type": kind,
            "kind": kind,
            "number": book.get("number") or "",
            "fav_side": fav_side,
            "fav": fav,
            "dog": dog,
            "t0_fav": t0_fav,
            "t0_dog": t0_dog,
            "t0_a": t0_a,
            "t0_b": t0_b,
            "c_wire": wire,
            "c_all_in": float(all_in) if all_in is not None else None,
            "fav_bucket": favorite_yes_bucket(t0_fav),
            "c_bucket": wire_c_bucket(wire) if wire is not None else "",
            "c_all_in_bucket": wire_c_bucket(float(all_in)) if all_in is not None else "",
            "stay_above": bool(path.get("stay_above")),
            "fav_won": book.get("fav_won"),
            "post_t0_n": int(path.get("n_post") or 0),
            "t0_source": book.get("t0_source") or "",
            "t0_label": book.get("t0_label") or "",
            "path_status": path.get("path_status") or "",
            "missing_crash": bool(path.get("missing_crash")),
            "stay_above_but_lost": bool(path.get("stay_above_but_lost")),
            "raw_never_le50": bool(path.get("raw_never_le50")),
            "last_px": path.get("last_px"),
            "two_sided": bool(book.get("two_sided")),
            "t0_ts": book.get("t0_ts"),
            "end_ts": book.get("end_ts"),
            "side_a": book.get("side_a") or "",
            "side_b": book.get("side_b") or "",
            "winner": book.get("winner"),
            "listed_raw": book.get("listed_raw") or "",
        })
    return rows


def rate_cell(hits: int, n: int) -> str:
    if n <= 0:
        return "— (0)"
    return f"{pct(hits, n)}% ({hits}/{n})"


def empty_bag() -> dict:
    return {
        "n": 0, "stay": 0, "wins": 0, "all_in_n": 0,
        "stay_lost": 0, "missing_crash": 0, "no_post": 0, "raw_stay": 0,
    }


def add_row(bag: dict, row: dict) -> None:
    bag["n"] += 1
    if row.get("stay_above"):
        bag["stay"] += 1
    if row.get("fav_won"):
        bag["wins"] += 1
    if row.get("c_all_in") is not None:
        bag["all_in_n"] += 1
    if row.get("stay_above_but_lost"):
        bag["stay_lost"] += 1
    if row.get("missing_crash"):
        bag["missing_crash"] += 1
    if int(row.get("post_t0_n") or 0) <= 0:
        bag["no_post"] += 1
    if row.get("raw_never_le50"):
        bag["raw_stay"] += 1


def bag_view(label: str, bag: dict, *, total: bool = False, callout: str = "") -> dict:
    n = bag["n"]
    viol = bag["stay"] > bag["wins"]
    return {
        "bucket": label,
        "n": n,
        "stay_n": bag["stay"],
        "stay_rate": rate_cell(bag["stay"], n),
        "win_n": bag["wins"],
        "win_rate": rate_cell(bag["wins"], n),
        "all_in_n": bag["all_in_n"],
        "stay_lost": bag.get("stay_lost") or 0,
        "missing_crash": bag.get("missing_crash") or 0,
        "no_post": bag.get("no_post") or 0,
        "raw_stay_n": bag.get("raw_stay") or 0,
        "violates": "YES — bug" if viol else "no",
        "note": callout or tiny_note(n),
        "_total": total,
    }


def summarize_fav_buckets(rows: list[dict]) -> list[dict]:
    bags = {label: empty_bag() for label, _lo, _hi in FAV_BUCKETS}
    all_bag = empty_bag()
    cum = {label: empty_bag() for label, _lo in FAV_CUMULATIVE}
    for row in rows:
        add_row(all_bag, row)
        label = row.get("fav_bucket") or ""
        if label in bags:
            add_row(bags[label], row)
        px = row.get("t0_fav")
        if px is not None:
            for cum_label, lo in FAV_CUMULATIVE:
                if float(px) >= lo - 1e-12:
                    add_row(cum[cum_label], row)
    out = [bag_view(label, bags[label]) for label, _lo, _hi in FAV_BUCKETS]
    out.extend(bag_view(f"cumulative {label}", cum[label]) for label, _lo in FAV_CUMULATIVE)
    out.append(bag_view("All", all_bag, total=True))
    return out


def summarize_c_buckets(rows: list[dict], *, all_in: bool = False) -> list[dict]:
    key = "c_all_in_bucket" if all_in else "c_bucket"
    bags = {label: empty_bag() for label, _lo, _hi in C_BUCKETS}
    all_bag = empty_bag()
    for row in rows:
        if all_in and row.get("c_all_in") is None:
            continue
        add_row(all_bag, row)
        label = row.get(key) or ""
        if label in bags:
            add_row(bags[label], row)
    out = []
    for label, _lo, _hi in C_BUCKETS:
        callout = "Moutet-like (1.01 asks / 1.035 all-in sat here on the wire)" if label == MOUTET_C else ""
        out.append(bag_view(label, bags[label], callout=callout))
    out.append(bag_view("All", all_bag, total=True))
    return out


def summarize_group(rows: list[dict], field: str) -> list[dict]:
    bags: dict[str, dict] = defaultdict(empty_bag)
    for row in rows:
        add_row(bags[str(row.get(field) or "unknown")], row)
    out = [bag_view(label, bag) for label, bag in sorted(bags.items(), key=lambda kv: (-kv[1]["n"], kv[0]))]
    all_bag = empty_bag()
    for row in rows:
        add_row(all_bag, row)
    out.append(bag_view("All", all_bag, total=True))
    return out


def summarize_sport_kind(rows: list[dict]) -> list[dict]:
    bags: dict[tuple[str, str], dict] = defaultdict(empty_bag)
    for row in rows:
        key = (str(row.get("sport") or "unknown"), str(row.get("market_type") or "moneyline"))
        add_row(bags[key], row)
    out = []
    for (sport, kind), bag in sorted(bags.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        view = bag_view(f"{sport} · {kind}", bag)
        view["sport"] = sport
        view["market_type"] = kind
        out.append(view)
    all_bag = empty_bag()
    for row in rows:
        add_row(all_bag, row)
    total = bag_view("All", all_bag, total=True)
    total["sport"] = "All"
    total["market_type"] = "All"
    out.append(total)
    return out


def summarize_sport_fav(rows: list[dict]) -> list[dict]:
    bags: dict[tuple[str, str], dict] = defaultdict(empty_bag)
    for row in rows:
        key = (str(row.get("sport") or "unknown"), str(row.get("fav_bucket") or ""))
        add_row(bags[key], row)
    out = []
    for (sport, bucket), bag in sorted(bags.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        view = bag_view(bucket, bag)
        view["sport"] = sport
        out.append(view)
    return out


def stream_yes_series() -> dict:
    """Stream Yes ticks. Line-by-line; do not load the jsonl into RAM as one list."""
    print("streaming moneyline+spread Yes (archive + shards)", flush=True)
    series: dict[tuple, dict] = {}
    n_lines = 0
    n_hits = 0
    seen_min = ""
    seen_max = ""
    for line in iter_tick_lines():
        n_lines += 1
        if n_lines % 400000 == 0:
            print(f"  {n_lines} lines, series {len(series)} ticks {n_hits}", flush=True)
        low = line.lower()
        if '"yes"' not in low:
            continue
        if "moneyline" not in low and "spread" not in low:
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
        kind = str(rec.get("market_type") or "")
        if kind not in ("moneyline", "spread"):
            continue
        if str(rec.get("pay") or "yes").lower() != "yes":
            continue
        price = as_float(rec.get("price"))
        if price is None or price <= 0.0 or price >= 1.0:
            continue
        seen = rec.get("seen_at") or ""
        dt = parse_dt(seen)
        if dt is None:
            continue
        ts = int(to_et(dt).timestamp())
        game = rec.get("game") or ""
        side = rec.get("side") or rec.get("side_label") or ""
        venue = rec.get("venue") or ""
        if not game or not side or not venue:
            continue
        number = "" if kind == "moneyline" else str(rec.get("number") or "")
        sport = str(rec.get("sport") or "unknown")
        key = (sport, game, venue, kind, number, side)
        st = series.get(key)
        if st is None:
            st = {
                "sport": sport,
                "game": game,
                "venue": venue,
                "market_type": kind,
                "number": number,
                "side": side,
                "start": rec.get("game_start") or "",
                "ticks": [],
            }
            series[key] = st
        else:
            if rec.get("game_start") and not st["start"]:
                st["start"] = rec.get("game_start") or ""
            if rec.get("sport") and st["sport"] in ("", "unknown"):
                st["sport"] = rec["sport"]
        ticks = st["ticks"]
        px = round(price, 4)
        if ticks and ticks[-1][0] == ts and ticks[-1][1] == px:
            continue
        if ticks and ticks[-1][1] == px:
            continue
        ticks.append((ts, px))
        n_hits += 1
        if seen:
            if not seen_min or seen < seen_min:
                seen_min = seen
            if not seen_max or seen > seen_max:
                seen_max = seen
    for st in series.values():
        st["ticks"].sort(key=lambda row: row[0])
    print(f"stream done lines={n_lines} yes_change_ticks={n_hits} series={len(series)}", flush=True)
    return {
        "series": series,
        "n_lines": n_lines,
        "n_hits": n_hits,
        "seen_min": seen_min,
        "seen_max": seen_max,
    }


def pair_two_sided(series: dict[tuple, dict]) -> list[dict]:
    bags: dict[tuple, dict] = {}
    for (_sport, game, venue, kind, number, side), st in series.items():
        gkey = (game, venue, kind, number)
        bag = bags.get(gkey)
        if bag is None:
            bag = {
                "game": game,
                "venue": venue,
                "sport": st.get("sport") or "unknown",
                "market_type": kind,
                "number": number,
                "yes": {},
                "starts": [],
            }
            bags[gkey] = bag
        if st.get("sport") and bag["sport"] in ("", "unknown"):
            bag["sport"] = st["sport"]
        if st.get("start"):
            bag["starts"].append(st["start"])
        bag["yes"][side] = st
    pairs = []
    skipped_sides = 0
    for bag in bags.values():
        sides = list(bag["yes"])
        if len(sides) != 2:
            skipped_sides += 1
            continue
        a, b = sides[0], sides[1]
        start_text = ""
        for raw in bag["starts"]:
            if parse_dt(raw):
                start_text = raw
                break
        pairs.append({
            "sport": bag["sport"] or "unknown",
            "game": bag["game"],
            "venue": bag["venue"],
            "market_type": bag["market_type"],
            "number": bag["number"],
            "side_a": a,
            "side_b": b,
            "yes_a": bag["yes"][a]["ticks"],
            "yes_b": bag["yes"][b]["ticks"],
            "start": start_text,
            "start_dt": parse_dt(start_text),
        })
    print(f"two-sided pairs {len(pairs)} (skipped one-sided {skipped_sides})", flush=True)
    return pairs


def load_all_settlements() -> list[dict]:
    rows: list[dict] = []
    if SETTLE_CACHE.is_file():
        try:
            raw = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = []
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict):
                    add_settlement(rows, row)
    try:
        extra = load_poly_tennis_resolutions()
    except Exception:
        extra = []
    for row in extra or []:
        if isinstance(row, dict):
            add_settlement(rows, row)
    print(f"settlements {len(rows)}", flush=True)
    return rows


def attach_winners(pairs: list[dict], settlements: list[dict]) -> None:
    index = build_index(settlements)
    crosses = []
    last_map = {}
    for i, pair in enumerate(pairs):
        kind = pair.get("market_type") or "moneyline"
        number = pair.get("number") or ""
        for letter, side, ticks in (
            ("a", pair["side_a"], pair.get("yes_a") or []),
            ("b", pair["side_b"], pair.get("yes_b") or []),
        ):
            key = f"pair{i}|{letter}"
            last_px = ticks[-1][1] if ticks else None
            last_ts = ticks[-1][0] if ticks else None
            last_map[key] = {
                "price": last_px,
                "seen_at": datetime.fromtimestamp(last_ts, ET).isoformat() if last_ts else "",
                "game_start": pair.get("start") or "",
                "sport": pair.get("sport") or "",
            }
            crosses.append({
                "key": key,
                "sport": pair.get("sport") or "",
                "game": pair.get("game") or "",
                "market_type": kind,
                "side": side,
                "side_key": game_norm(side),
                "number": number,
                "venue": pair.get("venue") or "",
                "cross_time": datetime.fromtimestamp(pair["t0_ts"], ET).isoformat() if pair.get("t0_ts") else "",
                "game_start": pair.get("start") or "",
            })
    attach_results(crosses, last_map, settlements, index)
    by_key = {c["key"]: c for c in crosses}
    for i, pair in enumerate(pairs):
        ca = by_key.get(f"pair{i}|a") or {}
        cb = by_key.get(f"pair{i}|b") or {}
        pair["off_a"] = ca.get("official") or "pending"
        pair["off_b"] = cb.get("official") or "pending"
        winner = None
        if pair["off_a"] == "win" and pair["off_b"] == "loss":
            winner = "a"
        elif pair["off_b"] == "win" and pair["off_a"] == "loss":
            winner = "b"
        pair["winner"] = winner
        pair["settled"] = winner in ("a", "b")


def collect_rows() -> tuple[list[dict], dict]:
    shared = _shared_module()
    if shared is not None:
        for name in ("iter_settled_trusted_pairs", "scored_pairs", "load_trusted_settled_games"):
            fn = getattr(shared, name, None)
            if not callable(fn):
                continue
            print(f"importing {name} from write_t0_all_games_stats", flush=True)
            try:
                raw = list(fn())
            except Exception as exc:
                print(f"shared {name} failed ({exc}); using local scan", flush=True)
                raw = None
            if raw:
                rows = []
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    if item.get("stay_above") is not None and item.get("c_bucket"):
                        rows.append(item)
                        continue
                    scored = score_pair(item)
                    if scored:
                        rows.append(scored)
                if rows:
                    return rows, {
                        "n_lines": None,
                        "n_hits": None,
                        "seen_min": "",
                        "seen_max": "",
                        "shared": name,
                    }
    stream = stream_yes_series()
    pairs = pair_two_sided(stream["series"])
    settlements = load_all_settlements()
    try:
        catalog = load_catalog()
    except Exception:
        catalog = []
    start_lookup = start_lookup_from(settlements, catalog)
    n_trusted = 0
    for pair in pairs:
        assign_trusted_t0(pair, start_lookup)
        if pair_has_trusted_t0(pair):
            n_trusted += 1
    attach_winners(pairs, settlements)
    rows = []
    n_settled = 0
    for pair in pairs:
        if not pair_has_trusted_t0(pair):
            continue
        if pair.get("settled"):
            n_settled += 1
        scored = score_pair(pair)
        if scored:
            rows.append(scored)
    meta = {
        "n_lines": stream["n_lines"],
        "n_hits": stream["n_hits"],
        "seen_min": stream["seen_min"],
        "seen_max": stream["seen_max"],
        "n_pairs": len(pairs),
        "n_trusted": n_trusted,
        "n_settled_trusted": n_settled,
        "n_scored": len(rows),
        "n_settlements": len(settlements),
        "shared": "",
    }
    print(
        f"trusted T0 {n_trusted} settled-trusted {n_settled} scored {len(rows)}",
        flush=True,
    )
    return rows, meta


def living_link_html() -> str:
    if LIVING_PAGE.is_file():
        return (
            '<p class="note">Living all-game T0 stats (~2h refresh; Q1 stay-above-50, '
            "Q2 dog one-cross-and-hold, Q3 T0 favorite win-by-bucket): "
            '<a href="t0_all_games_stats.html">t0_all_games_stats.html</a>. '
            "This page is the companion band table, not that dashboard.</p>"
        )
    return (
        '<p class="note">A living all-game T0 stats page is a separate job. '
        "This file is only the companion decision table for the both-Yes band.</p>"
    )


def maybe_patch_living_link() -> None:
    """Add a one-line link on the living page if it already exists. No rewrite."""
    if not LIVING_PAGE.is_file():
        return
    try:
        text = LIVING_PAGE.read_text(encoding="utf-8")
    except OSError:
        return
    if "t0_band_from_stay_above_20261024.html" in text:
        return
    if "</h1>" not in text or "</html>" not in text:
        return
    snippet = (
        '\n<p class="note">Companion band table (research-only; live C_HI still 1.20): '
        '<a href="t0_band_from_stay_above_20261024.html">t0_band_from_stay_above_20261024.html</a>.</p>\n'
    )
    patched = text.replace("</h1>", "</h1>" + snippet, 1)
    if patched == text:
        return
    try:
        LIVING_PAGE.write_text(patched, encoding="utf-8")
    except OSError:
        return


def tennis_ml_rows(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if str(r.get("sport") or "").lower() == "tennis"
        and str(r.get("market_type") or "") == "moneyline"
    ]


def headline_bits(rows: list[dict]) -> dict:
    fav = {r["bucket"]: r for r in summarize_fav_buckets(rows)}
    cwire = {r["bucket"]: r for r in summarize_c_buckets(rows, all_in=False)}
    tennis = tennis_ml_rows(rows)
    tfav = {r["bucket"]: r for r in summarize_fav_buckets(tennis)}
    tcwire = {r["bucket"]: r for r in summarize_c_buckets(tennis, all_in=False)}
    all_in_rows = [r for r in rows if r.get("c_all_in") is not None]
    return {
        "n": len(rows),
        "all_in_n": len(all_in_rows),
        "stay_all": fav.get("All", {}).get("stay_rate") or "—",
        "stay_70": fav.get("70-79", {}).get("stay_rate") or "—",
        "stay_50": fav.get("50-59", {}).get("stay_rate") or "—",
        "stay_gt70": fav.get("cumulative >70", {}).get("stay_rate") or "—",
        "c_moutet": cwire.get(MOUTET_C, {}).get("stay_rate") or "—",
        "c_110": cwire.get("1.10-1.14", {}).get("stay_rate") or "—",
        "c_115": cwire.get("1.15-1.20", {}).get("stay_rate") or "—",
        "c_hi": cwire.get(">1.20", {}).get("stay_rate") or "—",
        "n_ml": sum(1 for r in rows if r.get("market_type") == "moneyline"),
        "n_spread": sum(1 for r in rows if r.get("market_type") == "spread"),
        "n_tennis_ml": len(tennis),
        "tennis_stay_all": tfav.get("All", {}).get("stay_rate") or "—",
        "tennis_stay_70": tfav.get("70-79", {}).get("stay_rate") or "—",
        "tennis_stay_50": tfav.get("50-59", {}).get("stay_rate") or "—",
        "tennis_stay_gt70": tfav.get("cumulative >70", {}).get("stay_rate") or "—",
        "tennis_c_moutet": tcwire.get(MOUTET_C, {}).get("stay_rate") or "—",
        "tennis_c_115": tcwire.get("1.15-1.20", {}).get("stay_rate") or "—",
        "sports": sorted({r.get("sport") or "" for r in rows if r.get("sport")}),
    }


def implications_html(bits: dict) -> str:
    return f"""
<div class="hold">
<h2>Band implications (research only — HOLD on live change)</h2>
<p>Live today: the C_LO=0.95 floor is going away (other job). <strong>C_HI=1.20 stays</strong>
until Paul says otherwise. Stack another 1-contract both-Yes while all-in C (asks + documented
fees) is under $1. This page does not KEEP or DISMISS a new C_HI.</p>
<ul>
<li>Read the <strong>tennis moneyline</strong> slice first. That is live Strategy B’s
sport and market. Tennis ML stay-above-50 is {esc(bits['tennis_stay_all'])};
70-79 is {esc(bits['tennis_stay_70'])}; 50-59 is {esc(bits['tennis_stay_50'])};
cumulative &gt;70 is {esc(bits['tennis_stay_gt70'])}. All-sports numbers mix in
college-football spreads (very high stay-above) and pro-football spreads (very low).
If tennis stay-above-50 is high only when the T0 favorite is ≥70 and collapses in
50-59, a tighter C_HI — less vig on two mid prices — is a <strong>hypothesis</strong>,
not a wire.</li>
<li>How to read the C tables: this settled tape has almost nobody in 1.15-1.20
({esc(bits['c_115'])}) and only a handful above 1.20 ({esc(bits['c_hi'])}).
1.10-1.14 is {esc(bits['c_110'])}. On this pass the 1.20 vig cap is not the
binding risk — there is not enough N up there to judge it. Moutet-like wire
1.00-1.04 is {esc(bits['c_moutet'])} all-sports and {esc(bits['tennis_c_moutet'])}
on tennis ML.</li>
<li>Stay-above-50 and T0-favorite win rate are different. A favorite can print ≤50 and still win.
Use the win-rate C table as calibration, not as a second stay-above number.</li>
<li>Do not pick 1.15 (or any new cap) from this one pass. In-sample / out-of-sample
anti-overfit: this tape is one collection window, all out-of-sample-era 2026 live ticks
(every T0 is on or after 2024-01-01; there is no in-sample row). Choosing a cap after
seeing the table is selection bias.</li>
</ul>
<p>Acronyms, first use: T0 = first trusted start price. C = sum of the two Yes asks
(vig / house overround). C_HI = live both-Yes upper cap, still 1.20. C_LO = former
0.95 floor, going away. All-in = wire asks plus documented taker fees. Moneyline =
who wins the game. Spread = point margin. Kalshi / Gemini / Polymarket / Novig are
the four venues on this tape.</p>
</div>
"""


def write_html(rows: list[dict], meta: dict) -> None:
    bits = headline_bits(rows)
    now = iso_now()
    fav_tbl = summarize_fav_buckets(rows)
    c_wire = summarize_c_buckets(rows, all_in=False)
    c_all = summarize_c_buckets(rows, all_in=True)
    by_sport = summarize_group(rows, "sport")
    by_kind = summarize_group(rows, "market_type")
    sport_kind = summarize_sport_kind(rows)
    sport_fav = summarize_sport_fav(rows)
    all_in_note = (
        f"All-in C was computable on {bits['all_in_n']} of {bits['n']} scored "
        "venue-games (Kalshi, Gemini, Polymarket with the standard 0.0695 coefficient). "
        "Novig is wire-only here: the documented Novig taker needs a per-market coefficient "
        "and a WHEN_LIVE / ALWAYS flag, which the tick store does not carry."
        if bits["n"]
        else "No scored rows."
    )
    fav_headers = [
        ("T0 favorite Yes", "text"),
        ("Stay-above-50 (n/N)", "text"),
        ("N", "num"),
        ("Stay n", "num"),
        ("T0 favorite win rate (n/N)", "text"),
        ("Win n", "num"),
        ("Note", "text"),
    ]
    fav_fields = ["bucket", "stay_rate", "n", "stay_n", "win_rate", "win_n", "note"]
    c_headers = [
        ("T0 both-Yes C", "text"),
        ("Stay-above-50 (n/N)", "text"),
        ("N", "num"),
        ("Stay n", "num"),
        ("T0 favorite win rate (n/N)", "text"),
        ("Win n", "num"),
        ("Note", "text"),
    ]
    c_fields = fav_fields
    sport_headers = [
        ("Sport", "text"),
        ("Stay-above-50 (n/N)", "text"),
        ("N", "num"),
        ("Stay n", "num"),
        ("T0 favorite win rate (n/N)", "text"),
        ("Win n", "num"),
        ("Stay-above-but-lost", "num"),
        ("Missing crash", "num"),
        ("No post-T0 path", "num"),
        ("Stay > win (bug)?", "text"),
        ("Note", "text"),
    ]
    kind_headers = [
        ("Market", "text"),
        ("Stay-above-50 (n/N)", "text"),
        ("N", "num"),
        ("Stay n", "num"),
        ("T0 favorite win rate (n/N)", "text"),
        ("Win n", "num"),
        ("Stay-above-but-lost", "num"),
        ("Missing crash", "num"),
        ("No post-T0 path", "num"),
        ("Stay > win (bug)?", "text"),
        ("Note", "text"),
    ]
    sk_headers = [
        ("Sport · market", "text"),
        ("Sport", "text"),
        ("Market", "text"),
        ("Stay-above-50 (n/N)", "text"),
        ("N", "num"),
        ("Stay n", "num"),
        ("T0 favorite win rate (n/N)", "text"),
        ("Win n", "num"),
        ("Stay-above-but-lost", "num"),
        ("Missing crash", "num"),
        ("No post-T0 path", "num"),
        ("Stay > win (bug)?", "text"),
        ("Note", "text"),
    ]
    sk_fields = [
        "bucket", "sport", "market_type", "stay_rate", "n", "stay_n", "win_rate", "win_n",
        "stay_lost", "missing_crash", "no_post", "violates", "note",
    ]
    ineq_fields = [
        "bucket", "stay_rate", "n", "stay_n", "win_rate", "win_n",
        "stay_lost", "missing_crash", "no_post", "violates", "note",
    ]
    sf_headers = [
        ("Sport", "text"),
        ("T0 favorite Yes", "text"),
        ("Stay-above-50 (n/N)", "text"),
        ("N", "num"),
        ("Stay n", "num"),
        ("T0 favorite win rate (n/N)", "text"),
        ("Win n", "num"),
        ("Note", "text"),
    ]
    sf_fields = ["sport", "bucket", "stay_rate", "n", "stay_n", "win_rate", "win_n", "note"]
    shared_note = (
        f" Metrics imported from <code>write_t0_all_games_stats.py</code> ({esc(meta.get('shared'))})."
        if meta.get("shared")
        else " Living-dashboard helper was not present at scan time; T0 and stay-above use this file's copy of the house trusted-serve rule."
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>T0 band vs stay-above-50 — 2026-10-24</title>
<style>
body {{ font-family: Georgia, serif; margin: 1.2rem auto; padding: 0 1rem 3rem; color: #0f172a; background: #fff; }}
h1, h2 {{ font-family: "Segoe UI", sans-serif; }}
.asked, .plain, .hold, .freeze {{ padding: 0.8rem 1rem; margin: 0.8rem 0 1.2rem; border-radius: 8px; }}
.asked {{ background: #eef2ff; border: 1px solid #c7d2fe; }}
.plain {{ background: #f0fdf4; border: 1px solid #bbf7d0; }}
.hold {{ background: #fff7ed; border: 1px solid #fdba74; }}
.freeze {{ background: #f8fafc; border: 1px solid #cbd5e1; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.9em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>T0 both-Yes band from stay-above-50</h1>
{living_link_html()}
<div class="asked">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="plain">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<div class="freeze">
<p><strong>Live knobs (not changed by this page):</strong> C_HI = 1.20 (vig cap).
D = 0.25 (extra-pair lock, unused here). Stack while all-in C &lt; $1. C_LO=0.95
floor is the other job. No GTC. No second Strategy B. Research only. Not gold. Not DailyRun.</p>
<p><strong>Universe:</strong> every tracked two-sided moneyline or spread on the local
price_memory tape (archive + dated shards) with a trusted T0 and an official
settlement. Not fills only. Grain is venue-game (spread line included): one tennis
match on Kalshi and Gemini is two rows. Trusted T0 (occurrence or scheduled listed/feed):
{esc(meta.get("n_trusted"))}. Official two-sided settlement among those:
{esc(meta.get("n_settled_trusted"))}. N scored = {bits['n']}. Tennis moneyline N =
{bits['n_tennis_ml']}. Moneyline N = {bits['n_ml']}. Spread N = {bits['n_spread']}.
Sports: {esc(", ".join(bits["sports"]) or "none")}.
All-in C rows = {bits['all_in_n']}. Tick lines streamed = {esc(meta.get("n_lines"))}.
Tape {esc(meta.get("seen_min"))} → {esc(meta.get("seen_max"))}. Written {esc(now)} ET.</p>
</div>
<p><strong>Headline.</strong> Tennis moneyline (live Strategy B’s book): stay-above-50
{esc(bits["tennis_stay_all"])}; 70-79 {esc(bits["tennis_stay_70"])}; 50-59
{esc(bits["tennis_stay_50"])}; cumulative &gt;70 {esc(bits["tennis_stay_gt70"])};
Moutet-like wire C 1.00-1.04 {esc(bits["tennis_c_moutet"])}; 1.15-1.20
{esc(bits["tennis_c_115"])}. All scored venue-games (ML + spread, every sport):
{esc(bits["stay_all"])} stay-above-50. 70-79 {esc(bits["stay_70"])}. 50-59
{esc(bits["stay_50"])}. Cumulative &gt;70 {esc(bits["stay_gt70"])}.</p>
<p class="note">{esc(all_in_note)}{shared_note} Click column headers to sort.</p>
{implications_html(bits)}
<h2>0. Tennis moneyline only (Strategy B slice)</h2>
<p class="note">Live Strategy B buys tennis moneyline both-Yes. Use this slice to think
about the band. The all-sports tables below are the full tracked tape, including
spreads.</p>
{html_table(fav_headers, summarize_fav_buckets(tennis_ml_rows(rows)), fav_fields)}
<h3>Tennis moneyline, by wire C</h3>
{html_table(c_headers, summarize_c_buckets(tennis_ml_rows(rows), all_in=False), c_fields)}
<h3>Tennis moneyline, by all-in C</h3>
{html_table(c_headers, summarize_c_buckets(tennis_ml_rows(rows), all_in=True), c_fields)}
<h2>1. Stay-above-50 of the T0 favorite, by T0 Yes bucket (all sports)</h2>
<p class="note">Favorite = higher T0 Yes ask. Stay-above-50 = that Yes never printed
≤0.50 after T0 on a complete watch (post-T0 ticks; last tick still &gt;50¢ plus an
official loss is path_incomplete, not stay-above). Empty tape after T0 is not
stay-above. Win rate on the same rows is shown so you can see they are not the same
number. After the completeness fix, stay-above should be ≤ win rate on this N.
Cumulative rows are not disjoint.</p>
{html_table(fav_headers, fav_tbl, fav_fields)}
<h2>2a. Stay-above-50 by T0 both-Yes wire C</h2>
<p class="note">Wire C is the two Yes asks, no fees. 1.00-1.04 is the Moutet-like
band (his asks were 1.01; all-in 1.035).</p>
{html_table(c_headers, c_wire, c_fields)}
<h2>2b. Stay-above-50 by T0 both-Yes all-in C</h2>
<p class="note">{esc(all_in_note)} Rows without a documented fee (Novig) are omitted
from this table, not treated as zero-fee.</p>
{html_table(c_headers, c_all, c_fields)}
<h2>3. T0 favorite win rate in the same C buckets</h2>
<p class="note">Calibration, not stay-above-50. A favorite can dip below 50 and still
win. Same N as table 2a (wire) and 2b (all-in). The win-rate column is already on
those tables; this restates the wire book so the two ideas stay side by side.</p>
{html_table(c_headers, c_wire, c_fields)}
<h2>4. Split by sport and moneyline vs spread</h2>
<p class="note">Tiny N is labeled. Spread two-sided Yes at the same line (example:
Indiana wins by over 4.5 vs Michigan wins by over 4.5). Totals are out.</p>
<h3>By sport</h3>
{html_table(sport_headers, by_sport, ineq_fields)}
<h3>By moneyline vs spread vs total</h3>
{html_table(kind_headers, by_kind, ineq_fields)}
<h3>Sport × market</h3>
{html_table(sk_headers, sport_kind, sk_fields)}
<h3>Sport × T0 favorite bucket</h3>
{html_table(sf_headers, sport_fav, sf_fields)}
<p class="note">Sources: local <code>price_memory</code> archive + dated sport shards;
<code>odds_cross_settlements_20261020.json</code> plus Polymarket tennis resolutions.
T0 via <code>assign_actual_t0</code> then drop untrusted clocks. Did not edit
<code>live_strategy_b.py</code>. Did not sell tickets. Did not wire GTC. Did not
change live C_HI=1.20 or D=0.25. Pulled {esc(now)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def main() -> int:
    rows, meta = collect_rows()
    write_html(rows, meta)
    maybe_patch_living_link()
    bits = headline_bits(rows)
    print(
        f"HEADLINE stay-all={bits['stay_all']} fav70={bits['stay_70']} "
        f"fav50={bits['stay_50']} C1.00-1.04={bits['c_moutet']} "
        f"C1.15-1.20={bits['c_115']} N={bits['n']} all_in_n={bits['all_in_n']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
