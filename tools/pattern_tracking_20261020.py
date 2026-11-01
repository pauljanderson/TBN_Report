"""Research tracking dashboard: leftover watch, jump-fade, stale ask, T-2h transition.

Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json or one_leg_watch.json except read.
Does not write odds_snapshots.jsonl (sibling collector owns that file).
Not gold. Not DailyRun.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras
from odds_cross_no_roi_60_70_20261020 import copy_g
from odds_cross_winrate_20261020 import (
    DECADE_LABELS,
    as_float,
    attach_results,
    build_index,
    decade_label,
    parse_dt,
    pct,
    table,
    tiny_note,
)
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from tennis_decade_at_start_20261020 import (
    ASKED_TRACK,
    overlay_last,
    snapshot_for,
    start_lookup_from,
    stream_tennis_ticks,
    is_clocked_start,
    prefer_start,
    transition_4049,
    named_hypotheses,
)
from odds_cross_winrate_20261020 import game_norm
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW
from price_memory import to_et
PAGE = STAMP / "pattern_tracking_20261020.html"
ONE_LEG_PAGE = STAMP / "one_leg_20s_watch_20261021.html"
OLD_ONE_LEG_PAGE = STAMP / "one_leg_minute_watch_20261020.html"
JUMP_FADE = RAW / "jump_fade.jsonl"
LEFTOVER_LIVE = RAW / "leftover_watch_stats.jsonl"
SEND_LIVE = RAW / "send_quote_age.jsonl"
SNAPSHOTS = RAW / "odds_snapshots.jsonl"
ORDERS = RAW / "orders.jsonl"
ORDER_IO = RAW / "order_io.jsonl"
SUPERVISOR = RAW / "live_supervisor.log"
ONE_LEG_WATCH = RAW / "one_leg_watch.json"
ONE_LEG_ALERTS = RAW / "one_leg_alerts.jsonl"
DECADE_CSV = RAW / "tennis_decade_at_start_20261020.csv"
DECADE_JSON = RAW / "tennis_decade_at_start_20261020.json"
ET = ZoneInfo("America/New_York")

ASKED = ASKED_TRACK
PLAIN = (
    "These are count-and-wait trackers, not trading rules. After we fill one side of a two-sided "
    "lock, we already watch the leftover opposite about every 20 seconds on all venues, including "
    "the origin. This page adds how often that leftover "
    "became cheap enough to try, how often the try filled, how often the game ended first, and how "
    "often we were still watching at 60 minutes. Jump-then-fade watches a named side that was under "
    "60 cents, then first printed over 70 cents between 15 and 60 minutes after listed start: if "
    "that side later won, the jump KEPT; if it lost, it GAVE BACK. That is a scoreboard, not a No-buy "
    "recipe. Stale-ask tracking logs how old the quote was when we sent, the book size at that price, "
    "and whether the immediate-or-cancel filled zero — Nagal’s Kalshi send was about 1.3 seconds "
    "old with advertised size 2 and filled 0. T−2h means two hours before scheduled match start. "
    "The 40–49 underdog table follows that same player to their start-time decade to see whether "
    "late money lifted them, faded them, or left them. Hypotheses stay HOLD until N is large. "
    "Research only. Not gold. Not DailyRun."
)


def esc(value) -> str:
    import html as html_mod
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                rows.append(rec)
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def parse_ts(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", ""))
    except Exception:
        return None


def age_bucket(lag) -> str:
    try:
        seconds = float(lag)
    except (TypeError, ValueError):
        return "unknown"
    if seconds < 0.5:
        return "<0.5s"
    if seconds <= 2:
        return "0.5–2s"
    return ">2s"


def fill_qty_from_io(row: dict) -> Decimal:
    payload = row.get("response")
    if not isinstance(payload, dict):
        return Decimal("0")
    for key in ("fill_count", "filledQuantity", "filled_quantity", "cumQuantity"):
        number = dec(payload.get(key))
        if number is not None:
            return number
    status = str(payload.get("status") or "").lower()
    if status == "filled":
        return Decimal("1")
    best = Decimal("0")
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, item in node.items():
                folded = str(key).replace("_", "").lower()
                if folded in ("fillcount", "filledquantity", "cumquantity") and dec(item) is not None:
                    best = max(best, dec(item) or Decimal("0"))
                elif isinstance(item, (dict, list)):
                    stack.append(item)
        elif isinstance(node, list):
            stack.extend(node)
    return best


def leftover_from_supervisor() -> list[dict]:
    if not SUPERVISOR.is_file():
        return []
    rows = []
    send_re = re.compile(
        r"order watch send venue=(?P<venue>\S+) instrument=(?P<instrument>\S+) "
        r"ask=(?P<ask>\S+) max=(?P<max>\S+)"
    )
    skip_re = re.compile(
        r"order watch skip ask=(?P<ask>\S+) max=(?P<max>\S+) venue=(?P<venue>\S+) "
        r"instrument=(?P<instrument>\S+)"
    )
    miss_re = re.compile(r"order watch miss venue=(?P<venue>\S+) instrument=(?P<instrument>\S+)")
    resume_re = re.compile(r"order watch resume (?P<game>.+) missed (?P<venue>\S+) max=(?P<max>\S+)")
    complete_re = re.compile(r"order watch complete (?P<game>.+);")
    stop_re = re.compile(r"order watch stop (?P<reason>.+); latch stays on")
    missing_re = re.compile(r"order watch ask missing venue=(?P<venue>\S+) instrument=(?P<instrument>\S+)")
    with SUPERVISOR.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "order watch " not in line:
                continue
            ts, _, rest = line.strip().partition(" ")
            rec = {"seen_at": ts, "source": "supervisor_log", "raw": rest[:240]}
            m = send_re.search(rest)
            if m:
                rec.update({"event": "buyable_send", "buyable": True, **m.groupdict()})
                rec["max_other_price"] = rec.pop("max", None)
                rows.append(rec)
                continue
            m = skip_re.search(rest)
            if m:
                rec.update({"event": "ask_above_max", "buyable": False, **m.groupdict()})
                rec["max_other_price"] = rec.pop("max", None)
                rows.append(rec)
                continue
            m = miss_re.search(rest)
            if m:
                rec.update({"event": "ioc_miss", "buyable": True, "ioc_filled": False, **m.groupdict()})
                rows.append(rec)
                continue
            m = resume_re.search(rest)
            if m:
                rec.update({"event": "resume", **m.groupdict(), "max_other_price": m.group("max")})
                rows.append(rec)
                continue
            m = complete_re.search(rest)
            if m:
                rec.update({"event": "ioc_filled", "buyable": True, "ioc_filled": True, "game": m.group("game")})
                rows.append(rec)
                continue
            m = stop_re.search(rest)
            if m:
                reason = m.group("reason")
                event = "resolved_first" if "closed" in reason.lower() or "404" in reason else "stop"
                rec.update({"event": event, "buyable": False, "stop_reason": reason})
                rows.append(rec)
                continue
            m = missing_re.search(rest)
            if m:
                rec.update({"event": "ask_missing", "buyable": False, **m.groupdict()})
                rows.append(rec)
    return rows


def leftover_episodes(events: list[dict], alerts: list[dict], watch: dict | None) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in events:
        key = str(row.get("instrument") or row.get("bet_key") or row.get("game") or "unknown")
        groups[key].append(row)
    episodes = []
    for key, rows in groups.items():
        rows = sorted(rows, key=lambda r: str(r.get("seen_at") or ""))
        started = parse_ts(rows[0].get("seen_at"))
        last = parse_ts(rows[-1].get("seen_at"))
        buyable = any(r.get("buyable") or r.get("event") in {"buyable_send", "ioc_filled", "ioc_miss"} for r in rows)
        filled = any(r.get("event") in {"ioc_filled"} or r.get("ioc_filled") for r in rows)
        resolved = any(r.get("event") == "resolved_first" for r in rows)
        hour = False
        if started and last and (last - started).total_seconds() >= 3600:
            hour = True
        if any(r.get("event") == "still_watching_60m" for r in rows):
            hour = True
        still_open = False
        if watch and str(watch.get("missed_instrument") or watch.get("bet_key") or "") in {key, str(watch.get("bet_key") or "")}:
            still_open = not bool(watch.get("stopped"))
            if started is None:
                started = parse_ts(watch.get("started_at"))
            if started and (datetime.now(ET) - started).total_seconds() >= 3600:
                hour = True
        episodes.append({
            "key": key,
            "game": rows[0].get("game") or (watch or {}).get("game") or "",
            "n_ticks": len(rows),
            "became_buyable": buyable,
            "ioc_filled": filled,
            "resolved_first": resolved and not filled,
            "still_watching_60m": hour and not filled and not resolved,
            "still_open": still_open,
            "first_seen": rows[0].get("seen_at") or "",
            "last_seen": rows[-1].get("seen_at") or "",
            "source": "watch_era",
        })
    pre = []
    watch_era_start = parse_ts("2026-10-20T21:30:00-04:00")
    for alert in alerts:
        seen = parse_ts(alert.get("seen_at"))
        if seen is not None and watch_era_start is not None and seen >= watch_era_start:
            continue
        pre.append({
            "key": str(alert.get("contract") or alert.get("game") or ""),
            "game": alert.get("game") or "",
            "n_ticks": 0,
            "became_buyable": False,
            "ioc_filled": False,
            "resolved_first": False,
            "still_watching_60m": False,
            "still_open": False,
            "first_seen": alert.get("seen_at") or "",
            "last_seen": alert.get("seen_at") or "",
            "source": "pre_watch_one_leg",
        })
    watch_eps = episodes
    n = len(watch_eps)
    counts = {
        "watch_episodes": n,
        "became_buyable": sum(1 for e in watch_eps if e["became_buyable"]),
        "ioc_filled": sum(1 for e in watch_eps if e["ioc_filled"]),
        "resolved_first": sum(1 for e in watch_eps if e["resolved_first"]),
        "still_watching_60m": sum(1 for e in watch_eps if e["still_watching_60m"]),
        "still_open": sum(1 for e in watch_eps if e["still_open"]),
        "pre_watch_one_legs": len(pre),
        "note": tiny_note(n),
    }
    return {"counts": counts, "episodes": watch_eps + pre, "events": events}


def quote_age_from_orders() -> list[dict]:
    sent = [r for r in load_jsonl(ORDERS) if r.get("event") == "sent"]
    filled_by = {}
    for row in load_jsonl(ORDERS):
        if row.get("event") != "filled":
            continue
        filled_by[(str(row.get("bet_key") or ""), str(row.get("venue") or ""), str(row.get("instrument") or ""))] = row
    io_orders = [r for r in load_jsonl(ORDER_IO) if r.get("kind") == "order"]
    io_by_id = {}
    for row in io_orders:
        req = row.get("request") if isinstance(row.get("request"), dict) else {}
        oid = ""
        resp = row.get("response") if isinstance(row.get("response"), dict) else {}
        oid = str(resp.get("order_id") or resp.get("orderId") or resp.get("id") or "")
        if oid:
            io_by_id[oid] = row
    live = load_jsonl(SEND_LIVE)
    live_keys = {(str(r.get("sent_at") or ""), str(r.get("venue") or ""), str(r.get("instrument") or "")) for r in live}
    out = list(live)
    for row in sent:
        key = (str(row.get("sent_at") or ""), str(row.get("venue") or ""), str(row.get("instrument") or ""))
        if key in live_keys:
            continue
        if str(row.get("http_status") or "") in {"", "pending"}:
            continue
        oid = str(row.get("order_id") or "")
        io_row = io_by_id.get(oid)
        fill = dec(row.get("fill_qty"))
        if fill is None and io_row is not None:
            fill = fill_qty_from_io(io_row)
        if fill is None:
            filled = filled_by.get((str(row.get("bet_key") or ""), str(row.get("venue") or ""), str(row.get("instrument") or "")))
            fill = dec((filled or {}).get("size") or (filled or {}).get("qty")) if filled else Decimal("0")
        if fill is None:
            fill = Decimal("0")
        lag = row.get("lag_seconds")
        if lag in (None, "") and row.get("quote_seen_at") and row.get("sent_at"):
            a = parse_ts(row.get("quote_seen_at"))
            b = parse_ts(row.get("sent_at"))
            if a and b:
                lag = format(Decimal(str(round((b - a).total_seconds(), 3))), "f")
        size = row.get("quote_size") or ""
        if not size and io_row is not None:
            quote = io_row.get("quote") if isinstance(io_row.get("quote"), dict) else {}
            size = quote.get("quote_size") or io_row.get("quote_size") or ""
        out.append({
            "event": "send_quote_age",
            "venue": row.get("venue") or "",
            "instrument": row.get("instrument") or "",
            "side": row.get("side") or "",
            "bet_key": row.get("bet_key") or "",
            "step": row.get("step") or "",
            "quote_source": row.get("quote_source") or "",
            "quote_price": row.get("quote_price") or row.get("limit_price") or "",
            "quote_seen_at": row.get("quote_seen_at") or "",
            "sent_at": row.get("sent_at") or "",
            "lag_seconds": lag or "",
            "quote_size": size,
            "fill_qty": format(fill, "f"),
            "http_status": row.get("http_status"),
            "source": "orders_jsonl",
        })
    # Nagal documented size 2 when missing.
    for row in out:
        game = str(row.get("bet_key") or "") + " " + str(row.get("instrument") or "")
        if "nagsan" in game.lower() or "NAGSAN" in game:
            if row.get("quote_size") in (None, ""):
                row["quote_size"] = "2"
                row["size_note"] = "nagal yes_size 2 from HTTP compare"
    return out


def summarize_quote_age(rows: list[dict]) -> dict:
    buckets = ("<0.5s", "0.5–2s", ">2s", "unknown")
    by_venue = defaultdict(lambda: {"n": 0, "fill0": 0})
    by_age = {b: {"n": 0, "fill0": 0} for b in buckets}
    by_both = defaultdict(lambda: {"n": 0, "fill0": 0})
    nagal = []
    for row in rows:
        venue = str(row.get("venue") or "unknown").lower()
        lag = row.get("lag_seconds")
        bucket = age_bucket(lag) if lag not in (None, "") else "unknown"
        fill = dec(row.get("fill_qty")) or Decimal("0")
        zero = fill <= 0
        by_venue[venue]["n"] += 1
        by_age[bucket]["n"] += 1
        by_both[(venue, bucket)]["n"] += 1
        if zero:
            by_venue[venue]["fill0"] += 1
            by_age[bucket]["fill0"] += 1
            by_both[(venue, bucket)]["fill0"] += 1
        inst = str(row.get("instrument") or "")
        if "NAGSAN" in inst or "sumnag" in inst:
            nagal.append(row)

    def rate(cell):
        n = cell["n"]
        z = cell["fill0"]
        return {
            "n": n,
            "fill0": z,
            "fill0_pct": pct(z, n),
            "note": tiny_note(n),
        }

    venue_rows = [{"venue": k, **rate(v)} for k, v in sorted(by_venue.items())]
    age_rows = [{"bucket": k, **rate(v)} for k, v in by_age.items()]
    both_rows = [
        {"venue": k[0], "bucket": k[1], **rate(v)}
        for k, v in sorted(by_both.items())
    ]
    return {
        "n": len(rows),
        "n_with_lag": sum(1 for r in rows if r.get("lag_seconds") not in (None, "")),
        "n_with_size": sum(1 for r in rows if r.get("quote_size") not in (None, "")),
        "by_venue": venue_rows,
        "by_age": age_rows,
        "by_both": both_rows,
        "nagal": nagal,
        "note": tiny_note(len(rows)),
    }


def jump_fade_from_tape() -> dict:
    print("streaming tennis ticks for jump-then-fade", flush=True)
    settlements = load_settlements()
    catalog = load_catalog()
    starts = start_lookup_from(settlements, catalog)
    stream = stream_tennis_ticks()
    states = stream["states"]
    overlay_last(states)
    last_map = {}
    events = []
    for st in states.values():
        game = st.get("game") or ""
        feed_start = st.get("game_start") or ""
        looked_text, looked_source = starts.get(game_norm(game), ("", ""))
        if str(looked_source).startswith("occurrence"):
            start_text, start_source = prefer_start(feed_start, looked_text, "")
        else:
            start_text, start_source = prefer_start(feed_start, "", looked_text)
        if not is_clocked_start(start_text):
            continue
        start_dt = parse_dt(start_text)
        if start_dt is None:
            continue
        start_dt = to_et(start_dt)
        ticks = st.get("ticks") or []
        saw_under = False
        first_over = None
        window_lo = start_dt + timedelta(minutes=15)
        window_hi = start_dt + timedelta(minutes=60)
        for seen, price in ticks:
            dt = parse_dt(seen)
            if dt is None:
                continue
            dt = to_et(dt)
            if price < 0.60:
                saw_under = True
            if price > 0.70:
                if dt < window_lo:
                    first_over = None
                    break
                if saw_under and window_lo <= dt <= window_hi:
                    first_over = (seen, price, dt)
                    break
                if dt > window_hi:
                    break
        if first_over is None:
            continue
        seen, price, dt = first_over
        minutes = (dt - start_dt).total_seconds() / 60.0
        events.append({
            "key": st.get("key") or "",
            "sport": "tennis",
            "game": game,
            "market_type": "moneyline",
            "side": st.get("side") or "",
            "side_key": st.get("side_key") or "",
            "number": "",
            "venue": st.get("venue") or "",
            "game_start": start_text,
            "start_source": start_source,
            "cross_time": seen,
            "first_above": price,
            "price": price,
            "minutes_in": round(minutes, 1),
            "under60": True,
        })
        last = ticks[-1] if ticks else None
        if last:
            last_map[st["key"]] = {
                "price": last[1],
                "seen_at": last[0],
                "game_start": start_text,
                "sport": "tennis",
            }
    index = build_index(settlements)
    attach_results(events, last_map, settlements, index)
    write_jsonl(JUMP_FADE, events)
    kept = [e for e in events if e.get("official") == "win"]
    gave = [e for e in events if e.get("official") == "loss"]
    pending = [e for e in events if e.get("official") == "pending"]
    settled = kept + gave
    by_venue = defaultdict(lambda: {"n": 0, "kept": 0, "gave": 0, "pending": 0})
    for row in events:
        cell = by_venue[row.get("venue") or ""]
        if row.get("official") == "win":
            cell["n"] += 1
            cell["kept"] += 1
        elif row.get("official") == "loss":
            cell["n"] += 1
            cell["gave"] += 1
        else:
            cell["pending"] += 1
    venue_rows = []
    for venue, cell in sorted(by_venue.items()):
        n = cell["n"]
        venue_rows.append({
            "venue": venue,
            "n": n,
            "kept": cell["kept"],
            "gave": cell["gave"],
            "keep_pct": pct(cell["kept"], n),
            "give_back_pct": pct(cell["gave"], n),
            "pending": cell["pending"],
            "note": tiny_note(n),
        })
    n = len(settled)
    summary = {
        "n_events": len(events),
        "n_settled": n,
        "kept": len(kept),
        "gave": len(gave),
        "pending": len(pending),
        "keep_pct": pct(len(kept), n),
        "give_back_pct": pct(len(gave), n),
        "note": tiny_note(n),
        "by_venue": venue_rows,
        "events": [
            {
                "game": e.get("game") or "",
                "side": e.get("side") or "",
                "venue": e.get("venue") or "",
                "jump_px": f"{as_float(e.get('price')):.4f}" if as_float(e.get("price")) is not None else "",
                "minutes_in": e.get("minutes_in"),
                "start": e.get("game_start") or "",
                "jump_time": e.get("cross_time") or "",
                "official": e.get("official") or "",
                "outcome": "KEPT" if e.get("official") == "win" else ("GAVE BACK" if e.get("official") == "loss" else (e.get("official") or "pending")),
                "source": e.get("official_source") or "",
            }
            for e in sorted(events, key=lambda z: z.get("cross_time") or "", reverse=True)
        ],
    }
    return summary


def transition_from_csv() -> dict:
    if not DECADE_CSV.is_file():
        return {"n_t2_4049": 0, "n_with_t0": 0, "table": [], "details": [], "dirs": {}, "note": "decade CSV missing"}
    t0, t2 = [], []
    with DECADE_CSV.open("r", encoding="utf-8", newline="") as handle:
        for rec in csv.DictReader(handle):
            price = as_float(rec.get("price"))
            row = {
                "venue": rec.get("venue") or "",
                "game": rec.get("game") or "",
                "side": rec.get("side") or "",
                "price": price,
                "band": rec.get("band") or (decade_label(price) if price is not None else ""),
                "cross_time": rec.get("seen_at") or "",
                "game_start": rec.get("game_start") or "",
                "official": rec.get("official") or "",
                "official_source": rec.get("official_source") or "",
                "bad_book": str(rec.get("bad_book") or "").lower() in {"true", "1", "yes"},
                "pair_sum": as_float(rec.get("pair_sum")),
            }
            if rec.get("snapshot") == "t0":
                t0.append(row)
            elif rec.get("snapshot") == "t2":
                t2.append(row)
    poly = transition_4049(t2, t0, "Polymarket")
    extra = {venue: transition_4049(t2, t0, venue) for venue in ("Kalshi", "Gemini")}
    poly["extra"] = extra
    return poly


def hypotheses_from_decade() -> list[dict]:
    if DECADE_JSON.is_file():
        try:
            payload = json.loads(DECADE_JSON.read_text(encoding="utf-8"))
            if payload.get("hypotheses"):
                return payload["hypotheses"]
            return named_hypotheses(payload.get("headline") or {}, payload.get("tables") or {})
        except (OSError, json.JSONDecodeError):
            pass
    return named_hypotheses({}, {})


def snapshot_status() -> dict:
    n = 0
    n_live = 0
    if SNAPSHOTS.is_file():
        for row in load_jsonl(SNAPSHOTS):
            n += 1
            if row.get("seed") is False:
                n_live += 1
    return {
        "present": SNAPSHOTS.is_file(),
        "n": n,
        "n_live": n_live,
        "note": "sibling collector owns this file; this job does not write it",
    }


def leftover_html_section(leftover: dict) -> str:
    counts = leftover["counts"]
    count_rows = [
        {"metric": "Watch-era episodes (leftover watch on)", "n": counts["watch_episodes"], "note": counts["note"]},
        {"metric": "Became buyable (ask ≤ max cap)", "n": counts["became_buyable"], "note": ""},
        {"metric": "IOC filled", "n": counts["ioc_filled"], "note": ""},
        {"metric": "Game ended / resolved first", "n": counts["resolved_first"], "note": ""},
        {"metric": "Still watching at 60 minutes", "n": counts["still_watching_60m"], "note": ""},
        {"metric": "Still open now", "n": counts["still_open"], "note": ""},
        {"metric": "Pre-watch one-legs (no minute ticks)", "n": counts["pre_watch_one_legs"], "note": "alerts before the watch existed"},
    ]
    ep_rows = []
    for e in leftover["episodes"]:
        ep_rows.append({
            "game": e.get("game") or "",
            "source": e.get("source") or "",
            "ticks": e.get("n_ticks"),
            "buyable": "yes" if e.get("became_buyable") else "no",
            "filled": "yes" if e.get("ioc_filled") else "no",
            "resolved": "yes" if e.get("resolved_first") else "no",
            "hour": "yes" if e.get("still_watching_60m") else "no",
            "open": "yes" if e.get("still_open") else "no",
            "first": e.get("first_seen") or "",
            "last": e.get("last_seen") or "",
        })
    return f"""
<h2>1. One-leg leftover — other ask through $0.95 in the next hour</h2>
<p class="note">After a Yes or No fill, the opposite bet is rechecked about every 20 seconds on Kalshi, Gemini, Polymarket US, and Novig, including the origin venue. Buyable means that opposite is still at or under the leftover cap (both sides plus fees ≤ $0.95). IOC is one immediate-or-cancel, cheapest qualifying venue first. Pre-watch one-legs are naked fills from before the leftover watch existed; we cannot reconstruct those ticks. Going forward, live ticks append to <code>raw/leftover_watch_stats.jsonl</code>.</p>
{table([("Count", "text"), ("N", "num"), ("Note", "text")], count_rows, ["metric", "n", "note"])}
<h3>Episodes</h3>
{table(
    [("Game", "text"), ("Source", "text"), ("Ticks", "num"), ("Buyable", "text"), ("IOC filled", "text"),
     ("Resolved first", "text"), ("Still watching at 60m", "text"), ("Open now", "text"),
     ("First", "date"), ("Last", "date")],
    ep_rows,
    ["game", "source", "ticks", "buyable", "filled", "resolved", "hour", "open", "first", "last"],
)}
"""


def write_html(payload: dict) -> None:
    leftover = payload["leftover"]
    jump = payload["jump"]
    quote = payload["quote"]
    trans = payload["transition"]
    hypos = payload["hypotheses"]
    snaps = payload["snapshots"]
    now = payload["written_at"]
    dirs = trans.get("dirs") or {}
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pattern tracking 2026-10-20</title>
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
<h1>Pattern tracking: leftover, jump-fade, stale ask, T−2h → T0</h1>
<p class="note">Written {esc(now)}. Research only. Not gold. Not DailyRun. This page does not place orders. Latch and one_leg_watch were left as they were. Sibling T−2h/T0 snapshot writer (<code>raw/odds_snapshots.jsonl</code>) was not interrupted.</p>
<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<div class="hl">
<p><strong>T−2h definition confirmed:</strong> two hours before scheduled match start. Last Yes print at or before that cutoff. A T0 print is also required for the 40–49 transition table.</p>
<p>Sibling snapshots present: {"yes" if snaps["present"] else "not yet"} — {snaps["n"]} rows ({snaps["n_live"]} live, not seed). {esc(snaps["note"])}.</p>
<p>Related: <a href="tennis_decade_at_start_20261020.html">tennis decade at start</a>,
<a href="tennis_decade_at_start_live.html">live decade page</a>,
<a href="one_leg_20s_watch_20261021.html">one-leg 20s all-venues watch</a>
(<a href="one_leg_minute_watch_20261020.html">prior minute-watch page</a>).</p>
</div>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>

{leftover_html_section(leftover)}

<h2>2. In-game jump then fade — under 60, first print over 70, 15–60 min after start</h2>
<p class="note">Tennis moneyline Yes. A side had a print under 60 cents, then its first print over 70 cents landed between 15 and 60 minutes after listed start. KEPT means that named side officially won. GAVE BACK means it officially lost. Last print at 99 cents is not a win. This is not a No-buy factory. Official settlements only.</p>
<p class="note">Events {jump['n_events']}. Settled N {jump['n_settled']}. Keep % {esc(jump.get('keep_pct') or 'n/a')} ({jump['kept']} / {jump['n_settled']}). Give-back % {esc(jump.get('give_back_pct') or 'n/a')} ({jump['gave']} / {jump['n_settled']}). Pending {jump['pending']}. {esc(jump.get('note') or '')}</p>
{table(
    [("Venue", "text"), ("Settled N", "num"), ("KEPT", "num"), ("GAVE BACK", "num"),
     ("Keep %", "num"), ("Give-back %", "num"), ("Pending", "num"), ("Note", "text")],
    jump.get("by_venue") or [],
    ["venue", "n", "kept", "gave", "keep_pct", "give_back_pct", "pending", "note"],
)}
<h3>Jump events</h3>
{table(
    [("Match", "text"), ("Player", "text"), ("Venue", "text"), ("First print over 70", "num"),
     ("Minutes after start", "num"), ("Start", "date"), ("Jump time", "date"),
     ("Official", "text"), ("Outcome", "text"), ("Source", "text")],
    jump.get("events") or [],
    ["game", "side", "venue", "jump_px", "minutes_in", "start", "jump_time", "official", "outcome", "source"],
)}

<h2>3. Ask gone 1–2s — quote age at send vs fill-0</h2>
<p class="note">Quote age is seen_at versus sent_at (lag_seconds). Book size is the advertised size at that price when we have it. Fill qty 0 means the immediate-or-cancel took nothing. Nagal Kalshi Yes: about 1.3s, size 2, fill 0. New sends log <code>raw/send_quote_age.jsonl</code>. Older sends are backfilled from orders.jsonl and order_io when quote fields exist.</p>
<p class="note">Sends {quote['n']}. With lag {quote['n_with_lag']}. With book size {quote['n_with_size']}. Fill-0 by venue includes every reconstructed send (most older rows have no quote age). Fill-0 by age uses only sends with seen_at versus sent_at. {esc(quote.get('note') or '')}</p>
<h3>Fill-0 by venue</h3>
{table(
    [("Venue", "text"), ("Sends", "num"), ("Fill 0", "num"), ("Fill-0 %", "num"), ("Note", "text")],
    quote.get("by_venue") or [],
    ["venue", "n", "fill0", "fill0_pct", "note"],
)}
<h3>Fill-0 by quote age</h3>
{table(
    [("Age bucket", "text"), ("Sends", "num"), ("Fill 0", "num"), ("Fill-0 %", "num"), ("Note", "text")],
    quote.get("by_age") or [],
    ["bucket", "n", "fill0", "fill0_pct", "note"],
)}
<h3>Fill-0 by venue and age</h3>
{table(
    [("Venue", "text"), ("Age bucket", "text"), ("Sends", "num"), ("Fill 0", "num"), ("Fill-0 %", "num"), ("Note", "text")],
    quote.get("by_both") or [],
    ["venue", "bucket", "n", "fill0", "fill0_pct", "note"],
)}

<h2>4. Named hypotheses on the T−2h / T0 page — HOLD</h2>
<p class="note">Raw decades stay on <a href="tennis_decade_at_start_20261020.html">tennis_decade_at_start_20261020.html</a>. Both hypotheses stay HOLD until settled N is large.</p>
{table(
    [("Id", "text"), ("Hypothesis", "text"), ("Definition", "text"),
     ("Settled N", "num"), ("Wins", "num"), ("Win %", "num"), ("Note", "text"), ("Verdict", "text")],
    hypos,
    ["id", "name", "definition", "settled", "wins", "win_pct", "note", "verdict"],
)}

<h2>5. Underdog 40–49 at T−2h → same player’s Yes at T0</h2>
<p class="note">T−2h = two hours before scheduled match start. Same named player. Requires a clocked start and a T0 print. Late money: lifted = T0 decade above 40–49; faded = below; left them = still 40–49. Pair sum is the two Yes prices at T−2h when the opponent also printed. Tennis Polymarket primary.</p>
<p class="note">T−2h 40–49 rows {trans.get('n_t2_4049') or 0}. With T0 print {trans.get('n_with_t0') or 0}. Missing T0 {trans.get('n_missing_t0') or 0}. Lifted {dirs.get('lifted') or 0}, faded {dirs.get('faded') or 0}, left them {dirs.get('left them') or 0}. Settled N {trans.get('total_settled') or 0}, win % {esc(trans.get('total_win_pct') or 'n/a')}. {esc(trans.get('note') or '')}</p>
{table(
    [("T0 decade", "text"), ("N with T0", "num"), ("Settled N", "num"), ("Wins", "num"),
     ("Losses", "num"), ("Win %", "num"), ("Pending", "num"), ("Note", "text")],
    trans.get("table") or [],
    ["band", "n", "settled", "wins", "losses", "win_pct", "pending", "note"],
)}
<h3>Same-player rows</h3>
{table(
    [("Match", "text"), ("Player", "text"), ("Venue", "text"), ("T−2h Yes", "num"),
     ("T0 Yes", "num"), ("T0 decade", "text"), ("Late money", "text"),
     ("Pair sum", "num"), ("Start", "date"), ("Official", "text")],
    trans.get("details") or [],
    ["game", "side", "venue", "t2_px", "t0_px", "t0_band", "late_money", "pair_sum", "start", "official"],
)}

<p class="note">Live trackers: <code>raw/leftover_watch_stats.jsonl</code>, <code>raw/jump_fade.jsonl</code>, <code>raw/send_quote_age.jsonl</code>. Snapshot file reused, not rewritten: <code>raw/odds_snapshots.jsonl</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def patch_one_leg_page(leftover: dict) -> None:
    if not ONE_LEG_PAGE.is_file():
        return
    text = ONE_LEG_PAGE.read_text(encoding="utf-8")
    marker = "<!-- leftover-counts -->"
    section = leftover_html_section(leftover)
    block = marker + "\n" + section + "\n"
    if marker in text:
        start = text.index(marker)
        end = text.find("<h2>Tonight", start)
        if end == -1:
            end = text.find("<p class=\"note\">Related:", start)
        if end == -1:
            return
        text = text[:start] + block + text[end:]
    else:
        needle = "<h2>Tonight"
        if needle not in text:
            needle = "<p class=\"note\">Related:"
        if needle not in text:
            return
        text = text.replace(needle, block + needle, 1)
    ONE_LEG_PAGE.write_text(text, encoding="utf-8")
    print(f"patched {ONE_LEG_PAGE}", flush=True)


def main() -> None:
    now = iso_now()
    print("leftover reconstruction", flush=True)
    watch = None
    if ONE_LEG_WATCH.is_file():
        try:
            watch = json.loads(ONE_LEG_WATCH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            watch = None
    live_left = load_jsonl(LEFTOVER_LIVE)
    sup_left = leftover_from_supervisor()
    alerts = load_jsonl(ONE_LEG_ALERTS)
    leftover = leftover_episodes(live_left + sup_left, alerts, watch if isinstance(watch, dict) else None)
    print(
        f"leftover watch_episodes={leftover['counts']['watch_episodes']} "
        f"buyable={leftover['counts']['became_buyable']} filled={leftover['counts']['ioc_filled']} "
        f"pre={leftover['counts']['pre_watch_one_legs']}",
        flush=True,
    )

    print("quote-age backfill", flush=True)
    quote_rows = quote_age_from_orders()
    quote = summarize_quote_age(quote_rows)
    print(f"quote sends={quote['n']} with_lag={quote['n_with_lag']} with_size={quote['n_with_size']}", flush=True)

    print("T-2h 40-49 transition from decade CSV", flush=True)
    trans = transition_from_csv()
    hypos = hypotheses_from_decade()
    snaps = snapshot_status()
    print(
        f"transition n_t2_4049={trans.get('n_t2_4049')} with_t0={trans.get('n_with_t0')} "
        f"snapshots={snaps['n']}",
        flush=True,
    )

    jump = jump_fade_from_tape()
    print(
        f"jump-fade events={jump['n_events']} settled={jump['n_settled']} "
        f"keep={jump['keep_pct']} give={jump['give_back_pct']}",
        flush=True,
    )

    payload = {
        "written_at": now,
        "leftover": leftover,
        "jump": jump,
        "quote": quote,
        "transition": trans,
        "hypotheses": hypos,
        "snapshots": snaps,
    }
    (RAW / "pattern_tracking_20261020.json").write_text(
        json.dumps({k: v for k, v in payload.items() if k != "leftover"} | {
            "leftover": leftover["counts"],
            "jump_n": jump["n_events"],
        }, indent=2, default=str),
        encoding="utf-8",
    )
    write_html(payload)
    patch_one_leg_page(leftover)
    for path in (PAGE, ONE_LEG_PAGE, STAMP / "tennis_decade_at_start_20261020.html", STAMP / "tennis_decade_at_start_live.html"):
        if path.is_file():
            copy_g(path)


if __name__ == "__main__":
    main()
