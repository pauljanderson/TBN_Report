"""Tennis T0 / listed-start clusters for dual-Yes burst risk.

Research only. Reads the dense 182-book freeze HTML, settlements, catalogs,
live_health filenames, and market caches. Does not place, cancel, or amend
orders. Does not print secrets. Does not touch orders_stopped.json,
ORDERS_ENABLED, or live order files. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
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
from odds_cross_winrate_20261020 import game_norm, parse_dt, table
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from polymarket_us_live import match_listed_start
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from tennis_decade_at_start_20261020 import is_clocked_start
from price_memory import to_et

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "tennis_t0_start_clusters_20261021.html"
DENSE_HTML = STAMP / "dense_inplay_yes_dip_20261021.html"
DECADE_HTML = STAMP / "tennis_decade_at_start_live.html"
KALSHI_MARKETS = RAW / "kalshi_markets.jsonl"
POLY_US = RAW / "polymarket_us_markets.jsonl"
LIVE_HEALTH = RAW / "live_health"
TENNIS_TWINS = RAW / "polymarket_tennis_matches.json"
ALL_BOOKS = RAW / "tennis_all_books.json"

# European indoor morning session in late-October Eastern Time (CEST = ET+6).
# Association of Tennis Professionals (ATP) first-ball windows often list 11:00
# local, which is 05:00 ET while daylight time still holds.
MORNING_HOURS = range(4, 12)
# Dense freeze first tennis quote — T0s piled here are collection start, not first ball.
TAPE_FIRST = datetime(2026, 10, 18, 16, 12, 21, tzinfo=ET)
PROP_MARKERS = (
    "total", "spread", "set 1", "set 2", "set 3", "set score",
    "more than", "both win", "australian open", "cover",
    "table-tennis", "table tennis", "tabletennis",
)
KALSHI_ML_SERIES = (
    "KXATPMATCH", "KXATPCHALLENGERMATCH", "KXWTAMATCH", "KXWTACHALLENGERMATCH",
)

ASKED = (
    "Do a lot of tennis games start at the same time? Paul is about to live-wire "
    "strategy B (buy BOTH Yes at T0) and does not want a burst of dual-Yes at one clock. "
    "How many tennis moneylines share the same listed start clock in a typical ATP morning "
    "(same minute, same 5 min, same 15 min, same hour)? Same using actual T0 from the dense "
    "sim. Today's remaining slate: how many not-yet-started tennis could T0 in the next 1h / 3h. "
    "Recommend a max_open_b_matches cap (1 vs 2 vs 3) given dual-Yes costs ~$1.00–$1.20 per "
    "match for 2 contracts."
)

PLAIN = (
    "Strategy B buys one Yes ticket on each tennis player at match open (T0). Yes is a dollar "
    "from 0 to 1, also an implied chance. Only one player can win, so those two tickets always "
    "pay exactly $1. Cost C is the two Yes prices added together — about $1.00 to $1.20, which "
    "is the vig (the house overround), not a bug. If eight matches all open at the same clock, "
    "the desk would buy sixteen tickets at once and lock up about $8–$10 until those matches "
    "end. This page counts how often listed start times bunch (the schedule on the ticket, "
    "which can be stale) versus how often actual T0 bunches (the last two-sided Yes at or "
    "before a trusted actual start from the dense 182-book freeze). ATP is the Association of "
    "Tennis Professionals; a typical ATP morning here is Eastern Time hours 04:00–11:59, which "
    "is the European indoor first session in late October. We do not invent start clocks. "
    "Date-only labels such as 2026-10-21 are not a start time. Research only. Not gold. Not "
    "DailyRun. Same-day contracts, so annualized rate of return is omitted — we do not have "
    "days held."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def et_iso(ts) -> str:
    if ts is None:
        return ""
    if isinstance(ts, datetime):
        return to_et(ts).isoformat()
    try:
        return datetime.fromtimestamp(int(ts), ET).isoformat()
    except (TypeError, ValueError, OSError):
        return str(ts)


def floor_dt(dt: datetime, minutes: int) -> datetime:
    dt = to_et(dt)
    if minutes >= 60:
        return dt.replace(minute=0, second=0, microsecond=0)
    m = (dt.minute // minutes) * minutes
    return dt.replace(minute=m, second=0, microsecond=0)


def parse_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    out = []
    for block in re.findall(r"<table class=\"sortable\">(.*?)</table>", text, re.S | re.I):
        headers = []
        for raw in re.findall(r"<th[^>]*>(.*?)</th>", block, re.S | re.I):
            label = re.sub(r"<[^>]+>", "", raw)
            label = html_mod.unescape(re.sub(r"\s+", " ", label)).strip()
            headers.append(label)
        rows = []
        for tr in re.findall(r"<tr>(.*?)</tr>", block, re.S | re.I):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
            if not tds:
                continue
            cells = [
                html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", td))).strip()
                for td in tds
            ]
            rows.append(cells)
        out.append((headers, rows))
    return out


def col_index(headers: list[str], *needles: str) -> int | None:
    low = [h.lower() for h in headers]
    for needle in needles:
        n = needle.lower()
        for i, h in enumerate(low):
            if n == h or n in h:
                return i
    return None


def load_dense_t0() -> list[dict]:
    if not DENSE_HTML.is_file():
        return []
    text = DENSE_HTML.read_text(encoding="utf-8", errors="replace")
    rows_out = []
    for headers, rows in parse_tables(text):
        i_when = col_index(headers, "t0 when")
        i_game = col_index(headers, "match")
        if i_when is None or i_game is None:
            continue
        i_venue = col_index(headers, "venue")
        i_date = col_index(headers, "date")
        i_src = col_index(headers, "actual start source")
        i_stale = col_index(headers, "clock hid")
        i_c = col_index(headers, "c")
        for cells in rows:
            if i_when >= len(cells) or i_game >= len(cells):
                continue
            when = parse_dt(cells[i_when])
            if when is None or not is_clocked_start(cells[i_when]):
                continue
            game = cells[i_game]
            rows_out.append({
                "game": game,
                "game_n": game_norm(game),
                "venue": cells[i_venue] if i_venue is not None and i_venue < len(cells) else "",
                "date": cells[i_date] if i_date is not None and i_date < len(cells) else "",
                "t0": to_et(when),
                "t0_text": cells[i_when],
                "actual_source": cells[i_src] if i_src is not None and i_src < len(cells) else "",
                "listed_stale": cells[i_stale] if i_stale is not None and i_stale < len(cells) else "",
                "c0": cells[i_c] if i_c is not None and i_c < len(cells) else "",
                "kind": "dense_t0",
            })
        if rows_out:
            break
    return rows_out


def unique_match_clocks(rows: list[dict], clock_key: str = "t0") -> list[dict]:
    """One row per match. Earliest clock wins — first book that can fire dual-Yes."""
    best: dict[str, dict] = {}
    for row in rows:
        key = row.get("game_n") or game_norm(row.get("game") or "")
        if not key:
            continue
        clock = row.get(clock_key)
        if clock is None:
            continue
        prev = best.get(key)
        if prev is None or clock < prev[clock_key]:
            best[key] = row
    return list(best.values())


def cluster_stats(rows: list[dict], clock_key: str, windows: list[int] | None = None) -> dict:
    windows = windows or [1, 5, 15, 60]
    clocks = []
    for row in rows:
        dt = row.get(clock_key)
        if dt is None:
            continue
        clocks.append(to_et(dt))
    n = len(clocks)
    out = {
        "n": n,
        "windows": {},
        "hour_hist": [],
        "day_hist": [],
    }
    if not clocks:
        return out
    for minutes in windows:
        buckets: dict[datetime, list[datetime]] = defaultdict(list)
        for dt in clocks:
            buckets[floor_dt(dt, minutes)].append(dt)
        sizes = sorted((len(v) for v in buckets.values()), reverse=True)
        n_ge2 = sum(sz for sz in sizes if sz >= 2)
        n_matches_in_multi = sum(sz for sz in sizes if sz >= 2)
        out["windows"][str(minutes)] = {
            "n_buckets": len(buckets),
            "max": sizes[0] if sizes else 0,
            "p50": sizes[len(sizes) // 2] if sizes else 0,
            "mean": round(sum(sizes) / len(sizes), 2) if sizes else 0,
            "n_buckets_ge2": sum(1 for sz in sizes if sz >= 2),
            "n_buckets_ge3": sum(1 for sz in sizes if sz >= 3),
            "n_buckets_ge5": sum(1 for sz in sizes if sz >= 5),
            "n_matches_in_ge2": n_matches_in_multi,
            "share_in_ge2": round(100.0 * n_matches_in_multi / n, 1) if n else 0,
            "top": [
                {
                    "bucket": k.isoformat(),
                    "n": len(v),
                }
                for k, v in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:12]
            ],
        }
    hour_counts: dict[int, int] = defaultdict(int)
    day_counts: dict[str, int] = defaultdict(int)
    for dt in clocks:
        hour_counts[dt.hour] += 1
        day_counts[dt.date().isoformat()] += 1
    out["hour_hist"] = [{"hour_et": h, "n": hour_counts[h]} for h in range(24) if hour_counts[h]]
    out["day_hist"] = [{"day_et": d, "n": day_counts[d]} for d in sorted(day_counts)]
    return out


def morning_slice(rows: list[dict], clock_key: str) -> list[dict]:
    out = []
    for row in rows:
        dt = row.get(clock_key)
        if dt is None:
            continue
        dt = to_et(dt)
        if dt.hour in MORNING_HOURS:
            copy = dict(row)
            copy[clock_key] = dt
            out.append(copy)
    return out


def per_day_morning(rows: list[dict], clock_key: str) -> list[dict]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in morning_slice(rows, clock_key):
        dt = to_et(row[clock_key])
        by_day[dt.date().isoformat()].append(row)
    days = []
    for day in sorted(by_day):
        stats = cluster_stats(by_day[day], clock_key)
        rec = {"day_et": day, "n": stats["n"]}
        for minutes in (1, 5, 15, 60):
            win = stats["windows"].get(str(minutes)) or {}
            rec[f"max_{minutes}"] = win.get("max") or 0
            rec[f"ge2_{minutes}"] = win.get("n_buckets_ge2") or 0
            rec[f"share_ge2_{minutes}"] = win.get("share_in_ge2") or 0
            top = (win.get("top") or [{}])[0]
            rec[f"peak_{minutes}"] = top.get("bucket") or ""
            rec[f"peak_n_{minutes}"] = top.get("n") or 0
        days.append(rec)
    return days


def typical_morning_summary(days: list[dict]) -> dict:
    if not days:
        return {"n_days": 0}
    keys = ["n", "max_1", "max_5", "max_15", "max_60"]
    out = {"n_days": len(days), "days_used": [d["day_et"] for d in days]}
    for key in keys:
        vals = [int(d.get(key) or 0) for d in days]
        out[f"mean_{key}"] = round(sum(vals) / len(vals), 2)
        out[f"max_{key}"] = max(vals)
        out[f"min_{key}"] = min(vals)
    worst = max(days, key=lambda d: (d.get("max_1") or 0, d.get("n") or 0))
    out["worst_day"] = worst.get("day_et")
    out["worst_max_1"] = worst.get("max_1")
    out["worst_n"] = worst.get("n")
    return out


def has_vs(title: str) -> bool:
    return bool(re.search(r"\s+vs\.?\s+", title or "", re.I))


def is_table_tennis(title: str) -> bool:
    low = (title or "").lower()
    return "table-tennis" in low or "table tennis" in low or "tabletennis" in low


def is_prop_title(title: str) -> bool:
    low = (title or "").lower()
    return any(marker in low for marker in PROP_MARKERS)


def is_itp_phrasing(title: str) -> bool:
    low = (title or "").lower()
    return "upcoming tennis event" in low or "upcoming atp" in low or "upcoming wta" in low or "upcoming atpdb" in low


def is_tennis_moneyline_title(title: str) -> bool:
    if not has_vs(title):
        return False
    if is_table_tennis(title):
        return False
    if is_prop_title(title) and not is_itp_phrasing(title):
        return False
    return True


def kalshi_ml_series(ticker: str) -> bool:
    text = str(ticker or "").upper()
    return any(text.startswith(series) or f"-{series}-" in text or series in text.split("-")[0:1] or text.startswith(series) for series in KALSHI_ML_SERIES)


def as_clock_row(game: str, dt: datetime, source: str, extra: dict | None = None) -> dict:
    rec = {
        "game": game,
        "game_n": game_norm(game),
        "clock": to_et(dt),
        "clock_text": to_et(dt).isoformat(),
        "source": source,
        "preferred": to_et(dt),
        "preferred_source": source,
        "listed": to_et(dt) if "listed" in source or source in ("catalog_listed", "open_books", "twins") else None,
        "listed_source": source if "listed" in source or source in ("catalog_listed", "open_books", "twins") else "",
    }
    if extra:
        rec.update(extra)
    return rec


def load_occurrence_tennis() -> list[dict]:
    """Kalshi tennis moneyline occurrence — unique matches, earliest clock."""
    settlements = load_settlements()
    best: dict[str, dict] = {}
    for row in settlements:
        if str(row.get("sport") or "").lower() != "tennis":
            continue
        mtype = str(row.get("market_type") or "").lower()
        if mtype not in ("moneyline", "winner", "match", ""):
            continue
        game = row.get("game") or ""
        if not is_tennis_moneyline_title(game) and " vs " not in game_norm(game):
            continue
        occ = row.get("occurrence") or ""
        if not is_clocked_start(occ):
            continue
        dt = parse_dt(occ)
        if dt is None:
            continue
        rec = as_clock_row(game, dt, "occurrence", {"venue": row.get("venue") or "Kalshi"})
        rec["listed"] = None
        rec["listed_source"] = ""
        key = rec["game_n"]
        prev = best.get(key)
        if prev is None or rec["clock"] < prev["clock"]:
            best[key] = rec
    print(f"occurrence tennis moneyline unique {len(best)}", flush=True)
    return list(best.values())


def load_catalog_tennis() -> tuple[list[dict], list[dict]]:
    """Polymarket tennis two-way moneylines. Split ITF-phrasing vs named. Drop table tennis."""
    catalog = load_catalog()
    named: dict[str, dict] = {}
    itp: dict[str, dict] = {}
    for row in catalog:
        game = row.get("game") or row.get("event_title") or ""
        if is_table_tennis(game) or not has_vs(game):
            continue
        raw = row.get("start") or ""
        if not is_clocked_start(raw):
            continue
        dt = parse_dt(raw)
        if dt is None:
            continue
        rec = as_clock_row(game, dt, "catalog_listed", {"venue": "catalog", "ticker": row.get("kalshi_ticker") or ""})
        rec["listed"] = rec["clock"]
        rec["listed_source"] = "catalog_listed"
        bag = itp if is_itp_phrasing(game) else named
        prev = bag.get(rec["game_n"])
        if prev is None or rec["clock"] < prev["clock"]:
            bag[rec["game_n"]] = rec
    print(f"catalog named {len(named)} itp-phrasing {len(itp)}", flush=True)
    return list(named.values()), list(itp.values())


def load_json_matches(path: Path, source: str) -> list[dict]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    matches = []
    if isinstance(payload, dict):
        matches = payload.get("matches") or payload.get("games") or []
    elif isinstance(payload, list):
        matches = payload
    rows = []
    for rec in matches:
        if not isinstance(rec, dict):
            continue
        title = rec.get("title") or rec.get("event_title") or rec.get("game") or ""
        ticker = str(rec.get("event_ticker") or rec.get("series") or rec.get("ticker") or "")
        if is_table_tennis(title) or is_prop_title(title):
            continue
        if not has_vs(title) and not kalshi_ml_series(ticker):
            continue
        listed = match_listed_start(rec)
        if listed is None:
            continue
        extra = {
            "venue": source,
            "ticker": ticker,
            "series": rec.get("series") or "",
            "fetched_at": "",
        }
        row = as_clock_row(title, listed, source, extra)
        row["listed"] = row["clock"]
        row["listed_source"] = source
        rows.append(row)
    best: dict[str, dict] = {}
    for row in rows:
        prev = best.get(row["game_n"])
        if prev is None or row["clock"] < prev["clock"]:
            best[row["game_n"]] = row
    print(f"{source} clocked unique {len(best)} from {path.name}", flush=True)
    return list(best.values())


def load_snapshot_starts() -> list[dict]:
    path = RAW / "odds_snapshots.jsonl"
    if not path.is_file():
        return []
    best: dict[str, dict] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(rec.get("sport") or "").lower() != "tennis":
                continue
            game = rec.get("game") or ""
            raw = rec.get("start") or ""
            if not is_tennis_moneyline_title(game) or not is_clocked_start(raw):
                continue
            dt = parse_dt(raw)
            if dt is None:
                continue
            src = str(rec.get("start_source") or "snapshot")
            row = as_clock_row(game, dt, src, {"venue": rec.get("venue") or ""})
            if src == "occurrence":
                row["listed"] = None
            else:
                row["listed"] = row["clock"]
                row["listed_source"] = src
            prev = best.get(row["game_n"])
            if prev is None or row["clock"] < prev["clock"]:
                best[row["game_n"]] = row
    print(f"odds_snapshots tennis unique {len(best)}", flush=True)
    return list(best.values())


def merge_occurrence_and_listed(occurrence: list[dict], listed: list[dict]) -> list[dict]:
    """Occurrence wins when both exist. Used for ATP-style clocks, not ITF session dumps."""
    by_occ = {r["game_n"]: r for r in occurrence}
    by_lis = {r["game_n"]: r for r in listed}
    out = []
    for key in set(by_occ) | set(by_lis):
        occ = by_occ.get(key)
        lis = by_lis.get(key)
        if occ is not None:
            rec = dict(occ)
            rec["preferred"] = rec["clock"]
            rec["preferred_source"] = "occurrence"
            if lis is not None:
                rec["listed"] = lis["clock"]
                rec["listed_source"] = lis.get("source") or ""
                delta_min = (lis["clock"] - occ["clock"]).total_seconds() / 60.0
                rec["listed_minus_occ_min"] = round(delta_min, 1)
                rec["listed_stale_vs_occ"] = "yes" if abs(delta_min) >= 20 else "no"
            out.append(rec)
        elif lis is not None:
            rec = dict(lis)
            rec["preferred"] = rec["clock"]
            rec["preferred_source"] = rec.get("source") or "listed"
            rec["listed"] = rec["clock"]
            out.append(rec)
    return out


def is_tape_artifact(dt: datetime) -> bool:
    dt = to_et(dt)
    return abs((dt - TAPE_FIRST).total_seconds()) <= 120


def trusted_t0_rows(rows: list[dict]) -> list[dict]:
    """Drop collection-start pile-up. Keep occurrence / listed/feed T0."""
    out = []
    for row in rows:
        if is_tape_artifact(row["t0"]):
            continue
        src = str(row.get("actual_source") or "")
        if src in ("occurrence", "listed/feed"):
            out.append(row)
    return out


def load_decade_starts() -> list[dict]:
    if not DECADE_HTML.is_file():
        return []
    text = DECADE_HTML.read_text(encoding="utf-8", errors="replace")
    out = []
    for headers, rows in parse_tables(text):
        i_start = col_index(headers, "start")
        i_game = col_index(headers, "match")
        if i_start is None or i_game is None:
            continue
        for cells in rows:
            if i_start >= len(cells):
                continue
            raw = cells[i_start]
            if not is_clocked_start(raw):
                continue
            dt = parse_dt(raw)
            if dt is None:
                continue
            game = cells[i_game]
            out.append({
                "game": game,
                "game_n": game_norm(game),
                "clock": to_et(dt),
                "clock_text": raw,
                "source": "decade_html_start",
                "venue": "decade",
            })
    best: dict[str, dict] = {}
    for row in out:
        prev = best.get(row["game_n"])
        if prev is None or row["clock"] < prev["clock"]:
            best[row["game_n"]] = row
    return list(best.values())


def load_live_health_keys() -> list[dict]:
    if not LIVE_HEALTH.is_dir():
        return []
    rows = []
    for path in sorted(LIVE_HEALTH.glob("tennis_*.json")):
        name = path.stem  # tennis_bonpau_2026_10_21
        parts = name.split("_")
        day = ""
        if len(parts) >= 4 and parts[-3].isdigit():
            day = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rec = {}
        rows.append({
            "key": rec.get("key") or name,
            "game": rec.get("game") or "",
            "day": day,
            "started_at": rec.get("started_at") or "",
            "updated_at": rec.get("updated_at") or "",
            "path_mtime": datetime.fromtimestamp(path.stat().st_mtime, ET).isoformat(),
        })
    return rows


def remaining_slate(preferred: list[dict], now: datetime) -> dict:
    future = []
    past = []
    unknown = 0
    for row in preferred:
        clock = row.get("preferred") or row.get("clock")
        if clock is None:
            unknown += 1
            continue
        clock = to_et(clock)
        rec = dict(row)
        rec["preferred"] = clock
        rec["minutes_ahead"] = round((clock - now).total_seconds() / 60.0, 1)
        if clock > now:
            future.append(rec)
        else:
            past.append(rec)
    future.sort(key=lambda r: r["preferred"])
    next_1h = [r for r in future if r["preferred"] <= now + timedelta(hours=1)]
    next_3h = [r for r in future if r["preferred"] <= now + timedelta(hours=3)]
    next_12h = [r for r in future if r["preferred"] <= now + timedelta(hours=12)]
    return {
        "now": now.isoformat(),
        "n_clocked": len(preferred),
        "n_future": len(future),
        "n_past": len(past),
        "n_unknown": unknown,
        "next_1h": next_1h,
        "next_3h": next_3h,
        "next_12h": next_12h,
        "next_1h_n": len(next_1h),
        "next_3h_n": len(next_3h),
        "next_12h_n": len(next_12h),
        "future_preview": [
            {
                "game": r.get("game") or r.get("game_n"),
                "clock": r["preferred"].isoformat(),
                "source": r.get("preferred_source") or r.get("source") or "",
                "minutes_ahead": r["minutes_ahead"],
            }
            for r in future[:40]
        ],
        "next_1h_rows": [
            {
                "game": r.get("game") or r.get("game_n"),
                "clock": r["preferred"].isoformat(),
                "source": r.get("preferred_source") or r.get("source") or "",
                "minutes_ahead": r["minutes_ahead"],
            }
            for r in next_1h
        ],
        "next_3h_rows": [
            {
                "game": r.get("game") or r.get("game_n"),
                "clock": r["preferred"].isoformat(),
                "source": r.get("preferred_source") or r.get("source") or "",
                "minutes_ahead": r["minutes_ahead"],
            }
            for r in next_3h
        ],
    }


def fmt_pct(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)


def window_rows(stats: dict, label: str) -> list[dict]:
    rows = []
    names = {"1": "same minute", "5": "same 5 min", "15": "same 15 min", "60": "same hour"}
    for minutes, name in names.items():
        win = (stats.get("windows") or {}).get(minutes) or {}
        rows.append({
            "universe": label,
            "window": name,
            "n": stats.get("n") or 0,
            "max": win.get("max") or 0,
            "mean": win.get("mean") or 0,
            "buckets": win.get("n_buckets") or 0,
            "ge2": win.get("n_buckets_ge2") or 0,
            "ge3": win.get("n_buckets_ge3") or 0,
            "ge5": win.get("n_buckets_ge5") or 0,
            "share_ge2": fmt_pct(win.get("share_in_ge2")),
            "n_in_ge2": win.get("n_matches_in_ge2") or 0,
        })
    return rows


def top_cluster_rows(stats: dict, minutes: int, cap: int = 12) -> list[dict]:
    win = (stats.get("windows") or {}).get(str(minutes)) or {}
    rows = []
    for rec in (win.get("top") or [])[:cap]:
        rows.append({
            "bucket": rec.get("bucket") or "",
            "n": rec.get("n") or 0,
            "window": f"{minutes} min" if minutes < 60 else "hour",
        })
    return rows


def recommend_cap(listed_morn: dict, t0_morn: dict, listed_all: dict, t0_all: dict, remaining: dict) -> tuple[str, str, str]:
    """Return (cap, headline, detail). Concrete. Research only."""
    listed_max_min = ((listed_morn.get("windows") or {}).get("1") or {}).get("max") or 0
    t0_max_min = ((t0_morn.get("windows") or {}).get("1") or {}).get("max") or 0
    listed_max_5 = ((listed_morn.get("windows") or {}).get("5") or {}).get("max") or 0
    t0_max_5 = ((t0_morn.get("windows") or {}).get("5") or {}).get("max") or 0
    listed_all_min = ((listed_all.get("windows") or {}).get("1") or {}).get("max") or 0
    t0_all_min = ((t0_all.get("windows") or {}).get("1") or {}).get("max") or 0
    next_1h = remaining.get("next_1h_n") or 0
    next_3h = remaining.get("next_3h_n") or 0

    # Dual-Yes ~$1.00–$1.20 per unique match. Cap is unique matches, not venues.
    cost_lo, cost_hi = 1.00, 1.20
    cap = "1"
    if t0_max_min <= 1 and t0_max_5 <= 2 and listed_max_min <= 3:
        cap = "2"
    # Listed clocks bunch harder than actual T0. Live-wire that keys off listed
    # start (or a session :00) can still fire several dual-Yes at once even when
    # true first-ball is staggered. Paul asked not to burst at one clock → cap 1.
    if listed_max_min >= 4 or listed_max_5 >= 5 or t0_max_min >= 3:
        cap = "1"
    if next_1h >= 4:
        cap = "1"

    headline = (
        f"Recommend max_open_b_matches = {cap}. "
        f"Each dual-Yes is about ${cost_lo:.2f}–${cost_hi:.2f} for two contracts, so cap {cap} "
        f"locks at most about ${cost_lo * int(cap):.2f}–${cost_hi * int(cap):.2f} at one clock."
    )
    detail = (
        f"ATP morning listed same-minute max {listed_max_min}; same-5-min max {listed_max_5}. "
        f"Dense actual-T0 morning same-minute max {t0_max_min}; same-5-min max {t0_max_5}. "
        f"All-hours listed same-minute max {listed_all_min}; dense T0 same-minute max {t0_all_min}. "
        f"Remaining open-book listed clocks in the next 1 hour: {next_1h}; next 3 hours: {next_3h}. "
        f"Cap 3 would allow a ${3 * cost_lo:.2f}–${3 * cost_hi:.2f} burst if three moneylines "
        f"share a listed :00 — that is the failure mode this cap is for. Cap 2 is only safe if "
        f"the live-wire waits for actual T0 on the tape (not the listed session clock) and still "
        f"refuses a third. Cap 1 is the one that cannot double-fire at one clock."
    )
    return cap, headline, detail


def write_html(payload: dict) -> None:
    listed_rows = window_rows(payload["listed_all"], "Kalshi tennis moneyline occurrence, unique matches, all hours")
    listed_morn_rows = window_rows(payload["listed_morn"], "Kalshi occurrence, unique matches, ATP morning 04:00–11:59 ET")
    itp_rows = window_rows(payload["itp_all"], "Catalog ITF-phrasing tennis moneylines (session :00), all hours")
    open_rows = window_rows(payload["open_all"], "Open books cache (ATP/Challenger/WTA twins + extras), listed start")
    t0_book_rows = window_rows(payload["t0_books"], "Dense actual T0, 182 books (venue duplicates kept)")
    t0_match_rows = window_rows(payload["t0_matches"], "Dense actual T0, unique matches (earliest venue T0), raw")
    t0_trust_rows = window_rows(payload["t0_trusted"], "Dense actual T0, unique matches, trusted (occurrence or listed/feed; drop tape-start artifact)")
    t0_morn_rows = window_rows(payload["t0_morn"], "Dense trusted T0, unique matches, ATP morning 04:00–11:59 ET")
    day_rows = []
    for d in payload["listed_days"]:
        day_rows.append({
            "day": d["day_et"],
            "clock": "Kalshi occurrence",
            "n": d["n"],
            "max_1": d["max_1"],
            "max_5": d["max_5"],
            "max_15": d["max_15"],
            "max_60": d["max_60"],
            "peak_1": d.get("peak_1") or "",
            "peak_n_1": d.get("peak_n_1") or 0,
        })
    for d in payload["t0_days"]:
        day_rows.append({
            "day": d["day_et"],
            "clock": "dense trusted T0",
            "n": d["n"],
            "max_1": d["max_1"],
            "max_5": d["max_5"],
            "max_15": d["max_15"],
            "max_60": d["max_60"],
            "peak_1": d.get("peak_1") or "",
            "peak_n_1": d.get("peak_n_1") or 0,
        })
    hour_rows = payload["hour_rows"]
    remain_1 = payload["remaining"]["next_1h_rows"]
    remain_3 = payload["remaining"]["next_3h_rows"]
    live_rows = payload["live_today"]
    cap = payload["cap"]
    cap_head = payload["cap_head"]
    cap_detail = payload["cap_detail"]
    typ = payload["listed_typical"]
    typ_t0 = payload["t0_typical"]
    stale_n = payload["stale_n"]
    stale_share = payload["stale_share"]
    n_listed = payload["listed_all"].get("n") or 0
    n_t0_books = payload["t0_books"].get("n") or 0
    n_t0_matches = payload["t0_matches"].get("n") or 0
    n_dense_stale = payload["n_dense_stale"]
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tennis T0 start clusters 2026-10-21</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; max-width: none; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
h3 {{ font-size: 1.05rem; margin-top: 1.2rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.hl {{ background: #fef9c3; padding: 10px 12px; border: 1px solid #eab308; margin: 12px 0; }}
.warn {{ background: #fef2f2; padding: 10px 12px; border: 1px solid #f87171; margin: 12px 0; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Tennis start clusters — dual-Yes burst risk</h1>
<p class="note">Written {esc(payload['written_at'])}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Short October 2026 tape (about 18–21 Oct). No in-sample / out-of-sample split.</p>

<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<p><strong>Answer:</strong> Yes — listed and Kalshi occurrence clocks bunch. A typical Association of Tennis Professionals (ATP) morning on this tape (Kalshi tennis moneyline occurrence, Eastern Time 04:00–11:59) has mean {esc(typ.get('mean_n'))} unique moneylines, mean same-minute max {esc(typ.get('mean_max_1'))}, worst same-minute max {esc(typ.get('max_max_1'))} (worst day {esc(typ.get('worst_day'))}, {esc(typ.get('worst_n'))} morning matches). Trusted dense actual T0 bunches less: morning mean same-minute max {esc(typ_t0.get('mean_max_1'))}, worst {esc(typ_t0.get('max_max_1'))}. International Tennis Federation (ITF) session books on the Polymarket catalog can list 60–80 moneylines at one :00 — that is not the ATP twin desk, but it is what happens if strategy B is wired to every tennis moneyline. Listed vs occurrence ≥20 minutes apart: {esc(stale_n)} of {esc(payload['n_occ_listed'])} matched names ({esc(stale_share)}%).</p>
<p><strong>Cap:</strong> {esc(cap_head)}</p>
<p>Annualized rate of return (Ann ROR) is omitted. These are same-day tennis contracts. We do not have closed-trade days held, so the house Ann ROR formula is not computed.</p>
</div>

<div class="warn">
<p>{esc(cap_detail)} Research only. Not gold. Not DailyRun. Do not wire from this page alone.</p>
</div>

<h2>Freeze</h2>
<ul>
<li>Dense actual T0: parsed from <code>dense_inplay_yes_dip_20261021.html</code> per-match table (182-book freeze). Books with a clocked T0: {esc(n_t0_books)}. Unique matches: {esc(n_t0_matches)}. Trusted unique matches (occurrence or listed/feed, dropping the 2026-10-18 16:12 ET collection-start pile-up): {esc(payload['t0_trusted'].get('n'))}. Clock hid the listed start on {esc(n_dense_stale)} dense books.</li>
<li>Primary listed clock: Kalshi tennis moneyline occurrence, unique matches {esc(n_listed)}. Date-only labels dropped. This is not futures, not set markets, not table tennis, not college football.</li>
<li>ITF session catalog (Polymarket “upcoming tennis event” phrasing) is a separate universe. Those listed :00 clocks can print dozens of moneylines at once. Strategy B on ATP/Challenger/WTA twins should not silently include them.</li>
<li>ATP morning: Eastern Time hour 04:00 through 11:59. European indoor first session in late October (11:00 Central European Summer Time ≈ 05:00 ET). Days on tape: {esc(', '.join(typ.get('days_used') or []))}.</li>
<li>Live remaining: open-books cache <code>tennis_all_books.json</code> clocks strictly after write time {esc(payload['remaining'].get('now'))}. Poller <code>live_health</code> <code>started_at</code> is when the poller process started, not first ball — it is not used as T0.</li>
<li>This page does not read or write orders, secrets, <code>ORDERS_ENABLED</code>, or <code>orders_stopped.json</code>.</li>
</ul>
<p>Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}

<h2>1. Cluster sizes — listed vs actual T0</h2>
<p class="note">Unique match = one tennis moneyline, not one venue. Strategy B fires once per match. Same-minute / 5 / 15 / hour are floor buckets in Eastern Time. Share in ≥2 is the percent of matches that sit in a bucket that has at least one other match.</p>
{table(
    [("Universe", "text"), ("Window", "text"), ("N matches or books", "num"),
     ("Max in one bucket", "num"), ("Mean bucket size", "num"), ("N buckets", "num"),
     ("Buckets with ≥2", "num"), ("Buckets with ≥3", "num"), ("Buckets with ≥5", "num"),
     ("Share of matches in a ≥2 bucket %", "num"), ("N matches in a ≥2 bucket", "num")],
    listed_rows + listed_morn_rows + t0_trust_rows + t0_morn_rows + t0_match_rows + t0_book_rows + open_rows + itp_rows,
    ["universe", "window", "n", "max", "mean", "buckets", "ge2", "ge3", "ge5", "share_ge2", "n_in_ge2"],
)}

<h2>2. Typical ATP morning, by Eastern day</h2>
<p class="note">One row per Eastern calendar day in the 04:00–11:59 window. Max columns are the largest number of unique matches sharing that floor bucket on that morning. Click column headers to sort.</p>
{table(
    [("Day ET", "date"), ("Clock", "text"), ("N morning matches", "num"),
     ("Max same minute", "num"), ("Max same 5 min", "num"), ("Max same 15 min", "num"),
     ("Max same hour", "num"), ("Peak same-minute bucket", "text"), ("Peak bucket N", "num")],
    day_rows,
    ["day", "clock", "n", "max_1", "max_5", "max_15", "max_60", "peak_1", "peak_n_1"],
)}
<p class="note">Kalshi occurrence typical morning (mean across {esc(typ.get('n_days'))} days): N {esc(typ.get('mean_n'))}, same-minute max {esc(typ.get('mean_max_1'))} (range {esc(typ.get('min_max_1'))}–{esc(typ.get('max_max_1'))}), same-5-min max {esc(typ.get('mean_max_5'))}, same-15-min max {esc(typ.get('mean_max_15'))}, same-hour max {esc(typ.get('mean_max_60'))}.</p>
<p class="note">Dense trusted T0 typical morning (mean across {esc(typ_t0.get('n_days'))} days): N {esc(typ_t0.get('mean_n'))}, same-minute max {esc(typ_t0.get('mean_max_1'))} (range {esc(typ_t0.get('min_max_1'))}–{esc(typ_t0.get('max_max_1'))}), same-5-min max {esc(typ_t0.get('mean_max_5'))}, same-15-min max {esc(typ_t0.get('mean_max_15'))}, same-hour max {esc(typ_t0.get('mean_max_60'))}.</p>

<h2>3. Largest Kalshi occurrence clusters (same minute)</h2>
{table(
    [("Bucket ET", "date"), ("Unique matches", "num"), ("Window", "text")],
    top_cluster_rows(payload["listed_all"], 1) + top_cluster_rows(payload["listed_morn"], 1),
    ["bucket", "n", "window"],
)}

<h2>4. Largest dense trusted-T0 clusters (same minute)</h2>
<p class="note">Unique matches, earliest venue T0, occurrence or listed/feed only. The raw 22-match pile at 2026-10-18 16:12 ET is the first quote on this tape, not 22 first balls — it is excluded here. This is the better clock for a live-wire that waits for the tape, not the listed session :00.</p>
{table(
    [("Bucket ET", "date"), ("Unique matches", "num"), ("Window", "text")],
    top_cluster_rows(payload["t0_trusted"], 1) + top_cluster_rows(payload["t0_morn"], 1),
    ["bucket", "n", "window"],
)}

<h2>4b. ITF catalog session :00 (do not mix into ATP twins)</h2>
<p class="note">Polymarket catalog rows whose title is “Who will win in the upcoming tennis event …”. These are real listed clocks, but they are session-start dumps, not the Kalshi ATP/Challenger/WTA twin desk.</p>
{table(
    [("Bucket ET", "date"), ("Unique matches", "num"), ("Window", "text")],
    top_cluster_rows(payload["itp_all"], 1),
    ["bucket", "n", "window"],
)}

<h2>5. Hour-of-day histogram (unique matches)</h2>
<p class="note">Eastern Time hour of the Kalshi tennis moneyline occurrence clock, and of dense trusted T0. ATP morning is 04–11.</p>
{table(
    [("Hour ET", "num"), ("Kalshi occurrence N", "num"), ("Dense trusted T0 N", "num")],
    hour_rows,
    ["hour", "listed_n", "t0_n"],
)}

<h2>6. Today remaining — not-yet-started clocks</h2>
<p class="note">Write time {esc(payload['remaining'].get('now'))}. Universe is <code>tennis_all_books.json</code> (open ATP/Challenger/WTA moneylines the poller can quote), unique match, clocked listed start still in the future. Listed can be stale; a past listed start is not counted here even if the match has not actually begun. Date-only starts are excluded (not a clock).</p>
<p class="hl"><strong>Next 1 hour:</strong> {esc(payload['remaining'].get('next_1h_n'))} unique tennis moneylines could T0 by listed clock on the open-books cache (all tennis the poller can quote, including doubles and lower-level). <strong>Next 3 hours:</strong> {esc(payload['remaining'].get('next_3h_n'))}. <strong>Next 12 hours:</strong> {esc(payload['remaining'].get('next_12h_n'))}. Kalshi–Polymarket twins only: next 1 hour {esc(payload['remaining'].get('twins_next_1h_n'))}, next 3 hours {esc(payload['remaining'].get('twins_next_3h_n'))}, future {esc(payload['remaining'].get('twins_future'))}. Future clocked total (open books) {esc(payload['remaining'].get('n_future'))}; already-past listed on that open cache {esc(payload['remaining'].get('n_past'))}.</p>
<h3>Next 1 hour</h3>
{table(
    [("Match", "text"), ("Preferred clock ET", "date"), ("Source", "text"), ("Minutes ahead", "num")],
    remain_1,
    ["game", "clock", "source", "minutes_ahead"],
)}
<h3>Next 3 hours</h3>
{table(
    [("Match", "text"), ("Preferred clock ET", "date"), ("Source", "text"), ("Minutes ahead", "num")],
    remain_3,
    ["game", "clock", "source", "minutes_ahead"],
)}
<h3>Kalshi–Polymarket twins, next 3 hours</h3>
<p class="note">Tighter desk: only books in <code>polymarket_tennis_matches.json</code> (ATP/Challenger twins). If strategy B is twins-only, use this count, not the full open-books 19.</p>
{table(
    [("Match", "text"), ("Preferred clock ET", "date"), ("Source", "text"), ("Minutes ahead", "num")],
    payload["remaining"].get("twins_3h_rows") or [],
    ["game", "clock", "source", "minutes_ahead"],
)}

<h2>7. Currently polled tennis (live_health)</h2>
<p class="note">Filenames under <code>local/.../raw/live_health/</code> for 2026-10-21 and 2026-10-22. <code>started_at</code> is poller start, not first ball. Useful as “what the desk is already watching,” not as T0. N today+tomorrow files: {esc(payload.get('n_live_today') or len(live_rows))}. Table is the 40 most recently updated.</p>
{table(
    [("Key", "text"), ("Game", "text"), ("Day", "date"), ("Poller started_at", "date"), ("Updated", "date")],
    live_rows,
    ["key", "game", "day", "started_at", "updated_at"],
)}

<h2>8. Cap math</h2>
<p>Dual-Yes = two contracts, about $1.00–$1.20 cash out the door per unique match (C from the dense freeze sits in [0.95, 1.20]; T0-only mean on that page was about −1.5 cents, so a typical C is about $1.015).</p>
<ul>
<li><strong>Cap 1:</strong> at most ~$1.00–$1.20 open in strategy B at one time. Cannot burst. Recommended.</li>
<li><strong>Cap 2:</strong> at most ~$2.00–$2.40. Only if the live-wire keys off actual T0 on the tape (dense same-minute max in the morning was {esc(((payload['t0_morn'].get('windows') or {}).get('1') or {}).get('max'))}), not the listed session clock (listed morning same-minute max {esc(((payload['listed_morn'].get('windows') or {}).get('1') or {}).get('max'))}).</li>
<li><strong>Cap 3:</strong> at most ~$3.00–$3.60. Not recommended on this tape — listed same-hour morning max is {esc(((payload['listed_morn'].get('windows') or {}).get('60') or {}).get('max'))}, and a session :00 can print several moneylines at once.</li>
</ul>
<p class="note">Acronyms: T0 is match open / first trusted actual start. ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. C is the sum of the two Yes prices. ET is Eastern Time. CEST is Central European Summer Time.</p>

{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")


def main() -> None:
    now = datetime.now(ET)
    print("loading dense T0 from freeze HTML", flush=True)
    dense = load_dense_t0()
    n_dense_stale = sum(1 for r in dense if str(r.get("listed_stale") or "").lower().startswith("y"))
    t0_books = cluster_stats(dense, "t0")
    t0_matches_rows = unique_match_clocks(dense, "t0")
    t0_matches = cluster_stats(t0_matches_rows, "t0")
    t0_trusted_rows = unique_match_clocks(trusted_t0_rows(dense), "t0")
    t0_trusted = cluster_stats(t0_trusted_rows, "t0")
    t0_morn_rows = morning_slice(t0_trusted_rows, "t0")
    t0_morn = cluster_stats(t0_morn_rows, "t0")
    t0_days = per_day_morning(t0_trusted_rows, "t0")
    t0_typical = typical_morning_summary(t0_days)
    print(
        f"dense T0 books {len(dense)} unique {len(t0_matches_rows)} "
        f"trusted {len(t0_trusted_rows)} stale-listed {n_dense_stale}",
        flush=True,
    )

    print("loading occurrence / catalog / open books", flush=True)
    occurrence = load_occurrence_tennis()
    catalog_named, catalog_itp = load_catalog_tennis()
    open_books = load_json_matches(ALL_BOOKS, "open_books")
    twins = load_json_matches(TENNIS_TWINS, "twins")
    snapshots = load_snapshot_starts()
    # ATP-style listed: occurrence plus named catalog / open books / snapshots, not ITF phrasing.
    listed_atp = merge_occurrence_and_listed(
        occurrence,
        catalog_named + open_books + twins + [r for r in snapshots if r.get("listed") is not None],
    )
    both = [r for r in listed_atp if r.get("listed") is not None and r.get("preferred_source") == "occurrence"]
    stale_n = sum(1 for r in both if r.get("listed_stale_vs_occ") == "yes")
    stale_share = round(100.0 * stale_n / len(both), 1) if both else 0.0

    occ_unique = unique_match_clocks(occurrence, "clock")
    listed_all = cluster_stats(occ_unique, "clock")
    listed_morn_rows = morning_slice(occ_unique, "clock")
    listed_morn = cluster_stats(listed_morn_rows, "clock")
    listed_days = per_day_morning(occ_unique, "clock")
    listed_typical = typical_morning_summary(listed_days)
    itp_all = cluster_stats(unique_match_clocks(catalog_itp, "clock"), "clock")
    open_all = cluster_stats(unique_match_clocks(open_books, "clock"), "clock")
    print(
        f"occurrence unique {listed_all.get('n')} morning {listed_morn.get('n')} "
        f"itp {itp_all.get('n')} open_books {open_all.get('n')} "
        f"both {len(both)} stale>=20min {stale_n}",
        flush=True,
    )

    remaining = remaining_slate(open_books, now)
    remaining_twins = remaining_slate(twins, now)
    remaining["twins_next_1h_n"] = remaining_twins["next_1h_n"]
    remaining["twins_next_3h_n"] = remaining_twins["next_3h_n"]
    remaining["twins_future"] = remaining_twins["n_future"]
    remaining["twins_1h_rows"] = remaining_twins["next_1h_rows"]
    remaining["twins_3h_rows"] = remaining_twins["next_3h_rows"]
    print(
        f"remaining next1h {remaining['next_1h_n']} next3h {remaining['next_3h_n']} "
        f"future {remaining['n_future']}; twins next1h {remaining_twins['next_1h_n']} "
        f"next3h {remaining_twins['next_3h_n']}",
        flush=True,
    )

    live_all = load_live_health_keys()
    live_today = [
        r for r in live_all
        if str(r.get("day") or "").startswith("2026-10-21")
        or str(r.get("day") or "").startswith("2026-10-22")
    ]
    live_today.sort(key=lambda r: (r.get("updated_at") or r.get("path_mtime") or ""), reverse=True)
    n_live_today = len(live_today)
    live_today = live_today[:40]
    print(f"live_health today+tomorrow {n_live_today}", flush=True)

    listed_hour = {int(r["hour_et"]): r["n"] for r in listed_all.get("hour_hist") or []}
    t0_hour = {int(r["hour_et"]): r["n"] for r in t0_trusted.get("hour_hist") or []}
    hour_rows = []
    for h in range(24):
        if listed_hour.get(h) or t0_hour.get(h):
            hour_rows.append({
                "hour": h,
                "listed_n": listed_hour.get(h) or 0,
                "t0_n": t0_hour.get(h) or 0,
            })

    cap, cap_head, cap_detail = recommend_cap(
        listed_morn, t0_morn, listed_all, t0_trusted, remaining
    )
    print(f"CAP {cap}", flush=True)
    print(cap_head, flush=True)
    print(cap_detail, flush=True)

    payload = {
        "written_at": iso_now(),
        "listed_all": listed_all,
        "listed_morn": listed_morn,
        "listed_days": listed_days,
        "listed_typical": listed_typical,
        "itp_all": itp_all,
        "open_all": open_all,
        "t0_books": t0_books,
        "t0_matches": t0_matches,
        "t0_trusted": t0_trusted,
        "t0_morn": t0_morn,
        "t0_days": t0_days,
        "t0_typical": t0_typical,
        "hour_rows": hour_rows,
        "remaining": remaining,
        "live_today": live_today,
        "n_live_today": n_live_today,
        "cap": cap,
        "cap_head": cap_head,
        "cap_detail": cap_detail,
        "stale_n": stale_n,
        "stale_share": stale_share,
        "n_occ_listed": len(both),
        "n_dense_stale": n_dense_stale,
    }
    write_html(payload)
    copy_g(PAGE)
    print(f"wrote {PAGE}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
