"""Tennis moneyline win rate by implied-odds decade at match start, T-24h, T-2h.

Research only. Reads the price_memory tape and official settlements.
Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Does not restart jobs.
Does not take price_memory.lock (read-only scan of the jsonl).

Do NOT use first-ever print for these tables. First print is a feed artifact.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from odds_cross_no_roi_60_70_20261020 import copy_g
from odds_cross_winrate_20261020 import (
    DECADE_LABELS,
    SETTLE_CACHE,
    STAMP,
    as_float,
    attach_results,
    build_index,
    bucket_rows,
    decade_label,
    fill_decade_rows,
    fmt_px,
    game_norm,
    iso,
    parse_dt,
    pct,
    table,
    tiny_note,
    with_pending_from,
)
from polymarket_tennis_no_90plus_20261020 import (
    instrument_for,
    load_catalog,
    load_settlements,
    start_status,
    settle_bucket,
)
from prediction_paths import RAW_DIR as RAW
from price_memory import HISTORY, iter_tick_lines, load_last, to_et
PAGE = STAMP / "tennis_decade_at_start_20261020.html"
LIVE_PAGE = STAMP / "tennis_decade_at_start_live.html"
JSON_OUT = RAW / "tennis_decade_at_start_20261020.json"
CSV_OUT = RAW / "tennis_decade_at_start_20261020.csv"
UPCOMING_CSV = RAW / "tennis_decade_at_start_upcoming_20261020.csv"
SNAPSHOTS = RAW / "odds_snapshots.jsonl"
ET = ZoneInfo("America/New_York")
VENUES = ("Polymarket", "Kalshi", "Gemini")
SUM_LIMIT = 1.15
GRACE_MIN = 30
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ASKED = (
    "thanks. i think we need to collect more data due to tiny/small sampole size. it currently looks "
    "like any tennis matches on polymarket that are 40-49 at T-2h are a good investment as 65% win. "
    "conversely a match that is 60-69 at T-2h would be a good No to buy."
)
ASKED_PRIOR = (
    "Prior ask (still the decade-at-start study): what might be more worthwhile than first print. "
    "How about win rate for each decade at game start time? 24 hours before?"
)
ASKED_TRACK = (
    "Track going forward, research only, not gold, not DailyRun, do not wire lock sends. "
    "(1) One-leg leftover: after we own Yes or No, does the other ask come down through $0.95 "
    "in the next hour? Add counts: how often it becomes buyable (ask ≤ max cap), how often that "
    "IOC fills, how often the game ends/resolves first, how often still watching at 60 minutes. "
    "(2) In-game jump then fade: side under 60 then first print over 70, 15–60 min after start. "
    "Outcome favorite KEPT vs GAVE BACK. Official settlements. Not a No-buy factory. "
    "(3) Ask gone 1–2s: on every order send, log quote age, book size at that price, venue, fill qty. "
    "Summarize fill-0 rate by venue and by age bucket (<0.5s, 0.5–2s, >2s). Nagal was 1.3s / size 2 / fill 0. "
    "(4) Named hypotheses on the T−2h/T0 page: (A) favorite ≥90 at T0; (B) underdog 40–49 at T−2h. "
    "Raw decades stay. HOLD until N is large. New: T−2h = two hours before scheduled match start. "
    "Underdog 40–49 at T−2h: what is that SAME player’s Yes at T0? Transition table from 40–49 at "
    "T−2h → T0 decade, N, and later win% by destination band. Did late money lift them, fade them, "
    "or leave them? Require known start and a T0 print. If opponent also has T−2h, note pair sum. "
    "Tennis Polymarket primary."
)
PLAIN = (
    "A Yes price is a dollar from 0 to 1, also an implied chance: 0.45 means that named tennis player "
    "is listed at 45 percent to win the match (moneyline: who wins). T−2h is the last Yes print two "
    "hours before listed start. Decade 40–49 means that snapshot sat between 40 and 49 cents. Win % "
    "is how often that named player actually won. The 65% figure on this page is real for Polymarket "
    "tennis at T−2h in 40–49, but the settled sample is small — it is not KEEP, not gold, and not a "
    "trading rule. We are now writing one snapshot per player at T−2h and one at match start (T0) as "
    "start times approach, even while new lock orders stay however they already were. T−2h is two "
    "hours before scheduled match start. Named hypotheses (A) favorite ≥90 at T0 and (B) underdog "
    "40–49 at T−2h stay HOLD until N is large. The transition table follows the same 40–49 player "
    "to their T0 decade to see whether late money lifted them, faded them, or left them. Research only. "
    "Not DailyRun."
)
MEANINGFUL = (
    "Start-time odds are the actual listed favorite — the last Yes print when first ball is about to "
    "be struck, not the first tick the feed ever saw. Twenty-four hours before is the consensus before "
    "late money moves the line. A real two-player book has the two Yes prices summing near 1 (we drop "
    "the match when they sum over 1.15). First print is a feed artifact: an empty or one-sided first "
    "websocket tick can print both names at 90%+."
)


def esc(value) -> str:
    import html as html_mod
    return html_mod.escape("" if value is None else str(value))


def is_clocked_start(text) -> bool:
    raw = str(text or "").strip()
    if not raw or DATE_ONLY.fullmatch(raw):
        return False
    return parse_dt(raw) is not None


def prefer_start(*candidates: str) -> tuple[str, str]:
    """Return (iso-or-raw, source) preferring a clocked datetime."""
    clocked = []
    dated = []
    for i, raw in enumerate(candidates):
        text = str(raw or "").strip()
        if not text:
            continue
        source = ("feed", "occurrence", "catalog", "other")[min(i, 3)]
        if is_clocked_start(text):
            dt = parse_dt(text)
            clocked.append((iso(dt) if dt else text, source))
        elif DATE_ONLY.fullmatch(text) or parse_dt(text) is not None:
            dated.append((text, source))
    if clocked:
        return clocked[0][0], clocked[0][1]
    if dated:
        return dated[0][0], dated[0][1] + "_date_only"
    return "", ""


def start_lookup_from(settlements: list[dict], catalog: list[dict]) -> dict[str, tuple[str, str]]:
    occ: dict[str, str] = {}
    for row in settlements:
        game = row.get("game_n") or game_norm(row.get("game") or "")
        raw = row.get("occurrence") or ""
        if game and raw and is_clocked_start(raw):
            occ.setdefault(game, raw)
    cat: dict[str, str] = {}
    for row in catalog:
        raw = row.get("start") or row.get("date") or ""
        for title in (row.get("game") or "", row.get("event_title") or ""):
            g = game_norm(title)
            if g and raw:
                cat.setdefault(g, raw)
    keys = set(occ) | set(cat)
    out = {}
    for game in keys:
        text, source = prefer_start("", occ.get(game, ""), cat.get(game, ""))
        if text:
            out[game] = (text, source)
    return out


def stream_tennis_ticks() -> dict:
    print("streaming tennis moneyline Yes ticks (archive + shards)", flush=True)
    states: dict[str, dict] = {}
    n_lines = 0
    n_hits = 0
    n_skip_01 = 0
    seen_min = None
    seen_max = None
    venues: dict[str, int] = defaultdict(int)
    for line in iter_tick_lines(sport="tennis"):
            n_lines += 1
            if n_lines % 400000 == 0:
                print(f"  {n_lines} lines, tennis keys {len(states)} ticks {n_hits}", flush=True)
            if "tennis" not in line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if str(rec.get("sport") or "").lower() != "tennis":
                continue
            if str(rec.get("market_type") or "") != "moneyline":
                continue
            if str(rec.get("pay") or "yes").lower() != "yes":
                continue
            venue = str(rec.get("venue") or "")
            if venue not in VENUES:
                continue
            price = as_float(rec.get("price"))
            if price is None:
                continue
            key = rec.get("key") or ""
            if not key:
                continue
            seen = rec.get("seen_at") or ""
            if seen:
                if seen_min is None or seen < seen_min:
                    seen_min = seen
                if seen_max is None or seen > seen_max:
                    seen_max = seen
            st = states.get(key)
            if st is None:
                st = {
                    "key": key,
                    "sport": "tennis",
                    "game": rec.get("game") or "",
                    "market_type": "moneyline",
                    "side": rec.get("side") or rec.get("side_label") or "",
                    "side_key": rec.get("side_key") or "",
                    "number": "",
                    "venue": venue,
                    "game_start": rec.get("game_start") or "",
                    "ticks": [],
                    "first_px": None,
                    "first_time": "",
                }
                states[key] = st
                venues[venue] += 1
            else:
                if rec.get("game_start") and not st.get("game_start"):
                    st["game_start"] = rec.get("game_start") or ""
                if rec.get("game") and not st.get("game"):
                    st["game"] = rec.get("game") or ""
                if rec.get("side") and not st.get("side"):
                    st["side"] = rec.get("side") or rec.get("side_label") or ""
            if price <= 0.0 or price >= 1.0:
                n_skip_01 += 1
                continue
            n_hits += 1
            st["ticks"].append((seen, price))
            if st["first_px"] is None:
                st["first_px"] = price
                st["first_time"] = seen
    print(
        f"stream done lines={n_lines} tennis_yes={n_hits} keys={len(states)} "
        f"skip_0_or_1={n_skip_01} seen {seen_min} .. {seen_max}",
        flush=True,
    )
    return {
        "n_lines": n_lines,
        "n_hits": n_hits,
        "n_keys": len(states),
        "n_skip_01": n_skip_01,
        "seen_min": seen_min or "",
        "seen_max": seen_max or "",
        "venues": dict(venues),
        "states": states,
    }


def overlay_last(states: dict[str, dict]) -> None:
    try:
        stored = load_last()
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        return
    n_add = 0
    for key, row in stored.items():
        if not isinstance(row, dict):
            continue
        if str(row.get("sport") or "").lower() != "tennis":
            continue
        if str(row.get("pay") or "yes").lower() != "yes":
            continue
        kind = str(row.get("market_type") or "moneyline")
        if kind not in ("moneyline", ""):
            continue
        venue = str(row.get("venue") or "")
        if venue not in VENUES:
            continue
        price = as_float(row.get("price"))
        if price is None or price <= 0.0 or price >= 1.0:
            continue
        seen = row.get("seen_at") or ""
        st = states.get(key)
        if st is None:
            st = {
                "key": key,
                "sport": "tennis",
                "game": row.get("game") or "",
                "market_type": "moneyline",
                "side": row.get("side") or row.get("side_label") or "",
                "side_key": row.get("side_key") or "",
                "number": "",
                "venue": venue,
                "game_start": row.get("game_start") or "",
                "ticks": [],
                "first_px": price,
                "first_time": seen,
            }
            states[key] = st
        if row.get("game_start") and not st.get("game_start"):
            st["game_start"] = row.get("game_start") or ""
        last_seen = st["ticks"][-1][0] if st["ticks"] else ""
        if seen and seen != last_seen:
            st["ticks"].append((seen, price))
            n_add += 1
        if st["first_px"] is None:
            st["first_px"] = price
            st["first_time"] = seen
    print(f"overlaid price_last extra ticks {n_add}; keys {len(states)}", flush=True)


def last_at_or_before(ticks: list[tuple[str, float]], cutoff: datetime) -> tuple[str, float] | None:
    last = None
    cutoff = to_et(cutoff)
    for seen, price in ticks:
        dt = parse_dt(seen)
        if dt is None:
            continue
        if to_et(dt) <= cutoff:
            last = (seen, price)
    return last


def last_in_window(
    ticks: list[tuple[str, float]], lo: datetime, hi: datetime,
) -> tuple[str, float] | None:
    last = None
    lo = to_et(lo)
    hi = to_et(hi)
    for seen, price in ticks:
        dt = parse_dt(seen)
        if dt is None:
            continue
        dt = to_et(dt)
        if lo < dt <= hi:
            last = (seen, price)
    return last


def snapshot_for(st: dict, start_dt: datetime, hours_before: float | None) -> dict | None:
    """hours_before None means T0 (with +30m grace). Else last print at start − hours."""
    ticks = st.get("ticks") or []
    if hours_before is None:
        hit = last_at_or_before(ticks, start_dt)
        source = "pre-start"
        if hit is None:
            hit = last_in_window(ticks, start_dt, start_dt + timedelta(minutes=GRACE_MIN))
            source = f"grace+{GRACE_MIN}m"
        if hit is None:
            return None
        seen, price = hit
        return {"price": price, "seen_at": seen, "source": source}
    cutoff = start_dt - timedelta(hours=hours_before)
    hit = last_at_or_before(ticks, cutoff)
    if hit is None:
        return None
    seen, price = hit
    return {"price": price, "seen_at": seen, "source": f"T-{hours_before:g}h"}


def annotate_pair_sums(rows: list[dict], px_key: str) -> dict:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row.get("venue") or "", row.get("game") or "")].append(row)
    n_dropped_matches = 0
    n_dropped_rows = 0
    n_both90_matches = 0
    both90_names = []
    dropped_names = []
    for (venue, game), members in groups.items():
        prices = [as_float(m.get(px_key)) for m in members]
        prices = [p for p in prices if p is not None]
        pair_sum = sum(prices) if len(prices) >= 2 else None
        n90 = sum(1 for p in prices if 0.90 <= p < 1.0)
        both90 = n90 >= 2
        bad = pair_sum is not None and pair_sum > SUM_LIMIT
        for m in members:
            m["pair_sum"] = pair_sum
            m["bad_book"] = bad
            m["both90"] = both90
        if both90:
            n_both90_matches += 1
            both90_names.append(f"{game} ({venue})")
        if bad:
            n_dropped_matches += 1
            n_dropped_rows += len(members)
            dropped_names.append(f"{game} ({venue})")
    return {
        "n_dropped_matches": n_dropped_matches,
        "n_dropped_rows": n_dropped_rows,
        "n_both90_matches": n_both90_matches,
        "both90_names": both90_names,
        "dropped_names": dropped_names,
    }


def decade_table(rows: list[dict]) -> list[dict]:
    kept = [r for r in rows if not r.get("bad_book")]
    filled = fill_decade_rows(
        with_pending_from(kept, bucket_rows(kept, "official", ("band",), True), ("band",)),
        include_leftover=False,
    )
    return filled


def band_stats(table_rows: list[dict], band: str) -> dict:
    for row in table_rows:
        if row.get("band") == band:
            return row
    return {
        "band": band,
        "settled": 0,
        "wins": 0,
        "losses": 0,
        "win_pct": "",
        "pending": 0,
        "n": 0,
        "note": "no settled rows",
    }


def _player_id(row: dict) -> tuple[str, str]:
    return (game_norm(row.get("game") or ""), game_norm(row.get("side") or ""))


def late_money_label(src_band: str, dest_band: str) -> str:
    try:
        a = DECADE_LABELS.index(src_band)
        b = DECADE_LABELS.index(dest_band)
    except ValueError:
        return ""
    if b > a:
        return "lifted"
    if b < a:
        return "faded"
    return "left them"


def transition_4049(t2_rows: list[dict], t0_rows: list[dict], venue: str = "Polymarket") -> dict:
    """Same player, 40–49 at T−2h → T0 decade. Requires known start (already on these rows) and a T0 print."""
    t0_map: dict[tuple[str, str], dict] = {}
    for row in t0_rows:
        if row.get("venue") != venue or row.get("bad_book"):
            continue
        t0_map[_player_id(row)] = row
    details = []
    buckets: dict[str, dict] = {
        label: {"band": label, "n": 0, "settled": 0, "wins": 0, "losses": 0, "pending": 0, "win_pct": "", "note": ""}
        for label in DECADE_LABELS
    }
    dirs = {"lifted": 0, "faded": 0, "left them": 0}
    missing_t0 = 0
    n_src = 0
    for row in t2_rows:
        if row.get("venue") != venue or row.get("bad_book"):
            continue
        px = as_float(row.get("price"))
        if px is None or px < 0.40 or px >= 0.50:
            continue
        n_src += 1
        t0 = t0_map.get(_player_id(row))
        if t0 is None:
            missing_t0 += 1
            continue
        t0_px = as_float(t0.get("price"))
        dest = t0.get("band") or (decade_label(t0_px) if t0_px is not None else "")
        direction = late_money_label("40–49", dest) if dest else ""
        official = t0.get("official") or row.get("official") or ""
        if direction:
            dirs[direction] = dirs.get(direction, 0) + 1
        bucket = buckets.get(dest)
        if bucket is not None:
            bucket["n"] += 1
            if official == "win":
                bucket["settled"] += 1
                bucket["wins"] += 1
            elif official == "loss":
                bucket["settled"] += 1
                bucket["losses"] += 1
            elif official == "pending":
                bucket["pending"] += 1
        pair_sum = row.get("pair_sum")
        if pair_sum is None:
            pair_sum = t0.get("pair_sum")
        details.append({
            "game": row.get("game") or "",
            "side": row.get("side") or "",
            "venue": venue,
            "t2_px": fmt_px(px),
            "t2_time": row.get("cross_time") or "",
            "t0_px": fmt_px(t0_px),
            "t0_band": dest,
            "t0_time": t0.get("cross_time") or "",
            "late_money": direction,
            "pair_sum": f"{pair_sum:.3f}" if isinstance(pair_sum, (int, float)) else (str(pair_sum) if pair_sum not in (None, "") else ""),
            "start": row.get("game_start") or t0.get("game_start") or "",
            "official": official,
            "source": t0.get("official_source") or row.get("official_source") or "",
        })
    table_rows = []
    for label in DECADE_LABELS:
        bucket = buckets[label]
        n = int(bucket["settled"])
        bucket["win_pct"] = pct(int(bucket["wins"]), n)
        bucket["note"] = tiny_note(n)
        table_rows.append(bucket)
    total_settled = sum(int(b["settled"]) for b in table_rows)
    total_wins = sum(int(b["wins"]) for b in table_rows)
    return {
        "venue": venue,
        "n_t2_4049": n_src,
        "n_with_t0": len(details),
        "n_missing_t0": missing_t0,
        "dirs": dirs,
        "table": table_rows,
        "details": details,
        "total_settled": total_settled,
        "total_wins": total_wins,
        "total_win_pct": pct(total_wins, total_settled),
        "note": tiny_note(total_settled),
    }


def named_hypotheses(headline: dict, tables: dict) -> list[dict]:
    a = headline.get("polymarket_t0_90") or {}
    b = band_stats((tables.get("Polymarket") or {}).get("t2") or [], "40–49")
    return [
        {
            "id": "A",
            "name": "Favorite ≥90 at T0",
            "definition": "Polymarket tennis moneyline Yes in decade 90–99 at match start.",
            "settled": a.get("n") or 0,
            "wins": a.get("wins") or 0,
            "win_pct": a.get("win_pct") or "",
            "note": a.get("note") or tiny_note(int(a.get("n") or 0)),
            "verdict": "HOLD",
        },
        {
            "id": "B",
            "name": "Underdog 40–49 at T−2h",
            "definition": "Polymarket tennis moneyline Yes in decade 40–49 two hours before scheduled start.",
            "settled": b.get("settled") or b.get("n") or 0,
            "wins": b.get("wins") or 0,
            "win_pct": b.get("win_pct") or "",
            "note": b.get("note") or tiny_note(int(b.get("settled") or b.get("n") or 0)),
            "verdict": "HOLD",
        },
    ]


def band90(rows: list[dict]) -> dict:
    kept = [r for r in rows if not r.get("bad_book") and r.get("band") == "90–99"]
    settled = [r for r in kept if r.get("official") in ("win", "loss")]
    wins = sum(1 for r in settled if r.get("official") == "win")
    n = len(settled)
    return {
        "n": n,
        "wins": wins,
        "win_pct": pct(wins, n),
        "pending": sum(1 for r in kept if r.get("official") == "pending"),
        "note": tiny_note(n),
        "unique_games": len({r.get("game") for r in settled}),
    }


def row_from_state(st: dict, snap: dict, start_text: str, start_source: str) -> dict:
    price = snap["price"]
    band = decade_label(price)
    return {
        "key": st["key"],
        "sport": "tennis",
        "game": st.get("game") or "",
        "market_type": "moneyline",
        "side": st.get("side") or "",
        "side_key": st.get("side_key") or "",
        "number": "",
        "venue": st.get("venue") or "",
        "game_start": start_text,
        "start_source": start_source,
        "cross_time": snap["seen_at"],
        "first_above": price,
        "price": price,
        "price_src": snap["source"],
        "band": band or "",
        "first_px": st.get("first_px"),
        "first_time": st.get("first_time") or "",
    }


def last_map_of(states: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for key, st in states.items():
        ticks = st.get("ticks") or []
        if not ticks:
            continue
        seen, price = ticks[-1]
        out[key] = {
            "price": price,
            "seen_at": seen,
            "game_start": st.get("game_start") or "",
            "sport": "tennis",
        }
    return out


def upcoming_start_ok(start_text: str, now: datetime) -> tuple[bool, str]:
    status = start_status(start_text, now)
    if status == "listed start not yet":
        return True, status
    return False, status


def write_html(payload: dict) -> None:
    now = payload["written_at"]
    meta = payload["meta"]
    poly_t0 = payload["tables"]["Polymarket"]["t0"]
    poly_t24 = payload["tables"]["Polymarket"]["t24"]
    poly_t2 = payload["tables"]["Polymarket"]["t2"]
    h90_t0 = payload["headline"]["polymarket_t0_90"]
    h90_t24 = payload["headline"]["polymarket_t24_90"]
    h90_t2 = payload["headline"]["polymarket_t2_90"]
    filters = payload["filters"]
    upcoming = payload["upcoming_90_start"]
    dropped = payload["dropped_t0"]
    metric_headers = [
        ("Band", "text"), ("Settled N", "num"), ("Wins", "num"), ("Losses", "num"),
        ("Win %", "num"), ("Pending (excluded)", "num"), ("Note", "text"),
    ]
    fields = ["band", "settled", "wins", "losses", "win_pct", "pending", "note"]
    upcoming_headers = [
        ("Match", "text"), ("Player", "text"), ("Venue", "text"),
        ("T0 Yes", "num"), ("T0 time", "date"), ("T0 source", "text"),
        ("First print Yes (not used)", "num"), ("Start", "date"), ("Status", "text"),
        ("Pair sum", "num"), ("Instrument", "text"),
    ]
    upcoming_fields = [
        "game", "side", "venue", "t0_px", "t0_time", "t0_src",
        "first_px", "start", "status", "pair_sum", "instrument",
    ]
    dropped_headers = [
        ("Match", "text"), ("Venue", "text"), ("Player A", "text"), ("Yes A", "num"),
        ("Player B", "text"), ("Yes B", "num"), ("Sum", "num"), ("Start", "date"),
    ]
    detail_headers = [
        ("Match", "text"), ("Player", "text"), ("Venue", "text"),
        ("T0 Yes", "num"), ("T0 time", "date"), ("T0 source", "text"),
        ("First print Yes (not used)", "num"), ("Start", "date"),
        ("Official", "text"), ("Source", "text"), ("Settlement", "text"),
        ("Pair sum", "num"),
    ]
    extra_blocks = []
    for venue in ("Kalshi", "Gemini"):
        t0 = payload["tables"][venue]["t0"]
        t24 = payload["tables"][venue]["t24"]
        t2 = payload["tables"][venue]["t2"]
        h0 = payload["headline"][f"{venue.lower()}_t0_90"]
        h24 = payload["headline"][f"{venue.lower()}_t24_90"]
        extra_note = ""
    if venue == "Gemini" and h0["n"] == 0 and h24["n"] == 0:
        extra_note = " No Gemini tennis moneyline Yes ticks were in this tape."
    extra_blocks.append(f"""
<h2>{esc(venue)} extra: decade at match start</h2>
<p class="note">Same tennis moneyline definition, {esc(venue)} Yes prints only. 90–99 at start: N = {h0['n']}, win % {esc(h0['win_pct'] or 'n/a')} ({h0['wins']} / {h0['n']}). {esc(h0['note'])}{esc(extra_note)}</p>
{table(metric_headers, t0, fields)}
<h3>{esc(venue)} decade at T−24h</h3>
<p class="note">90–99 at T−24h: N = {h24['n']}, win % {esc(h24['win_pct'] or 'n/a')} ({h24['wins']} / {h24['n']}). {esc(h24['note'])}</p>
{table(metric_headers, t24, fields)}
<h3>{esc(venue)} decade at T−2h</h3>
{table(metric_headers, t2, fields)}
""")
    extra_html = "".join(extra_blocks)
    both_after = filters["t0_poly"]["n_both90_after"]
    t2_4049 = band_stats(poly_t2, "40–49")
    t2_6069 = band_stats(poly_t2, "60–69")
    n4049 = int(t2_4049.get("settled") or 0)
    n6069 = int(t2_6069.get("settled") or 0)
    w4049 = int(t2_4049.get("wins") or 0)
    w6069 = int(t2_6069.get("wins") or 0)
    l6069 = int(t2_6069.get("losses") or 0)
    no6069 = pct(l6069, n6069) if n6069 else ""
    snap_n = int((payload.get("meta") or {}).get("snapshot_rows") or 0)
    snap_live = int((payload.get("meta") or {}).get("snapshot_live") or 0)
    hypos = payload.get("hypotheses") or named_hypotheses(payload.get("headline") or {}, payload.get("tables") or {})
    trans = payload.get("transition_4049") or {}
    trans_table = trans.get("table") or []
    trans_details = trans.get("details") or []
    dirs = trans.get("dirs") or {}
    hypo_headers = [
        ("Id", "text"), ("Hypothesis", "text"), ("Definition", "text"),
        ("Settled N", "num"), ("Wins", "num"), ("Win %", "num"), ("Note", "text"), ("Verdict", "text"),
    ]
    hypo_fields = ["id", "name", "definition", "settled", "wins", "win_pct", "note", "verdict"]
    trans_headers = [
        ("T0 decade", "text"), ("N (with T0 print)", "num"), ("Settled N", "num"),
        ("Wins", "num"), ("Losses", "num"), ("Win %", "num"), ("Pending", "num"), ("Note", "text"),
    ]
    trans_fields = ["band", "n", "settled", "wins", "losses", "win_pct", "pending", "note"]
    trans_detail_headers = [
        ("Match", "text"), ("Player", "text"), ("Venue", "text"),
        ("T−2h Yes", "num"), ("T0 Yes", "num"), ("T0 decade", "text"),
        ("Late money", "text"), ("Pair sum at T−2h", "num"),
        ("Start", "date"), ("Official", "text"),
    ]
    trans_detail_fields = [
        "game", "side", "venue", "t2_px", "t0_px", "t0_band",
        "late_money", "pair_sum", "start", "official",
    ]
    deadline_note = (payload.get("meta") or {}).get("deadline_note") or (
        "Supervisor deadline extended to 8:00 AM ET Thursday 2026-10-22 so T−2h and T0 snapshots "
        "keep writing overnight Wednesday. That is collection, not more lock trading. "
        "orders_stopped.json and one_leg_watch.json were left as they were."
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis odds at start: win rate by decade</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; max-width: none; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
h3 {{ font-size: 1.05rem; margin-top: 1.2rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.hl {{ background: #fef9c3; padding: 10px 12px; border: 1px solid #eab308; margin: 12px 0; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Tennis moneyline: win rate by decade at match start, not first print</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Tape is tennis moneyline Yes quotes in <code>price_memory.jsonl</code> (about 17–20 Oct 2026, plus whatever is in memory now).</p>
<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<p class="note">{esc(ASKED_PRIOR)}</p>
<p>{esc(ASKED_TRACK)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<div class="callout"><h2>What is more meaningful than first print</h2>
<p>{esc(MEANINGFUL)}</p>
<p>The first-print 90+ page is <a href="polymarket_tennis_no_90plus_20261020.html">Buying No on a Polymarket tennis player whose first print is 90+</a>. Both players can first-print at 90%+ (Herbert/Fritz, Medvedev/Shimabukuro, Moutet/Balshaw, Navone/Griekspoor, Duckworth/Darderi) because the first websocket tick is often an empty or one-sided book: the long Yes is the ask and the short Yes is one minus the bid, so a 0.02 / 0.98 book can print <em>both</em> names at 0.96. That is not two 96% favorites. Parent odds-cross page: <a href="odds_cross_winrate_20261020.html">odds cross win rates</a>.</p>
</div>

<h2>Definition</h2>
<ul>
<li><strong>Event:</strong> tennis moneyline (player wins the match). Primary tables are Polymarket US. Kalshi and Gemini sit in extra tables. One row per (match, player, venue).</li>
<li><strong>Known start:</strong> a clocked datetime (hour and minute), from the feed, else Kalshi/Gemini occurrence, else catalog. Date-only labels such as 2026-10-21 are not a start time and are excluded from historical T0 / T−24h / T−2h (counted below). Upcoming rows with a future date-only start use the latest print as a pre-match snapshot and are labeled.</li>
<li><strong>T0 (at start):</strong> last Yes print with timestamp ≤ start. If none, last Yes print in the first {GRACE_MIN} minutes after start (<code>grace+{GRACE_MIN}m</code>). Exact $0.00 and $1.00 prints are skipped (empty book). This is not first-ever print.</li>
<li><strong>T−24h:</strong> last Yes print with timestamp ≤ start − 24 hours. No grace. If the book had not printed yet, the player is excluded from that table.</li>
<li><strong>T−2h:</strong> last Yes print with timestamp ≤ start − 2 hours. No grace. Same exclusion rule.</li>
<li><strong>Decade:</strong> 00–09 is 0.00 &lt; price &lt; 0.10, …, 90–99 is 0.90 ≤ price &lt; 1.00. One disjoint bucket per snapshot.</li>
<li><strong>Bad book:</strong> when both sides have a snapshot Yes and yesA + yesB &gt; {SUM_LIMIT:.2f}, drop that match at that venue. Both-at-90+ cannot survive this filter (0.90 + 0.90 = 1.80).</li>
<li><strong>Settlements:</strong> prefer Polymarket resolved 0/1. When Polymarket has no 0/1, same-game Kalshi or Gemini is used and labeled <code>same-game</code>. Last print at 99 cents is not a win.</li>
<li><strong>Fees:</strong> not subtracted. Not a bet. Not gold.</li>
</ul>
<p class="note">Acronyms: ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. US here means Polymarket US (polymarket.us), not the international book. T0 is match start. T−24h is 24 hours before start. T−2h is 2 hours before start.</p>

<div class="hl">
<p><strong>Headline, Polymarket tennis moneyline, decade 90–99:</strong>
at start (T0) win % {esc(h90_t0['win_pct'] or 'n/a')} ({h90_t0['wins']} wins / {h90_t0['n']} settled{'' if not h90_t0['unique_games'] else f', {h90_t0["unique_games"]} matches'});
T−24h win % {esc(h90_t24['win_pct'] or 'n/a')} ({h90_t24['wins']} wins / {h90_t24['n']} settled).
T−2h 90–99 win % {esc(h90_t2['win_pct'] or 'n/a')} ({h90_t2['wins']} / {h90_t2['n']}). {esc(h90_t0['note'] or '')}</p>
<p>T−24h 90–99 is empty on this tape: the first tennis Yes quote is 18 Oct 2026 16:12 ET, so almost no match has a stored print a full day before start ({meta['n_t24_missing']} player-rows excluded). T−2h is the short-tape stand-in for “before late money.” The 00–09 band at T0 is the complement of 90–99 (dogs vs favorites) on a real two-sided book.</p>
<p>Both-sides-90+ at Polymarket T0 before the sum filter: {filters['t0_poly']['n_both90_before']} matches. After dropping yesA+yesB &gt; {SUM_LIMIT:.2f}: {both_after} (should be 0). Matches dropped as bad book at T0: {filters['t0_poly']['n_dropped_matches']} ({filters['t0_poly']['n_dropped_rows']} player-rows). Upcoming 90+ at start still listed: {len(upcoming)} player-rows (Herbert/Fritz, Moutet/Balshaw, Navone/Griekspoor, Duckworth/Darderi are gone; they were first-print artifacts). Research only. Not gold.</p>
</div>

<div class="hl">
<p><strong>HOLD / research only — Polymarket tennis T−2h 40–49 and 60–69.</strong>
This is not KEEP. This is not gold. This is not DailyRun. The lock system is not a 40–49 Yes / 60–69 No strategy.</p>
<p>Actual T−2h 40–49 (Polymarket tennis moneyline): settled N = {n4049}, win % {esc(t2_4049.get('win_pct') or 'n/a')} ({w4049} / {n4049}). Note: {esc(t2_4049.get('note') or '')}. The “65% win” read is this row. N = {n4049} is a small sample. Do not treat 65% as a law.</p>
<p>Actual T−2h 60–69 (same table): settled N = {n6069}, Yes win % {esc(t2_6069.get('win_pct') or 'n/a')} ({w6069} / {n6069}). Note: {esc(t2_6069.get('note') or '')}. Buying No on that named player would have been {esc(no6069 or 'n/a')} ({l6069} / {n6069}) on those same {n6069} rows — the complement of <em>that player’s Yes</em>, not a second independent study.</p>
<p>Inverse No on 60–69 is the same table’s complement only if both players are in the match and the two Yes prices sum near 1. Then a 60–69 Yes should have an opponent near 30–40, and No on the favorite is Yes on the dog. It is <em>not</em> the same as the 40–49 Yes table: that band has N = {n4049}, this band has N = {n6069}. Different rows. A book that does not sum near 1 is not a two-sided complement.</p>
<p>We are now snapshotting T−2h and T0 going forward into <code>raw/odds_snapshots.jsonl</code> (one row per player at each cutoff, later filled with settlement when known). Snapshot log rows: {snap_n} (live, not seed: {snap_live}). {esc(deadline_note)}</p>
<p>Pattern tracking dashboard (leftover watch counts, jump-then-fade, stale-ask fill-0, this transition): <a href="pattern_tracking_20261020.html">pattern_tracking_20261020.html</a>.</p>
</div>

<h2>Sample and honesty</h2>
<p>Short October 2026 tape: first tennis Yes quote {esc(meta.get('seen_min') or '')}, last {esc(meta.get('seen_max') or '')}. Lines scanned {meta.get('n_lines') if meta.get('n_lines') is not None else 'n/a'}. Tennis moneyline Yes ticks {meta.get('n_hits') if meta.get('n_hits') is not None else 'n/a'} across {meta.get('n_keys') if meta.get('n_keys') is not None else 'n/a'} (match, player, venue) keys. Almost every print is after 2024-01-01, so there is no in-sample / out-of-sample split to report. If N is small, do not read a decade as a trading rule. Nothing here is KEEP, gold, or DailyRun.</p>
<p>Player-rows with a clocked start: {meta['n_clocked']}. Date-only or missing start (excluded from historical tables): {meta['n_no_clock']}. T0 missing even with grace (excluded): {meta['n_t0_missing']}. T−24h no print yet (excluded): {meta['n_t24_missing']}. T−2h no print yet (excluded): {meta['n_t2_missing']}. Settlement mix on Polymarket T0 settled rows: Polymarket 0/1 {meta['n_poly_settle']}; same-game Kalshi/Gemini {meta['n_samegame_settle']}; other {meta['n_other_settle']}.</p>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>

<h2>Polymarket primary: decade at match start (T0)</h2>
<p class="note">Last Yes print at or before listed start, or in the first {GRACE_MIN} minutes after start if there was no pre-start print. Bad books (yesA+yesB &gt; {SUM_LIMIT:.2f}) dropped. Not first print.</p>
{table(metric_headers, poly_t0, fields)}

<h2>Polymarket primary: decade at T−24h</h2>
<p class="note">Last Yes print at or before start − 24 hours. Players with no print yet 24 hours before are excluded ({meta['n_t24_missing_poly']} Polymarket player-rows). That is almost the whole clocked book on this two-day tape, so 90–99 at T−24h has no settled N. Bad books at this snapshot also dropped ({filters['t24_poly']['n_dropped_matches']} matches). Do not read the leftover handful of other decades as a 24-hour law.</p>
{table(metric_headers, poly_t24, fields)}

<h2>Polymarket primary: decade at T−2h</h2>
<p class="note">Last Yes print at or before start − 2 hours. Excluded if no print yet: {meta['n_t2_missing_poly']} Polymarket player-rows. T−2h is two hours before scheduled match start.</p>
{table(metric_headers, poly_t2, fields)}

<h2>Named hypotheses — HOLD until N is large</h2>
<p class="note">Raw decade tables stay above. These two named reads are research tracking only. Verdict is HOLD on both. Do not KEEP. Do not wire lock sends. Do not gold or DailyRun.</p>
{table(hypo_headers, hypos, hypo_fields)}

<h2>Underdog 40–49 at T−2h → that same player’s Yes at T0</h2>
<p class="note">T−2h is confirmed as two hours before scheduled match start. A player in 40–49 at that snapshot is followed to their T0 decade. Requires a clocked start and a T0 print. Pair sum is the two Yes prices at T−2h when the opponent also had a T−2h print. Late money: lifted = T0 decade higher than 40–49; faded = lower; left them = still 40–49. Polymarket tennis moneyline primary. This is not a trading rule.</p>
<p class="note">T−2h 40–49 player-rows: {trans.get('n_t2_4049') or 0}. With a T0 print: {trans.get('n_with_t0') or 0}. Missing T0: {trans.get('n_missing_t0') or 0}. Late money among those with T0: lifted {dirs.get('lifted') or 0}, faded {dirs.get('faded') or 0}, left them {dirs.get('left them') or 0}. Settled N after the move: {trans.get('total_settled') or 0}, win % {esc(trans.get('total_win_pct') or 'n/a')}. {esc(trans.get('note') or '')}</p>
{table(trans_headers, trans_table, trans_fields)}
<h3>Same-player rows (40–49 at T−2h with a T0 print)</h3>
{table(trans_detail_headers, trans_details, trans_detail_fields)}

<h2>Upcoming 90+ at start (still listed)</h2>
<p class="note">Not yet settled. T0 Yes is already in 90–99 after the sum filter, and the listed start is still in the future. For a clocked future start this is the last print ≤ start (the latest print so far). For a date-only future start it is the latest print, labeled date-only. This is the list that should replace “first print 90+” for anything still on the board. Both-at-90 from an empty first tick should not appear here after the sum filter.</p>
{table(upcoming_headers, upcoming, upcoming_fields)}

<h2>Bad books dropped at Polymarket T0 (yesA + yesB &gt; {SUM_LIMIT:.2f})</h2>
<p class="note">These matches are out of the T0 decade table. After this filter, both-sides-90+ at start should be 0.</p>
{table(dropped_headers, dropped, ["game", "venue", "side_a", "px_a", "side_b", "px_b", "pair_sum", "start"])}

{extra_html}

<h2>Polymarket 90–99 at start, settled rows</h2>
<p class="note">Official win means the named player won. Source <code>same-game</code> is Kalshi or Gemini for the same match when Polymarket has no 0/1. First print is shown only so you can see it is not the T0 price.</p>
{table(detail_headers, payload["detail_poly_t0_90"], ["game", "side", "venue", "t0_px", "t0_time", "t0_src", "first_px", "start", "official", "source", "bucket", "pair_sum"])}

<p class="note">Rows saved as <code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw/tennis_decade_at_start_20261020.csv</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html_out = report_page_extras.inject_report_page_extras(page)
    PAGE.write_text(html_out, encoding="utf-8")
    LIVE_PAGE.write_text(html_out, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    print(f"wrote {LIVE_PAGE}", flush=True)


def dropped_table(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if not row.get("bad_book"):
            continue
        groups[(row.get("venue") or "", row.get("game") or "")].append(row)
    out = []
    for (venue, game), members in sorted(groups.items(), key=lambda kv: kv[0][1]):
        members = sorted(members, key=lambda r: r.get("side") or "")
        a = members[0]
        b = members[1] if len(members) > 1 else {}
        out.append({
            "game": game,
            "venue": venue,
            "side_a": a.get("side") or "",
            "px_a": fmt_px(a.get("price")),
            "side_b": b.get("side") or "",
            "px_b": fmt_px(b.get("price")) if b else "",
            "pair_sum": f"{a.get('pair_sum'):.3f}" if a.get("pair_sum") is not None else "",
            "start": a.get("game_start") or "",
        })
    return out


def patch_related_pages() -> None:
    link_90 = (
        '<p>More meaningful than first print: tennis moneyline win rate by decade at match start '
        'and 24 hours before (not first print). See '
        '<a href="tennis_decade_at_start_20261020.html">Tennis odds at start</a>.</p>'
    )
    page_90 = STAMP / "polymarket_tennis_no_90plus_20261020.html"
    if page_90.is_file():
        text = page_90.read_text(encoding="utf-8")
        if "tennis_decade_at_start_20261020.html" not in text:
            needle = '<h2>Sample and honesty</h2>'
            if needle in text:
                text = text.replace(needle, link_90 + "\n" + needle, 1)
                page_90.write_text(text, encoding="utf-8")
                print(f"patched {page_90}", flush=True)
            else:
                print("90+ page: Sample and honesty not found", flush=True)
        else:
            print("90+ page already linked", flush=True)
    src_90 = ROOT / "tools" / "polymarket_tennis_no_90plus_20261020.py"
    if src_90.is_file():
        py = src_90.read_text(encoding="utf-8")
        marker = "tennis_decade_at_start_20261020.html"
        if marker not in py:
            old = '<h2>Sample and honesty</h2>'
            new = (
                "<p>More meaningful than first print: tennis moneyline win rate by decade at "
                "match start and 24 hours before (not first print). See "
                '<a href="tennis_decade_at_start_20261020.html">Tennis odds at start</a>.</p>\n'
                "<h2>Sample and honesty</h2>"
            )
            if old in py:
                py = py.replace(old, new, 1)
                src_90.write_text(py, encoding="utf-8")
                print(f"patched {src_90}", flush=True)

    link_cross = (
        "<p>Follow-up: tennis moneyline win rate by decade at match start and 24 hours before, "
        "not first print. See "
        '<a href="tennis_decade_at_start_20261020.html">Tennis odds at start</a>.</p>'
    )
    page_cross = STAMP / "odds_cross_winrate_20261020.html"
    if page_cross.is_file():
        text = page_cross.read_text(encoding="utf-8")
        if "tennis_decade_at_start_20261020.html" not in text:
            needle = "</div>\n\n<div class=\"hl\">"
            # insert before headline after plain-english callout — use What you asked close
            asked_end = "that there is actually a 70% chance they win, etc.</p>"
            if "Tennis odds at start" not in text:
                if asked_end in text:
                    text = text.replace(asked_end, asked_end + "\n" + link_cross, 1)
                    page_cross.write_text(text, encoding="utf-8")
                    print(f"patched {page_cross}", flush=True)
                else:
                    alt = '<h2>Sample and honesty</h2>'
                    if alt in text:
                        text = text.replace(alt, link_cross + "\n" + alt, 1)
                        page_cross.write_text(text, encoding="utf-8")
                        print(f"patched {page_cross} (honesty)", flush=True)
                    else:
                        print("odds-cross page: insert point not found", flush=True)
        else:
            print("odds-cross page already linked", flush=True)
    src_cross = ROOT / "tools" / "odds_cross_winrate_20261020.py"
    if src_cross.is_file():
        py = src_cross.read_text(encoding="utf-8")
        if "tennis_decade_at_start_20261020.html" not in py:
            old = "<p>{esc(ASKED_DECADE)}</p>"
            new = (
                "<p>{esc(ASKED_DECADE)}</p>\n"
                "<p>Follow-up: tennis moneyline win rate by decade at match start and 24 hours "
                "before, not first print. See "
                '<a href="tennis_decade_at_start_20261020.html">Tennis odds at start</a>.</p>'
            )
            if old in py:
                py = py.replace(old, new, 1)
                src_cross.write_text(py, encoding="utf-8")
                print(f"patched {src_cross}", flush=True)


def _snap_to_row(s: dict) -> dict:
    price = as_float(s.get("yes_price"))
    official = s.get("settlement") or "pending"
    if official not in ("win", "loss", "pending"):
        official = "pending"
    pair_sum = s.get("pair_sum")
    try:
        pair_sum = float(pair_sum) if pair_sum not in (None, "") else None
    except (TypeError, ValueError):
        pair_sum = None
    return {
        "key": s.get("key") or "",
        "sport": "tennis",
        "game": s.get("game") or "",
        "market_type": "moneyline",
        "side": s.get("player") or "",
        "side_key": game_norm(s.get("player") or ""),
        "number": "",
        "venue": s.get("venue") or "",
        "game_start": s.get("start") or "",
        "start_source": s.get("start_source") or "",
        "cross_time": s.get("at") or "",
        "first_above": price,
        "price": price,
        "price_src": s.get("source") or s.get("snapshot") or "",
        "band": decade_label(price) if price is not None else "",
        "first_px": None,
        "first_time": "",
        "official": official,
        "official_source": s.get("settlement_source") or "",
        "pair_sum": pair_sum,
    }


def assemble_payload(
    t0_rows: list[dict],
    t24_rows: list[dict],
    t2_rows: list[dict],
    upcoming_candidates: list[dict],
    stream_meta: dict,
    extra_meta: dict,
    settlements: list,
    catalog: list,
    now_dt: datetime,
) -> dict:
    last_map = last_map_of({r["key"]: {
        "ticks": [(r.get("cross_time") or "", r.get("price"))] if r.get("price") is not None else [],
        "game_start": r.get("game_start") or "",
        "sport": "tennis",
    } for r in t0_rows + t24_rows + t2_rows if r.get("key")})
    try:
        stored = load_last()
        if isinstance(stored, dict):
            last_map.update(last_map_of({
                k: {
                    "ticks": [(v.get("seen_at") or "", as_float(v.get("price")))] if as_float(v.get("price")) is not None else [],
                    "game_start": v.get("game_start") or "",
                    "sport": v.get("sport") or "tennis",
                }
                for k, v in stored.items() if isinstance(v, dict)
            }))
    except Exception:
        pass
    index = build_index(settlements)
    attach_results(t0_rows, last_map, settlements, index)
    attach_results(t24_rows, last_map, settlements, index)
    attach_results(t2_rows, last_map, settlements, index)
    attach_results(upcoming_candidates, last_map, settlements, index)

    def venue_rows(rows, venue):
        return [r for r in rows if r.get("venue") == venue]

    filters = {}
    tables = {}
    headline = {}
    for venue in VENUES:
        v0 = venue_rows(t0_rows, venue)
        v24 = venue_rows(t24_rows, venue)
        v2 = venue_rows(t2_rows, venue)
        f0 = annotate_pair_sums(v0, "price")
        f24 = annotate_pair_sums(v24, "price")
        f2 = annotate_pair_sums(v2, "price")
        after0 = [r for r in v0 if not r.get("bad_book")]
        bags = defaultdict(int)
        for r in after0:
            px = as_float(r.get("price"))
            if px is not None and 0.90 <= px < 1.0:
                bags[(r.get("game"), r.get("venue"))] += 1
        n_both_after = sum(1 for n in bags.values() if n >= 2)
        f0["n_both90_before"] = f0["n_both90_matches"]
        f0["n_both90_after"] = n_both_after
        key = "t0_poly" if venue == "Polymarket" else f"t0_{venue.lower()}"
        filters[key] = f0
        filters[f"t24_{'poly' if venue == 'Polymarket' else venue.lower()}"] = f24
        filters[f"t2_{'poly' if venue == 'Polymarket' else venue.lower()}"] = f2
        tables[venue] = {
            "t0": decade_table(v0),
            "t24": decade_table(v24),
            "t2": decade_table(v2),
        }
        headline[f"{venue.lower()}_t0_90"] = band90(v0)
        headline[f"{venue.lower()}_t24_90"] = band90(v24)
        headline[f"{venue.lower()}_t2_90"] = band90(v2)

    f_up = annotate_pair_sums(upcoming_candidates, "price")
    upcoming_kept = []
    for r in upcoming_candidates:
        if r.get("bad_book"):
            continue
        if r.get("official") in ("win", "loss"):
            continue
        px = as_float(r.get("price"))
        if px is None or px < 0.90 or px >= 1.0:
            continue
        upcoming_kept.append({
            "game": r.get("game") or "",
            "side": r.get("side") or "",
            "venue": r.get("venue") or "",
            "t0_px": fmt_px(px),
            "t0_time": r.get("cross_time") or "",
            "t0_src": r.get("price_src") or "",
            "first_px": fmt_px(r.get("first_px")),
            "start": r.get("game_start") or "",
            "status": r.get("status") or "",
            "pair_sum": f"{r['pair_sum']:.3f}" if r.get("pair_sum") is not None else "",
            "instrument": instrument_for(r, catalog),
        })
    upcoming_kept.sort(key=lambda r: (
        0 if r.get("venue") == "Polymarket" else 1,
        r.get("start") or "zzz",
        r.get("game") or "",
        r.get("side") or "",
    ))

    poly_t0 = [r for r in t0_rows if r.get("venue") == "Polymarket"]
    annotate_pair_sums(poly_t0, "price")
    settled_poly = [
        r for r in poly_t0
        if not r.get("bad_book") and r.get("official") in ("win", "loss")
    ]
    n_poly_settle = sum(1 for r in settled_poly if settle_bucket(r.get("official_source") or "") == "polymarket")
    n_same = sum(1 for r in settled_poly if settle_bucket(r.get("official_source") or "") == "same-game")
    n_other = sum(1 for r in settled_poly if settle_bucket(r.get("official_source") or "") == "other")

    detail = []
    for r in sorted(
        [x for x in poly_t0 if not x.get("bad_book") and x.get("band") == "90–99" and x.get("official") in ("win", "loss")],
        key=lambda z: z.get("cross_time") or "",
        reverse=True,
    ):
        detail.append({
            "game": r.get("game") or "",
            "side": r.get("side") or "",
            "venue": r.get("venue") or "",
            "t0_px": fmt_px(r.get("price")),
            "t0_time": r.get("cross_time") or "",
            "t0_src": r.get("price_src") or "",
            "first_px": fmt_px(r.get("first_px")),
            "start": r.get("game_start") or "",
            "official": r.get("official") or "",
            "source": r.get("official_source") or "",
            "bucket": settle_bucket(r.get("official_source") or ""),
            "pair_sum": f"{r['pair_sum']:.3f}" if r.get("pair_sum") is not None else "",
        })

    dropped = dropped_table([r for r in t0_rows if r.get("venue") == "Polymarket"])
    meta = {
        "seen_min": stream_meta.get("seen_min") or "",
        "seen_max": stream_meta.get("seen_max") or "",
        "n_lines": stream_meta.get("n_lines"),
        "n_hits": stream_meta.get("n_hits"),
        "n_keys": stream_meta.get("n_keys"),
        "venues": stream_meta.get("venues") or {},
        "n_clocked": extra_meta.get("n_clocked", len(t0_rows) + extra_meta.get("n_t0_missing", 0)),
        "n_no_clock": extra_meta.get("n_no_clock", 0),
        "n_t0_missing": extra_meta.get("n_t0_missing", 0),
        "n_t24_missing": extra_meta.get("n_t24_missing", 0),
        "n_t2_missing": extra_meta.get("n_t2_missing", 0),
        "n_t24_missing_poly": extra_meta.get("n_t24_missing_poly", 0),
        "n_t2_missing_poly": extra_meta.get("n_t2_missing_poly", 0),
        "n_poly_settle": n_poly_settle,
        "n_samegame_settle": n_same,
        "n_other_settle": n_other,
        "settle_total": len(settlements),
        "grace_min": GRACE_MIN,
        "sum_limit": SUM_LIMIT,
    }
    meta.update(extra_meta)
    trans_poly = transition_4049(t2_rows, t0_rows, "Polymarket")
    trans_extra = {
        venue: transition_4049(t2_rows, t0_rows, venue)
        for venue in ("Kalshi", "Gemini")
    }
    hypos = named_hypotheses(headline, tables)
    return {
        "written_at": now_dt.isoformat(),
        "asked": ASKED,
        "plain": PLAIN,
        "meaningful": MEANINGFUL,
        "meta": meta,
        "tables": tables,
        "headline": headline,
        "filters": filters,
        "upcoming_90_start": upcoming_kept,
        "dropped_t0": dropped,
        "detail_poly_t0_90": detail,
        "transition_4049": trans_poly,
        "transition_4049_extra": trans_extra,
        "hypotheses": hypos,
        "upcoming_filter": {
            "n_both90_before": f_up["n_both90_matches"],
            "n_dropped_matches": f_up["n_dropped_matches"],
        },
    }


def rebuild_from_snapshots() -> Path:
    """Cheap regenerator: snapshots + settlement cache. No price_memory.jsonl scan."""
    from odds_snapshots import latest_by_identity, SNAP_T0, SNAP_T2, seed_from_csv

    seed_from_csv()
    latest = latest_by_identity()
    t0_rows, t24_rows, t2_rows = [], [], []
    n_live = 0
    for rec in latest.values():
        if rec.get("seed") is False:
            n_live += 1
        row = _snap_to_row(rec)
        snap = rec.get("snapshot")
        if snap == SNAP_T0:
            t0_rows.append(row)
        elif snap == SNAP_T2:
            t2_rows.append(row)
        elif snap == "tminus24h":
            t24_rows.append(row)
    settlements = load_settlements()
    catalog = load_catalog()
    now_dt = datetime.now(ET)
    upcoming_candidates = []
    try:
        stored = load_last()
    except Exception:
        stored = {}
    starts = start_lookup_from(settlements, catalog)
    if isinstance(stored, dict):
        for key, rec in stored.items():
            if not isinstance(rec, dict):
                continue
            if str(rec.get("sport") or "").lower() != "tennis":
                continue
            if str(rec.get("pay") or "yes").lower() != "yes":
                continue
            if str(rec.get("market_type") or "moneyline") not in ("moneyline", ""):
                continue
            venue = str(rec.get("venue") or "")
            if venue not in VENUES:
                continue
            price = as_float(rec.get("price"))
            if price is None:
                continue
            game = rec.get("game") or ""
            start_text, start_source = starts.get(game_norm(game), ("", ""))
            start_text = prefer_start(rec.get("game_start") or "", "", start_text)[0] or start_text
            future_ok, status = upcoming_start_ok(start_text, now_dt)
            if not future_ok:
                continue
            src = "pre-start" if is_clocked_start(start_text) else "date-only latest (listed start still future)"
            upcoming_candidates.append(row_from_state(
                {
                    "key": key,
                    "game": game,
                    "side": rec.get("side") or rec.get("side_label") or "",
                    "side_key": rec.get("side_key") or "",
                    "venue": venue,
                    "first_px": price,
                    "first_time": rec.get("seen_at") or "",
                },
                {"price": price, "seen_at": rec.get("seen_at") or "", "source": src},
                start_text,
                start_source,
            ))
            upcoming_candidates[-1]["status"] = status
    extra = {
        "n_clocked": len(t0_rows) + len(t2_rows),
        "n_no_clock": 0,
        "n_t0_missing": 0,
        "n_t24_missing": 0,
        "n_t2_missing": 0,
        "n_t24_missing_poly": 0,
        "n_t2_missing_poly": 0,
        "snapshot_rows": len(latest),
        "snapshot_live": n_live,
        "rebuild_source": "odds_snapshots.jsonl",
        "deadline_note": (
            "Supervisor deadline extended to 8:00 AM ET Thursday 2026-10-22 so T−2h and T0 "
            "snapshots keep writing overnight Wednesday. Collection only — not more lock trading. "
            "orders_stopped.json and one_leg_watch.json were left as they were."
        ),
    }
    payload = assemble_payload(
        t0_rows, t24_rows, t2_rows, upcoming_candidates,
        {
            "seen_min": extra.get("seen_min"),
            "seen_max": iso(now_dt),
            "n_lines": None,
            "n_hits": len(latest),
            "n_keys": len({r.get("key") for r in t0_rows + t2_rows}),
            "venues": {},
        },
        extra, settlements, catalog, now_dt,
    )
    JSON_OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    write_html(payload)
    copy_g(PAGE)
    copy_g(LIVE_PAGE)
    return PAGE


def main() -> None:
    now_dt = datetime.now(ET)
    now = now_dt.isoformat()
    print("loading settlements + catalog", flush=True)
    settlements = load_settlements()
    catalog = load_catalog()
    starts = start_lookup_from(settlements, catalog)
    print(f"start lookup games {len(starts)} settlements {len(settlements)} catalog {len(catalog)}", flush=True)

    stream = stream_tennis_ticks()
    states = stream["states"]
    overlay_last(states)

    t0_rows: list[dict] = []
    t24_rows: list[dict] = []
    t2_rows: list[dict] = []
    n_clocked = 0
    n_no_clock = 0
    n_t0_missing = 0
    n_t24_missing = 0
    n_t2_missing = 0
    n_t24_missing_poly = 0
    n_t2_missing_poly = 0
    upcoming_candidates: list[dict] = []

    for st in states.values():
        game = st.get("game") or ""
        feed_start = st.get("game_start") or ""
        looked_text, looked_source = starts.get(game_norm(game), ("", ""))
        if str(looked_source).startswith("occurrence"):
            start_text, start_source = prefer_start(feed_start, looked_text, "")
        else:
            start_text, start_source = prefer_start(feed_start, "", looked_text)
        st["resolved_start"] = start_text
        st["start_source"] = start_source
        clocked = is_clocked_start(start_text)
        start_dt = parse_dt(start_text) if clocked else None

        if clocked and start_dt is not None:
            n_clocked += 1
            snap0 = snapshot_for(st, start_dt, None)
            if snap0 is None:
                n_t0_missing += 1
            else:
                t0_rows.append(row_from_state(st, snap0, start_text, start_source))
            snap24 = snapshot_for(st, start_dt, 24.0)
            if snap24 is None:
                n_t24_missing += 1
                if st.get("venue") == "Polymarket":
                    n_t24_missing_poly += 1
            else:
                t24_rows.append(row_from_state(st, snap24, start_text, start_source))
            snap2 = snapshot_for(st, start_dt, 2.0)
            if snap2 is None:
                n_t2_missing += 1
                if st.get("venue") == "Polymarket":
                    n_t2_missing_poly += 1
            else:
                t2_rows.append(row_from_state(st, snap2, start_text, start_source))
        else:
            n_no_clock += 1

        future_ok, status = upcoming_start_ok(start_text, now_dt)
        ticks = st.get("ticks") or []
        if future_ok and ticks:
            seen, price = ticks[-1]
            src = "pre-start" if clocked else "date-only latest (listed start still future)"
            upcoming_candidates.append(row_from_state(
                st, {"price": price, "seen_at": seen, "source": src}, start_text, start_source,
            ))
            upcoming_candidates[-1]["status"] = status

    last_map = last_map_of(states)
    index = build_index(settlements)
    attach_results(t0_rows, last_map, settlements, index)
    attach_results(t24_rows, last_map, settlements, index)
    attach_results(t2_rows, last_map, settlements, index)
    attach_results(upcoming_candidates, last_map, settlements, index)

    def venue_rows(rows, venue):
        return [r for r in rows if r.get("venue") == venue]

    filters = {}
    tables = {}
    headline = {}
    for venue in VENUES:
        v0 = venue_rows(t0_rows, venue)
        v24 = venue_rows(t24_rows, venue)
        v2 = venue_rows(t2_rows, venue)
        f0 = annotate_pair_sums(v0, "price")
        f24 = annotate_pair_sums(v24, "price")
        f2 = annotate_pair_sums(v2, "price")
        after0 = [r for r in v0 if not r.get("bad_book")]
        bags = defaultdict(int)
        for r in after0:
            px = as_float(r.get("price"))
            if px is not None and 0.90 <= px < 1.0:
                bags[(r.get("game"), r.get("venue"))] += 1
        n_both_after = sum(1 for n in bags.values() if n >= 2)
        f0["n_both90_before"] = f0["n_both90_matches"]
        f0["n_both90_after"] = n_both_after
        key = "t0_poly" if venue == "Polymarket" else f"t0_{venue.lower()}"
        filters[key] = f0
        filters[f"t24_{'poly' if venue == 'Polymarket' else venue.lower()}"] = f24
        filters[f"t2_{'poly' if venue == 'Polymarket' else venue.lower()}"] = f2
        tables[venue] = {
            "t0": decade_table(v0),
            "t24": decade_table(v24),
            "t2": decade_table(v2),
        }
        headline[f"{venue.lower()}_t0_90"] = band90(v0)
        headline[f"{venue.lower()}_t24_90"] = band90(v24)
        headline[f"{venue.lower()}_t2_90"] = band90(v2)

    f_up = annotate_pair_sums(upcoming_candidates, "price")
    upcoming_kept = []
    for r in upcoming_candidates:
        if r.get("bad_book"):
            continue
        if r.get("official") in ("win", "loss"):
            continue
        px = as_float(r.get("price"))
        if px is None or px < 0.90 or px >= 1.0:
            continue
        upcoming_kept.append({
            "game": r.get("game") or "",
            "side": r.get("side") or "",
            "venue": r.get("venue") or "",
            "t0_px": fmt_px(px),
            "t0_time": r.get("cross_time") or "",
            "t0_src": r.get("price_src") or "",
            "first_px": fmt_px(r.get("first_px")),
            "start": r.get("game_start") or "",
            "status": r.get("status") or "",
            "pair_sum": f"{r['pair_sum']:.3f}" if r.get("pair_sum") is not None else "",
            "instrument": instrument_for(r, catalog),
        })
    upcoming_kept.sort(key=lambda r: (
        0 if r.get("venue") == "Polymarket" else 1,
        r.get("start") or "zzz",
        r.get("game") or "",
        r.get("side") or "",
    ))

    poly_t0 = [r for r in t0_rows if r.get("venue") == "Polymarket"]
    annotate_pair_sums(poly_t0, "price")  # already annotated; safe
    settled_poly = [
        r for r in poly_t0
        if not r.get("bad_book") and r.get("official") in ("win", "loss")
    ]
    n_poly_settle = sum(1 for r in settled_poly if settle_bucket(r.get("official_source") or "") == "polymarket")
    n_same = sum(1 for r in settled_poly if settle_bucket(r.get("official_source") or "") == "same-game")
    n_other = sum(1 for r in settled_poly if settle_bucket(r.get("official_source") or "") == "other")

    detail = []
    for r in sorted(
        [x for x in poly_t0 if not x.get("bad_book") and x.get("band") == "90–99" and x.get("official") in ("win", "loss")],
        key=lambda z: z.get("cross_time") or "",
        reverse=True,
    ):
        detail.append({
            "game": r.get("game") or "",
            "side": r.get("side") or "",
            "venue": r.get("venue") or "",
            "t0_px": fmt_px(r.get("price")),
            "t0_time": r.get("cross_time") or "",
            "t0_src": r.get("price_src") or "",
            "first_px": fmt_px(r.get("first_px")),
            "start": r.get("game_start") or "",
            "official": r.get("official") or "",
            "source": r.get("official_source") or "",
            "bucket": settle_bucket(r.get("official_source") or ""),
            "pair_sum": f"{r['pair_sum']:.3f}" if r.get("pair_sum") is not None else "",
        })

    dropped = dropped_table([r for r in t0_rows if r.get("venue") == "Polymarket"])

    meta = {
        "seen_min": stream.get("seen_min") or "",
        "seen_max": stream.get("seen_max") or "",
        "n_lines": stream.get("n_lines"),
        "n_hits": stream.get("n_hits"),
        "n_keys": stream.get("n_keys"),
        "venues": stream.get("venues"),
        "n_clocked": n_clocked,
        "n_no_clock": n_no_clock,
        "n_t0_missing": n_t0_missing,
        "n_t24_missing": n_t24_missing,
        "n_t2_missing": n_t2_missing,
        "n_t24_missing_poly": n_t24_missing_poly,
        "n_t2_missing_poly": n_t2_missing_poly,
        "n_poly_settle": n_poly_settle,
        "n_samegame_settle": n_same,
        "n_other_settle": n_other,
        "settle_total": len(settlements),
        "grace_min": GRACE_MIN,
        "sum_limit": SUM_LIMIT,
        "snapshot_rows": 0,
        "snapshot_live": 0,
        "deadline_note": (
            "Supervisor deadline extended to 8:00 AM ET Thursday 2026-10-22 so T−2h and T0 "
            "snapshots keep writing overnight Wednesday. Collection only — not more lock trading. "
            "orders_stopped.json and one_leg_watch.json were left as they were."
        ),
    }
    payload = {
        "written_at": now,
        "asked": ASKED,
        "plain": PLAIN,
        "meaningful": MEANINGFUL,
        "meta": meta,
        "tables": tables,
        "headline": headline,
        "filters": filters,
        "upcoming_90_start": upcoming_kept,
        "dropped_t0": dropped,
        "detail_poly_t0_90": detail,
        "upcoming_filter": {
            "n_both90_before": f_up["n_both90_matches"],
            "n_dropped_matches": f_up["n_dropped_matches"],
        },
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {JSON_OUT}", flush=True)

    csv_rows = []
    for label, rows in (("t0", t0_rows), ("t24", t24_rows), ("t2", t2_rows)):
        for r in rows:
            csv_rows.append({
                "snapshot": label,
                "venue": r.get("venue"),
                "game": r.get("game"),
                "side": r.get("side"),
                "price": r.get("price"),
                "band": r.get("band"),
                "price_src": r.get("price_src"),
                "seen_at": r.get("cross_time"),
                "game_start": r.get("game_start"),
                "start_source": r.get("start_source"),
                "first_px": r.get("first_px"),
                "official": r.get("official"),
                "official_source": r.get("official_source"),
                "bad_book": r.get("bad_book"),
                "pair_sum": r.get("pair_sum"),
            })
    if csv_rows:
        with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"wrote {CSV_OUT}", flush=True)
    if upcoming_kept:
        with UPCOMING_CSV.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(upcoming_kept[0].keys()))
            writer.writeheader()
            writer.writerows(upcoming_kept)
        print(f"wrote {UPCOMING_CSV}", flush=True)

    write_html(payload)
    patch_related_pages()
    copy_g(PAGE)
    copy_g(LIVE_PAGE)
    copy_g(STAMP / "polymarket_tennis_no_90plus_20261020.html")
    copy_g(STAMP / "odds_cross_winrate_20261020.html")

    p0 = headline["polymarket_t0_90"]
    p24 = headline["polymarket_t24_90"]
    print(
        f"POLY T0 90-99 N={p0['n']} wins={p0['wins']} wr={p0['win_pct']} "
        f"T-24h N={p24['n']} wins={p24['wins']} wr={p24['win_pct']} "
        f"both90_before={filters['t0_poly']['n_both90_before']} "
        f"both90_after={filters['t0_poly']['n_both90_after']} "
        f"dropped={filters['t0_poly']['n_dropped_matches']} "
        f"upcoming90={len(upcoming_kept)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
