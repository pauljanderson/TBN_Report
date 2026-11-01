"""Polymarket tennis: No ROI when the opener Yes print is 90% or higher.

Research only. Reads the price_memory tape and official settlements.
Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Does not restart jobs.
Does not take price_memory.lock (read-only scan of the jsonl).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from odds_cross_no_roi_60_70_20261020 import (
    SLICE_FIELDS,
    SLICE_HEADERS,
    annotate_crosses,
    as_float,
    backfill_starts,
    copy_g,
    esc,
    fmt_px,
    fmt_signed_pct,
    pct,
    summarize,
    summary_row,
    table,
    tiny_note,
    trade_from,
)
from odds_cross_winrate_20261020 import (
    SETTLE_CACHE,
    STAMP,
    _games_overlap,
    attach_results,
    build_index,
    game_norm,
    parse_dt,
)
from polymarket_us_live import CACHE as TENNIS_TWINS, two_way_moneyline
from prediction_paths import RAW_DIR as RAW
from price_memory import HISTORY, iter_tick_lines, load_last, to_et
PAGE = STAMP / "polymarket_tennis_no_90plus_20261020.html"
JSON_OUT = RAW / "polymarket_tennis_no_90plus_20261020.json"
CSV_OUT = RAW / "polymarket_tennis_no_90plus_20261020.csv"
UPCOMING_CSV = RAW / "polymarket_tennis_no_90plus_upcoming_20261020.csv"
ET = ZoneInfo("America/New_York")
POLY_MARKETS = RAW / "polymarket_us_markets.jsonl"

ASKED = (
    "track the following historically. what if we buy a No to a tennis player whose first print "
    "is in 90+ band on polymarket? what would our return be? and can you then show me upcoming "
    "matches where the first print is 90+"
)
PLAIN = (
    "A Polymarket Yes price is a dollar from 0 to 1, also read as an implied chance: 0.90 means "
    "the venue is pricing that named tennis player at 90 percent to win the match (moneyline: "
    "who wins). We take the first stored Yes quote we ever saw for that player on Polymarket US "
    "— the opener, not a later climb. If that opener sits in the 90+ band (90 cents or more, "
    "and below a full dollar so a No can be priced), we buy No on that same player. No costs "
    "one dollar minus the opener Yes. If that player loses the match, No pays a dollar. If that "
    "player wins, No pays nothing and the one-dollar stake is gone. Return on investment (ROI) "
    "is the average of those trade-by-trade returns. Official win or loss prefers a Polymarket "
    "resolved 0/1 price; when Polymarket has no result, the same match on Kalshi or Gemini is "
    "used only when labeled same-game. A last print at 99 cents is not counted as a win. "
    "Upcoming rows are matches not yet settled whose stored opener is already 90+. Research "
    "only. Not gold. Not DailyRun. Not a trading rule."
)
THRESHOLD = 0.90


def load_settlements() -> list[dict]:
    if not SETTLE_CACHE.is_file():
        raise FileNotFoundError(SETTLE_CACHE)
    rows = json.loads(SETTLE_CACHE.read_text(encoding="utf-8"))
    extra = load_poly_tennis_resolutions()
    if extra:
        rows = list(rows) + extra
    return rows


def _poly_result_from_market(rec: dict) -> str | None:
    status = str(rec.get("status") or "") + " " + str(rec.get("ep3Status") or "")
    closed = rec.get("closed") is True
    settled = closed or "SETTLED" in status.upper() or "RESOLVED" in status.upper()
    prices = rec.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except json.JSONDecodeError:
            prices = None
    outcomes = rec.get("outcomes")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = None
    result = None
    if isinstance(prices, list) and isinstance(outcomes, list) and len(prices) == len(outcomes):
        mapped = {str(o).lower(): as_float(p) for o, p in zip(outcomes, prices)}
        yes = mapped.get("yes")
        if yes is not None and yes >= 0.99:
            result = "yes"
        elif yes is not None and yes <= 0.01:
            result = "no"
    if result is None:
        return None
    if not settled:
        # Rank/futures 0.01 quotes are not match resolutions.
        return None
    return result


def load_poly_tennis_resolutions() -> list[dict]:
    """Polymarket US tennis moneylines that already resolved 0/1 in the local dump."""
    out: list[dict] = []
    if not POLY_MARKETS.is_file():
        return out
    with POLY_MARKETS.open("r", encoding="utf-8") as handle:
        for line in handle:
            if "tennis" not in line.lower() and "atp-" not in line.lower() and "wta-" not in line.lower():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            parsed = two_way_moneyline(rec)
            if parsed is None:
                continue
            result = _poly_result_from_market(rec)
            if result is None:
                continue
            game = rec.get("event_title") or rec.get("question") or rec.get("title") or ""
            for side, side_result in (
                (parsed["long_name"], result),
                (parsed["short_name"], "no" if result == "yes" else "yes"),
            ):
                if not side:
                    continue
                out.append({
                    "source": "polymarket_local",
                    "venue": "Polymarket",
                    "venue_n": "Polymarket",
                    "sport": "tennis",
                    "game": game,
                    "game_n": game_norm(str(game)),
                    "market_type": "moneyline",
                    "side": side,
                    "side_n": game_norm(side),
                    "number": "",
                    "number_n": "",
                    "result": side_result,
                    "ticker": parsed.get("slug") or rec.get("slug") or "",
                    "occurrence": rec.get("gameStartTime") or rec.get("endDate") or "",
                })
    print(f"polymarket tennis resolved 0/1 rows {len(out)}", flush=True)
    return out


def stream_poly_tennis_openers() -> dict:
    """First Yes print per Polymarket tennis moneyline player from price_memory.jsonl."""
    print("streaming polymarket tennis openers (archive + shards)", flush=True)
    openers: dict[str, dict] = {}
    last_map: dict[str, dict] = {}
    n_lines = 0
    n_hits = 0
    n_yes_1 = 0
    seen_min = None
    seen_max = None
    for line in iter_tick_lines(sport="tennis"):
            n_lines += 1
            if n_lines % 400000 == 0:
                print(f"  {n_lines} lines, tennis poly keys {len(openers)}", flush=True)
            if "Polymarket" not in line or "tennis" not in line:
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
            if str(rec.get("venue") or "") != "Polymarket":
                continue
            if str(rec.get("sport") or "").lower() != "tennis":
                continue
            if str(rec.get("market_type") or "") != "moneyline":
                continue
            if str(rec.get("pay") or "yes").lower() != "yes":
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
            n_hits += 1
            prev_last = last_map.get(key)
            last_map[key] = {
                "price": rec.get("price"),
                "seen_at": seen,
                "sport": rec.get("sport") or "tennis",
                "game": rec.get("game") or "",
                "market_type": "moneyline",
                "side": rec.get("side") or rec.get("side_label") or "",
                "number": "",
                "venue": "Polymarket",
                "pay": "yes",
                "game_start": rec.get("game_start") or (prev_last or {}).get("game_start") or "",
            }
            if price >= 1.0:
                n_yes_1 += 1
                st = openers.get(key)
                if st is None:
                    openers[key] = {
                        "key": key,
                        "sport": "tennis",
                        "game": rec.get("game") or "",
                        "market_type": "moneyline",
                        "side": rec.get("side") or rec.get("side_label") or "",
                        "side_key": rec.get("side_key") or "",
                        "number": "",
                        "venue": "Polymarket",
                        "first_tick_price": price,
                        "first_tick_time": seen,
                        "first_tick_was_1": True,
                        "first_above": None,
                        "cross_time": "",
                        "game_start": rec.get("game_start") or "",
                        "band": "1.00",
                        "defn": "opener",
                    }
                continue
            if price <= 0.0:
                continue
            st = openers.get(key)
            if st is None:
                band = "90–99" if price >= THRESHOLD else "below-90"
                openers[key] = {
                    "key": key,
                    "sport": "tennis",
                    "game": rec.get("game") or "",
                    "market_type": "moneyline",
                    "side": rec.get("side") or rec.get("side_label") or "",
                    "side_key": rec.get("side_key") or "",
                    "number": "",
                    "venue": "Polymarket",
                    "first_tick_price": price,
                    "first_tick_time": seen,
                    "first_tick_was_1": False,
                    "first_above": price,
                    "cross_time": seen,
                    "game_start": rec.get("game_start") or "",
                    "band": band,
                    "defn": "opener",
                    "phase_feed": rec.get("phase") or "",
                }
                continue
            if st.get("first_above") is None:
                st["first_above"] = price
                st["cross_time"] = seen
                st["band"] = "90–99" if price >= THRESHOLD else "below-90"
                if rec.get("game_start") and not st.get("game_start"):
                    st["game_start"] = rec.get("game_start") or ""
            elif rec.get("game_start") and not st.get("game_start"):
                st["game_start"] = rec.get("game_start") or ""
    print(
        f"stream done lines={n_lines} tennis_poly_yes={n_hits} keys={len(openers)} "
        f"ticks_at_1={n_yes_1} seen {seen_min} .. {seen_max}",
        flush=True,
    )
    return {
        "n_lines": n_lines,
        "n_hits": n_hits,
        "n_keys": len(openers),
        "n_yes_1_ticks": n_yes_1,
        "seen_min": seen_min or "",
        "seen_max": seen_max or "",
        "openers": list(openers.values()),
        "last_map": last_map,
    }


def overlay_price_last(last_map: dict[str, dict]) -> dict[str, dict]:
    try:
        stored = load_last()
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        return last_map
    for key, row in stored.items():
        if not isinstance(row, dict):
            continue
        if str(row.get("venue") or "") != "Polymarket":
            continue
        if str(row.get("sport") or "").lower() != "tennis":
            continue
        if str(row.get("pay") or "yes").lower() != "yes":
            continue
        if str(row.get("market_type") or "") not in ("moneyline", ""):
            continue
        prev = last_map.get(key) or {}
        merged = dict(prev)
        merged.update({
            "price": row.get("price"),
            "seen_at": row.get("seen_at") or prev.get("seen_at") or "",
            "sport": "tennis",
            "game": row.get("game") or prev.get("game") or "",
            "market_type": "moneyline",
            "side": row.get("side") or prev.get("side") or "",
            "number": "",
            "venue": "Polymarket",
            "pay": "yes",
            "game_start": row.get("game_start") or prev.get("game_start") or "",
        })
        last_map[key] = merged
    return last_map


def settle_bucket(source: str) -> str:
    text = (source or "").lower()
    if "same-game" in text:
        return "same-game"
    if "polymarket" in text:
        return "polymarket"
    if source:
        return "other"
    return ""


def load_catalog() -> list[dict]:
    """Local Polymarket tennis moneylines: Kalshi-twin cache plus US markets dump."""
    rows: list[dict] = []
    seen_slugs: set[str] = set()
    if TENNIS_TWINS.is_file():
        try:
            payload = json.loads(TENNIS_TWINS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        fetched = payload.get("fetched_at") or ""
        for match in payload.get("matches") or []:
            if not isinstance(match, dict):
                continue
            slug = str(match.get("slug") or "")
            if slug:
                seen_slugs.add(slug)
            title = match.get("event_title") or match.get("title") or ""
            rows.append({
                "source": "kalshi_twin_cache",
                "fetched_at": fetched,
                "slug": slug,
                "game": match.get("title") or title,
                "event_title": title,
                "long_name": match.get("long_name") or "",
                "short_name": match.get("short_name") or "",
                "start": match.get("date") or "",
                "date": match.get("date") or "",
                "kalshi_ticker": match.get("event_ticker") or "",
            })
    if POLY_MARKETS.is_file():
        with POLY_MARKETS.open("r", encoding="utf-8") as handle:
            for line in handle:
                if "tennis" not in line.lower() and "atp-" not in line.lower() and "wta-" not in line.lower():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                parsed = two_way_moneyline(rec)
                if parsed is None:
                    continue
                slug = parsed.get("slug") or rec.get("slug") or ""
                if slug and slug in seen_slugs:
                    continue
                if slug:
                    seen_slugs.add(str(slug))
                title = rec.get("event_title") or rec.get("question") or rec.get("title") or ""
                if "/" in str(title):
                    continue
                rows.append({
                    "source": "polymarket_us_markets.jsonl",
                    "fetched_at": rec.get("updatedAt") or rec.get("ep3SyncedAt") or "",
                    "slug": slug,
                    "game": title,
                    "event_title": title,
                    "long_name": parsed.get("long_name") or "",
                    "short_name": parsed.get("short_name") or "",
                    "start": rec.get("gameStartTime") or rec.get("startDate") or rec.get("endDate") or "",
                    "date": "",
                    "kalshi_ticker": "",
                    "status": rec.get("status") or rec.get("ep3Status") or "",
                    "closed": rec.get("closed"),
                })
    print(f"catalog rows {len(rows)}", flush=True)
    return rows


def _split_vs(title: str) -> list[str]:
    import re
    return [part.strip() for part in re.split(r"\s+vs\.?\s+", title or "", maxsplit=1) if part.strip()]


def catalog_for_game(game: str, catalog: list[dict]) -> dict | None:
    g = game_norm(game)
    if not g:
        return None
    for row in catalog:
        titles = [row.get("game") or "", row.get("event_title") or ""]
        if any(game_norm(t) == g for t in titles if t):
            return row
        for t in titles:
            if t and _games_overlap(g, game_norm(t)):
                return row
    return None


def instrument_for(row: dict, catalog: list[dict]) -> str:
    hit = catalog_for_game(row.get("game") or "", catalog)
    if not hit:
        return ""
    slug = hit.get("slug") or ""
    ticker = hit.get("kalshi_ticker") or ""
    if slug and ticker:
        return f"{slug} / {ticker}"
    return slug or ticker


def both_sides_90(rows: list[dict]) -> set[str]:
    by_game: dict[str, int] = defaultdict(int)
    for row in rows:
        by_game[row.get("game") or ""] += 1
    return {game for game, n in by_game.items() if n >= 2}


def current_from_last(key: str, last_map: dict) -> tuple[float | None, str]:
    rec = last_map.get(key) or {}
    return as_float(rec.get("price")), rec.get("seen_at") or ""


def is_settled_trade(row: dict) -> bool:
    return row.get("official") in ("win", "loss")


def start_status(start: str, now: datetime) -> str:
    text = (start or "").strip()
    today = to_et(now).date()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            day = datetime.fromisoformat(text).date()
        except ValueError:
            day = None
        if day is not None:
            if day > today:
                return "listed start not yet"
            if day == today:
                return "listed today / may be live"
            return "listed start already passed; still unsettled"
    parsed = parse_dt(text)
    if parsed is None:
        return "start unknown"
    start_et = to_et(parsed)
    now_et = to_et(now)
    if start_et.date() > today:
        return "listed start not yet"
    if start_et > now_et:
        return "listed start not yet"
    return "already started / still unsettled"


def upcoming_rows(openers_90: list[dict], last_map: dict, catalog: list[dict], now: datetime) -> list[dict]:
    out = []
    for row in openers_90:
        if is_settled_trade(row):
            continue
        cur_px, cur_seen = current_from_last(row.get("key") or "", last_map)
        first_px = as_float(row.get("first_above"))
        start = row.get("game_start") or ""
        hit = catalog_for_game(row.get("game") or "", catalog)
        if hit and not start:
            start = hit.get("start") or hit.get("date") or ""
        different = (
            cur_px is not None
            and first_px is not None
            and abs(cur_px - first_px) >= 0.00005
        )
        out.append({
            "game": row.get("game") or "",
            "side": row.get("side") or "",
            "first_px": fmt_px(first_px),
            "first_time": row.get("cross_time") or "",
            "current_px": fmt_px(cur_px) if different else "",
            "current_same": "" if different else ("same as first print" if cur_px is not None else ""),
            "current_raw": fmt_px(cur_px),
            "current_seen": cur_seen,
            "start": start,
            "status": start_status(start, now),
            "instrument": instrument_for(row, catalog),
            "official": row.get("official") or "pending",
        })
    rank = {
        "listed start not yet": 0,
        "listed today / may be live": 1,
        "already started / still unsettled": 2,
        "listed start already passed; still unsettled": 3,
        "start unknown": 4,
    }
    out.sort(key=lambda r: (
        rank.get(r.get("status") or "", 9),
        r.get("start") or "zzz",
        r.get("game") or "",
        r.get("side") or "",
    ))
    return out


def current_only_90(openers: list[dict], last_map: dict, catalog: list[dict], opener_90_keys: set[str]) -> list[dict]:
    """Current Yes ≥ 0.90 where we do not have a stored 90+ opener."""
    opener_by_key = {r.get("key"): r for r in openers}
    settled_games = {
        r.get("game") for r in openers if is_settled_trade(r)
    }
    out = []
    seen = set()
    for key, rec in last_map.items():
        if key in opener_90_keys:
            continue
        px = as_float(rec.get("price"))
        if px is None or px < THRESHOLD or px >= 1.0:
            continue
        game = rec.get("game") or ""
        if game in settled_games:
            continue
        opener = opener_by_key.get(key) or {}
        first_px = as_float(opener.get("first_above"))
        if first_px is not None and first_px >= THRESHOLD and first_px < 1.0:
            continue
        if is_settled_trade(opener):
            continue
        ident = (game, rec.get("side") or "")
        if ident in seen:
            continue
        seen.add(ident)
        start = rec.get("game_start") or opener.get("game_start") or ""
        hit = catalog_for_game(game, catalog)
        if hit and not start:
            start = hit.get("start") or hit.get("date") or ""
        out.append({
            "game": game,
            "side": rec.get("side") or "",
            "current_px": fmt_px(px),
            "current_seen": rec.get("seen_at") or "",
            "first_px": fmt_px(first_px) if first_px is not None else "(no stored first print)",
            "start": start,
            "instrument": instrument_for({"game": game}, catalog),
            "note": "current price, not a stored first print",
        })
    out.sort(key=lambda r: (r.get("start") or "zzz", r.get("game") or "", r.get("side") or ""))
    return out


def proxy_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        if row.get("official") in ("win", "loss"):
            continue
        if row.get("proxy") not in ("win", "loss"):
            continue
        out.append({
            "game": row.get("game") or "",
            "side": row.get("side") or "",
            "first_px": fmt_px(row.get("first_above")),
            "last_px": fmt_px(row.get("last_price")),
            "last_seen": row.get("last_seen") or "",
            "proxy": row.get("proxy") or "",
            "note": "last-print 99c/1c proxy only; not used in ROI",
        })
    return out


def write_html(
    main: dict,
    tight: dict,
    trades: list[dict],
    upcoming: list[dict],
    current_only: list[dict],
    proxy: list[dict],
    counts: dict,
    meta: dict,
    now: str,
) -> None:
    settled = [t for t in trades if t.get("official") in ("win", "loss") and t.get("roi") is not None]
    detail = []
    for row in sorted(settled, key=lambda r: r.get("cross_time") or "", reverse=True):
        detail.append({
            "game": row["game"],
            "side": row["side"],
            "first_px": fmt_px(row["yes_price_at_cross"]),
            "no_cost": fmt_px(row["no_cost"]),
            "cross_time": row["cross_time"],
            "game_start": row["game_start"],
            "official": row["official"],
            "no_result": row["no_result"],
            "roi_pct": fmt_signed_pct(row["roi"]),
            "pnl": f"{row['pnl_1_stake']:+.4f}" if row.get("pnl_1_stake") is not None else "",
            "source": row["official_source"],
            "bucket": settle_bucket(row.get("official_source") or ""),
            "wide": "both sides 90+" if row.get("wide_book") else "",
        })
    n = main["n"]
    headline_roi = fmt_signed_pct(main["avg_roi"])
    headline_med = fmt_signed_pct(main.get("median_roi"))
    no_wr = pct(main["no_wins"], n)
    mean_cost = f"{main['mean_no_cost']:.4f}" if main["mean_no_cost"] is not None else "n/a"
    total_pnl = f"{main['total_pnl_1_stake']:+.2f}" if main["total_pnl_1_stake"] is not None else "n/a"
    unique_games = main.get("unique_games") or 0
    arith = (
        "90+ band for ROI is 0.90 ≤ opener Yes < 1.00. A first print of exactly 1.00 is counted "
        "separately and is not a No (cost would be 0). One row per player on Polymarket US. "
        "No cost = 1 − opener_yes. Equal stake $1: if that player loses, ROI = (1 / no_cost) − 1; "
        "if that player wins, ROI = −1. Average ROI is the mean of those per-trade returns. "
        "Median is the middle trade. Total dollars with $1 No each is the sum of those ROIs."
    )
    pending_hist = [
        {
            "game": t.get("game") or "",
            "side": t.get("side") or "",
            "first_px": fmt_px(t.get("yes_price_at_cross")),
            "no_cost": fmt_px(t.get("no_cost")),
            "cross_time": t.get("cross_time") or "",
            "source": t.get("official_source") or "pending",
        }
        for t in trades if t.get("official") == "pending"
    ]
    upcoming_headers = [
        ("Match", "text"), ("Player", "text"), ("First print Yes", "num"),
        ("First print time", "date"), ("Current Yes if different", "num"),
        ("Start", "date"), ("Status", "text"), ("Venue instrument", "text"),
    ]
    upcoming_fields = ["game", "side", "first_px", "first_time", "current_px", "start", "status", "instrument"]
    n_upcoming_future = sum(1 for r in upcoming if r.get("status") == "listed start not yet")
    n_upcoming_matches = len({r.get("game") for r in upcoming})
    n_upcoming_future_matches = len({
        r.get("game") for r in upcoming if r.get("status") == "listed start not yet"
    })
    current_headers = [
        ("Match", "text"), ("Player", "text"), ("Current Yes", "num"),
        ("Current time", "date"), ("Stored first print", "text"),
        ("Start", "date"), ("Venue instrument", "text"), ("Note", "text"),
    ]
    current_fields = ["game", "side", "current_px", "current_seen", "first_px", "start", "instrument", "note"]

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polymarket tennis: No on a 90+ opener</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; max-width: none; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.hl {{ background: #fef9c3; padding: 10px 12px; border: 1px solid #eab308; margin: 12px 0; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Buying No on a Polymarket tennis player whose first print is 90+</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Tape is Polymarket US tennis moneyline Yes quotes in <code>price_memory.jsonl</code> (about 17–20 Oct 2026, plus whatever is in memory now). Kalshi is not substituted for a missing Polymarket opener.</p>
<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Definition</h2>
<ul>
<li><strong>Event:</strong> tennis moneyline (player wins the match) on Polymarket US only. Opener = first stored Yes print of that player’s series. If Polymarket has no first print, that player is not in the historical book (N stays 0; we do not borrow a Kalshi opener).</li>
<li><strong>90+ band:</strong> primary ROI uses <em>0.90 ≤ opener Yes &lt; 1.00</em>. Including exactly 1.00 would add {counts['n_opener_1']} first ticks that are not a tradable No (cost 0). Those are left out of ROI.</li>
<li><strong>Bet:</strong> buy No on that same player at no_cost = 1 − opener_yes. Equal $1 stake.</li>
<li><strong>Payoff:</strong> {esc(arith)}</li>
<li><strong>Settlements:</strong> prefer Polymarket resolved 0/1. This tape has <strong>N_poly = {counts['n_poly']}</strong> settled from Polymarket 0/1 and <strong>N_samegame = {counts['n_samegame']}</strong> settled from a same-game Kalshi/Gemini official result. Last print ≥ 0.99 is not a win; those rows sit in a labeled proxy table only.</li>
<li><strong>Fees:</strong> not subtracted.</li>
</ul>
<p class="note">Acronyms: ROI is return on investment. ATP is Association of Tennis Professionals. WTA is Women’s Tennis Association. US here means Polymarket US (polymarket.us), not the international book.</p>

<div class="hl">
<p><strong>Headline, Polymarket tennis moneyline opener Yes ≥ 0.90 and &lt; 1.00, buy No, $1 stake, no fees:</strong>
N = {n} settled rows ({unique_games} unique matches), No win rate {esc(no_wr)}% ({main['no_wins']} No wins / {n} settled),
average ROI {esc(headline_roi)}%, median ROI {esc(headline_med)}%, mean No cost {esc(mean_cost)},
total $ if $1 No each {esc(total_pnl)}. {esc(main['note'] or '')}</p>
<p>Settlement mix on those {n} rows: Polymarket 0/1 {counts['n_poly']}; same-game Kalshi/Gemini {counts['n_samegame']}; other {counts['n_other']}. Pending (excluded from ROI): {counts['n_pending']}. Unsettled 90+ first prints: {counts['n_upcoming']} player-rows ({n_upcoming_matches} matches), of which {n_upcoming_future} still have a listed start in the future ({n_upcoming_future_matches} matches). {esc(counts.get('wide_note') or '')} Research only. Not gold.</p>
</div>

<p>More meaningful than first print: tennis moneyline win rate by decade at match start and 24 hours before (not first print). See <a href="tennis_decade_at_start_20261020.html">Tennis odds at start</a>.</p>
<h2>Sample and honesty</h2>
<p>Short tape: first tennis Polymarket Yes quote {esc(meta.get('seen_min') or '')}, last {esc(meta.get('seen_max') or '')}. Almost every print is after 2024-01-01, so there is no in-sample / out-of-sample split to report. If N is small, do not read this as a trading rule. Nothing here is KEEP, gold, or DailyRun.</p>
<p>Polymarket US tennis moneyline players with any stored Yes opener: {counts['n_openers']}. Of those, first tradable print in 90+ (0.90 ≤ p &lt; 1.00): {counts['n_90']}. First stored tick exactly 1.00 and no later tradable print: {counts['n_opener_1']}. Wide-book both-sides: on a single two-player instrument the long Yes is the ask and the short Yes is one minus the bid, so a 0.02 / 0.98 book can print <em>both</em> players at 0.98 on the first snapshot. The formula still uses no_cost = 1 − opener_yes. Those rows are in the primary book and flagged; a companion drops any match where both players opened 90+.</p>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>

<h2>Arithmetic (quoted)</h2>
<p>{esc(arith)} Example: opener Yes is 0.92, so No costs 0.08. If that player loses, ROI = (1 / 0.08) − 1 = +1150%. If that player wins, ROI = −100%.</p>

<h2>Primary slice: Polymarket tennis opener 90+, buy No</h2>
{table(SLICE_HEADERS, [summary_row(main)], SLICE_FIELDS)}

<h2>Companion: drop matches where both players opened 90+</h2>
<p class="note">Same bet, but skip the wide first snapshot (both named players in the 90+ band). This is closer to “a true favorite opened at 90+.”</p>
{table(SLICE_HEADERS, [summary_row(tight)], SLICE_FIELDS)}

<h2>Upcoming matches whose stored first print is 90+</h2>
<p class="note">Not yet settled on this tape. First stored Polymarket Yes for that player is ≥ 0.90 and &lt; 1.00. Current Yes is shown only when it differs from the opener. Instrument is the Polymarket US slug and, when we have a Kalshi twin, that ticker. Rows with a listed start still in the future are the ones that have not begun; earlier dates are in-progress or finished-but-unsettled (no official 0/1 yet). This is not a live order list.</p>
{table(upcoming_headers, upcoming, upcoming_fields)}

<h2>Current 90+, no stored 90+ first print</h2>
<p class="note">Separate from the first-print table. These players are ≥ 0.90 on the latest websocket / price_last quote, but we do not have a stored opener in the 90+ band (missing first print, or the opener was below 90). Do not mix this into the historical ROI.</p>
{table(current_headers, current_only, current_fields)}

<h2>Proxy only (not in ROI)</h2>
<p class="note">Last Yes print ≥ 0.99 or ≤ 0.01, no official settlement yet. Shown so a 99-cent last print is not silently treated as a win.</p>
{table(
    [("Match", "text"), ("Player", "text"), ("Opener Yes", "num"), ("Last Yes", "num"),
     ("Last seen", "date"), ("Proxy", "text"), ("Note", "text")],
    proxy,
    ["game", "side", "first_px", "last_px", "last_seen", "proxy", "note"],
)}

<h2>Pending 90+ openers (historical book, no official result yet)</h2>
{table(
    [("Match", "text"), ("Player", "text"), ("Opener Yes", "num"), ("No cost", "num"),
     ("First print time", "date"), ("Source", "text")],
    pending_hist,
    ["game", "side", "first_px", "no_cost", "cross_time", "source"],
)}

<h2>Event rows (primary slice, settled only)</h2>
<p class="note">Official win means the named player won (No lost). Official loss means the named player lost (No won). Source <code>same-game</code> is Kalshi or Gemini for the same match, not a Polymarket 0/1.</p>
{table(
    [
        ("Match", "text"), ("Player", "text"), ("Opener Yes", "num"), ("No cost", "num"),
        ("First print time", "date"), ("Start", "date"),
        ("Official (Yes side)", "text"), ("No result", "text"), ("ROI %", "num"),
        ("$ PnL ($1 No)", "num"), ("Official source", "text"), ("Settlement", "text"),
        ("Wide book", "text"),
    ],
    detail,
    [
        "game", "side", "first_px", "no_cost", "cross_time", "game_start",
        "official", "no_result", "roi_pct", "pnl", "source", "bucket", "wide",
    ],
)}

<p class="note">Rows saved as <code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw/polymarket_tennis_no_90plus_20261020.csv</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def main() -> None:
    now = datetime.now(ET).isoformat()
    stream = stream_poly_tennis_openers()
    last_map = overlay_price_last(dict(stream["last_map"]))
    openers = list(stream["openers"])
    settlements = load_settlements()
    index = build_index(settlements)
    attach_results(openers, last_map, settlements, index)
    for row in openers:
        row["start_source"] = "feed" if row.get("game_start") else ""
    backfill_starts(openers, settlements)
    annotate_crosses(openers)

    n_opener_1 = sum(
        1 for r in openers
        if r.get("first_tick_was_1") and r.get("first_above") is None
    )
    rows_90 = [
        r for r in openers
        if (as_float(r.get("first_above")) is not None)
        and as_float(r["first_above"]) >= THRESHOLD
        and as_float(r["first_above"]) < 1.0
    ]
    wide_games = both_sides_90(rows_90)
    for row in rows_90:
        row["wide_book"] = (row.get("game") or "") in wide_games
    tight_rows = [r for r in rows_90 if not r.get("wide_book")]

    trades = []
    for row in rows_90:
        trade = trade_from(row)
        if not trade:
            continue
        trade["wide_book"] = bool(row.get("wide_book"))
        trade["official_source"] = row.get("official_source") or ""
        trades.append(trade)
    for trade in trades:
        trade["settle_bucket"] = settle_bucket(trade.get("official_source") or "")

    settled = [t for t in trades if t.get("official") in ("win", "loss") and t.get("roi") is not None]
    n_poly = sum(1 for t in settled if t.get("settle_bucket") == "polymarket")
    n_same = sum(1 for t in settled if t.get("settle_bucket") == "same-game")
    n_other = sum(1 for t in settled if t.get("settle_bucket") == "other")
    n_pending = sum(1 for t in trades if t.get("official") == "pending")

    main_sum = summarize(trades, "Polymarket tennis opener 90+, buy No")
    tight_sum = summarize(trades_of_rows(tight_rows), "Same, drop both-sides 90+ openers")

    catalog = load_catalog()
    upcoming = upcoming_rows(rows_90, last_map, catalog, datetime.now(ET))
    n_upcoming_future = sum(1 for r in upcoming if r.get("status") == "listed start not yet")
    opener_90_keys = {r.get("key") for r in rows_90}
    current_only = current_only_90(openers, last_map, catalog, opener_90_keys)
    proxy = proxy_rows(rows_90)

    wide_n = sum(1 for t in settled if t.get("wide_book"))
    counts = {
        "n_openers": len(openers),
        "n_90": len(rows_90),
        "n_opener_1": n_opener_1,
        "n_poly": n_poly,
        "n_samegame": n_same,
        "n_other": n_other,
        "n_pending": n_pending,
        "n_upcoming": len(upcoming),
        "n_upcoming_future": n_upcoming_future,
        "n_upcoming_matches": len({r.get("game") for r in upcoming}),
        "n_current_only": len(current_only),
        "n_proxy": len(proxy),
        "n_wide_settled": wide_n,
        "wide_note": (
            f"{wide_n} of {len(settled)} settled rows are matches where both players opened 90+ "
            f"({len(wide_games)} such matches in the 90+ opener set)."
        ),
    }
    meta = {
        "seen_min": stream.get("seen_min") or "",
        "seen_max": stream.get("seen_max") or "",
        "n_lines": stream.get("n_lines"),
        "n_hits": stream.get("n_hits"),
        "n_keys": stream.get("n_keys"),
        "settle_total": len(settlements),
        "poly_settle_rows": sum(1 for r in settlements if str(r.get("venue") or "") == "Polymarket"),
        "kalshi_tennis": sum(
            1 for r in settlements
            if str(r.get("venue") or "") == "Kalshi" and str(r.get("sport") or "").lower() == "tennis"
        ),
    }

    payload = {
        "written_at": now,
        "asked": ASKED,
        "threshold": "0.90 <= opener_yes < 1.00",
        "including_1_00": "counted separately, excluded from ROI",
        "arithmetic": (
            "no_cost = 1 - opener_yes; if player loses: ROI = (1 / no_cost) - 1; "
            "if player wins: ROI = -1; $1 stake"
        ),
        "counts": counts,
        "meta": meta,
        "primary": {k: v for k, v in main_sum.items() if k not in ("by_sport", "by_venue")},
        "tight": {k: v for k, v in tight_sum.items() if k not in ("by_sport", "by_venue")},
        "upcoming": upcoming,
        "current_only_90": current_only,
        "trades": trades,
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {JSON_OUT}", flush=True)

    if trades:
        fieldnames = list(trades[0].keys())
        with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trades)
        print(f"wrote {CSV_OUT}", flush=True)
    if upcoming:
        with UPCOMING_CSV.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(upcoming[0].keys()))
            writer.writeheader()
            writer.writerows(upcoming)
        print(f"wrote {UPCOMING_CSV}", flush=True)

    write_html(main_sum, tight_sum, trades, upcoming, current_only, proxy, counts, meta, now)
    copy_g(PAGE)

    print(
        f"PRIMARY N={main_sum['n']} unique={main_sum.get('unique_games')} "
        f"no_wr={main_sum['no_win_rate']} avg_roi={main_sum['avg_roi']} "
        f"median_roi={main_sum.get('median_roi')} mean_no_cost={main_sum['mean_no_cost']} "
        f"N_poly={n_poly} N_samegame={n_same} upcoming={len(upcoming)} current_only={len(current_only)}",
        flush=True,
    )


def trades_of_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        trade = trade_from(row)
        if trade:
            trade["wide_book"] = bool(row.get("wide_book"))
            out.append(trade)
    return out


if __name__ == "__main__":
    main()
