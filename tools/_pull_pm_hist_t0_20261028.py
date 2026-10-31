"""Resumable Kalshi + Polymarket historical T0 pull. Public APIs only.

Does not place, cancel, or sell. Does not print secrets.
Does not touch dashboard, orders_performance, live A-E, poller merge, GTC, or venue-fill.
Research tape only. Does not wire the live kitchen.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prediction_paths import LOCAL_STAMP

UA = {
    "User-Agent": "Mozilla/5.0 stockresearch-pm-hist-t0/1.0",
    "Accept": "application/json",
}
KBASE = "https://api.elections.kalshi.com/trade-api/v2"
GBASE = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
HIST = LOCAL_STAMP / "hist"
KDIR = HIST / "kalshi"
PDIR = HIST / "poly"
CUTOFF = datetime(2026, 8, 29, tzinfo=timezone.utc)
SLEEP = 0.04
WORKERS = 4
EVENT_PAGE_CAP = 400
POLY_EVENT_PAGE_CAP = 80
_TLS = threading.local()
_JSONL_LOCK = threading.Lock()

# Full-game moneyline / spread / Points Total only. Skip quarters, halves, props.
_SKIP_FRAG = (
    "1Q", "2Q", "3Q", "4Q", "1P", "2P", "3P", "1H", "2H",
    "TEAMTOTAL", "EXACTMATCH", "CELEBRITY", "PREPACK", "FFSEASON",
    "GAMESACK", "GAMETD", "GAMEFG", "GAMELOCATION", "GAMESPECIAL",
    "GAMEHIGHSCORE", "GOALEVERY", "TEAMSINGAME", "SERIESSPREAD",
)
PRIORITY_TICKER = (
    "KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL",
    "KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL",
    "KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL",
    "KXNHLGAME", "KXNHLSPREAD", "KXNHLTOTAL",
    "KXMLBGAME", "KXMLBSPREAD", "KXMLBTOTAL",
    "KXWNBAGAME", "KXWNBASPREAD", "KXWNBATOTAL",
    "KXATPMATCH", "KXWTAMATCH",
    "KXEPLGAME", "KXEPLSPREAD", "KXEPLTOTAL",
    "KXMLSGAME", "KXMLSSPREAD", "KXMLSTOTAL",
    "KXUCLGAME", "KXUCLSPREAD", "KXUCLTOTAL",
    "KXBUNDESLIGAGAME", "KXBUNDESLIGASPREAD", "KXBUNDESLIGATOTAL",
    "KXSERIEAGAME", "KXSERIEASPREAD", "KXSERIEATOTAL",
    "KXLALIGAGAME", "KXLALIGASPREAD", "KXLALIGATOTAL",
    "KXLIGUE1GAME", "KXLIGUE1SPREAD", "KXLIGUE1TOTAL",
    "KXUFCFIGHT", "KXMMAFIGHT",
    "KXPGARYDERMATCH", "KXPRESCUPMATCH", "KXTGLMATCH", "KXPGAH2H",
    # Second wave: tennis besides ATP/WTA tour. After soccer/UFC/golf so a
    # resume of the big-four leagues is not stuck behind Challenger volume.
    "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH", "KXITFMATCH", "KXITFWMATCH",
    "KXCHALLENGERMATCH",
)
# After reboot: Ligue 1 GAME/SPREAD/TOTAL already candled. Pull only holes.
# Soccer spread/total first so a resume is not stuck behind ITF volume.
LEFTOVER_TICKER = (
    "KXEPLSPREAD", "KXEPLTOTAL",
    "KXMLSSPREAD", "KXMLSTOTAL",
    "KXUCLSPREAD", "KXUCLTOTAL",
    "KXBUNDESLIGASPREAD", "KXBUNDESLIGATOTAL",
    "KXSERIEASPREAD", "KXSERIEATOTAL",
    "KXLALIGASPREAD", "KXLALIGATOTAL",
    "KXLIGUE1SPREAD", "KXLIGUE1TOTAL",
    "KXUFCFIGHT", "KXMMAFIGHT",
    "KXPGARYDERMATCH", "KXPRESCUPMATCH", "KXTGLMATCH", "KXPGAH2H",
    "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH",
    "KXCHALLENGERMATCH",
    "KXITFMATCH", "KXITFWMATCH",
)
POLY_SPORT_KEYS = (
    "nfl", "cfb", "nba", "nhl", "mlb", "wnba", "atp", "wta",
    "ufc", "pga", "epl", "mls", "ucl", "ncaab",
)
# Gamma /sports lists these; we have no T0 (or only events) on disk.
POLY_HOLE_KEYS = (
    "ncaab", "itf", "lal", "fl1", "bun", "sea", "uel",
    "atp-doubles", "wta-doubles", "daviscup", "bjkcup", "lpga",
)
# Event-list offset capped at 2,050. Date windows can still add later games.
POLY_CAPPED_KEYS = ("atp", "wta", "mlb", "mls")
LEFTOVER_K_STATUS = HIST / "leftover_kalshi_status.json"
LEFTOVER_P_STATUS = HIST / "leftover_poly_status.json"
POLY_KIND = {
    "moneyline": "moneyline",
    "ml": "moneyline",
    "spreads": "spread",
    "spread": "spread",
    "totals": "total",
    "total": "total",
    "over/under": "total",
    "over_under": "total",
    "points": "total",
}


def _sport_from_kalshi(ticker: str, tags: list, title: str) -> tuple[str, str]:
    t = (ticker or "").upper()
    tag = " ".join(tags or []).lower()
    blob = f"{t} {tag} {title or ''}".lower()
    if "ncaaf" in t.lower() or "college football" in blob:
        return "college football", "CFB"
    if "nfl" in t.lower() or ("football" in tag and "ncaaf" not in t.lower() and "cfl" not in t.lower()):
        if "cfl" in t.lower() or "ufl" in t.lower() or "afl" in t.lower():
            return "football", t.replace("KX", "")[:8]
        return "pro football", "NFL"
    if "wnba" in t.lower():
        return "basketball", "WNBA"
    if "ncaamb" in t.lower() or "ncaab" in t.lower():
        return "basketball", "NCAAB"
    if "nba" in t.lower():
        return "basketball", "NBA"
    if "nhl" in t.lower():
        return "hockey", "NHL"
    if "mlb" in t.lower():
        return "baseball", "MLB"
    if any(x in t for x in ("ATP", "WTA", "ITF", "CHALLENGER")) or "tennis" in tag:
        league = "ATP" if "ATP" in t else ("WTA" if "WTA" in t else ("ITF" if "ITF" in t else "tennis"))
        return "tennis", league
    if "ufc" in t.lower() or "mma" in t.lower() or "wrestling" in t.lower() or tag == "mma":
        return "mma", "UFC" if "UFC" in t else "MMA"
    if "golf" in tag or any(x in t for x in ("PGA", "GOLF", "MASTERS", "RYDER", "TGL", "PRESCUP")):
        return "golf", "golf"
    if "soccer" in tag or any(
        x in t for x in ("EPL", "MLS", "UCL", "BUNDESLIGA", "SERIEA", "LALIGA", "LIGUE", "SOCCER", "UEL", "UECL")
    ):
        return "soccer", "soccer"
    if "basketball" in tag:
        return "basketball", "basketball"
    if "hockey" in tag:
        return "hockey", "hockey"
    if "baseball" in tag:
        return "baseball", "baseball"
    if "football" in tag:
        return "football", "football"
    return (tag or "other"), (tag or "other")


def classify_series(row: dict) -> dict | None:
    ticker = str(row.get("ticker") or "")
    u = ticker.upper()
    # H2H is PGA head-to-head. Check before skip frags: "2H" would match KXPGAH2H.
    if u.endswith("H2H"):
        kind = "moneyline"
    elif any(frag in u for frag in _SKIP_FRAG):
        return None
    else:
        kind = None
        if u.endswith("SPREAD"):
            kind = "spread"
        elif u.endswith("TOTAL") and "TEAMTOTAL" not in u and "TCORNERS" not in u:
            kind = "total"
        elif u.endswith("GAME") or u.endswith("MATCH") or u.endswith("FIGHT"):
            kind = "moneyline"
        if not kind:
            return None
    sport, league = _sport_from_kalshi(ticker, row.get("tags") or [], row.get("title") or "")
    return {
        "ticker": ticker,
        "title": row.get("title") or "",
        "kind": kind,
        "sport": sport,
        "league": league,
        "tags": row.get("tags") or [],
        "priority": ticker in PRIORITY_TICKER,
    }


def _session() -> requests.Session:
    ses = getattr(_TLS, "session", None)
    if ses is None:
        ses = requests.Session()
        ses.headers.update(UA)
        _TLS.session = ses
    return ses


def http(url: str, tries: int = 5) -> tuple[int, object]:
    delay = 1.5
    last_code = 0
    last_body: object = None
    for attempt in range(tries):
        try:
            resp = _session().get(url, timeout=25)
            last_code = int(resp.status_code)
            try:
                last_body = resp.json()
            except Exception:
                last_body = (resp.text or "")[:400]
            if last_code in (429, 503) and attempt < tries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 45)
                continue
            return last_code, last_body
        except Exception as exc:
            last_code = 0
            last_body = {"error": type(exc).__name__, "msg": str(exc)[:200]}
            if attempt < tries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            return last_code, last_body
    return last_code, last_body


def parse_ts(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def load_jsonl_map(path: Path, key: str) -> dict:
    out = {}
    if not path.is_file():
        return out
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get(key):
                out[str(row[key])] = row
    return out


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, default=str) + "\n"
    with _JSONL_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def log_pull_error(label: str, where: str, exc: BaseException) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "where": where,
        "err": type(exc).__name__,
        "msg": str(exc)[:400],
        "trace": traceback.format_exc()[-1500:],
    }
    try:
        append_jsonl(HIST / "pull_error.jsonl", rec)
    except Exception:
        pass
    print(f"ERROR {label} {where} {type(exc).__name__}: {str(exc)[:200]}", flush=True)


def _px_float(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        for key in ("close_dollars", "close", "dollars"):
            if value.get(key) not in (None, ""):
                return _px_float(value.get(key))
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def yes_ask_from_candles(candles: list, t0_ts: int) -> tuple[float | None, int | None]:
    best_px = None
    best_ts = None
    for c in candles or []:
        if not isinstance(c, dict):
            continue
        ts = c.get("end_period_ts")
        try:
            ts_i = int(ts)
        except (TypeError, ValueError):
            continue
        ya = c.get("yes_ask")
        px = None
        if isinstance(ya, dict):
            px = ya.get("close_dollars")
            if px in (None, ""):
                px = ya.get("close")
        elif ya not in (None, ""):
            px = ya
        p = _px_float(px)
        if p is None:
            continue
        if ts_i <= t0_ts and (best_ts is None or ts_i >= best_ts):
            best_ts = ts_i
            best_px = p
    return best_px, best_ts


def primary_markets(markets: list, kind: str) -> list:
    settled = [
        m for m in markets
        if isinstance(m, dict) and str(m.get("result") or "").lower() in ("yes", "no")
    ]
    if kind == "moneyline" or len(settled) <= 4:
        return settled

    def strike(m: dict) -> float | None:
        for key in ("floor_strike", "cap_strike", "strike_price"):
            v = m.get(key)
            if v not in (None, ""):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None

    bags: dict[str, list] = defaultdict(list)
    for m in settled:
        s = strike(m)
        if kind == "spread" and s is not None:
            key = f"{abs(s):.1f}"
        elif s is not None:
            key = f"{s:.1f}"
        else:
            key = str(m.get("yes_sub_title") or m.get("subtitle") or "x")
        bags[key].append(m)
    ranked = []
    for key, ms in bags.items():
        vol = 0.0
        for m in ms:
            try:
                vol += float(m.get("volume") or m.get("volume_fp") or 0)
            except (TypeError, ValueError):
                pass
        ranked.append((-vol, 0 if len(ms) == 2 else 1, key, ms))
    ranked.sort()
    return ranked[0][3] if ranked else settled[:2]


def candle_url(series: str, ticker: str, t0_ts: int, *, hist: bool, interval: int) -> str:
    q = urllib.parse.urlencode({
        "start_ts": t0_ts - 45 * 60,
        "end_ts": t0_ts + 90,
        "period_interval": interval,
        "include_latest_before_start": "true",
    })
    tok = urllib.parse.quote(ticker)
    if hist:
        return f"{KBASE}/historical/markets/{tok}/candlesticks?{q}"
    return f"{KBASE}/series/{urllib.parse.quote(series)}/markets/{tok}/candlesticks?{q}"


def fetch_t0_ask(series: str, ticker: str, t0_ts: int) -> dict:
    use_hist = t0_ts < int(CUTOFF.timestamp())
    last = {"http": 0, "n": 0, "yes_ask": None, "candle_ts": None, "interval": None, "endpoint": None}
    for interval in (1, 60):
        for hist_flag in (use_hist, not use_hist):
            url = candle_url(series, ticker, t0_ts, hist=hist_flag, interval=interval)
            time.sleep(SLEEP)
            code, body = http(url)
            candles = []
            if isinstance(body, dict):
                candles = body.get("candlesticks") or []
            px, cts = yes_ask_from_candles(candles if isinstance(candles, list) else [], t0_ts)
            last = {
                "http": code,
                "n": len(candles) if isinstance(candles, list) else 0,
                "yes_ask": px,
                "candle_ts": cts,
                "interval": interval,
                "endpoint": "historical" if hist_flag else "live",
            }
            if px is not None:
                return last
    return last


def page_kalshi_events(series: str) -> list[dict]:
    path = KDIR / "events" / f"{series}.jsonl"
    have = load_jsonl_map(path, "event_ticker")
    cursor = ""
    pages = 0
    while True:
        q = {
            "series_ticker": series,
            "status": "settled",
            "limit": "200",
            "with_nested_markets": "true",
        }
        if cursor:
            q["cursor"] = cursor
        time.sleep(SLEEP)
        code, body = http(KBASE + "/events?" + urllib.parse.urlencode(q))
        pages += 1
        events = (body or {}).get("events") if isinstance(body, dict) else []
        if not isinstance(events, list) or not events:
            break
        new = 0
        for ev in events:
            try:
                if not isinstance(ev, dict) or not ev.get("event_ticker"):
                    continue
                et = str(ev["event_ticker"])
                if et in have:
                    continue
                mkts = ev.get("markets") or []
                if not isinstance(mkts, list):
                    mkts = []
                if not mkts:
                    time.sleep(SLEEP)
                    hcode, hbody = http(
                        KBASE + "/historical/markets?" + urllib.parse.urlencode(
                            {"event_ticker": et, "limit": "200"}
                        )
                    )
                    hm = (hbody or {}).get("markets") if isinstance(hbody, dict) else []
                    if isinstance(hm, list) and hm:
                        mkts = hm
                compact = {
                    "event_ticker": et,
                    "title": ev.get("title") or "",
                    "series_ticker": series,
                    "markets": [
                        {
                            "ticker": m.get("ticker"),
                            "result": m.get("result"),
                            "status": m.get("status"),
                            "occurrence_datetime": m.get("occurrence_datetime"),
                            "expected_expiration_time": m.get("expected_expiration_time"),
                            "yes_sub_title": m.get("yes_sub_title") or m.get("subtitle"),
                            "floor_strike": m.get("floor_strike"),
                            "cap_strike": m.get("cap_strike"),
                            "volume": m.get("volume") or m.get("volume_fp"),
                        }
                        for m in mkts if isinstance(m, dict)
                    ],
                }
                append_jsonl(path, compact)
                have[et] = compact
                new += 1
            except Exception as exc:
                log_pull_error(series, "page_event", exc)
                continue
        print(f"    {series} events page={pages} have={len(have)} new={new} http={code}", flush=True)
        cursor = (body or {}).get("cursor") if isinstance(body, dict) else None
        if not cursor:
            break
        if pages > EVENT_PAGE_CAP:
            break
    return list(have.values())


def kalshi_side(meta: dict, mkt: dict, t0: dict) -> dict | None:
    px = t0.get("yes_ask")
    result = str(mkt.get("result") or "").lower()
    if px is None or result not in ("yes", "no"):
        return None
    occ = mkt.get("occurrence_datetime") or mkt.get("expected_expiration_time")
    t0_ts = parse_ts(occ)
    strike = mkt.get("floor_strike")
    if strike in (None, ""):
        strike = mkt.get("cap_strike")
    won = result == "yes"
    return {
        "sport": meta["sport"],
        "league": meta["league"],
        "kind": meta["kind"],
        "game": mkt.get("event_ticker") or meta.get("event_ticker") or "",
        "game_n": str(mkt.get("event_ticker") or meta.get("event_ticker") or "").lower(),
        "venue": "kalshi",
        "number": "" if strike in (None, "") else str(strike),
        "ticker": mkt.get("ticker"),
        "t0_a": px,
        "t0_fav": px,
        "t0_ts": t0_ts,
        "end_ts": t0_ts,
        "fav": "a",
        "fav_name": mkt.get("yes_sub_title") or mkt.get("ticker"),
        "fav_won": won,
        "off_a": "win" if won else "loss",
        "void": False,
        "settled": True,
        "cover_known": True,
        "_side_letter": str(mkt.get("ticker") or ""),
        "source": "kalshi_hist_candle",
        "t0_label": "last yes_ask.close at/just before occurrence or expected_expiration",
        "candle_interval": t0.get("interval"),
        "candle_endpoint": t0.get("endpoint"),
        "entry_date": datetime.fromtimestamp(t0_ts, timezone.utc).date().isoformat() if t0_ts else "",
    }


def count_kalshi_events(series: str) -> int:
    n = 0
    cursor = ""
    pages = 0
    while True:
        q = {"series_ticker": series, "status": "settled", "limit": "200"}
        if cursor:
            q["cursor"] = cursor
        time.sleep(SLEEP)
        code, body = http(KBASE + "/events?" + urllib.parse.urlencode(q))
        pages += 1
        events = (body or {}).get("events") if isinstance(body, dict) else []
        if not isinstance(events, list) or not events:
            break
        n += len(events)
        cursor = (body or {}).get("cursor") if isinstance(body, dict) else None
        if not cursor or pages > EVENT_PAGE_CAP:
            break
    return n


def pull_kalshi_series(meta: dict, *, candles: bool) -> dict:
    series = meta["ticker"]
    t0_path = KDIR / "t0" / f"{series}.jsonl"
    have_t0 = load_jsonl_map(t0_path, "ticker")
    if not candles:
        n_ev = count_kalshi_events(series)
        return {
            "platform": "kalshi",
            "series": series,
            "sport": meta["sport"],
            "league": meta["league"],
            "kind": meta["kind"],
            "n_events": n_ev,
            "n_markets": 0,
            "n_t0": sum(1 for r in have_t0.values() if r.get("yes_ask") is not None),
            "n_missing": n_ev,
            "span_lo": "",
            "span_hi": "",
            "price_kind": "yes_ask candle close",
            "candles_fetched": False,
            "note": "exists on Kalshi; candles not fetched (non-priority series)",
        }
    events = page_kalshi_events(series)
    n_mkt = 0
    n_miss = 0
    dates = []
    jobs = []
    for ev in events:
        mkts = primary_markets(ev.get("markets") or [], meta["kind"])
        n_mkt += len(mkts)
        et = ev.get("event_ticker")
        for m in mkts:
            ticker = m.get("ticker")
            if not ticker:
                n_miss += 1
                continue
            if ticker in have_t0 and have_t0[ticker].get("yes_ask") is not None:
                occ = have_t0[ticker].get("occurrence") or m.get("occurrence_datetime")
                ts = parse_ts(occ)
                if ts:
                    dates.append(ts)
                continue
            occ = m.get("occurrence_datetime") or m.get("expected_expiration_time")
            t0_ts = parse_ts(occ)
            if not t0_ts:
                n_miss += 1
                row = {"ticker": ticker, "event_ticker": et, "skip": "no_clock"}
                append_jsonl(t0_path, row)
                have_t0[ticker] = row
                continue
            jobs.append((ticker, m, et, occ, t0_ts))

    def _job(item):
        ticker, m, et, occ, t0_ts = item
        got = fetch_t0_ask(series, ticker, t0_ts)
        return ticker, m, et, occ, t0_ts, got

    done_n = sum(1 for r in have_t0.values() if r.get("yes_ask") is not None)
    batch = 250
    if jobs:
        print(f"    {series} candle jobs={len(jobs)} already_t0={done_n}", flush=True)
        for i in range(0, len(jobs), batch):
            chunk = jobs[i:i + batch]
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futs = [pool.submit(_job, item) for item in chunk]
                for fut in as_completed(futs):
                    try:
                        ticker, m, et, occ, t0_ts, got = fut.result()
                    except Exception as exc:
                        n_miss += 1
                        log_pull_error(series, "t0_worker", exc)
                        continue
                    row = {
                        "ticker": ticker,
                        "event_ticker": et,
                        "result": m.get("result"),
                        "occurrence": occ,
                        "yes_sub_title": m.get("yes_sub_title"),
                        "floor_strike": m.get("floor_strike"),
                        "cap_strike": m.get("cap_strike"),
                        **got,
                    }
                    append_jsonl(t0_path, row)
                    have_t0[ticker] = row
                    if got.get("yes_ask") is None:
                        n_miss += 1
                    else:
                        done_n += 1
                        dates.append(t0_ts)
                    finished = done_n + n_miss
                    if finished and finished % 25 == 0:
                        print(f"    {series} t0={done_n} miss={n_miss}", flush=True)
    span_lo = span_hi = ""
    if dates:
        span_lo = datetime.fromtimestamp(min(dates), timezone.utc).date().isoformat()
        span_hi = datetime.fromtimestamp(max(dates), timezone.utc).date().isoformat()
    return {
        "platform": "kalshi",
        "series": series,
        "sport": meta["sport"],
        "league": meta["league"],
        "kind": meta["kind"],
        "n_events": len(events),
        "n_markets": n_mkt,
        "n_t0": sum(1 for r in have_t0.values() if r.get("yes_ask") is not None),
        "n_missing": n_miss,
        "span_lo": span_lo,
        "span_hi": span_hi,
        "price_kind": "yes_ask candle close",
        "candles_fetched": candles,
        "note": "primary line only on spread/Points Total" if meta["kind"] != "moneyline" else "both named Yes",
    }


def build_kalshi_books() -> list[dict]:
    series_path = KDIR / "series_keep.json"
    if not series_path.is_file():
        return []
    keep = json.loads(series_path.read_text(encoding="utf-8"))
    by_ticker = {r["ticker"]: r for r in keep}
    sides = []
    t0_dir = KDIR / "t0"
    ev_dir = KDIR / "events"
    if not t0_dir.is_dir():
        return []
    event_mkts: dict[str, dict] = {}
    if ev_dir.is_dir():
        for path in ev_dir.glob("*.jsonl"):
            for row in load_jsonl_map(path, "event_ticker").values():
                for m in row.get("markets") or []:
                    if m.get("ticker"):
                        mm = dict(m)
                        mm["event_ticker"] = row.get("event_ticker")
                        event_mkts[str(m["ticker"])] = mm
    for path in sorted(t0_dir.glob("*.jsonl")):
        series = path.stem
        meta = by_ticker.get(series) or classify_series({"ticker": series, "tags": [], "title": ""})
        if not meta:
            continue
        for row in load_jsonl_map(path, "ticker").values():
            if row.get("yes_ask") is None:
                continue
            mkt = event_mkts.get(row["ticker"]) or {
                "ticker": row.get("ticker"),
                "result": row.get("result"),
                "occurrence_datetime": row.get("occurrence"),
                "yes_sub_title": row.get("yes_sub_title"),
                "floor_strike": row.get("floor_strike"),
                "cap_strike": row.get("cap_strike"),
                "event_ticker": row.get("event_ticker"),
            }
            mkt.setdefault("result", row.get("result"))
            mkt.setdefault("occurrence_datetime", row.get("occurrence"))
            side = kalshi_side(meta, mkt, row)
            if side:
                sides.append(side)
    return sides


def _json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            got = json.loads(value)
            return got if isinstance(got, list) else []
        except json.JSONDecodeError:
            return []
    return []


def poly_kind_of(mkt: dict) -> str | None:
    raw = str(mkt.get("sportsMarketType") or mkt.get("marketType") or "").strip().lower()
    if raw in POLY_KIND:
        return POLY_KIND[raw]
    q = str(mkt.get("question") or "").lower()
    if "spread" in q or "handicap" in q:
        return "spread"
    if "over/under" in q or "o/u" in q or "total points" in q or "total goals" in q:
        return "total"
    if raw:
        return None
    # moneyline often has no type on older rows; two team outcomes, no line
    if mkt.get("line") in (None, "", 0) and " vs" in q:
        return "moneyline"
    return None


def poly_t0_clock(ev: dict, mkt: dict) -> int | None:
    for blob in (mkt, ev):
        for key in ("gameStartTime", "game_start_time", "eventStartTime"):
            ts = parse_ts(blob.get(key))
            if ts:
                return ts
    # listed :00 endDate is sometimes kickoff-day midnight — prefer not
    return parse_ts(ev.get("startTime") or ev.get("start_date"))


def fetch_poly_last_trade(token: str, t0_ts: int) -> dict:
    last = {"http": 0, "n": 0, "px": None, "px_ts": None, "fidelity": None}
    for fid in (1, 60):
        q = urllib.parse.urlencode({
            "market": token,
            "startTs": t0_ts - 3600,
            "endTs": t0_ts + 120,
            "fidelity": fid,
        })
        time.sleep(SLEEP)
        code, body = http(CLOB + "/prices-history?" + q)
        hist = (body or {}).get("history") if isinstance(body, dict) else None
        n = len(hist) if isinstance(hist, list) else 0
        px = pts = None
        for pt in hist or []:
            if not isinstance(pt, dict):
                continue
            ts = pt.get("t") or pt.get("timestamp")
            p = pt.get("p") or pt.get("price")
            try:
                ts_i = int(ts)
                p_f = float(p)
            except (TypeError, ValueError):
                continue
            if ts_i <= t0_ts and (pts is None or ts_i >= pts):
                pts = ts_i
                px = p_f
        last = {"http": code, "n": n, "px": px, "px_ts": pts, "fidelity": fid}
        if px is not None:
            return last
    return last


def _compact_poly_event(ev: dict, series_id: str, sport: str) -> dict:
    compact = {
        "id": str(ev["id"]),
        "slug": ev.get("slug") or ev.get("ticker"),
        "title": ev.get("title") or "",
        "sport": sport,
        "series_id": series_id,
        "gameStartTime": ev.get("gameStartTime") or ev.get("startTime"),
        "startDate": ev.get("startDate") or ev.get("start_date"),
        "markets": [],
    }
    for m in ev.get("markets") or []:
        if not isinstance(m, dict):
            continue
        kind = poly_kind_of(m)
        if not kind:
            continue
        compact["markets"].append({
            "id": m.get("id"),
            "question": m.get("question"),
            "slug": m.get("slug"),
            "sportsMarketType": m.get("sportsMarketType"),
            "kind": kind,
            "line": m.get("line"),
            "outcomes": m.get("outcomes"),
            "outcomePrices": m.get("outcomePrices"),
            "clobTokenIds": m.get("clobTokenIds"),
            "gameStartTime": m.get("gameStartTime"),
            "umaResolutionStatus": m.get("umaResolutionStatus"),
            "closed": m.get("closed"),
        })
    return compact


def _page_poly_chunk(
    series_id: str,
    sport: str,
    have: dict,
    path: Path,
    extra: dict | None = None,
) -> int:
    """Append new events for one query. Returns how many new ids were stored."""
    offset = 0
    pages = 0
    stored = 0
    while True:
        q = {
            "series_id": series_id,
            "closed": "true",
            "limit": "50",
            "offset": str(offset),
        }
        if extra:
            q.update(extra)
        time.sleep(SLEEP)
        code, body = http(GBASE + "/events?" + urllib.parse.urlencode(q))
        pages += 1
        evs = body if isinstance(body, list) else ((body or {}).get("events") if isinstance(body, dict) else [])
        if not isinstance(evs, list) or not evs:
            break
        new = 0
        for ev in evs:
            if not isinstance(ev, dict) or not ev.get("id"):
                continue
            eid = str(ev["id"])
            if eid in have:
                continue
            compact = _compact_poly_event(ev, series_id, sport)
            append_jsonl(path, compact)
            have[eid] = compact
            new += 1
            stored += 1
        offset += len(evs)
        if len(evs) < 50:
            break
        if pages > POLY_EVENT_PAGE_CAP:
            break
        if new == 0 and pages > 2:
            if offset > 5000:
                break
    return stored


def page_poly_events(series_id: str, sport: str, *, date_windows: bool = False) -> list[dict]:
    path = PDIR / "events" / f"{sport}.jsonl"
    have = load_jsonl_map(path, "id")
    added = _page_poly_chunk(series_id, sport, have, path)
    print(f"    poly {sport} offset-page new={added} have={len(have)}", flush=True)
    if date_windows:
        for start, end in poly_date_windows():
            extra = {"end_date_min": start, "end_date_max": end}
            got = _page_poly_chunk(series_id, sport, have, path, extra)
            if got:
                print(
                    f"    poly {sport} window {start[:7]} new={got} have={len(have)}",
                    flush=True,
                )
    return list(have.values())


def poly_sport_map() -> dict[str, dict]:
    path = HIST / "probe" / "poly_sports.json"
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for r in rows:
        if isinstance(r, dict) and r.get("sport") and r.get("series"):
            out[str(r["sport"]).lower()] = r
    return out


def _poly_sport_league(sport_key: str) -> tuple[str, str]:
    s = sport_key.lower()
    if s == "nfl":
        return "pro football", "NFL"
    if s == "cfb":
        return "college football", "CFB"
    if s == "nba":
        return "basketball", "NBA"
    if s == "wnba":
        return "basketball", "WNBA"
    if s == "ncaab":
        return "basketball", "NCAAB"
    if s == "nhl":
        return "hockey", "NHL"
    if s == "mlb":
        return "baseball", "MLB"
    if s in ("atp", "wta"):
        return "tennis", s.upper()
    if s == "ufc":
        return "mma", "UFC"
    if s == "pga":
        return "golf", "PGA"
    if s in ("epl", "mls", "ucl", "uel"):
        return "soccer", s.upper()
    if s == "lal":
        return "soccer", "LaLiga"
    if s == "fl1":
        return "soccer", "Ligue 1"
    if s == "bun":
        return "soccer", "Bundesliga"
    if s == "sea":
        return "soccer", "Serie A"
    if s == "itf":
        return "tennis", "ITF"
    if s == "atp-doubles":
        return "tennis", "ATP doubles"
    if s == "wta-doubles":
        return "tennis", "WTA doubles"
    if s == "daviscup":
        return "tennis", "Davis Cup"
    if s == "bjkcup":
        return "tennis", "Billie Jean King Cup"
    if s == "lpga":
        return "golf", "LPGA"
    return s, s


def pull_poly_sport(sport_key: str, series_id: str, *, date_windows: bool = False) -> dict:
    t0_path = PDIR / "t0" / f"{sport_key}.jsonl"
    have = load_jsonl_map(t0_path, "token")
    events = page_poly_events(series_id, sport_key, date_windows=date_windows)
    sport, league = _poly_sport_league(sport_key)
    n_mkt = 0
    n_t0 = 0
    n_miss = 0
    dates = []
    kinds_seen = set()
    for ev in events:
        mkts = ev.get("markets") or []
        # primary: one moneyline market + one spread + one total (first of each)
        by_kind: dict[str, list] = defaultdict(list)
        for m in mkts:
            k = m.get("kind")
            if k:
                by_kind[k].append(m)
                kinds_seen.add(k)
        picked = []
        for k in ("moneyline", "spread", "total"):
            if by_kind.get(k):
                picked.append(by_kind[k][0])
        n_mkt += len(picked)
        t0_ts = poly_t0_clock(ev, picked[0] if picked else {})
        poly_jobs = []
        for m in picked:
            tokens = _json_list(m.get("clobTokenIds"))
            outcomes = _json_list(m.get("outcomes"))
            prices = _json_list(m.get("outcomePrices"))
            clock = parse_ts(m.get("gameStartTime")) or t0_ts
            if not clock or not tokens:
                n_miss += 1
                continue
            for i, token in enumerate(tokens):
                token = str(token)
                if token in have and have[token].get("px") is not None:
                    n_t0 += 1
                    dates.append(clock)
                    continue
                settled = None
                if i < len(prices):
                    try:
                        settled = float(prices[i])
                    except (TypeError, ValueError):
                        settled = None
                poly_jobs.append((token, m, ev, clock, outcomes[i] if i < len(outcomes) else str(i), settled))
        if not poly_jobs:
            continue

        def _poly_job(item):
            token, m, ev, clock, outcome, settled = item
            got = fetch_poly_last_trade(token, clock)
            return token, m, ev, clock, outcome, settled, got

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = [pool.submit(_poly_job, item) for item in poly_jobs]
            for fut in as_completed(futs):
                try:
                    token, m, ev, clock, outcome, settled, got = fut.result()
                except Exception as exc:
                    n_miss += 1
                    log_pull_error(sport_key, "poly_t0_worker", exc)
                    continue
                row = {
                    "token": token,
                    "event_id": ev.get("id"),
                    "slug": ev.get("slug"),
                    "title": ev.get("title"),
                    "question": m.get("question"),
                    "kind": m.get("kind"),
                    "line": m.get("line"),
                    "outcome": outcome,
                    "settled_px": settled,
                    "clock": clock,
                    "sport": sport,
                    "league": league,
                    **got,
                }
                append_jsonl(t0_path, row)
                have[token] = row
                if got.get("px") is None or settled is None:
                    n_miss += 1
                else:
                    n_t0 += 1
                    dates.append(clock)
    span_lo = span_hi = ""
    if dates:
        span_lo = datetime.fromtimestamp(min(dates), timezone.utc).date().isoformat()
        span_hi = datetime.fromtimestamp(max(dates), timezone.utc).date().isoformat()
    return {
        "platform": "polymarket",
        "series": series_id,
        "sport": sport,
        "league": league,
        "kind": ",".join(sorted(kinds_seen)) or "unknown",
        "n_events": len(events),
        "n_markets": n_mkt,
        "n_t0": sum(1 for r in have.values() if r.get("px") is not None),
        "n_missing": n_miss,
        "span_lo": span_lo,
        "span_hi": span_hi,
        "price_kind": "CLOB last-trade (not Yes ask); global book not Polymarket US",
        "candles_fetched": True,
        "note": "primary ML/spread/Points Total per event; last p at/before gameStartTime",
    }


def build_poly_books() -> list[dict]:
    sides = []
    t0_dir = PDIR / "t0"
    if not t0_dir.is_dir():
        return []
    for path in sorted(t0_dir.glob("*.jsonl")):
        for row in load_jsonl_map(path, "token").values():
            px = row.get("px")
            settled = row.get("settled_px")
            if px is None or settled is None:
                continue
            try:
                won = float(settled) >= 0.5
            except (TypeError, ValueError):
                continue
            t0_ts = row.get("clock")
            try:
                t0_ts = int(t0_ts) if t0_ts is not None else None
            except (TypeError, ValueError):
                t0_ts = None
            sides.append({
                "sport": row.get("sport") or path.stem,
                "league": row.get("league") or path.stem,
                "kind": row.get("kind") or "moneyline",
                "game": row.get("slug") or row.get("title") or "",
                "game_n": str(row.get("slug") or row.get("event_id") or "").lower(),
                "venue": "polymarket",
                "number": "" if row.get("line") in (None, "") else str(row.get("line")),
                "ticker": row.get("token"),
                "t0_a": float(px),
                "t0_fav": float(px),
                "t0_ts": t0_ts,
                "end_ts": t0_ts,
                "fav": "a",
                "fav_name": row.get("outcome"),
                "fav_won": won,
                "off_a": "win" if won else "loss",
                "void": False,
                "settled": True,
                "cover_known": True,
                "_side_letter": str(row.get("token") or ""),
                "source": "poly_clob_last_trade",
                "t0_label": "last CLOB trade at/just before gameStartTime (not ask)",
                "entry_date": datetime.fromtimestamp(t0_ts, timezone.utc).date().isoformat() if t0_ts else "",
            })
    return sides


def leftover_should_skip(row: dict | None) -> bool:
    """Skip a leftover series only when T0 is complete (candled, some T0, nothing missing)."""
    if not row:
        return False
    n_t0 = int(row.get("n_t0") or 0)
    n_miss = int(row.get("n_missing") or 0)
    fetched = bool(row.get("candles_fetched"))
    return bool(fetched and n_t0 > 0 and n_miss == 0)


def _meta_for_leftover_ticker(keep_by: dict, ticker: str) -> dict | None:
    if ticker in keep_by:
        return keep_by[ticker]
    tags = []
    if any(x in ticker for x in ("PGA", "TGL", "PRESCUP", "RYDER")):
        tags = ["Golf"]
    elif "UFC" in ticker or "MMA" in ticker:
        tags = ["MMA"]
    elif any(x in ticker for x in ("ATP", "WTA", "ITF", "CHALLENGER")):
        tags = ["Tennis"]
    elif any(x in ticker for x in ("EPL", "MLS", "UCL", "BUNDES", "SERIE", "LALIGA", "LIGUE")):
        tags = ["Soccer"]
    return classify_series({"ticker": ticker, "tags": tags, "title": ticker})


def leftover_metas(keep: list[dict], coverage: list[dict] | None = None) -> list[dict]:
    by = {r["ticker"]: r for r in keep if r and r.get("ticker")}
    cov_by = {
        str(r.get("series")): r
        for r in (coverage or [])
        if r.get("platform") == "kalshi" and r.get("series")
    }
    tickers: list[str] = []
    seen: set[str] = set()
    for ticker in LEFTOVER_TICKER:
        if leftover_should_skip(cov_by.get(ticker)):
            continue
        if ticker not in seen:
            tickers.append(ticker)
            seen.add(ticker)
    for row in coverage or []:
        if row.get("platform") != "kalshi":
            continue
        ticker = str(row.get("series") or "")
        if not ticker or ticker in seen:
            continue
        if leftover_should_skip(row):
            continue
        if ticker in PRIORITY_TICKER or ticker in LEFTOVER_TICKER:
            tickers.append(ticker)
            seen.add(ticker)
    out = []
    for ticker in tickers:
        got = _meta_for_leftover_ticker(by, ticker)
        if got:
            out.append(got)
        else:
            print(f"leftover skip unknown {ticker}", flush=True)
    return out


def write_leftover_status(path: Path, rec: dict) -> None:
    rec = dict(rec)
    rec["written_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    rec["pid"] = os.getpid()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    tmp.replace(path)


def poly_date_windows() -> list[tuple[str, str]]:
    """Monthly end_date windows so Gamma offset caps do not hide later seasons."""
    out: list[tuple[str, str]] = []
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            if year == 2026 and month > 11:
                break
            start = f"{year:04d}-{month:02d}-01T00:00:00Z"
            if month == 12:
                end = f"{year + 1:04d}-01-01T00:00:00Z"
            else:
                end = f"{year:04d}-{month + 1:02d}-01T00:00:00Z"
            out.append((start, end))
    return out


def poly_coverage_from_disk() -> list[dict]:
    """Rebuild Polymarket coverage rows from t0 jsonl. Does not fetch."""
    t0_dir = PDIR / "t0"
    if not t0_dir.is_dir():
        return []
    sports = poly_sport_map()
    out = []
    for path in sorted(t0_dir.glob("*.jsonl")):
        key = path.stem
        have = load_jsonl_map(path, "token")
        n_t0 = sum(1 for r in have.values() if r.get("px") is not None)
        n_miss = sum(1 for r in have.values() if r.get("px") is None)
        dates = []
        for row in have.values():
            try:
                dates.append(int(row.get("clock")))
            except (TypeError, ValueError):
                pass
        span_lo = span_hi = ""
        if dates:
            span_lo = datetime.fromtimestamp(min(dates), timezone.utc).date().isoformat()
            span_hi = datetime.fromtimestamp(max(dates), timezone.utc).date().isoformat()
        ev_path = PDIR / "events" / f"{key}.jsonl"
        n_ev = len(load_jsonl_map(ev_path, "id")) if ev_path.is_file() else 0
        sport, league = _poly_sport_league(key)
        sid = str((sports.get(key) or {}).get("series") or key)
        kinds = sorted({str(r.get("kind") or "") for r in have.values() if r.get("kind")})
        out.append({
            "platform": "polymarket",
            "series": sid,
            "sport": sport,
            "league": league,
            "kind": ",".join(k for k in kinds if k),
            "n_events": n_ev,
            "n_markets": 0,
            "n_t0": n_t0,
            "n_missing": n_miss,
            "span_lo": span_lo,
            "span_hi": span_hi,
            "price_kind": "CLOB last-trade (not Yes ask); global book not Polymarket US",
            "candles_fetched": True,
            "note": "from disk t0 jsonl; not re-fetched this leftover job",
        })
    return out


def ensure_poly_coverage(coverage: list[dict]) -> list[dict]:
    disk = poly_coverage_from_disk()
    if not disk:
        return coverage
    kalshi = [r for r in coverage if str(r.get("platform") or "").lower() == "kalshi"]
    return kalshi + disk


def write_books_and_coverage(coverage: list[dict]) -> None:
    HIST.mkdir(parents=True, exist_ok=True)
    (HIST / "coverage.json").write_text(json.dumps(coverage, indent=2, default=str), encoding="utf-8")
    try:
        k_sides = build_kalshi_books()
        p_sides = build_poly_books()
        (HIST / "books_kalshi.json").write_text(json.dumps(k_sides, default=str), encoding="utf-8")
        (HIST / "books_poly.json").write_text(json.dumps(p_sides, default=str), encoding="utf-8")
        print(f"wrote books kalshi={len(k_sides)} poly={len(p_sides)} coverage={len(coverage)}", flush=True)
    except Exception as exc:
        log_pull_error("books", "write_books_and_coverage", exc)
        print(f"wrote coverage={len(coverage)} (books rebuild failed)", flush=True)


def load_or_classify_series() -> list[dict]:
    KDIR.mkdir(parents=True, exist_ok=True)
    keep_path = KDIR / "series_keep.json"
    if keep_path.is_file():
        return json.loads(keep_path.read_text(encoding="utf-8"))
    flat = HIST / "probe" / "kalshi_series_flat.json"
    if not flat.is_file():
        raise SystemExit("missing probe series list; run tools/_probe_pm_hist_t0_20261028.py")
    rows = json.loads(flat.read_text(encoding="utf-8"))
    keep = []
    for r in rows:
        got = classify_series(r)
        if got:
            keep.append(got)
    keep_path.write_text(json.dumps(keep, indent=2), encoding="utf-8")
    return keep


def main() -> int:
    HIST.mkdir(parents=True, exist_ok=True)
    keep = load_or_classify_series()
    print(f"kalshi classified series {len(keep)}", flush=True)
    coverage: list[dict] = []
    cov_path = HIST / "coverage.json"
    if cov_path.is_file():
        try:
            coverage = json.loads(cov_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            coverage = []
    done_series = {r.get("series") for r in coverage if r.get("platform") == "kalshi" and r.get("candles_fetched")}
    poly_only = "--poly-only" in sys.argv
    leftover = "--leftover" in sys.argv
    poly_holes = "--poly-holes" in sys.argv

    pri = [r for r in keep if r["ticker"] in PRIORITY_TICKER]
    rest = [r for r in keep if r["ticker"] not in PRIORITY_TICKER]
    # stable priority order
    order = {t: i for i, t in enumerate(PRIORITY_TICKER)}
    pri.sort(key=lambda r: order.get(r["ticker"], 99))

    if poly_holes:
        pri = []
        rest = []
        leftover = False
        poly_only = True
        print("poly-holes: skip Kalshi; pull missing/capped Poly leagues if Gamma lists them", flush=True)

    if leftover:
        pri = leftover_metas(keep, coverage)
        rest = []
        print(
            f"leftover Kalshi only: {len(pri)} series with missing T0; skip complete books; do not re-pull Poly",
            flush=True,
        )
        coverage = ensure_poly_coverage(coverage)
        write_books_and_coverage(coverage)
        write_leftover_status(LEFTOVER_K_STATUS, {
            "running": True,
            "cmd": "python -u tools/_pull_pm_hist_t0_20261028.py --leftover",
            "series_queue": [r["ticker"] for r in pri],
            "n_series": len(pri),
            "current_series": "",
            "note": "Resume-safe T0 Yes-ask leftover. Does not touch in-play jsonl.",
        })
        print("restored Poly coverage from disk; Kalshi leftover candles next", flush=True)

    if poly_only:
        pri = []
        print("poly-only: skip remaining Kalshi candles; classified rest as events-only", flush=True)
        have_cov = {r.get("series") for r in coverage if r.get("platform") == "kalshi"}
        for meta in rest:
            if meta["ticker"] in have_cov:
                continue
            coverage.append({
                "platform": "kalshi",
                "series": meta["ticker"],
                "sport": meta["sport"],
                "league": meta["league"],
                "kind": meta["kind"],
                "n_events": 0,
                "n_markets": 0,
                "n_t0": 0,
                "n_missing": 0,
                "span_lo": "",
                "span_hi": "",
                "price_kind": "yes_ask candle close",
                "candles_fetched": False,
                "note": "exists on Kalshi (GAME/SPREAD/TOTAL); candles not fetched this job",
            })
        rest = []

    for meta in pri:
        cov_row = next(
            (r for r in coverage if r.get("platform") == "kalshi" and r.get("series") == meta["ticker"]),
            None,
        )
        if leftover:
            if leftover_should_skip(cov_row):
                print(f"skip {meta['ticker']} leftover complete", flush=True)
                continue
        elif meta["ticker"] in done_series:
            print(f"skip {meta['ticker']} already candled", flush=True)
            continue
        print(f"kalshi {meta['ticker']} {meta['kind']} {meta['sport']}", flush=True)
        if leftover:
            write_leftover_status(LEFTOVER_K_STATUS, {
                "running": True,
                "cmd": "python -u tools/_pull_pm_hist_t0_20261028.py --leftover",
                "series_queue": [r["ticker"] for r in pri],
                "current_series": meta["ticker"],
                "note": "Resume-safe T0 Yes-ask leftover. Does not touch in-play jsonl.",
            })
        try:
            rec = pull_kalshi_series(meta, candles=True)
        except Exception as exc:
            log_pull_error(meta["ticker"], "pull_kalshi_series", exc)
            rec = {
                "platform": "kalshi",
                "series": meta["ticker"],
                "sport": meta["sport"],
                "league": meta["league"],
                "kind": meta["kind"],
                "n_events": 0,
                "n_markets": 0,
                "n_t0": 0,
                "n_missing": 0,
                "span_lo": "",
                "span_hi": "",
                "price_kind": "yes_ask candle close",
                "candles_fetched": False,
                "note": f"series failed: {type(exc).__name__}: {str(exc)[:180]}",
            }
        coverage = [r for r in coverage if not (r.get("platform") == "kalshi" and r.get("series") == meta["ticker"])]
        coverage.append(rec)
        if leftover:
            coverage = ensure_poly_coverage(coverage)
        write_books_and_coverage(coverage)
        print(
            f"  events={rec['n_events']} markets={rec['n_markets']} t0={rec['n_t0']} "
            f"miss={rec['n_missing']} {rec['span_lo']}..{rec['span_hi']}",
            flush=True,
        )

    for meta in rest:
        already = next((r for r in coverage if r.get("series") == meta["ticker"]), None)
        if already and already.get("n_events") is not None:
            continue
        print(f"kalshi count {meta['ticker']}", flush=True)
        try:
            rec = pull_kalshi_series(meta, candles=False)
        except Exception as exc:
            log_pull_error(meta["ticker"], "count_kalshi_series", exc)
            continue
        coverage = [r for r in coverage if not (r.get("platform") == "kalshi" and r.get("series") == meta["ticker"])]
        coverage.append(rec)
        if len(coverage) % 20 == 0:
            write_books_and_coverage(coverage)

    if leftover:
        coverage = ensure_poly_coverage(coverage)
        write_books_and_coverage(coverage)
        write_leftover_status(LEFTOVER_K_STATUS, {
            "running": False,
            "cmd": "python -u tools/_pull_pm_hist_t0_20261028.py --leftover",
            "note": "leftover Kalshi T0 complete",
        })
        print("leftover Kalshi pull complete (Poly left on disk, not re-fetched)", flush=True)
        return 0

    sports = poly_sport_map()
    done_poly = {r.get("league") or r.get("series") for r in coverage if r.get("platform") == "polymarket" and r.get("candles_fetched")}
    poly_keys = list(POLY_SPORT_KEYS)
    use_windows = False
    if poly_holes:
        poly_keys = list(dict.fromkeys(list(POLY_HOLE_KEYS) + list(POLY_CAPPED_KEYS)))
        use_windows = True
        done_poly = set()
        write_leftover_status(LEFTOVER_P_STATUS, {
            "running": True,
            "cmd": "python -u tools/_pull_pm_hist_t0_20261028.py --poly-holes",
            "series_queue": poly_keys,
            "note": "Poly leftover last-trade for missing/capped leagues. Date windows on.",
        })
    for key in poly_keys:
        row = sports.get(key)
        if not row:
            coverage = [r for r in coverage if not (
                r.get("platform") == "polymarket" and (r.get("league") or r.get("sport")) == key
            )]
            coverage.append({
                "platform": "polymarket",
                "series": "",
                "sport": key,
                "league": key,
                "kind": "",
                "n_events": 0,
                "n_markets": 0,
                "n_t0": 0,
                "n_missing": 0,
                "span_lo": "",
                "span_hi": "",
                "price_kind": "CLOB last-trade",
                "candles_fetched": False,
                "note": "not in gamma /sports list",
            })
            continue
        sid = str(row.get("series"))
        if not poly_holes and (key.upper() in done_poly or sid in done_poly):
            print(f"skip poly {key}", flush=True)
            continue
        print(f"poly {key} series={sid}", flush=True)
        if poly_holes:
            write_leftover_status(LEFTOVER_P_STATUS, {
                "running": True,
                "cmd": "python -u tools/_pull_pm_hist_t0_20261028.py --poly-holes",
                "series_queue": poly_keys,
                "current_series": key,
                "note": "Poly leftover last-trade for missing/capped leagues. Date windows on.",
            })
        try:
            rec = pull_poly_sport(key, sid, date_windows=use_windows)
        except Exception as exc:
            log_pull_error(key, "pull_poly_sport", exc)
            rec = {
                "platform": "polymarket",
                "series": sid,
                "sport": key,
                "league": key,
                "kind": "",
                "n_events": 0,
                "n_markets": 0,
                "n_t0": 0,
                "n_missing": 0,
                "span_lo": "",
                "span_hi": "",
                "price_kind": "CLOB last-trade (not Yes ask); global book not Polymarket US",
                "candles_fetched": False,
                "note": f"poly failed: {type(exc).__name__}: {str(exc)[:180]}",
            }
        coverage = [r for r in coverage if not (r.get("platform") == "polymarket" and r.get("series") == sid)]
        coverage.append(rec)
        write_books_and_coverage(coverage)
        print(
            f"  events={rec['n_events']} t0={rec['n_t0']} miss={rec['n_missing']} "
            f"{rec['span_lo']}..{rec['span_hi']}",
            flush=True,
        )

    write_books_and_coverage(coverage)
    if poly_holes:
        write_leftover_status(LEFTOVER_P_STATUS, {
            "running": False,
            "cmd": "python -u tools/_pull_pm_hist_t0_20261028.py --poly-holes",
            "note": "poly leftover complete",
        })
    print("pull complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
