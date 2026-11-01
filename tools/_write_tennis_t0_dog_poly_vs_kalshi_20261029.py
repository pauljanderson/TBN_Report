"""Polymarket vs Kalshi tennis T0 dog prices, plus E / decile 1.05 answers.

Research display only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not retune E 11-49 or B
after-fee <= 1.05. Does not DailyRun. Does not rewrite dashboard.html.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import statistics
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

import live_tennis_t0_dog as live_e
import live_t0_yes
import prediction_systems as systems
import report_page_extras
import t0_all_games_stats as t0
from live_strategy_b import C_HI
from odds_cross_winrate_20261020 import as_float, game_norm
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP, RAW_DIR as RAW
from price_memory import iter_tick_lines
from write_t0_band_from_stay_above import documented_leg_fee

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "tennis_t0_dog_poly_vs_kalshi_20261029.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/tennis_t0_dog_poly_vs_kalshi_20261029.html"
)
DECILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/sport_league_t0_decile_20261027.html"
)
HIST_DIR = LOCAL_STAMP / "hist"
STOP_NAME = {
    "van", "de", "da", "di", "le", "la", "el", "del", "von", "der", "the", "mc",
}
ASKED = (
    "Paul: A lot of our T0 tennis dogs were bought on Polymarket. Can we see if "
    "the price was the same or lower than Kalshi? For all tennis T0 starts we have "
    "prices for BOTH Kalshi and Polymarket, show the total (and typical) dog price "
    "on each platform, and how many matches we have that data for. When running "
    "the decile report, do we have any idea if opponent + dog > 1.05? Do we only "
    "buy the dog when dog and opponent are <= 1.05?"
)
PLAIN = (
    "We often bought the cheap tennis player on Polymarket at first serve. This "
    "page asks whether Kalshi was asking the same price, more, or less for that "
    "cheap side — and how many matches we actually saw on both books. Typical "
    "means the average and the middle (median) cheap-side price. Total is what "
    "you would have paid to buy one contract of every dual-listed cheap side. "
    "The 10-cent bucket sheet is a different question: it groups named Yes prices "
    "at start into 10¢ bands. It does not look at whether the other player’s Yes "
    "plus this dog added up to more than $1.05, so a 20¢ dog sitting next to a "
    "90¢ favorite (pair $1.20) still lands in tennis 10–49. Live E buys that dog "
    "when it is 11–49¢ and Tennis crossover (B) did not already take the match. "
    "E does not require the pair to be $1.05. B is the one that only buys both "
    "Yes when the after-fee sum is at most $1.05; those games skip E."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def fnum(value) -> float | None:
    got = as_float(value)
    if got is None:
        return None
    try:
        x = float(got)
    except (TypeError, ValueError):
        return None
    if x <= 0.0 or x >= 1.0:
        return None
    return x


def fmt_px(value, digits: int = 3) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_money(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def mean(xs: list[float]) -> float | None:
    return float(statistics.mean(xs)) if xs else None


def median(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def pid(name: str) -> str:
    text = str(name or "").strip()
    if "," in text:
        text = text.split(",", 1)[0]
    bits = [
        t for t in re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
        if t and t not in STOP_NAME and len(t) >= 3
    ]
    if bits:
        return bits[-1]
    return live_t0_yes.last_name_token(text)


def player_ids(*names: str) -> frozenset[str]:
    got = {pid(n) for n in names if str(n or "").strip()}
    got.discard("")
    return frozenset(got)


def book_ids(book: dict) -> frozenset[str]:
    sides = player_ids(str(book.get("side_a") or ""), str(book.get("side_b") or ""))
    if len(sides) == 2:
        return sides
    named = player_ids(str(book.get("dog_name") or ""), str(book.get("fav_name") or ""))
    if len(named) == 2:
        return named
    title = live_t0_yes.match_player_set(book.get("game") or book.get("title") or "")
    return title if len(title) == 2 else frozenset()


def same_cent(a: float, b: float) -> bool:
    return round(a * 100.0) == round(b * 100.0)


def cmp_poly_vs_k(poly: float, kalshi: float) -> str:
    if same_cent(poly, kalshi):
        return "same"
    if poly < kalshi:
        return "lower"
    return "higher"


def dog_from_two(name_px: dict[str, float]) -> dict | None:
    """Cheaper named Yes under 50c. Skip ties and missing. min(yes_a, yes_b) if min<0.50."""
    rows = [(n, p) for n, p in name_px.items() if n and p is not None]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda item: item[1])
    if rows[0][1] == rows[1][1]:
        return None
    if rows[0][1] >= 0.50:
        return None
    dog_n, dog_px = rows[0]
    fav_n, fav_px = rows[1]
    return {
        "dog": dog_n,
        "dog_px": dog_px,
        "fav": fav_n,
        "fav_px": fav_px,
        "pair": dog_px + fav_px,
        "ids": player_ids(dog_n, fav_n),
    }


def after_fee_pair(venue: str, dog_px: float, fav_px: float) -> float | None:
    fee_d = documented_leg_fee(venue, dog_px)
    fee_f = documented_leg_fee(venue, fav_px)
    if fee_d is None or fee_f is None:
        return None
    return float(Decimal(str(dog_px)) + Decimal(str(fav_px)) + fee_d + fee_f)


def summarize(xs: list[float]) -> dict:
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "total": float(sum(xs)) if xs else None,
    }


def dual_stats(pairs: list[dict]) -> dict:
    k = [r["k_dog_px"] for r in pairs]
    p = [r["p_dog_px"] for r in pairs]
    gaps = [r["p_dog_px"] - r["k_dog_px"] for r in pairs]
    n_lt = sum(1 for r in pairs if cmp_poly_vs_k(r["p_dog_px"], r["k_dog_px"]) == "lower")
    n_eq = sum(1 for r in pairs if cmp_poly_vs_k(r["p_dog_px"], r["k_dog_px"]) == "same")
    n_gt = sum(1 for r in pairs if cmp_poly_vs_k(r["p_dog_px"], r["k_dog_px"]) == "higher")
    same_name = sum(1 for r in pairs if pid(r.get("k_dog") or "") == pid(r.get("p_dog") or ""))
    return {
        "n": len(pairs),
        "k": summarize(k),
        "p": summarize(p),
        "mean_gap": mean(gaps),
        "median_gap": median(gaps),
        "n_poly_lower": n_lt,
        "n_same": n_eq,
        "n_poly_higher": n_gt,
        "pct_poly_lower": (100.0 * n_lt / len(pairs)) if pairs else None,
        "pct_same": (100.0 * n_eq / len(pairs)) if pairs else None,
        "pct_poly_higher": (100.0 * n_gt / len(pairs)) if pairs else None,
        "n_same_dog_name": same_name,
        "n_pair_gt_105_k": sum(1 for r in pairs if (r.get("k_pair") or 0) > 1.05 + 1e-12),
        "n_pair_gt_105_p": sum(1 for r in pairs if (r.get("p_pair") or 0) > 1.05 + 1e-12),
    }


def pair_hist_sides(sides: list[dict], *, venue: str) -> tuple[list[dict], dict]:
    bags: dict[str, list[dict]] = defaultdict(list)
    n_tennis = 0
    for row in sides:
        if str(row.get("sport") or "").lower() != "tennis":
            continue
        if str(row.get("kind") or "") != "moneyline":
            continue
        n_tennis += 1
        bags[str(row.get("game_n") or row.get("game") or "")].append(row)
    out = []
    counts = {
        "n_sides": n_tennis,
        "n_events": len(bags),
        "n_lt2": 0,
        "n_gt2": 0,
        "n_bad_px": 0,
        "n_tie": 0,
        "n_no_dog": 0,
        "n_ok": 0,
    }
    for key, rows in bags.items():
        name_px: dict[str, float] = {}
        t0_ts = None
        entry = ""
        title = ""
        for row in rows:
            name = str(row.get("fav_name") or "").strip()
            px = fnum(row.get("t0_fav") if row.get("t0_fav") is not None else row.get("t0_a"))
            if name and px is not None:
                name_px[name] = px
            if t0_ts is None:
                t0_ts = row.get("t0_ts")
            if not entry:
                entry = str(row.get("entry_date") or "")
            if not title:
                title = str(row.get("game") or key)
        if len(name_px) < 2:
            counts["n_lt2"] += 1
            continue
        if len(name_px) > 2:
            counts["n_gt2"] += 1
            continue
        if any(px is None for px in name_px.values()):
            counts["n_bad_px"] += 1
            continue
        dog = dog_from_two(name_px)
        if dog is None:
            vals = list(name_px.values())
            if len(vals) >= 2 and vals[0] == vals[1]:
                counts["n_tie"] += 1
            elif min(vals) >= 0.50:
                counts["n_no_dog"] += 1
            else:
                counts["n_bad_px"] += 1
            continue
        if len(dog["ids"]) < 2:
            counts["n_lt2"] += 1
            continue
        counts["n_ok"] += 1
        fee_pair = after_fee_pair(venue, dog["dog_px"], dog["fav_px"])
        out.append({
            "venue": venue,
            "game": title or key,
            "game_n": key,
            "entry_date": entry,
            "t0_ts": int(t0_ts) if t0_ts not in (None, "") else None,
            **dog,
            "fee_pair": fee_pair,
            "source": "hist",
        })
    return out, counts


def live_two_sided_row(book: dict) -> dict | None:
    """Two-sided tennis ML T0 Yes asks. Dog fields filled only when min < 0.50."""
    if str(book.get("sport") or "").lower() != "tennis":
        return None
    if str(book.get("kind") or "moneyline") != "moneyline":
        return None
    if not book.get("two_sided"):
        return None
    a = fnum(book.get("t0_a"))
    b = fnum(book.get("t0_b"))
    if a is None or b is None:
        return None
    name_a = str(book.get("side_a") or "a")
    name_b = str(book.get("side_b") or "b")
    name_px = {name_a: a, name_b: b}
    dog = dog_from_two(name_px) or {}
    venue = str(book.get("venue") or "").strip().lower()
    fee_pair = None
    if dog.get("dog_px") is not None:
        fee_pair = after_fee_pair(venue, dog["dog_px"], dog["fav_px"])
    t0_ts = book.get("t0_ts")
    entry = ""
    if t0_ts:
        try:
            entry = datetime.fromtimestamp(int(t0_ts), ET).date().isoformat()
        except (OSError, ValueError, TypeError, OverflowError):
            entry = ""
    ids = dog.get("ids") or player_ids(name_a, name_b)
    return {
        "venue": venue,
        "game": str(book.get("game") or ""),
        "game_n": str(book.get("game_n") or ""),
        "entry_date": entry,
        "t0_ts": int(t0_ts) if t0_ts not in (None, "") else None,
        "t0_label": str(book.get("t0_label") or ""),
        "name_px": name_px,
        "ids": ids,
        "dog": dog.get("dog"),
        "dog_px": dog.get("dog_px"),
        "fav": dog.get("fav"),
        "fav_px": dog.get("fav_px"),
        "pair": dog.get("pair") if dog else (a + b),
        "fee_pair": fee_pair,
        "source": "live",
        "c0": book.get("c0"),
    }


def live_dog_row(book: dict) -> dict | None:
    row = live_two_sided_row(book)
    if row is None or row.get("dog_px") is None:
        return None
    return row


def match_dual(kalshi_rows: list[dict], poly_rows: list[dict], *, max_gap_sec: int = 18 * 3600) -> tuple[list[dict], dict]:
    idx: dict[frozenset[str], list[dict]] = defaultdict(list)
    for row in kalshi_rows:
        ids = row.get("ids") or frozenset()
        if len(ids) == 2:
            idx[ids].append(row)
    matched = []
    unmatched = 0
    used: set[int] = set()
    for prow in poly_rows:
        ids = prow.get("ids") or frozenset()
        cands = [c for c in (idx.get(ids) or []) if id(c) not in used]
        if not cands:
            unmatched += 1
            continue
        chosen = None
        pts = prow.get("t0_ts")
        pdate = str(prow.get("entry_date") or "")
        dated = [c for c in cands if pdate and str(c.get("entry_date") or "") == pdate]
        pool = dated or cands
        if pts:
            with_ts = [c for c in pool if c.get("t0_ts")]
            if with_ts:
                with_ts.sort(key=lambda c: abs(int(c["t0_ts"]) - int(pts)))
                if abs(int(with_ts[0]["t0_ts"]) - int(pts)) <= max_gap_sec:
                    chosen = with_ts[0]
        if chosen is None and dated:
            chosen = dated[0]
        if chosen is None and not pts:
            if len(pool) == 1:
                chosen = pool[0]
        if chosen is None:
            unmatched += 1
            continue
        used.add(id(chosen))
        k_px_named = None
        want = pid(prow.get("dog") or "")
        if want:
            if pid(chosen.get("dog") or "") == want:
                k_px_named = chosen["dog_px"]
            elif pid(chosen.get("fav") or "") == want:
                k_px_named = chosen["fav_px"]
        matched.append({
            "game_k": chosen.get("game"),
            "game_p": prow.get("game"),
            "date": pdate or chosen.get("entry_date") or "",
            "k_dog": chosen.get("dog"),
            "p_dog": prow.get("dog"),
            "k_fav": chosen.get("fav"),
            "p_fav": prow.get("fav"),
            "k_dog_px": chosen["dog_px"],
            "p_dog_px": prow["dog_px"],
            "k_fav_px": chosen.get("fav_px"),
            "p_fav_px": prow.get("fav_px"),
            "k_pair": chosen.get("pair"),
            "p_pair": prow.get("pair"),
            "k_fee_pair": chosen.get("fee_pair"),
            "p_fee_pair": prow.get("fee_pair"),
            "gap": prow["dog_px"] - chosen["dog_px"],
            "cmp": cmp_poly_vs_k(prow["dog_px"], chosen["dog_px"]),
            "same_dog_name": pid(chosen.get("dog") or "") == pid(prow.get("dog") or ""),
            "k_px_named_poly_dog": k_px_named,
            "source_k": chosen.get("source"),
            "source_p": prow.get("source"),
        })
    return matched, {"n_poly": len(poly_rows), "n_kalshi": len(kalshi_rows), "n_matched": len(matched), "n_unmatched_poly": unmatched}


def stream_tennis_yes_sides() -> tuple[dict, dict]:
    """Tennis-only copy of t0.stream_yes_sides. Scans tennis shards + archive lines with tennis."""
    sides: dict[tuple, dict] = {}
    n_lines = 0
    n_yes = 0
    seen_min = ""
    seen_max = ""
    sports: dict[str, int] = defaultdict(int)
    kinds: dict[str, int] = defaultdict(int)
    for line in iter_tick_lines(sport="tennis"):
        n_lines += 1
        if n_lines % 400000 == 0:
            print(f"  tennis stream {n_lines} lines, sides {len(sides)} ticks {n_yes}", flush=True)
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
        if sport.strip().lower() != "tennis":
            continue
        game = rec.get("game") or ""
        kind = str(rec.get("market_type") or "moneyline") or "moneyline"
        number = "" if kind == "moneyline" else str(rec.get("number") or "")
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
    n_overlay = t0.overlay_last_yes(sides)
    tennis_sides = {k: v for k, v in sides.items() if str(k[0]).lower() == "tennis"}
    print(
        f"tennis stream done lines={n_lines} yes={n_yes} sides={len(tennis_sides)} "
        f"overlay={n_overlay} seen {seen_min} .. {seen_max}",
        flush=True,
    )
    for st in tennis_sides.values():
        st["ticks"].sort(key=lambda row: row[0])
    return tennis_sides, {
        "n_lines": n_lines,
        "n_yes": n_yes,
        "n_sides": len(tennis_sides),
        "n_overlay": n_overlay,
        "seen_min": seen_min,
        "seen_max": seen_max,
        "sports": dict(sports),
        "kinds": dict(kinds),
    }


def load_live_tennis_books() -> tuple[list[dict], dict]:
    print("loading tennis settlements / T0 clocks", flush=True)
    settlements = t0.load_settlement_rows()
    occ_map = t0.start_lookup_from_settlements(settlements)
    index = t0.build_index(settlements)
    sides, meta = stream_tennis_yes_sides()
    books = t0.pair_books(sides)
    print(f"paired {len(books)} tennis venue-game books", flush=True)
    for i, book in enumerate(books):
        t0.settle_book(book, settlements, index)
        t0.score_book(book, occ_map)
        book.pop("yes_a", None)
        book.pop("yes_b", None)
        if (i + 1) % 500 == 0:
            print(f"  scored {i + 1}/{len(books)}", flush=True)
    meta["n_books"] = len(books)
    meta["n_two_sided_t0"] = sum(
        1 for b in books if b.get("two_sided") and b.get("t0_a") is not None and b.get("t0_b") is not None
    )
    return books, meta


def slice_1049(rows: list[dict]) -> dict:
    """Tennis 10-49 cheaper Yes. WITHOUT = all; WITH = raw pair <= 1.05."""
    band = []
    for row in rows:
        px = row.get("dog_px")
        if px is None:
            continue
        if px < 0.10 - 1e-12 or px >= 0.50 - 1e-12:
            continue
        band.append(row)
    with_raw = [r for r in band if (r.get("pair") or 9) <= 1.05 + 1e-12]
    with_fee = [r for r in band if r.get("fee_pair") is not None and r["fee_pair"] <= 1.05 + 1e-12]
    over = [r for r in band if (r.get("pair") or 0) > 1.05 + 1e-12]
    over120 = [r for r in band if (r.get("pair") or 0) > 1.20 - 1e-12]

    def pack(xs: list[dict], label: str) -> dict:
        dogs = [r["dog_px"] for r in xs]
        pairs = [r["pair"] for r in xs if r.get("pair") is not None]
        return {
            "label": label,
            "n": len(xs),
            "mean_dog": mean(dogs),
            "median_dog": median(dogs),
            "mean_pair": mean(pairs),
            "median_pair": median(pairs),
        }

    return {
        "without": pack(band, "tennis 10-49 (no pair filter — sheet cells)"),
        "with_raw": pack(with_raw, "tennis 10-49 AND dog+fav <= 1.05 (raw Yes)"),
        "with_fee": pack(with_fee, "tennis 10-49 AND after-fee pair <= 1.05 (B gate, same venue)"),
        "over_105": pack(over, "tennis 10-49 with pair > 1.05"),
        "over_120": pack(over120, "tennis 10-49 with pair > 1.20 (e.g. 30c + 90c)"),
    }


def load_json(path: Path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data


def yes_player_from_side(side: str, game: str) -> str:
    text = str(side or "").strip()
    if text.lower().startswith("yes "):
        return text[4:].strip()
    if text.lower().startswith("no "):
        who = text[3:].strip()
        parts = live_t0_yes._VS_SPLIT.split(str(game or ""), maxsplit=1)
        if len(parts) == 2:
            a, b = parts[0].strip(), parts[1].strip()
            if pid(who) == pid(a):
                return b
            if pid(who) == pid(b):
                return a
        return who
    return text


def load_e_poly_fills() -> list[dict]:
    cache = load_json(RAW / "dashboard_cache.json")
    watch = load_json(RAW / "tennis_t0_dog_watch.json")
    by_game = {}
    for row in watch.get("matches") or []:
        if isinstance(row, dict) and row.get("game"):
            by_game[game_norm(row.get("game") or "")] = row
    out = []
    seen = set()
    for row in cache.get("all_rows") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("system") or "") != "E":
            continue
        if str(row.get("venue") or "").lower() != "polymarket":
            continue
        if str(row.get("filled") or "").lower() != "yes":
            continue
        oid = str(row.get("order_id") or "")
        if oid and oid in seen:
            continue
        if oid:
            seen.add(oid)
        game = str(row.get("game") or "")
        watch_row = by_game.get(game_norm(game)) or {}
        px = fnum(row.get("wire") or row.get("quote_price") or watch_row.get("dog_ask"))
        player = yes_player_from_side(str(row.get("side") or ""), game) or str(watch_row.get("dog") or "")
        out.append({
            "when": str(row.get("when") or row.get("when_raw") or ""),
            "game": game,
            "player": player,
            "poly_px": px,
            "fee": fnum(row.get("fee")) if row.get("fee") not in (None, "") else None,
            "qty": str(row.get("qty") or ""),
            "order_id": oid,
            "side": str(row.get("side") or ""),
            "dog_ask_watch": fnum(watch_row.get("dog_ask")),
            "t0_when": str(watch_row.get("t0_when") or ""),
            "watch_venue": str(watch_row.get("venue") or ""),
        })
    out.sort(key=lambda r: str(r.get("when") or ""))
    return out


def attach_kalshi_to_fills(fills: list[dict], k_rows: list[dict]) -> list[dict]:
    idx: dict[frozenset[str], list[dict]] = defaultdict(list)
    for row in k_rows:
        ids = row.get("ids") or frozenset()
        if len(ids) == 2:
            idx[ids].append(row)
    attached = []
    for fill in fills:
        game = fill.get("game") or ""
        ids = live_t0_yes.match_player_set(game)
        if len(ids) < 2:
            ids = player_ids(*[p.strip() for p in live_t0_yes._VS_SPLIT.split(game, maxsplit=1)])
        cands = list(idx.get(ids) or [])
        if not cands:
            for krow in k_rows:
                kg = krow.get("game") or ""
                if live_t0_yes.same_game(kg, game):
                    cands.append(krow)
                    continue
                kids = krow.get("ids") or frozenset()
                if ids and kids and ids == kids:
                    cands.append(krow)
        chosen = None
        if cands:
            t0_when = fill.get("t0_when") or ""
            ts = None
            if t0_when:
                try:
                    ts = int(datetime.fromisoformat(t0_when).timestamp())
                except ValueError:
                    ts = None
            if ts:
                with_ts = [c for c in cands if c.get("t0_ts")]
                if with_ts:
                    with_ts.sort(key=lambda c: abs(int(c["t0_ts"]) - ts))
                    chosen = with_ts[0]
            if chosen is None:
                chosen = cands[0]
        row = dict(fill)
        if chosen is None:
            row["k_present"] = False
            row["k_dog"] = ""
            row["k_dog_px"] = None
            row["k_named_px"] = None
            row["cmp"] = "Kalshi T0 missing"
            row["k_game"] = ""
            row["k_pair"] = None
        else:
            want = pid(fill.get("player") or "")
            named = None
            for name, px in (chosen.get("name_px") or {}).items():
                if pid(name) == want:
                    named = px
                    break
            if named is None:
                if want and pid(chosen.get("dog") or "") == want:
                    named = chosen.get("dog_px")
                elif want and pid(chosen.get("fav") or "") == want:
                    named = chosen.get("fav_px")
            poly_px = fill.get("poly_px")
            k_px = named if named is not None else chosen.get("dog_px")
            row["k_present"] = True
            row["k_dog"] = chosen.get("dog")
            row["k_dog_px"] = chosen.get("dog_px")
            row["k_named_px"] = named
            row["k_fav_px"] = chosen.get("fav_px")
            row["k_pair"] = chosen.get("pair")
            if row["k_pair"] is None and chosen.get("name_px"):
                xs = [float(v) for v in chosen["name_px"].values() if v is not None]
                if len(xs) >= 2:
                    row["k_pair"] = xs[0] + xs[1]
            row["k_game"] = chosen.get("game")
            if poly_px is None or k_px is None:
                row["cmp"] = "price missing"
            else:
                row["cmp"] = cmp_poly_vs_k(poly_px, k_px)
            row["gap"] = (poly_px - k_px) if poly_px is not None and k_px is not None else None
        attached.append(row)
    return attached


def e_code_answers() -> dict:
    """Read live E / B. Do not guess — call plan_send / b_holds_match."""
    over = {
        "matches": [{
            "game": "Ada vs Bea",
            "stage": "skipped",
            "skip_reason": live_e.T0_C_OVER,
            "note": live_e.T0_C_OVER,
        }]
    }
    held = {
        "matches": [{
            "game": "Ada vs Bea",
            "stage": "waiting_t0",
        }]
    }
    still = live_e.b_holds_match("Ada vs Bea", b_status=over) is False
    skip_b = live_e.b_holds_match("Ada vs Bea", b_status=held) is True
    plan = live_e.plan_send(
        side_asks={"Ada": Decimal("0.30"), "Bea": Decimal("0.80")},
        title="Ada vs Bea",
        b_status=over,
    )
    plan_held = live_e.plan_send(
        side_asks={"Ada": Decimal("0.30"), "Bea": Decimal("0.80")},
        title="Ada vs Bea",
        b_status=held,
    )
    band = systems.DOG_LO == Decimal("0.10") and systems.DOG_HI == Decimal("0.50")
    b_c = C_HI == Decimal("1.05")
    return {
        "e_requires_pair_105": False,
        "e_skip_if_b": skip_b and plan_held.get("reason") == "B already on match",
        "e_still_sends_when_b_c_over": still and plan.get("action") == "send",
        "dog_band": "0.10 < px < 0.50",
        "b_c_hi": str(C_HI),
        "b_c_ok": b_c,
        "band_ok": band,
        "source_e": "tools/live_tennis_t0_dog.py plan_send / b_holds_match",
        "source_b": "tools/live_strategy_b.py C_HI=1.05 t0_allin_c_over_105",
    }


def decile_answers() -> dict:
    src = (ROOT / "tools" / "_write_sport_league_t0_decile_20261027.py").read_text(encoding="utf-8")
    knows_opp = "pair" in src.lower() and "1.05" in src and "dog+opp" in src
    filters = "1.05" in src and ("pair <=" in src or "c0" in src and "filter" in src)
    # Generator mentions C=1.05 as a freeze-not-to-retune, not as a cell filter.
    cell_filter = False
    return {
        "knows_opponent_ask": False,
        "filters_pair_105": cell_filter,
        "mentions_c105_as_freeze": "retune C=1.05" in src,
        "one_cheaper_yes_per_game_side": "pick_one_side" in src,
        "explode_both_sides": "explode_cover_yes_sides" in src,
        "knows_opp_scan": knows_opp,
        "filters_scan": filters,
        "source": "tools/_write_sport_league_t0_decile_20261027.py",
    }


def pct_cell(n: int | None, d: int | None) -> str:
    if not d:
        return "—"
    return f"{100.0 * (n or 0) / d:.1f}%"


def stats_rows(label: str, st: dict) -> list[list[str]]:
    n = int(st.get("n") or 0)
    k, p = st.get("k") or {}, st.get("p") or {}
    return [[
        esc(label),
        str(n),
        fmt_px(k.get("mean")),
        fmt_px(k.get("median")),
        fmt_money(k.get("total")),
        fmt_px(p.get("mean")),
        fmt_px(p.get("median")),
        fmt_money(p.get("total")),
        str(st.get("n_poly_lower") or 0),
        pct_cell(st.get("n_poly_lower"), n),
        str(st.get("n_same") or 0),
        pct_cell(st.get("n_same"), n),
        str(st.get("n_poly_higher") or 0),
        pct_cell(st.get("n_poly_higher"), n),
        fmt_px(st.get("mean_gap")),
        fmt_px(st.get("median_gap")),
        str(st.get("n_same_dog_name") or 0),
        str(st.get("n_pair_gt_105_k") or 0),
        str(st.get("n_pair_gt_105_p") or 0),
    ]]


def slice_rows(book: str, sl: dict) -> list[list[str]]:
    out = []
    for key in ("without", "with_raw", "with_fee", "over_105", "over_120"):
        rec = sl.get(key) or {}
        out.append([
            esc(book),
            esc(rec.get("label") or key),
            str(rec.get("n") or 0),
            fmt_px(rec.get("mean_dog")),
            fmt_px(rec.get("median_dog")),
            fmt_px(rec.get("mean_pair")),
            fmt_px(rec.get("median_pair")),
        ])
    return out


def write_html(payload: dict) -> str:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    e_ans = payload["e"]
    d_ans = payload["decile"]
    live_st = payload["live_stats"]
    hist_st = payload["hist_stats"]
    live_n = int(live_st.get("n") or 0)
    hist_n = int(hist_st.get("n") or 0)
    fills = payload["fills"]
    fills_k = [r for r in fills if r.get("k_present")]
    n_fill = len(fills)
    n_fill_k = len(fills_k)
    n_lower = sum(1 for r in fills_k if r.get("cmp") == "lower")
    n_same = sum(1 for r in fills_k if r.get("cmp") == "same")
    n_higher = sum(1 for r in fills_k if r.get("cmp") == "higher")

    dual_headers = [
        ("Book", "text"),
        ("N matches both books", "num"),
        ("Kalshi mean dog", "num"),
        ("Kalshi median dog", "num"),
        ("Kalshi total (1-contract sum)", "num"),
        ("Poly mean dog", "num"),
        ("Poly median dog", "num"),
        ("Poly total (1-contract sum)", "num"),
        ("Poly lower N", "num"),
        ("Poly lower %", "num"),
        ("Same N", "num"),
        ("Same %", "num"),
        ("Poly higher N", "num"),
        ("Poly higher %", "num"),
        ("Mean gap (Poly − Kalshi)", "num"),
        ("Median gap", "num"),
        ("Same dog name N", "num"),
        ("Kalshi pair > 1.05 N", "num"),
        ("Poly pair > 1.05 N", "num"),
    ]
    dual_table = t0.table(
        dual_headers,
        stats_rows("Live four-platform T0 Yes ask (venue-true)", live_st)
        + stats_rows("Hist: Kalshi yes_ask candle vs Poly CLOB last-trade", hist_st),
    )

    slice_headers = [
        ("Book", "text"),
        ("Slice", "text"),
        ("N dogs 10-49", "num"),
        ("Mean dog", "num"),
        ("Median dog", "num"),
        ("Mean pair (dog+fav)", "num"),
        ("Median pair", "num"),
    ]
    slice_table = t0.table(
        slice_headers,
        slice_rows("Live Kalshi Yes ask", payload["slice_live_k"])
        + slice_rows("Live Polymarket Yes ask", payload["slice_live_p"])
        + slice_rows("Hist Kalshi yes_ask candle", payload["slice_hist_k"])
        + slice_rows("Hist Poly last-trade", payload["slice_hist_p"]),
    )

    fill_headers = [
        ("When", "text"),
        ("Match", "text"),
        ("E dog (Poly Yes)", "text"),
        ("Poly fill / wire", "num"),
        ("Kalshi Yes that player", "num"),
        ("Kalshi cheaper Yes", "num"),
        ("Kalshi cheaper name", "text"),
        ("Poly vs Kalshi", "text"),
        ("Gap (Poly − Kalshi named)", "num"),
        ("Kalshi pair", "num"),
        ("Kalshi game", "text"),
        ("Order id", "text"),
    ]
    fill_rows = []
    for row in fills:
        named = row.get("k_named_px")
        k_cmp_px = named if named is not None else row.get("k_dog_px")
        gap = None
        if row.get("poly_px") is not None and k_cmp_px is not None:
            gap = row["poly_px"] - k_cmp_px
        fill_rows.append([
            esc(row.get("when") or ""),
            esc(row.get("game") or ""),
            esc(row.get("player") or ""),
            fmt_px(row.get("poly_px")),
            fmt_px(named),
            fmt_px(row.get("k_dog_px")),
            esc(row.get("k_dog") or ("—" if not row.get("k_present") else "")),
            esc(row.get("cmp") or ""),
            fmt_px(gap),
            fmt_px(row.get("k_pair")),
            esc(row.get("k_game") or ""),
            esc(row.get("order_id") or ""),
        ])
    fill_total = [
        f"E Poly fills {n_fill}",
        "",
        "",
        "",
        "",
        "",
        "",
        f"vs Kalshi N={n_fill_k}: lower {n_lower} / same {n_same} / higher {n_higher}",
        "",
        "",
        "",
        "",
    ]
    fill_table = t0.table(fill_headers, fill_rows, fill_total)

    live_pairs = payload["live_pairs"]
    pair_headers = [
        ("Date", "date"),
        ("Kalshi match", "text"),
        ("Poly match", "text"),
        ("Kalshi dog", "text"),
        ("Kalshi dog Yes ask", "num"),
        ("Poly dog", "text"),
        ("Poly dog Yes ask", "num"),
        ("Poly vs Kalshi", "text"),
        ("Gap", "num"),
        ("Kalshi fav Yes", "num"),
        ("Kalshi pair", "num"),
        ("Poly pair", "num"),
        ("Same dog name?", "text"),
    ]
    pair_rows = []
    for row in live_pairs:
        pair_rows.append([
            esc(row.get("date") or ""),
            esc(row.get("game_k") or ""),
            esc(row.get("game_p") or ""),
            esc(row.get("k_dog") or ""),
            fmt_px(row.get("k_dog_px")),
            esc(row.get("p_dog") or ""),
            fmt_px(row.get("p_dog_px")),
            esc(row.get("cmp") or ""),
            fmt_px(row.get("gap")),
            fmt_px(row.get("k_fav_px")),
            fmt_px(row.get("k_pair")),
            fmt_px(row.get("p_pair")),
            "yes" if row.get("same_dog_name") else "no",
        ])
    pair_table = t0.table(pair_headers, pair_rows)

    hist_pairs = payload["hist_pairs"]
    hist_pair_rows = []
    for row in hist_pairs:
        hist_pair_rows.append([
            esc(row.get("date") or ""),
            esc(row.get("game_k") or ""),
            esc(row.get("game_p") or ""),
            esc(row.get("k_dog") or ""),
            fmt_px(row.get("k_dog_px")),
            esc(row.get("p_dog") or ""),
            fmt_px(row.get("p_dog_px")),
            esc(row.get("cmp") or ""),
            fmt_px(row.get("gap")),
            fmt_px(row.get("k_fav_px")),
            fmt_px(row.get("k_pair")),
            fmt_px(row.get("p_pair")),
            "yes" if row.get("same_dog_name") else "no",
        ])
    hist_pair_table = t0.table(pair_headers, hist_pair_rows)

    live_meta = payload.get("live_meta") or {}
    hist_k_c = payload.get("hist_k_counts") or {}
    hist_p_c = payload.get("hist_p_counts") or {}
    live_match = payload.get("live_match_meta") or {}
    hist_match = payload.get("hist_match_meta") or {}

    e_line = (
        "<strong>Live E does not require dog+favorite ≤ 1.05.</strong> "
        "E sends a unique cheaper tennis Yes in (0.10, 0.50) on the cheapest of four "
        "platforms, stake $1, skip-if-B. If B already holds the match (both-Yes after-fee "
        f"≤ {esc(e_ans.get('b_c_hi'))}), E skips. If B skipped because all-in C &gt; 1.05, "
        "E may still buy the dog. Games with only the dog in 11–49¢ and the pair above 1.05 "
        "are E’s lane, not B’s."
    )
    d_line = (
        "<strong>The decile report does not know the opponent ask and does not filter "
        "dog+opp ≤ 1.05.</strong> It explodes both named Yes sides, then keeps one cheaper "
        "Yes per game-side. Tennis 10–49 is every named Yes in that band — including a 20¢ "
        "dog whose favorite was 90¢ and the pair was $1.20. The extra slice below is new "
        "and labeled; the existing sheet cells were not replaced."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{report_page_extras.CACHE_META}
<title>Tennis T0 dog Polymarket vs Kalshi 29 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.ok {{ background: #ecfdf3; border-color: #86efac; }}
.warn {{ background: #fef3c7; border-color: #f59e0b; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Tennis T0 dog — Polymarket vs Kalshi</h1>
<p class="note">Written {esc(now)}. Stamp <code>prediction_market_arb_exhaustive_20261017</code>.
Did not commit. Did not start a second Tennis crossover (B). Did not retune E 11–49 or B
after-fee ≤ 1.05. Did not DailyRun. Dashboard.html was not touched.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout ok">
<h2>Answers</h2>
<ul>
<li>{e_line}</li>
<li>{d_line}</li>
<li><strong>Dual-listed live T0 Yes asks:</strong> N={esc(live_n)}.
Kalshi typical dog {esc(fmt_px(live_st.get('k', {}).get('mean')))} mean /
{esc(fmt_px(live_st.get('k', {}).get('median')))} median;
Polymarket {esc(fmt_px(live_st.get('p', {}).get('mean')))} mean /
{esc(fmt_px(live_st.get('p', {}).get('median')))} median.
Poly cheaper (lower cent) on {esc(live_st.get('n_poly_lower'))} /
same {esc(live_st.get('n_same'))} / higher {esc(live_st.get('n_poly_higher'))}
({esc(pct_cell(live_st.get('n_poly_lower'), live_n))} cheaper).</li>
<li><strong>Live E Poly fills vs Kalshi T0:</strong> {esc(n_fill)} kitchen E fills on Polymarket;
Kalshi T0 present for {esc(n_fill_k)}.
Poly lower {esc(n_lower)} / same {esc(n_same)} / higher {esc(n_higher)}
versus Kalshi Yes on the player we bought (venue-true Poly wire vs Kalshi Yes ask).</li>
</ul>
</div>

<h2>Live E vs the $1.05 pair (read from code)</h2>
<p class="note">E: <code>tools/live_tennis_t0_dog.py</code> + <code>prediction_systems.in_dog_band</code>
= 0.10 &lt; px &lt; 0.50, cheapest of four, stake $1, skip-if-B.
B: <code>tools/live_strategy_b.py</code> both-Yes after-fee ≤ {esc(e_ans.get('b_c_hi'))}
then 50-cross + 25¢ dip. Docstring: if B skipped all-in C&gt;1.05, E may still send the dog.
<code>plan_send</code> never sums dog+favorite. Skip-if-B is “B already on match”, not “pair ≤ 1.05”.</p>
<ul>
<li>E requires pair ≤ 1.05? <strong>No.</strong></li>
<li>E skip-if-B? <strong>{"Yes" if e_ans.get("e_skip_if_b") else "No"}.</strong></li>
<li>E can still fire when both-Yes &gt; 1.05 and the dog is 11–49¢? <strong>{"Yes" if e_ans.get("e_still_sends_when_b_c_over") else "No"}.</strong></li>
</ul>

<h2>Decile report and opponent + dog</h2>
<p class="note">Generator <code>tools/_write_sport_league_t0_decile_20261027.py</code>.
Named Yes at T0, one cheaper Yes per game-side on that tape
(<code>explode_cover_yes_sides</code> then <code>pick_one_side</code>).
It does not keep a pair sum, does not read opponent ask as a gate, and does not drop
rows where dog+fav &gt; 1.05. Page:
<a href="{esc(DECILE_URL)}">sport_league_t0_decile_20261027.html</a>.
Existing 10–49 tennis cells were not rewritten. The table below is a <strong>labeled extra slice</strong>.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{slice_table}
<p class="tiny">10–49 here is sheet convention 0.10 ≤ px &lt; 0.50 (10.0¢ included). Live E skips exact 10¢.
Pair is same-venue Yes_dog + Yes_fav (raw asks). After-fee uses documented taker fees on that same venue —
B shops the cheapest legs across platforms, so this after-fee slice is not live B, only “would this
same-book pair have cleared 1.05”. Click column headers to sort.</p>

<h2>Dual-listed tennis T0 dogs — Kalshi vs Polymarket</h2>
<p class="note">Dog = cheaper named Yes under 50¢: <code>min(yes_a, yes_b)</code> if that min is &lt; 0.50.
Ties (50–50) skipped. Not “who lost.” Live book is four-platform memory Yes <em>ask</em> at trusted T0
(Kalshi/Gemini occurrence or listed :00 clock). Hist Kalshi is 1-minute <code>yes_ask</code> candle close
at occurrence / expected expiration — candles already at 0 or 1 are dropped (match already done).
<strong>Hist Polymarket is CLOB last-trade, not ask</strong>, global book, not Polymarket US kitchen.
Same = rounded to the same cent. Gap = Poly dog − Kalshi dog (negative means Poly cheaper).
Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{dual_table}
<p class="tiny">Live match: {esc(live_match.get('n_matched'))} dual-listed of
{esc(live_match.get('n_poly'))} Poly dogs / {esc(live_match.get('n_kalshi'))} Kalshi dogs
(unmatched Poly {esc(live_match.get('n_unmatched_poly'))}).
Hist match: {esc(hist_match.get('n_matched'))} of
{esc(hist_match.get('n_poly'))} Poly / {esc(hist_match.get('n_kalshi'))} Kalshi
(unmatched Poly {esc(hist_match.get('n_unmatched_poly'))}).
Hist Kalshi tennis ML sides {esc(hist_k_c.get('n_sides'))}, events {esc(hist_k_c.get('n_events'))},
usable two-sided dogs {esc(hist_k_c.get('n_ok'))}, dropped bad 0/1 candles {esc(hist_k_c.get('n_bad_px'))}.
Hist Poly tennis ML sides {esc(hist_p_c.get('n_sides'))}, usable dogs {esc(hist_p_c.get('n_ok'))}.
Poly hist span is shorter than Kalshi hist (Poly last-trade book ends earlier on disk).</p>

<h3>Live tape — each dual-listed match</h3>
{report_page_extras.SWIPE_NOTE_HTML}
{pair_table}

<h3>Hist — each dual-listed match (Poly last-trade vs Kalshi yes_ask)</h3>
{report_page_extras.SWIPE_NOTE_HTML}
{hist_pair_table}

<h2>Live E fills on Polymarket vs Kalshi T0</h2>
<p class="note">Kitchen E rows (dashboard <code>all_rows</code>, system E, venue Polymarket, filled yes).
Poly price is venue-true send wire (Yes on the underdog; Polymarket BUY_SHORT that pays if that
player wins is Yes that player). Kalshi column is that same player’s Yes ask at trusted T0 on the
live tape when we have both books. If Kalshi’s cheaper name differs, both are shown. Same / lower /
higher vs Kalshi named Yes, else vs Kalshi cheaper Yes if the name did not match.
Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{fill_table}

<p class="tiny">Live tennis stream: lines={esc(live_meta.get('n_lines'))} yes ticks={esc(live_meta.get('n_yes'))}
sides={esc(live_meta.get('n_sides'))} books={esc(live_meta.get('n_books'))}
two-sided T0={esc(live_meta.get('n_two_sided_t0'))}
seen {esc(live_meta.get('seen_min'))} .. {esc(live_meta.get('seen_max'))}.
Generator <code>tools/_write_tennis_t0_dog_poly_vs_kalshi_20261029.py</code>.
E code <code>tools/live_tennis_t0_dog.py</code>. B code <code>tools/live_strategy_b.py</code>.
Decile <code>tools/_write_sport_league_t0_decile_20261027.py</code>.
File URL {esc(FILE_URL)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return str(PAGE)


def main() -> int:
    print("reading live E / B / decile generators", flush=True)
    e_ans = e_code_answers()
    d_ans = decile_answers()
    print(
        f"E pair<=1.05 required={e_ans['e_requires_pair_105']} "
        f"skip_if_b={e_ans['e_skip_if_b']} still_sends_if_B_C_over={e_ans['e_still_sends_when_b_c_over']}",
        flush=True,
    )
    print(f"decile knows opponent={d_ans['knows_opponent_ask']} filters_1.05={d_ans['filters_pair_105']}", flush=True)

    print("loading hist books", flush=True)
    k_raw = load_json(HIST_DIR / "books_kalshi.json")
    k_sides = k_raw if isinstance(k_raw, list) else []
    p_raw = load_json(HIST_DIR / "books_poly.json")
    p_sides = p_raw if isinstance(p_raw, list) else []
    hist_k, hist_k_c = pair_hist_sides(k_sides, venue="kalshi")
    hist_p, hist_p_c = pair_hist_sides(p_sides, venue="polymarket")
    hist_pairs, hist_match = match_dual(hist_k, hist_p)
    hist_stats = dual_stats(hist_pairs)
    print(f"hist dual N={hist_stats['n']} poly_lower={hist_stats['n_poly_lower']}", flush=True)

    books, live_meta = load_live_tennis_books()
    live_k = [r for r in (live_dog_row(b) for b in books) if r and r.get("venue") == "kalshi"]
    live_p = [r for r in (live_dog_row(b) for b in books) if r and r.get("venue") == "polymarket"]
    live_k_all = [
        r for r in (live_two_sided_row(b) for b in books)
        if r and r.get("venue") == "kalshi"
    ]
    live_pairs, live_match = match_dual(live_k, live_p)
    live_stats = dual_stats(live_pairs)
    print(f"live dual N={live_stats['n']} poly_lower={live_stats['n_poly_lower']}", flush=True)

    fills = attach_kalshi_to_fills(load_e_poly_fills(), live_k_all)
    print(f"E poly fills {len(fills)} with Kalshi T0 {sum(1 for r in fills if r.get('k_present'))}", flush=True)

    payload = {
        "e": e_ans,
        "decile": d_ans,
        "live_stats": live_stats,
        "hist_stats": hist_stats,
        "live_pairs": live_pairs,
        "hist_pairs": hist_pairs,
        "live_meta": live_meta,
        "live_match_meta": live_match,
        "hist_match_meta": hist_match,
        "hist_k_counts": hist_k_c,
        "hist_p_counts": hist_p_c,
        "slice_live_k": slice_1049(live_k),
        "slice_live_p": slice_1049(live_p),
        "slice_hist_k": slice_1049(hist_k),
        "slice_hist_p": slice_1049(hist_p),
        "fills": fills,
    }
    path = write_html(payload)
    print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
