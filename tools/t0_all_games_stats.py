"""All-game T0 favorite / dog / bucket stats. Research only.

Reads the in-match Yes tape (archive + dated shards) and official settlements.
Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Does not start Strategy B.
Not gold. Not DailyRun.

T0 = first trusted serve: a Kalshi/Gemini occurrence clock, else a listed/feed
clock whose seconds are 00 (same as live Strategy B). Tape-resume and
first-competitive-without-a-clock are not T0 here. Favorite = higher T0 Yes
ask on that venue book (not fill_px). Grain = one row per venue-game-market-
number as stored on the tape.
"""
from __future__ import annotations

import html as html_mod
import json
import shutil
import statistics
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from odds_cross_winrate_20261020 import (
    SETTLE_CACHE,
    as_float,
    attach_results,
    build_index,
    game_norm,
    parse_dt,
)
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from price_memory import iter_tick_lines, load_last, parse_time, to_et
from tennis_decade_at_start_20261020 import is_clocked_start

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "t0_all_games_stats.html"
REBUILD_STAMP = RAW / "t0_all_games_stats_rebuild.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/t0_all_games_stats.html"
)
G_DIR = Path(r"G:\My Drive\paul_experiments\prediction_market_arb_exhaustive_20261017")

CROSS = 0.50
ABSORB = 0.05
REBUILD_EVERY_SEC = 2 * 3600
VENUES = ("Polymarket", "Kalshi", "Gemini", "Novig")
VOID_RESULTS = {
    "void", "refund", "push", "cancelled", "canceled", "n/a", "na", "unsettled",
}
DECADE_BUCKETS = (
    (">90", 0.90, 1.01, "gt"),
    ("80-89", 0.80, 0.90, "ge_lt"),
    ("70-79", 0.70, 0.80, "ge_lt"),
    ("60-69", 0.60, 0.70, "ge_lt"),
    ("50-59", 0.50, 0.60, "ge_lt"),
)
CUMULATIVE = ((">80", 0.80), (">70", 0.70), (">60", 0.60))
C_BUCKETS = (
    ("<0.95", None, 0.95),
    ("0.95–1.00", 0.95, 1.00),
    ("1.00–1.05", 1.00, 1.05),
    ("1.05–1.20", 1.05, 1.20),
    (">1.20", 1.20, None),
)

ASKED = (
    "He wants a place to look at ongoing stats of ALL games, not just ones we bet on. "
    "Specifically: (1) What % of games have the winner at T0 remain above 50% for the "
    "entirety of the game. Of those, what % start out >80? >70? etc. (2) What % of games "
    "have the loser at T0 cross over once and remain above 50% for the rest of the game? "
    "(3) What % of T0 favorites at the outset win the game in the end, by bucket "
    "(e.g. >90, 80-89, etc.)? (4) What other statistics would be helpful? All those stats "
    "by sport, moneyline, and spread. Anything else useful. He knows we've prepared reports "
    "like this in the past. He wants to know where he can go to see them updated on a "
    "regular basis (once every 2 hours is fine)."
)
PLAIN = (
    "T0 is the first trusted price we treat as the start of the game — a real listed or "
    "venue start clock, not a random first tick on the feed. The favorite is the side the "
    "market had above 50 cents at that start (the higher Yes ask). A Yes price is a dollar "
    "from 0 to 1 and also an implied chance: 0.65 means that named side is listed at 65 "
    "percent. Stay-above-50 means the T0 favorite’s price never printed 50 cents or lower "
    "while we were watching a complete path. Winning means they actually won the market. "
    "Those are not the same number. If we missed the end of the game — last tick still "
    "80 cents, official result is a loss — we used to say they “never went below 50,” "
    "which is a hole in the tape, not a stay. This page no longer counts those as "
    "stay-above. Question 1 is the complete-watch stay. Question 2 asks how often the "
    "starting underdog (the cheaper Yes) later printed above 50 cents from below, once, "
    "and then stayed above 50 cents until the game was over. Question 3 asks how often "
    "the starting favorite actually won, grouped by how strong they were at T0. If 80–89 "
    "cent favorites win about 85 percent of the time, the market is well-calibrated. "
    "Rebuilds about every 2 hours while prediction jobs are running. Research only. Not "
    "gold. Not DailyRun. This tape is the October 2026 collection — every T0 is after "
    "2024-01-01, so there is no in-sample row."
)

_rebuild_thread: threading.Thread | None = None
_rebuild_lock = threading.Lock()


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def now_et() -> datetime:
    return datetime.now(ET)


def iso_now() -> str:
    return now_et().isoformat()


def pct(n: int, d: int) -> str:
    if d <= 0:
        return "—"
    return f"{100.0 * n / d:.1f}"


def median(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(statistics.median(xs))


def fmt_num(value, digits: int = 1) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def is_scheduled_clock(dt: datetime | None) -> bool:
    """Listed/feed stamps like 15:10:00 count. Polymarket 23:12:40Z does not."""
    if not isinstance(dt, datetime):
        return False
    return dt.second == 0 and dt.microsecond == 0


def bucket_of(px: float | None) -> str:
    if px is None:
        return "missing T0"
    if px > 0.90:
        return ">90"
    if px >= 0.80:
        return "80-89"
    if px >= 0.70:
        return "70-79"
    if px >= 0.60:
        return "60-69"
    if px > 0.50:
        return "50-59"
    if abs(px - 0.50) <= 1e-12:
        return "50-50"
    return "under-50"


def c_bucket_of(cost: float | None) -> str:
    if cost is None:
        return "missing"
    if cost < 0.95:
        return "<0.95"
    if cost < 1.00:
        return "0.95–1.00"
    if cost < 1.05:
        return "1.00–1.05"
    if cost <= 1.20:
        return "1.05–1.20"
    return ">1.20"


def last_at_or_before(ticks: list[tuple[int, float]], t: int) -> tuple[int, float] | None:
    hit = None
    for ts, px in ticks:
        if ts <= t:
            hit = (ts, px)
        else:
            break
    return hit


def first_absorbing(ticks_a: list[tuple[int, float]], ticks_b: list[tuple[int, float]]) -> int | None:
    hit = None
    for ts, px in ticks_a + ticks_b:
        if px <= ABSORB or px >= (1.0 - ABSORB):
            if hit is None or ts < hit:
                hit = ts
    return hit


def first_competitive_two_sided(
    yes_a: list[tuple[int, float]], yes_b: list[tuple[int, float]]
) -> tuple[float, float, int] | None:
    have_a = have_b = None
    merged = sorted([(t, "a", p) for t, p in yes_a] + [(t, "b", p) for t, p in yes_b])
    for t, who, p in merged:
        if who == "a":
            have_a = p
        else:
            have_b = p
        if have_a is None or have_b is None:
            continue
        if 0.10 < have_a < 0.90 and 0.10 < have_b < 0.90:
            return have_a, have_b, t
    return None


def clock_hides_match(
    yes_a: list[tuple[int, float]], yes_b: list[tuple[int, float]], start_ts: int
) -> bool:
    if not yes_b:
        for ts, px in yes_a:
            if ts >= start_ts:
                break
            if px <= ABSORB or px >= (1.0 - ABSORB):
                return True
        return False
    comp = first_competitive_two_sided(yes_a, yes_b)
    if comp is None:
        return False
    _a, _b, comp_ts = comp
    if comp_ts >= start_ts:
        return False
    after_a = [row for row in yes_a if row[0] > comp_ts]
    after_b = [row for row in yes_b if row[0] > comp_ts]
    absorb = first_absorbing(after_a, after_b)
    return absorb is not None and absorb < start_ts


def pick_trusted_clock(
    occ_dt: datetime | None,
    listed_dt: datetime | None,
    yes_a: list[tuple[int, float]],
    yes_b: list[tuple[int, float]],
) -> tuple[datetime | None, str, str]:
    """Occurrence, else scheduled listed/feed. Never tape-resume or first-competitive."""
    for dt, name in ((occ_dt, "occurrence"), (listed_dt, "listed/feed")):
        if dt is None:
            continue
        if name == "listed/feed" and not is_scheduled_clock(dt):
            continue
        start_ts = int(to_et(dt).timestamp())
        if clock_hides_match(yes_a, yes_b, start_ts):
            return None, "", "clock_hides_match"
        return dt, name, ""
    return None, "", "no_trusted_clock"


def assign_t0_prices(
    yes_a: list[tuple[int, float]],
    yes_b: list[tuple[int, float]],
    clock_ts: int,
) -> tuple[float | None, float | None, int | None, str]:
    """Last two-sided Yes at or before the trusted clock, else mixed first both-quoted."""
    pre_a = last_at_or_before(yes_a, clock_ts)
    pre_b = last_at_or_before(yes_b, clock_ts)
    if pre_a and pre_b:
        return pre_a[1], pre_b[1], max(pre_a[0], pre_b[0]), "last two-sided Yes <= clock"
    have_a = pre_a[1] if pre_a else None
    have_b = pre_b[1] if pre_b else None
    merged = sorted(
        [(t, "a", p) for t, p in yes_a if t >= clock_ts]
        + [(t, "b", p) for t, p in yes_b if t >= clock_ts]
    )
    for t, who, p in merged:
        if who == "a":
            have_a = p
        else:
            have_b = p
        if have_a is not None and have_b is not None:
            return have_a, have_b, t, "mixed pre-start + first in-game"
    return have_a, have_b, None, "incomplete T0 quotes"


def minutes_at_or_below(
    t0_ts: int,
    t0_px: float,
    ticks: list[tuple[int, float]],
    end_ts: int | None,
    threshold: float = CROSS,
) -> float:
    points = [(t0_ts, t0_px)] + list(ticks)
    total = 0.0
    for i in range(len(points) - 1):
        ts, px = points[i]
        nxt = points[i + 1][0]
        if px <= threshold + 1e-12:
            total += max(0, nxt - ts)
    last_ts, last_px = points[-1]
    stop = end_ts if end_ts is not None else last_ts
    if last_px <= threshold + 1e-12 and stop > last_ts:
        total += stop - last_ts
    return total / 60.0


def classify_stay_above(
    ticks: list[tuple[int, float]],
    t0_ts: int | None,
    *,
    fav_won: bool | None = None,
    ticks_are_post: bool = False,
) -> dict:
    """Stay-above-50 is a complete-watch path metric, not a win rate.

    Stay-above = we saw post-T0 ticks, the favorite never printed ≤50¢, and
    we did not lose while the last tick was still >50¢ (missing crash). An
    empty tape after T0 is no_post_t0_path, not stay-above. A last print at
    80¢ plus a loss is path_incomplete, not stay-above.

    On a complete path that includes settlement, stay-above-and-then-lose
    cannot happen: a losing Yes must go to $0, so it must print ≤50¢ unless
    ticks stop before the market reprices.
    """
    out = {
        "stay_above": False,
        "dipped": False,
        "raw_never_le50": False,
        "path_status": "no_post_t0_path",
        "missing_crash": False,
        "stay_above_but_lost": False,
        "n_post": 0,
        "last_px": None,
        "terminal": False,
    }
    if t0_ts is None:
        return out
    post: list[tuple[int, float]] = []
    for ts, px in ticks or []:
        if ticks_are_post or int(ts) > int(t0_ts):
            post.append((int(ts), float(px)))
    out["n_post"] = len(post)
    if not post:
        return out
    last_px = post[-1][1]
    out["last_px"] = last_px
    dipped = any(px <= CROSS + 1e-12 for _ts, px in post)
    out["dipped"] = dipped
    out["raw_never_le50"] = not dipped
    terminal = last_px <= ABSORB + 1e-12 or last_px >= (1.0 - ABSORB) - 1e-12
    out["terminal"] = terminal
    missing_crash = fav_won is False and last_px > CROSS + 1e-12
    out["missing_crash"] = missing_crash
    stay_lost = (not dipped) and fav_won is False
    out["stay_above_but_lost"] = stay_lost
    if missing_crash or stay_lost:
        out["path_status"] = "path_incomplete"
        out["stay_above"] = False
        return out
    if not dipped:
        out["stay_above"] = True
        out["path_status"] = "complete" if (terminal or fav_won is True) else "watched"
        return out
    out["stay_above"] = False
    out["path_status"] = "complete" if terminal else "watched"
    return out


def analyze_favorite_path(
    t0_px: float,
    t0_ts: int,
    ticks: list[tuple[int, float]],
    end_ts: int | None = None,
    fav_won: bool | None = None,
) -> dict:
    """Q1 path on the T0 favorite Yes. ticks are post-T0, chronological."""
    cls = classify_stay_above(ticks, t0_ts, fav_won=fav_won, ticks_are_post=True)
    out = {
        "empty": not bool(ticks),
        "stay_above": cls["stay_above"],
        "dipped": cls["dipped"],
        "recovered": False,
        "minutes_le50": 0.0,
        "n_post": len(ticks),
        "min_px": t0_px,
        "raw_never_le50": cls["raw_never_le50"],
        "path_status": cls["path_status"],
        "missing_crash": cls["missing_crash"],
        "stay_above_but_lost": cls["stay_above_but_lost"],
        "last_px": cls["last_px"],
        "terminal": cls["terminal"],
    }
    if not ticks:
        return out
    recovered = False
    min_px = t0_px
    dipped = False
    for _ts, px in ticks:
        if px < min_px:
            min_px = px
        if px <= CROSS + 1e-12:
            dipped = True
        elif dipped and px > CROSS:
            recovered = True
    out["recovered"] = recovered
    out["min_px"] = min_px
    out["minutes_le50"] = minutes_at_or_below(t0_ts, t0_px, ticks, end_ts)
    return out


def classify_dog_cross(
    t0_px: float,
    t0_ts: int,
    ticks: list[tuple[int, float]],
) -> dict:
    """Q2: T0 dog Yes from-below 50-cross. Aligns with Strategy B (strictly > 0.50)."""
    out = {
        "excluded": False,
        "reason": "",
        "kind": "",
        "n_cross": 0,
        "first_cross_ts": None,
        "minutes_to_first": None,
        "empty": not bool(ticks),
    }
    if t0_px >= CROSS - 1e-12:
        out["excluded"] = True
        out["reason"] = "dog_already_ge_50"
        out["kind"] = "already_ge_50"
        return out
    if not ticks:
        out["kind"] = "no_path"
        return out
    prev = t0_px
    cross_times: list[int] = []
    for ts, px in ticks:
        if prev <= CROSS + 1e-12 and px > CROSS:
            cross_times.append(ts)
        prev = px
    out["n_cross"] = len(cross_times)
    if not cross_times:
        out["kind"] = "never_cross"
        return out
    first = cross_times[0]
    out["first_cross_ts"] = first
    out["minutes_to_first"] = (first - t0_ts) / 60.0
    from_first = [(ts, px) for ts, px in ticks if ts >= first]
    held = all(px > CROSS for _ts, px in from_first)
    if len(cross_times) >= 2:
        out["kind"] = "multi_cross"
    elif held:
        out["kind"] = "one_cross_hold"
    else:
        out["kind"] = "cross_then_fail"
    return out


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(
    headers: list[tuple[str, str]],
    rows: list[list[str]],
    total: list[str] | None = None,
) -> str:
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


def _ts(value) -> int | None:
    dt = parse_dt(value) if value else None
    if dt is None:
        return None
    return int(to_et(dt).timestamp())


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_settlement_rows() -> list[dict]:
    rows: list[dict] = []
    if SETTLE_CACHE.is_file():
        try:
            raw = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = []
        if isinstance(raw, list):
            rows.extend(r for r in raw if isinstance(r, dict))
    try:
        from polymarket_tennis_no_90plus_20261020 import load_poly_tennis_resolutions

        extra = load_poly_tennis_resolutions()
        if extra:
            rows.extend(extra)
    except Exception:
        pass
    return rows


def start_lookup_from_settlements(rows: list[dict]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for row in rows:
        game = row.get("game_n") or game_norm(row.get("game") or "")
        raw = row.get("occurrence") or ""
        if not game or not raw or not is_clocked_start(raw):
            continue
        dt = parse_dt(raw)
        if dt is None:
            continue
        out.setdefault(game, to_et(dt))
    return out


def is_void_result(text: str) -> bool:
    low = (text or "").strip().lower()
    return low in VOID_RESULTS or "void" in low or "push" in low


def overlay_last_yes(sides: dict[tuple, dict]) -> int:
    try:
        stored = load_last()
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        return 0
    n_add = 0
    for key, row in stored.items():
        if not isinstance(row, dict):
            continue
        if str(row.get("pay") or "yes").lower() != "yes":
            continue
        venue = str(row.get("venue") or "")
        if venue not in VENUES:
            continue
        price = as_float(row.get("price"))
        if price is None or price <= 0.0 or price >= 1.0:
            continue
        seen = row.get("seen_at") or ""
        ts = _ts(seen)
        if ts is None:
            continue
        sport = str(row.get("sport") or "unknown")
        game = row.get("game") or ""
        kind = str(row.get("market_type") or "moneyline") or "moneyline"
        number = "" if kind == "moneyline" else str(row.get("number") or "")
        side_key = str(row.get("side_key") or row.get("side") or "").strip().lower()
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


def stream_yes_sides() -> tuple[dict[tuple, dict], dict]:
    sides: dict[tuple, dict] = {}
    n_lines = 0
    n_yes = 0
    seen_min = ""
    seen_max = ""
    sports: dict[str, int] = defaultdict(int)
    kinds: dict[str, int] = defaultdict(int)
    for line in iter_tick_lines():
        n_lines += 1
        if n_lines % 400000 == 0:
            print(f"  streamed {n_lines} lines, yes sides {len(sides)} ticks {n_yes}", flush=True)
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
        if venue not in VENUES:
            continue
        price = as_float(rec.get("price"))
        if price is None or price <= 0.0 or price >= 1.0:
            continue
        seen = rec.get("seen_at") or ""
        ts = _ts(seen)
        if ts is None:
            continue
        sport = str(rec.get("sport") or "unknown")
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
    n_overlay = overlay_last_yes(sides)
    print(
        f"stream done lines={n_lines} yes={n_yes} sides={len(sides)} overlay={n_overlay} "
        f"seen {seen_min} .. {seen_max}",
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


def pair_books(sides: dict[tuple, dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for ident, st in sides.items():
        sport, game_n, kind, venue, number, _side = ident
        groups[(sport, game_n, kind, venue, number)].append(st)
    books = []
    for (sport, game_n, kind, venue, number), members in groups.items():
        members = [m for m in members if m.get("ticks")]
        members.sort(key=lambda m: (m.get("side_key") or "", m.get("side") or ""))
        if not members:
            continue
        a = members[0]
        b = members[1] if len(members) > 1 else None
        extra = len(members) - 2
        listed = a.get("game_start") or (b.get("game_start") if b else "") or ""
        books.append({
            "sport": a.get("sport") or sport,
            "game": a.get("game") or game_n,
            "game_n": game_n,
            "kind": kind,
            "venue": venue,
            "number": number,
            "side_a": a.get("side") or "",
            "side_b": (b.get("side") if b else ""),
            "yes_a": a["ticks"],
            "yes_b": b["ticks"] if b else [],
            "listed_raw": listed,
            "n_sides": len(members),
            "n_extra_sides": max(0, extra),
            "two_sided": b is not None,
        })
    return books


def settle_book(book: dict, settlements: list[dict], index: dict) -> None:
    last_map = {}
    crosses = []
    for letter, side, ticks in (
        ("a", book.get("side_a") or "", book.get("yes_a") or []),
        ("b", book.get("side_b") or "", book.get("yes_b") or []),
    ):
        if not side:
            continue
        key = f"{id(book)}|{letter}"
        last_px = ticks[-1][1] if ticks else None
        last_ts = ticks[-1][0] if ticks else None
        last_map[key] = {
            "price": last_px,
            "seen_at": datetime.fromtimestamp(last_ts, ET).isoformat() if last_ts else "",
            "game_start": book.get("listed_raw") or "",
            "sport": book.get("sport") or "",
        }
        crosses.append({
            "key": key,
            "sport": book.get("sport") or "",
            "game": book.get("game") or "",
            "market_type": book.get("kind") or "",
            "side": side,
            "side_key": game_norm(side),
            "number": book.get("number") or "",
            "venue": book.get("venue") or "",
            "cross_time": "",
            "game_start": book.get("listed_raw") or "",
        })
    if not crosses:
        book["off_a"] = "pending"
        book["off_b"] = "pending"
        book["winner"] = None
        book["settled"] = False
        book["void"] = False
        return
    attach_results(crosses, last_map, settlements, index)
    by_key = {c["key"]: c for c in crosses}
    ca = by_key.get(f"{id(book)}|a") or {}
    cb = by_key.get(f"{id(book)}|b") or {}
    book["off_a"] = ca.get("official") or "pending"
    book["off_b"] = cb.get("official") or "pending"
    book["off_src_a"] = ca.get("official_source") or ""
    book["off_src_b"] = cb.get("official_source") or ""
    src_blob = f"{book['off_src_a']} {book['off_src_b']} {book['off_a']} {book['off_b']}"
    void = is_void_result(src_blob) or (
        book["off_a"] == "win" and book["off_b"] == "win"
    )
    winner = None
    if book["off_a"] == "win" and book["off_b"] != "win":
        winner = "a"
    elif book["off_b"] == "win" and book["off_a"] != "win":
        winner = "b"
    book["winner"] = winner
    book["void"] = void
    book["settled"] = winner is not None and not void


def score_book(book: dict, occ_map: dict[str, datetime]) -> None:
    yes_a = book.get("yes_a") or []
    yes_b = book.get("yes_b") or []
    listed_dt = parse_dt(book.get("listed_raw") or "")
    if listed_dt is not None:
        listed_dt = to_et(listed_dt)
    occ_dt = occ_map.get(book.get("game_n") or "")
    clock, src, skip = pick_trusted_clock(occ_dt, listed_dt, yes_a, yes_b)
    book["t0_source"] = src
    book["skip"] = skip
    book["clock"] = clock.isoformat() if clock else ""
    book["t0_a"] = None
    book["t0_b"] = None
    book["t0_ts"] = None
    book["t0_label"] = ""
    if clock is None:
        return
    clock_ts = int(to_et(clock).timestamp())
    if book.get("two_sided"):
        t0_a, t0_b, t0_ts, label = assign_t0_prices(yes_a, yes_b, clock_ts)
        book["t0_a"] = t0_a
        book["t0_b"] = t0_b
        book["t0_ts"] = t0_ts
        book["t0_label"] = f"{label} ({src})"
        if t0_a is None or t0_b is None or t0_ts is None:
            book["skip"] = "no_t0_quotes"
            return
        book["skip"] = ""
        if t0_b > t0_a + 1e-12:
            book["fav"] = "b"
            book["dog"] = "a"
        elif t0_a > t0_b + 1e-12:
            book["fav"] = "a"
            book["dog"] = "b"
        else:
            book["fav"] = ""
            book["dog"] = ""
            book["skip"] = "t0_50_50"
        book["c0"] = t0_a + t0_b
    else:
        t0 = last_at_or_before(yes_a, clock_ts)
        if t0 is None and yes_a:
            after = [row for row in yes_a if row[0] >= clock_ts]
            t0 = after[0] if after else None
            label = "first Yes after clock"
        else:
            label = "last Yes <= clock"
        if t0 is None:
            book["skip"] = "no_t0_quotes"
            return
        book["t0_a"] = t0[1]
        book["t0_ts"] = t0[0]
        book["t0_label"] = f"{label} ({src}); one-sided Yes"
        book["skip"] = ""
        book["c0"] = None
        if t0[1] > CROSS + 1e-12:
            book["fav"] = "a"
            book["dog"] = ""
        elif t0[1] < CROSS - 1e-12:
            book["fav"] = ""
            book["dog"] = "a"
        else:
            book["fav"] = ""
            book["dog"] = ""
            book["skip"] = "t0_50_50"
    fav = book.get("fav") or ""
    dog = book.get("dog") or ""
    t0_ts = book.get("t0_ts")
    if t0_ts is None:
        return
    absorb = first_absorbing(yes_a, yes_b)
    last_ts = None
    for bag in (yes_a, yes_b):
        if bag:
            last_ts = bag[-1][0] if last_ts is None else max(last_ts, bag[-1][0])
    end_ts = last_ts
    if absorb is not None:
        end_ts = absorb if last_ts is None else min(last_ts, absorb)
    book["end_ts"] = end_ts
    if book.get("settled") and fav:
        book["fav_won"] = book.get("winner") == fav
    else:
        book["fav_won"] = None

    def side_ticks(letter: str) -> list[tuple[int, float]]:
        bag = yes_a if letter == "a" else yes_b
        return [(ts, px) for ts, px in bag if ts > t0_ts and (end_ts is None or ts <= end_ts)]

    if fav:
        t0_fav = book["t0_a"] if fav == "a" else book["t0_b"]
        book["t0_fav"] = t0_fav
        book["fav_name"] = book["side_a"] if fav == "a" else book["side_b"]
        book["fav_path"] = analyze_favorite_path(
            t0_fav, t0_ts, side_ticks(fav), end_ts, fav_won=book.get("fav_won"),
        )
        book["fav_bucket"] = bucket_of(t0_fav)
    else:
        book["t0_fav"] = None
        book["fav_name"] = ""
        book["fav_path"] = None
        book["fav_bucket"] = bucket_of(None) if book.get("skip") == "no_t0_quotes" else "50-50"
    if dog:
        t0_dog = book["t0_a"] if dog == "a" else book["t0_b"]
        book["t0_dog"] = t0_dog
        book["dog_name"] = book["side_a"] if dog == "a" else book["side_b"]
        book["dog_path"] = classify_dog_cross(t0_dog, t0_ts, side_ticks(dog))
    else:
        book["t0_dog"] = None
        book["dog_name"] = ""
        book["dog_path"] = None


def slice_ok(book: dict, *, last7: datetime | None = None) -> bool:
    if last7 is None:
        return True
    t0_ts = book.get("t0_ts")
    if t0_ts is None:
        return False
    return datetime.fromtimestamp(t0_ts, ET) >= last7


def summarize(books: list[dict], *, last7: datetime | None = None) -> dict:
    skips: dict[str, int] = defaultdict(int)
    n_books = 0
    n_trusted = 0
    n_settled = 0
    n_void = 0
    n_pending = 0
    n_path = 0
    q1_stay = 0
    q1_dip = 0
    stay_buckets: dict[str, int] = defaultdict(int)
    stay_cum: dict[str, int] = defaultdict(int)
    dog_kinds: dict[str, int] = defaultdict(int)
    win_buckets: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_sport: dict[str, dict] = {}
    by_kind: dict[str, dict] = {}
    by_sk: dict[str, dict] = {}
    n_missing_crash = 0
    n_stay_lost = 0
    n_raw_stay = 0
    n_same_stay = 0
    n_incomplete = 0
    trap_n = 0
    trap_d = 0
    recover_n = 0
    recover_d = 0
    minutes_le50: list[float] = []
    minutes_to_cross: list[float] = []
    c_dist: dict[str, int] = defaultdict(int)
    n_one_sided = 0
    n_two_sided = 0

    def bag_for(store: dict, key: str) -> dict:
        got = store.get(key)
        if got is None:
            got = {
                "n_settled": 0, "q1_n": 0, "q1_stay": 0,
                "q2_n": 0, "q2_hold": 0, "q3_n": 0, "q3_win": 0,
                "same_stay": 0, "missing_crash": 0, "stay_lost": 0,
                "raw_stay": 0, "incomplete": 0, "no_post": 0,
            }
            store[key] = got
        return got

    for book in books:
        if not slice_ok(book, last7=last7):
            continue
        n_books += 1
        if book.get("two_sided"):
            n_two_sided += 1
        else:
            n_one_sided += 1
        skip = book.get("skip") or ""
        if skip:
            skips[skip] += 1
            if skip in ("t0_50_50", "no_t0_quotes") and book.get("settled") and not book.get("void"):
                label = "50-50" if skip == "t0_50_50" else "missing T0"
                wins, tot = win_buckets[label]
                win_buckets[label] = [wins, tot + 1]
            continue
        n_trusted += 1
        if book.get("void"):
            n_void += 1
            skips["void"] += 1
            continue
        if not book.get("settled"):
            n_pending += 1
            skips["not_settled"] += 1
            continue
        n_settled += 1
        sport = book.get("sport") or "unknown"
        kind = book.get("kind") or "unknown"
        sport_bag = bag_for(by_sport, sport)
        kind_bag = bag_for(by_kind, kind)
        sk_bag = bag_for(by_sk, f"{sport}\t{kind}")
        sport_bag["n_settled"] += 1
        kind_bag["n_settled"] += 1
        sk_bag["n_settled"] += 1
        c0 = book.get("c0")
        if c0 is not None:
            c_dist[c_bucket_of(c0)] += 1
        t0_fav = book.get("t0_fav")
        bucket = book.get("fav_bucket") or "missing T0"
        if t0_fav is not None and book.get("fav"):
            wins, tot = win_buckets[bucket]
            tot += 1
            if book.get("fav_won"):
                wins += 1
            win_buckets[bucket] = [wins, tot]
            sport_bag["q3_n"] += 1
            kind_bag["q3_n"] += 1
            sk_bag["q3_n"] += 1
            if book.get("fav_won"):
                sport_bag["q3_win"] += 1
                kind_bag["q3_win"] += 1
                sk_bag["q3_win"] += 1
            if t0_fav > 0.80:
                trap_d += 1
        elif bucket == "50-50":
            wins, tot = win_buckets["50-50"]
            win_buckets["50-50"] = [wins, tot + 1]
        path = book.get("fav_path")
        if path and book.get("fav"):
            if path.get("raw_never_le50"):
                n_raw_stay += 1
                sport_bag["raw_stay"] += 1
                kind_bag["raw_stay"] += 1
                sk_bag["raw_stay"] += 1
            if path.get("stay_above"):
                n_same_stay += 1
                sport_bag["same_stay"] += 1
                kind_bag["same_stay"] += 1
                sk_bag["same_stay"] += 1
            if path.get("missing_crash"):
                n_missing_crash += 1
                sport_bag["missing_crash"] += 1
                kind_bag["missing_crash"] += 1
                sk_bag["missing_crash"] += 1
            if path.get("stay_above_but_lost"):
                n_stay_lost += 1
                sport_bag["stay_lost"] += 1
                kind_bag["stay_lost"] += 1
                sk_bag["stay_lost"] += 1
            if path.get("path_status") == "path_incomplete":
                n_incomplete += 1
                sport_bag["incomplete"] += 1
                kind_bag["incomplete"] += 1
                sk_bag["incomplete"] += 1
                skips["path_incomplete"] += 1
        if path and not path.get("empty") and book.get("fav"):
            n_path += 1
            sport_bag["q1_n"] += 1
            kind_bag["q1_n"] += 1
            sk_bag["q1_n"] += 1
            if path.get("stay_above"):
                q1_stay += 1
                sport_bag["q1_stay"] += 1
                kind_bag["q1_stay"] += 1
                sk_bag["q1_stay"] += 1
                stay_buckets[bucket] += 1
                if t0_fav is not None:
                    for label, bar in CUMULATIVE:
                        if t0_fav > bar:
                            stay_cum[label] += 1
                    if t0_fav > 0.90:
                        stay_cum[">90"] += 1
            else:
                q1_dip += 1
            if path.get("dipped"):
                recover_d += 1
                minutes_le50.append(float(path.get("minutes_le50") or 0.0))
                if path.get("recovered"):
                    recover_n += 1
            if t0_fav is not None and t0_fav > 0.80 and path.get("dipped"):
                trap_n += 1
        elif book.get("fav"):
            skips["no_post_t0_path"] += 1
            sport_bag["no_post"] += 1
            kind_bag["no_post"] += 1
            sk_bag["no_post"] += 1
        dog = book.get("dog_path")
        if dog and not dog.get("excluded") and dog.get("kind") not in ("", "no_path"):
            kind_name = dog["kind"]
            dog_kinds[kind_name] += 1
            q2_n_add = kind_name in (
                "never_cross", "one_cross_hold", "cross_then_fail", "multi_cross",
            )
            if q2_n_add:
                sport_bag["q2_n"] += 1
                kind_bag["q2_n"] += 1
            if kind_name == "one_cross_hold":
                sport_bag["q2_hold"] += 1
                kind_bag["q2_hold"] += 1
            if dog.get("minutes_to_first") is not None:
                minutes_to_cross.append(float(dog["minutes_to_first"]))
        elif dog and dog.get("excluded"):
            dog_kinds["already_ge_50"] += 1
        elif dog and dog.get("kind") == "no_path":
            dog_kinds["no_path"] += 1

    q1_n = q1_stay + q1_dip
    q2_core = (
        dog_kinds.get("never_cross", 0)
        + dog_kinds.get("one_cross_hold", 0)
        + dog_kinds.get("cross_then_fail", 0)
        + dog_kinds.get("multi_cross", 0)
    )

    def decorate(store: dict) -> dict:
        out = {}
        for k, v in sorted(store.items()):
            q3_n = int(v.get("q3_n") or 0)
            out[k] = {
                **v,
                "q1_pct": pct(v["q1_stay"], v["q1_n"]),
                "q2_pct": pct(v["q2_hold"], v["q2_n"]),
                "q3_pct": pct(v["q3_win"], v["q3_n"]),
                "same_stay_pct": pct(v.get("same_stay") or 0, q3_n),
                "raw_stay_pct": pct(v.get("raw_stay") or 0, q3_n),
                "violates": (v.get("same_stay") or 0) > (v.get("q3_win") or 0),
            }
        return out

    return {
        "n_books": n_books,
        "n_trusted": n_trusted,
        "n_settled": n_settled,
        "n_void": n_void,
        "n_pending": n_pending,
        "n_path": n_path,
        "n_one_sided": n_one_sided,
        "n_two_sided": n_two_sided,
        "skips": dict(skips),
        "q1_n": q1_n,
        "q1_stay": q1_stay,
        "q1_dip": q1_dip,
        "q1_pct": pct(q1_stay, q1_n),
        "stay_buckets": dict(stay_buckets),
        "stay_cum": dict(stay_cum),
        "dog_kinds": dict(dog_kinds),
        "q2_n": q2_core,
        "q2_hold": dog_kinds.get("one_cross_hold", 0),
        "q2_pct": pct(dog_kinds.get("one_cross_hold", 0), q2_core),
        "win_buckets": {k: {"wins": v[0], "n": v[1], "pct": pct(v[0], v[1])} for k, v in win_buckets.items()},
        "by_sport": decorate(by_sport),
        "by_kind": decorate(by_kind),
        "by_sport_kind": decorate(by_sk),
        "n_missing_crash": n_missing_crash,
        "n_stay_lost": n_stay_lost,
        "n_raw_stay": n_raw_stay,
        "n_same_stay": n_same_stay,
        "n_incomplete": n_incomplete,
        "trap_n": trap_n,
        "trap_d": trap_d,
        "trap_pct": pct(trap_n, trap_d),
        "recover_n": recover_n,
        "recover_d": recover_d,
        "recover_pct": pct(recover_n, recover_d),
        "median_min_le50": median(minutes_le50),
        "median_min_to_cross": median(minutes_to_cross),
        "c_dist": dict(c_dist),
        "q3_n_all": sum(int(v.get("q3_n") or 0) for v in by_sport.values()),
    }


def _bucket_rows(summary: dict, stay: bool) -> list[list[str]]:
    rows = []
    source = summary["stay_buckets"] if stay else {
        k: v["n"] for k, v in summary["win_buckets"].items()
    }
    denom = summary["q1_stay"] if stay else None
    order = [">90", "80-89", "70-79", "60-69", "50-59", "50-50", "missing T0", "under-50"]
    if stay:
        for label in order[:5]:
            n = int(source.get(label, 0))
            rows.append([esc(label), str(n), pct(n, denom or 0), tiny(n)])
        for label, _bar in CUMULATIVE:
            n = int(summary["stay_cum"].get(label, 0))
            rows.append([esc(label + " (cumulative)"), str(n), pct(n, denom or 0), tiny(n)])
        n90 = int(summary["stay_cum"].get(">90", 0))
        rows.append([esc(">90 (cumulative)"), str(n90), pct(n90, denom or 0), tiny(n90)])
    else:
        for label in order:
            bag = summary["win_buckets"].get(label) or {"wins": 0, "n": 0, "pct": "—"}
            win_pct = "—" if label in ("50-50", "missing T0") else bag["pct"]
            wins_cell = "—" if label in ("50-50", "missing T0") else str(bag["wins"])
            rows.append([
                esc(label),
                str(bag["n"]),
                wins_cell,
                win_pct,
                tiny(bag["n"]),
            ])
    return rows


def tiny(n: int) -> str:
    if n <= 0:
        return "no settled rows"
    if n < 20:
        return "tiny sample"
    if n < 50:
        return "small sample"
    return ""


def calibration_note(summary: dict) -> str:
    bag = summary["win_buckets"].get("80-89") or {}
    n = int(bag.get("n") or 0)
    wins = int(bag.get("wins") or 0)
    if n <= 0:
        return "No 80–89 T0 favorites are settled yet, so we cannot talk about calibration in that band."
    rate = 100.0 * wins / n
    if 80.0 <= rate <= 90.0:
        how = "well-calibrated"
    elif rate > 90.0:
        how = "favorites in this band won more often than the price implied (under-confident market, or a small sample)"
    else:
        how = "favorites in this band won less often than the price implied (over-confident market, or a small sample)"
    return (
        f"80–89¢ T0 favorites won {rate:.1f}% ({wins}/{n}). Mid-band implied chance is about 85%. "
        f"That looks {how}."
    )


def sport_rows(summary: dict) -> list[list[str]]:
    rows = []
    for sport, bag in summary["by_sport"].items():
        rows.append([
            esc(sport),
            str(bag["n_settled"]),
            bag["q1_pct"],
            f"{bag['q1_stay']}/{bag['q1_n']}",
            bag["q2_pct"],
            f"{bag['q2_hold']}/{bag['q2_n']}",
            bag["q3_pct"],
            f"{bag['q3_win']}/{bag['q3_n']}",
        ])
    return rows


def inequality_rows(summary: dict) -> list[list[str]]:
    """Same-N stay-above vs win rate. Stay should be ≤ win after the completeness fix."""
    rows = []
    items = []
    for sport, bag in summary.get("by_sport", {}).items():
        items.append((sport, "all", bag))
    for key, bag in summary.get("by_sport_kind", {}).items():
        if "\t" in key:
            sport, kind = key.split("\t", 1)
        else:
            sport, kind = key, "all"
        items.append((sport, kind, bag))
    for kind, bag in summary.get("by_kind", {}).items():
        items.append(("All sports", kind, bag))
    all_q3 = int(summary.get("q3_n_all") or 0)
    all_win = sum(int(b.get("q3_win") or 0) for b in summary.get("by_sport", {}).values())
    all_stay = int(summary.get("n_same_stay") or 0)
    all_raw = int(summary.get("n_raw_stay") or 0)
    all_lost = int(summary.get("n_stay_lost") or 0)
    all_crash = int(summary.get("n_missing_crash") or 0)
    all_inc = int(summary.get("n_incomplete") or 0)
    all_path = int(summary.get("q1_n") or 0)
    all_nopost = int((summary.get("skips") or {}).get("no_post_t0_path") or 0)
    items.append(("All sports", "all", {
        "q3_n": all_q3,
        "q3_win": all_win,
        "q3_pct": pct(all_win, all_q3),
        "same_stay": all_stay,
        "same_stay_pct": pct(all_stay, all_q3),
        "raw_stay": all_raw,
        "q1_n": all_path,
        "stay_lost": all_lost,
        "missing_crash": all_crash,
        "incomplete": all_inc,
        "no_post": all_nopost,
        "violates": all_stay > all_win,
    }))
    seen = set()
    for sport, kind, bag in items:
        mark = (sport, kind)
        if mark in seen:
            continue
        seen.add(mark)
        q3 = int(bag.get("q3_n") or 0)
        stay = int(bag.get("same_stay") or 0)
        win = int(bag.get("q3_win") or 0)
        viol = "YES — bug" if stay > win else "no"
        rows.append([
            esc(sport),
            esc(kind),
            str(q3),
            str(int(bag.get("q1_n") or 0)),
            pct(stay, q3),
            f"{stay}/{q3}",
            bag.get("q3_pct") or pct(win, q3),
            f"{win}/{q3}",
            str(int(bag.get("stay_lost") or 0)),
            str(int(bag.get("missing_crash") or 0)),
            str(int(bag.get("no_post") or 0)),
            str(int(bag.get("incomplete") or 0)),
            viol,
            tiny(q3),
        ])
    return rows


def kind_rows(summary: dict) -> list[list[str]]:
    rows = []
    for kind, bag in summary["by_kind"].items():
        rows.append([
            esc(kind),
            str(bag["n_settled"]),
            bag["q1_pct"],
            f"{bag['q1_stay']}/{bag['q1_n']}",
            bag["q2_pct"],
            f"{bag['q2_hold']}/{bag['q2_n']}",
            bag["q3_pct"],
            f"{bag['q3_win']}/{bag['q3_n']}",
        ])
    return rows


def skip_rows(summary: dict) -> list[list[str]]:
    rows = []
    for reason, n in sorted(summary["skips"].items(), key=lambda kv: (-kv[1], kv[0])):
        rows.append([esc(reason), str(n)])
    return rows


def dog_rows(summary: dict) -> list[list[str]]:
    labels = (
        ("one_cross_hold", "Crossed once from below and stayed >50¢"),
        ("never_cross", "Never crossed 50¢"),
        ("cross_then_fail", "Crossed then fell back to ≤50¢ (exactly one from-below cross)"),
        ("multi_cross", "Crossed from below more than once"),
        ("already_ge_50", "Dog already ≥50¢ at T0 (excluded from Q2 %)"),
        ("no_path", "Trusted T0 but no post-T0 dog ticks"),
    )
    denom = summary["q2_n"]
    rows = []
    kinds = summary["dog_kinds"]
    for key, label in labels:
        n = int(kinds.get(key, 0))
        use = denom if key not in ("already_ge_50", "no_path") else 0
        rows.append([
            esc(label),
            str(n),
            pct(n, denom) if use else "—",
            tiny(n),
        ])
    return rows


def c_rows(summary: dict) -> list[list[str]]:
    rows = []
    total = sum(summary["c_dist"].values())
    for label, _lo, _hi in C_BUCKETS:
        n = int(summary["c_dist"].get(label, 0))
        rows.append([esc(label), str(n), pct(n, total), tiny(n)])
    return rows


def write_html(payload: dict) -> Path:
    full = payload["full"]
    week = payload["week"]
    meta = payload["meta"]
    now = payload["now"]
    q3_headers = [
        ("T0 favorite Yes", "text"),
        ("N", "num"),
        ("Favorite wins", "num"),
        ("Win %", "num"),
        ("Sample", "text"),
    ]
    q1_headers = [
        ("T0 favorite Yes among stay-above-50", "text"),
        ("N", "num"),
        ("% of stay-above games", "num"),
        ("Sample", "text"),
    ]
    sport_headers = [
        ("Sport", "text"),
        ("Settled N", "num"),
        ("Q1 stay>50 %", "num"),
        ("Q1 n", "text"),
        ("Q2 one-cross-hold %", "num"),
        ("Q2 n", "text"),
        ("Q3 favorite win %", "num"),
        ("Q3 n", "text"),
    ]
    kind_headers = [
        ("Market", "text"),
        ("Settled N", "num"),
        ("Q1 stay>50 %", "num"),
        ("Q1 n", "text"),
        ("Q2 one-cross-hold %", "num"),
        ("Q2 n", "text"),
        ("Q3 favorite win %", "num"),
        ("Q3 n", "text"),
    ]
    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>All-game T0 stats</title>
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
<h1>All-game T0 stats</h1>
<p class="note">Companion band table (research-only; live C_HI still 1.20):
<a href="t0_band_from_stay_above_20261024.html">t0_band_from_stay_above_20261024.html</a>.
T0-favorite &lt;90¢ one-Yes baseline:
<a href="t0_fav_lt90_baseline_20261024/compare.html">t0_fav_lt90_baseline_20261024/compare.html</a>.</p>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. Not a GitHub Pages live report.
Rebuilds about every 2 hours while prediction jobs are running. Bookmark
<code>{esc(FILE_URL)}</code>.</p>
<p class="note">Updated {esc(now)} Eastern Time. Tape ticks {esc(meta.get("seen_min") or "—")}
through {esc(meta.get("seen_max") or "—")}. Streamed {esc(meta.get("n_lines"))} lines,
{esc(meta.get("n_yes"))} Yes ticks, {esc(meta.get("n_sides"))} side-series.
Grain: one row per venue × game × market type × number. Same match on Kalshi and Polymarket
counts twice. T0 Yes asks on that venue book, never fill prices.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Where to look</h2>
<p>This page is the living dashboard for questions 1–3 on <strong>all tracked games</strong>, not only filled orders.
Older stamps still exist; they do not auto-refresh this way:</p>
<ul>
<li><a href="t0_all_games_stats.html">t0_all_games_stats.html</a> (this page) — all sports, moneyline and spread, ~2h refresh while the supervisor is up.</li>
<li><a href="t0_fav_lt90_baseline_20261024/compare.html">t0_fav_lt90_baseline_20261024/compare.html</a> — T0-favorite &lt;90¢ one-Yes baseline (not Strategy B) plus the stay-above vs win-rate audit.</li>
<li><a href="tennis_decade_at_start_live.html">tennis_decade_at_start_live.html</a> — tennis moneyline win rate by T0 decade only. Rebuilds about every 15 minutes from snapshots. Does not answer stay-above-50 or dog 50-cross.</li>
<li><a href="tennis_decade_at_start_20261020.html">tennis_decade_at_start_20261020.html</a> — same tennis decade study, named stamp (also rewritten on that snapshot rebuild).</li>
<li><a href="dense_inplay_fav_lock_cross_smalld_20261021.html">dense_inplay_fav_lock_cross_smalld_20261021.html</a> — one-off Strategy B sim on 182 dense tennis books, not all games.</li>
<li><a href="dense_inplay_yes_dip_20261021.html">dense_inplay_yes_dip_20261021.html</a> — one-off extra-Yes-on-dip tennis freeze.</li>
<li><a href="tracked_inmatch_books_20261021.html">tracked_inmatch_books_20261021.html</a> — one-off collection-hole audit.</li>
<li><a href="odds_cross_winrate_20261020.html">odds_cross_winrate_20261020.html</a> — one-off hysteresis up-cross win rates, all sports.</li>
<li><a href="tennis_t0_start_clusters_20261021.html">tennis_t0_start_clusters_20261021.html</a> — T0 start clustering, not path stats.</li>
<li><a href="inmatch_tick_collection_20261021.html">inmatch_tick_collection_20261021.html</a> — how in-match ticks are stored.</li>
</ul>
<p class="tiny">file:// this page: <code>{esc(FILE_URL)}</code></p>

<h2>T0 definition</h2>
<p>Same trusted-start idea as live Strategy B / the Moutet T0 page. A clock is trusted when it is a
Kalshi/Gemini <strong>occurrence</strong> (odd seconds still count) or a <strong>listed/feed</strong> time whose
seconds are 00 (15:10:00 yes; a Polymarket 23:12:40Z feed stamp no). We do not use tape-resume after a
quiet hour, and we do not use “first competitive two-sided Yes” as T0 when there is no trusted clock.
Those games are skipped and counted below. T0 prices are the last two-sided Yes at or before that clock,
else the mixed pre-start + first in-game quotes. Favorite = the side with the higher T0 Yes ask.
For a one-sided spread/total Yes, the favorite is that side when its T0 Yes is above 50¢.</p>

<h2>Headline — full collection</h2>
<p><strong>Q1.</strong> Among {esc(full["q1_n"])} settled games with a trusted T0, a unique favorite, and a post-T0
Yes path, the T0 favorite stayed strictly above 50¢ on a <em>complete</em> watch in
<strong>{esc(full["q1_pct"])}%</strong> ({esc(full["q1_stay"])}/{esc(full["q1_n"])}).
The favorite did go to 50¢ or below at least once in {esc(full["q1_dip"])} of those
({esc(pct(full["q1_dip"], full["q1_n"]))}%). Incomplete watches (last tick still &gt;50¢
while settlement says they lost, or no crash ticks) are <em>not</em> stay-above:
{esc(full.get("n_incomplete") or 0)} path_incomplete,
{esc(full.get("n_missing_crash") or 0)} missing-crash,
{esc(full.get("skips", {}).get("no_post_t0_path") or 0)} no_post_t0_path.
Same-N stay-above (among all {esc(full.get("q3_n_all") or 0)} settled unique favorites,
empty path = not stay-above) is {esc(pct(full.get("n_same_stay") or 0, full.get("q3_n_all") or 0))}%
({esc(full.get("n_same_stay") or 0)}/{esc(full.get("q3_n_all") or 0)}). That is not
“the T0 favorite won the game.”</p>
<p><strong>Q2.</strong> Among {esc(full["q2_n"])} settled games whose T0 dog Yes started under 50¢ and has a post-T0
path, the dog crossed 50¢ from below <em>once</em> and then stayed above 50¢ until the end in
<strong>{esc(full["q2_pct"])}%</strong> ({esc(full["q2_hold"])}/{esc(full["q2_n"])}).
That is the Strategy B 50-cross language: from below, first cross, strictly greater than 50¢.</p>
<p><strong>Q3.</strong> T0 favorite win rate by opening bucket is in the table below.
{esc(calibration_note(full))}</p>
<p class="note">Settled with trusted T0: {esc(full["n_settled"])}.
Voids excluded from win-rate denominators: {esc(full["n_void"])}.
Pending / still open: {esc(full["n_pending"])}.
Trusted T0 books: {esc(full["n_trusted"])} of {esc(full["n_books"])} venue-game books.
Two-sided: {esc(full["n_two_sided"])}. One-sided Yes: {esc(full["n_one_sided"])}.
The whole tape is out-of-sample versus the 2024-01-01 house split.</p>

<p class="note">Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}

<h2>Q1 — T0 favorite never dips to ≤50¢</h2>
<p class="note">Denominator is settled, non-void, trusted T0, unique favorite, at least one post-T0 favorite Yes tick.
Quiet “never dipped” with zero in-play ticks is a skip (no_post_t0_path), not a stay.
A last in-play tick still &gt;50¢ plus an official loss is path_incomplete (missing crash), not stay-above.
Stay-above-50 = the T0 favorite’s price never printed 50¢ or lower while we were watching a complete path.
Winning = they actually won.</p>
{table(q1_headers, _bucket_rows(full, True))}

<h2>Q2 — T0 dog 50-cross</h2>
<p class="note">From below, first cross, strictly &gt; 0.50. Games where the dog was already ≥50¢ at T0 are excluded from the percent.</p>
{table(
    [("Path", "text"), ("N", "num"), ("% of Q2 denom", "num"), ("Sample", "text")],
    dog_rows(full),
)}

<h2>Q3 — T0 favorite win rate by bucket</h2>
<p class="note">Official venue settlement. Voids excluded. A last print at 99¢ is not treated as a win.
The under-50 row is two-sided books where <em>both</em> Yes sat under 50¢ at T0; the higher one is still the labeled favorite.
Tennis moneyline win % near 50% on this tape may be settlement-matching noise (the local Polymarket 0/1 dump added 0 extra tennis rows this run) — treat that sport’s Q3 as provisional.</p>
{table(q3_headers, _bucket_rows(full, False))}

<h2>Inequality audit — stay-above vs win rate on the same rows</h2>
<p class="note">On a complete path that includes settlement, a losing Yes must go to $0, so it
must print ≤50¢ unless ticks stop before the market reprices. Therefore
<strong>win rate should be ≥ stay-above-50 on the same N</strong>. Different denominators were
the first bug: Q1 used to require a post-T0 path, Q3 used every settled favorite.
A second bug: incomplete watches (last tick still &gt;50¢, official loss) were counted
as stay-above. After the fix, stay-above requires a post-T0 path and is false when
settlement is a loss and the last tick never printed ≤50¢. Grain is venue-game
(same match on two venues is two rows). Voids are excluded. One-sided books can
be a T0 favorite when that Yes is above 50¢.</p>
{table(
    [
        ("Sport", "text"),
        ("Market", "text"),
        ("N win-rate (settled unique fav)", "num"),
        ("N stay path (post-T0 ticks)", "num"),
        ("Stay-above % (same N as win)", "num"),
        ("Stay n / N", "text"),
        ("T0 favorite win %", "num"),
        ("Win n / N", "text"),
        ("Stay-above-but-lost", "num"),
        ("Missing crash (last &gt;50, lost)", "num"),
        ("No post-T0 path", "num"),
        ("Path incomplete", "num"),
        ("Stay > win (bug)?", "text"),
        ("Sample", "text"),
    ],
    inequality_rows(full),
)}

<h2>By sport</h2>
{table(sport_headers, sport_rows(full))}

<h2>Moneyline vs spread vs total</h2>
{table(kind_headers, kind_rows(full))}

<h2>Last 7 days</h2>
<p class="note">Same rules, T0 timestamp on or after {esc(payload.get("week_start") or "—")}.
Q1 stay-above {esc(week["q1_pct"])}% ({esc(week["q1_stay"])}/{esc(week["q1_n"])}).
Q2 one-cross-hold {esc(week["q2_pct"])}% ({esc(week["q2_hold"])}/{esc(week["q2_n"])}).
Settled N {esc(week["n_settled"])}.</p>
{table(sport_headers, sport_rows(week))}
{table(kind_headers, kind_rows(week))}
{table(q3_headers, _bucket_rows(week, False))}

<h2>Extras</h2>
<ul>
<li><strong>Trap rate:</strong> T0 favorite starting &gt;80¢ who later printed ≤50¢:
{esc(full["trap_pct"])}% ({esc(full["trap_n"])}/{esc(full["trap_d"])}).</li>
<li><strong>Recover after a dip:</strong> of favorites who went ≤50¢, later printed &gt;50¢ again:
{esc(full["recover_pct"])}% ({esc(full["recover_n"])}/{esc(full["recover_d"])}).
Median minutes the favorite spent at or under 50¢ (among dippers): {esc(fmt_num(full["median_min_le50"]))}.</li>
<li><strong>Time to first dog 50-cross:</strong> median minutes {esc(fmt_num(full["median_min_to_cross"]))}.</li>
<li><strong>Push/void:</strong> {esc(full["n_void"])} void/push/conflict rows excluded from win-rate denominators.</li>
<li><strong>Coverage:</strong> {esc(full["n_books"])} venue-game books on the tape;
{esc(full["n_trusted"])} with a trusted T0; {esc(full["n_settled"])} settled non-void;
{esc(full["n_pending"])} still open or unmatched to a venue result;
{esc(full["skips"].get("no_trusted_clock", 0))} skipped for no trusted clock;
{esc(full["skips"].get("clock_hides_match", 0))} skipped because the clock sat after the match was already 5¢/95¢;
{esc(full["skips"].get("no_t0_quotes", 0))} skipped for missing T0 quotes;
{esc(full["skips"].get("no_post_t0_path", 0))} settled favorites with no post-T0 ticks (not counted as “never dipped”).</li>
</ul>
<p class="note">T0 both-Yes sum C (two-sided books only). Useful for the under-$1 stack question; this page is games, not orders. Fees are not subtracted here.</p>
{table(
    [("C = Yes+Yes at T0", "text"), ("N", "num"), ("% of two-sided settled with C", "num"), ("Sample", "text")],
    c_rows(full),
)}

<h2>Skip reasons</h2>
{table([("Reason", "text"), ("N", "num")], skip_rows(full))}

<h2>How this refreshes</h2>
<p>The job-status rewrite (about once a minute while the supervisor is up) and the live-game
supervisor loop both call <code>t0_all_games_stats.maybe_rebuild</code>. If this HTML is older than
2 hours, a background thread rewrites it. It does not start a second Strategy B, does not send
orders, and does not phone-ping every rebuild. Double-click <code>run_prediction_start.bat</code>
if the supervisor is down. You can also run <code>python tools/t0_all_games_stats.py</code> once.</p>
<p class="tiny">Generator: <code>tools/t0_all_games_stats.py</code>. Tests: <code>tools/test_t0_all_games_stats.py</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(html_out, encoding="utf-8")
    tmp.replace(PAGE)
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        REBUILD_STAMP.write_text(
            json.dumps({"written_at": iso_now(), "page": str(PAGE)}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return PAGE


def copy_g(path: Path) -> None:
    if not (G_DIR.parent.exists() or Path("G:/").exists()):
        return
    try:
        G_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, G_DIR / path.name)
    except OSError:
        pass


def build_payload() -> dict:
    print("loading settlements", flush=True)
    settlements = load_settlement_rows()
    occ_map = start_lookup_from_settlements(settlements)
    index = build_index(settlements)
    print(f"settlements {len(settlements)} occurrence clocks {len(occ_map)}", flush=True)
    sides, meta = stream_yes_sides()
    books = pair_books(sides)
    print(f"paired {len(books)} venue-game books", flush=True)
    for i, book in enumerate(books):
        settle_book(book, settlements, index)
        score_book(book, occ_map)
        if (i + 1) % 500 == 0:
            print(f"  scored {i + 1}/{len(books)}", flush=True)
    now = now_et()
    week_start = now - timedelta(days=7)
    full = summarize(books)
    week = summarize(books, last7=week_start)
    return {
        "now": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "week_start": week_start.strftime("%Y-%m-%d %H:%M %Z"),
        "meta": meta,
        "full": full,
        "week": week,
        "n_settlements": len(settlements),
        "books": books,
    }


def rebuild_band_companion(payload: dict, log=None) -> None:
    """Refresh the stay-above band page from the same scored books. No second tape scan."""
    try:
        import write_t0_band_from_stay_above as band
    except Exception as exc:
        if log is not None:
            try:
                log(f"t0 band companion import {type(exc).__name__}")
            except Exception:
                pass
        return
    try:
        rows = band.rows_from_living_books(payload.get("books") or [])
        meta = dict(payload.get("meta") or {})
        meta["shared"] = "t0_all_games_stats.rebuild_band_companion"
        meta["n_scored"] = len(rows)
        meta["n_settled_trusted"] = int((payload.get("full") or {}).get("n_settled") or 0)
        meta["n_trusted"] = int((payload.get("full") or {}).get("n_trusted") or 0)
        band.write_html(rows, meta)
    except Exception as exc:
        if log is not None:
            try:
                log(f"t0 band companion {type(exc).__name__}")
            except Exception:
                pass


def rebuild_html(log=None) -> str:
    try:
        payload = build_payload()
        path = write_html(payload)
        copy_g(path)
        rebuild_band_companion(payload, log)
    except Exception as exc:
        if log is not None:
            try:
                log(f"t0 all-games stats rebuild {type(exc).__name__}")
            except Exception:
                pass
        raise
    if log is not None:
        try:
            log(f"t0 all-games stats rebuilt {path}")
        except Exception:
            pass
    print(f"wrote {path}", flush=True)
    return str(path)


def _rebuild_due() -> bool:
    stamp = _load_json(REBUILD_STAMP)
    last = parse_time(str(stamp.get("written_at") or ""))
    if last is None:
        return True
    return (now_et() - to_et(last)).total_seconds() >= REBUILD_EVERY_SEC


def maybe_rebuild(log=None) -> None:
    """At most once per 2 hours. Fail-soft background thread. Does not ntfy."""
    global _rebuild_thread
    if not _rebuild_due():
        return
    with _rebuild_lock:
        if _rebuild_thread is not None and _rebuild_thread.is_alive():
            return

        def _run() -> None:
            try:
                rebuild_html(log)
            except Exception as exc:
                if log is not None:
                    try:
                        log(f"t0 all-games stats {type(exc).__name__}")
                    except Exception:
                        pass

        _rebuild_thread = threading.Thread(target=_run, name="t0-all-games-rebuild", daemon=True)
        _rebuild_thread.start()


def main() -> int:
    rebuild_html()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
