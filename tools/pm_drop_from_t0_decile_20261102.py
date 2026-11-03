#!/usr/bin/env python3
"""Max drop from T0 Yes, by sport / bet type / starting-price decile.

Research only. Public Kalshi candle + Polymarket CLOB last-trade APIs.
Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Does not start Strategy B.
Not gold. Not DailyRun.

Question: if we try to buy gaps by waiting for each named side to cheapen
from its opening price, how far do sides actually dip — on average, median,
and by percentile — and does that depend on the starting-price decile?

T0 (Kalshi) = last 1-min yes_ask.close at/just before occurrence_datetime
when that clock is before market close. Markets whose occurrence is at/after
close (bad clock) are skipped. Max dip = max(0, t0 − min yes_ask after T0).
Requires ≥5 post-T0 in-(0,1) bars.

Book A = dense multi-venue tennis live tape (Oct 21 HTML, already T0-labeled).
Book B = Kalshi 1-min yes_ask through-game paths pulled here.
Book C = Polymarket CLOB last-trade paths (not ask; labeled separately).
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import re
import statistics as st
import sys
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP  # noqa: E402
import report_page_extras  # noqa: E402

ET = ZoneInfo("America/New_York")
UA = {
    "User-Agent": "Mozilla/5.0 stockresearch-pm-drop-from-t0/1.0",
    "Accept": "application/json",
}
KBASE = "https://api.elections.kalshi.com/trade-api/v2"
GBASE = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
HIST = LOCAL_STAMP / "hist"
DROP_DIR = HIST / "drop_from_t0_20261102"
SIDE_JSONL = DROP_DIR / "kalshi_sides.jsonl"
PAIR_JSONL = DROP_DIR / "kalshi_pairs.jsonl"
POLY_JSONL = DROP_DIR / "poly_sides.jsonl"
STATUS = DROP_DIR / "status.json"
OUT_DIR = ROOT / "docs" / "prediction_market"
PAGE = OUT_DIR / "drop_from_t0_by_decile_20261102.html"
JSON_OUT = OUT_DIR / "drop_from_t0_by_decile_20261102.json"
DRIVE_PAGE = STAMP / "drop_from_t0_by_decile_20261102.html"
DRIVE_JSON = STAMP / "drop_from_t0_by_decile_20261102.json"
DENSE_HTML_CANDIDATES = (
    ROOT / "docs" / "prediction_market" / "dense_inplay_yes_dip_20261021.html",
    ROOT / "tmp_pm_backtest" / "dense_inplay_yes_dip_20261021.html",
)
DENSE_HTML = next((p for p in DENSE_HTML_CANDIDATES if p.is_file()), DENSE_HTML_CANDIDATES[0])
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/drop_from_t0_by_decile_20261102.html"
)

CUTOFF_TS = int(datetime(2026, 8, 29, tzinfo=timezone.utc).timestamp())
SLEEP = 0.08
WORKERS = 3
MIN_POST = 5
DECADES = (
    "0-9", "10-19", "20-29", "30-39", "40-49",
    "50-59", "60-69", "70-79", "80-89", "90-99",
)
THRESH = (0.05, 0.10, 0.15, 0.20, 0.25)
PCTILES = (10, 25, 50, 75, 90, 95)

SERIES_META = (
    ("KXATPMATCH", "tennis", "ATP", "moneyline"),
    ("KXWTAMATCH", "tennis", "WTA", "moneyline"),
    ("KXATPCHALLENGERMATCH", "tennis", "ATP Challenger", "moneyline"),
    ("KXWTACHALLENGERMATCH", "tennis", "WTA Challenger", "moneyline"),
    ("KXITFMATCH", "tennis", "ITF", "moneyline"),
    ("KXITFWMATCH", "tennis", "ITF W", "moneyline"),
    ("KXNFLGAME", "pro football", "NFL", "moneyline"),
    ("KXNFLSPREAD", "pro football", "NFL", "spread"),
    ("KXNFLTOTAL", "pro football", "NFL", "total"),
    ("KXNCAAFGAME", "college football", "CFB", "moneyline"),
    ("KXNCAAFSPREAD", "college football", "CFB", "spread"),
    ("KXNCAAFTOTAL", "college football", "CFB", "total"),
    ("KXNBAGAME", "basketball", "NBA", "moneyline"),
    ("KXNBASPREAD", "basketball", "NBA", "spread"),
    ("KXNBATOTAL", "basketball", "NBA", "total"),
    ("KXNHLGAME", "hockey", "NHL", "moneyline"),
    ("KXNHLSPREAD", "hockey", "NHL", "spread"),
    ("KXNHLTOTAL", "hockey", "NHL", "total"),
    ("KXMLBGAME", "baseball", "MLB", "moneyline"),
    ("KXEPLGAME", "soccer", "EPL", "moneyline"),
    ("KXUFCFIGHT", "mma", "UFC", "moneyline"),
)

ASKED = (
    "New predictions market system. Run backtests. Look at each sport / bet type "
    "combo. At the beginning of the game there is a favorite and an underdog. "
    "Tennis odds fluctuate greatly. If we buy gaps on players that don't exist in "
    "real time but statistically WILL show up — e.g. Kolar started 29%→18.3%, "
    "Moller 79%→63.4%; buy each at −10pp from start → ~0.19+0.69+fee ≈ 0.90 lock "
    "10¢ — what can we get away with? Average / median / percentiles of drop from "
    "starting price, overlay by original price decile. Hypothesis: 55/45 twitch "
    "more than 90/10."
)
PLAIN = (
    "Max drop from T0 is how many cents a named Yes cheapened after the trusted "
    "kickoff clock, measured on the through-game tape (not a random first tick). "
    "A 10¢ drop on a 70¢ opener means the Yes later printed 60¢. Deciles are "
    "10-cent starting-price bands. Favorite = the higher T0 Yes on that book; "
    "dog = the cheaper Yes. Moneyline is who wins; spread is cover; total is "
    "over/under. Kalshi uses 1-minute Yes-ask candle closes. Polymarket CLOB is "
    "last trade, not ask — shown separately. Dense tennis Book A is the Oct 21 "
    "multi-venue live tape already labeled with T0 and max dip. Research only."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def now_et() -> datetime:
    return datetime.now(ET)


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


def decile_of(px) -> str | None:
    if px is None:
        return None
    try:
        p = float(px)
    except (TypeError, ValueError):
        return None
    if p < 0 or p > 1:
        return None
    if p >= 0.90 - 1e-12:
        return "90-99"
    band = int(p * 10.0 + 1e-12)
    lo = band * 10
    return f"{lo}-{lo + 9}"


def _px_float(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        for key in ("close_dollars", "close", "dollars"):
            if value.get(key) not in (None, ""):
                return _px_float(value.get(key))
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def session() -> requests.Session:
    if not hasattr(session, "_s"):
        s = requests.Session()
        s.headers.update(UA)
        session._s = s  # type: ignore[attr-defined]
    return session._s  # type: ignore[attr-defined]


def http_get(url: str, tries: int = 5) -> tuple[int, object]:
    delay = 1.2
    last_code = 0
    last_body: object = None
    for attempt in range(tries):
        try:
            resp = session().get(url, timeout=30)
            last_code = int(resp.status_code)
            try:
                last_body = resp.json()
            except Exception:
                last_body = (resp.text or "")[:400]
            if last_code in (429, 503) and attempt < tries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 40)
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


def write_status(rec: dict) -> None:
    DROP_DIR.mkdir(parents=True, exist_ok=True)
    rec = dict(rec)
    rec["written_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    STATUS.write_text(json.dumps(rec, indent=2), encoding="utf-8")


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
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def path_from_candles(candles: list) -> list[list]:
    best: dict[int, float] = {}
    for candle in candles or []:
        if not isinstance(candle, dict):
            continue
        try:
            ts = int(candle.get("end_period_ts"))
        except (TypeError, ValueError):
            continue
        px = _px_float(candle.get("yes_ask"))
        if px is None or px < 0 or px > 1:
            continue
        best[ts] = float(px)
    return [[ts, best[ts]] for ts in sorted(best)]


def fetch_candles(series: str, ticker: str, start_ts: int, end_ts: int, *, hist: bool) -> list:
    q = urllib.parse.urlencode({
        "start_ts": int(start_ts),
        "end_ts": int(end_ts),
        "period_interval": 1,
        "include_latest_before_start": "true",
    })
    tok = urllib.parse.quote(ticker)
    if hist:
        url = f"{KBASE}/historical/markets/{tok}/candlesticks?{q}"
    else:
        url = f"{KBASE}/series/{urllib.parse.quote(series)}/markets/{tok}/candlesticks?{q}"
    time.sleep(SLEEP)
    code, body = http_get(url)
    candles = body.get("candlesticks") if isinstance(body, dict) else []
    if not isinstance(candles, list):
        candles = []
    if code != 200:
        return []
    return candles


def fetch_path(series: str, ticker: str, t0_ts: int, end_ts: int) -> list[list]:
    use_hist = int(t0_ts) < CUTOFF_TS
    start = int(t0_ts) - 45 * 60
    stop = max(int(end_ts), int(t0_ts) + 90)
    parts: list[list[list]] = []
    cur = start
    first = True
    while cur < stop:
        nxt = min(cur + 90 * 60, stop)
        candles = fetch_candles(series, ticker, cur, nxt, hist=use_hist)
        part = path_from_candles(candles)
        if not part and not use_hist:
            candles = fetch_candles(series, ticker, cur, nxt, hist=True)
            part = path_from_candles(candles)
        parts.append(part)
        if first and not part:
            break
        first = False
        if not part:
            break
        cur = nxt
    best: dict[int, float] = {}
    for part in parts:
        for ts, px in part:
            best[int(ts)] = float(px)
    return [[ts, best[ts]] for ts in sorted(best)]


def side_metrics(path: list[list], t0_ts: int) -> dict | None:
    t0_px = None
    after: list[float] = []
    for ts, px in path:
        if int(ts) <= int(t0_ts):
            t0_px = float(px)
        else:
            if 0.0 < float(px) < 1.0:
                after.append(float(px))
    if t0_px is None or len(after) < MIN_POST:
        return None
    if t0_px <= 0.005 or t0_px >= 0.995:
        return None
    mn = min(after)
    mx = max(after)
    dip = max(0.0, float(t0_px) - float(mn))
    return {
        "t0_px": round(float(t0_px), 4),
        "min_px": round(float(mn), 4),
        "max_px": round(float(mx), 4),
        "max_dip": round(float(dip), 4),
        "n_post": len(after),
        "hit": {f"d{int(t * 100):02d}": bool(dip + 1e-12 >= t) for t in THRESH},
    }


def list_series_markets(series: str, *, max_pages: int = 8) -> list[dict]:
    out: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params = {"series_ticker": series, "limit": 200, "status": "settled"}
        if cursor:
            params["cursor"] = cursor
        q = urllib.parse.urlencode(params)
        time.sleep(SLEEP)
        code, body = http_get(f"{KBASE}/markets?{q}")
        if code != 200 or not isinstance(body, dict):
            break
        ms = body.get("markets") or []
        if not isinstance(ms, list):
            break
        out.extend([m for m in ms if isinstance(m, dict)])
        cursor = body.get("cursor")
        if not cursor or not ms:
            break
    return out


def duration_sec(sport: str) -> int:
    return {
        "tennis": 6 * 3600,
        "pro football": int(4.5 * 3600),
        "college football": int(4.5 * 3600),
        "basketball": int(3.5 * 3600),
        "hockey": int(3.5 * 3600),
        "baseball": 4 * 3600,
        "soccer": int(2.5 * 3600),
        "mma": int(1.5 * 3600),
    }.get(sport, 4 * 3600)


def pull_kalshi_series(
    series: str,
    sport: str,
    league: str,
    kind: str,
    *,
    limit: int,
    done: dict,
) -> list[dict]:
    markets = list_series_markets(series)
    # newest first
    markets.sort(key=lambda m: str(m.get("close_time") or ""), reverse=True)
    rows: list[dict] = []
    considered = 0
    for m in markets:
        if len(rows) >= limit:
            break
        ticker = str(m.get("ticker") or "")
        if not ticker or ticker in done:
            if ticker in done and done[ticker].get("usable"):
                rows.append(done[ticker])
            continue
        occ = m.get("occurrence_datetime") or m.get("expected_expiration_time")
        t0_ts = parse_ts(occ)
        close_ts = parse_ts(m.get("close_time"))
        if not t0_ts or not close_ts:
            continue
        if t0_ts >= close_ts - 60:
            # occurrence at/after close → not a start clock on this book
            continue
        considered += 1
        end_ts = min(close_ts + 300, t0_ts + duration_sec(sport))
        path = fetch_path(series, ticker, t0_ts, end_ts)
        metrics = side_metrics(path, t0_ts)
        row = {
            "ticker": ticker,
            "event_ticker": m.get("event_ticker") or "",
            "title": m.get("title") or "",
            "series": series,
            "sport": sport,
            "league": league,
            "kind": kind,
            "t0_ts": t0_ts,
            "close_ts": close_ts,
            "result": str(m.get("result") or "").lower(),
            "source": "kalshi_yes_ask_1m",
            "usable": bool(metrics),
            "path_n": len(path),
        }
        if metrics:
            row.update(metrics)
            role = None
            rows.append(row)
            append_jsonl(SIDE_JSONL, row)
            done[ticker] = row
        else:
            row["usable"] = False
            append_jsonl(SIDE_JSONL, row)
            done[ticker] = row
    _out(f"  {series}: usable_new_or_cached={len(rows)} considered≈{considered} listed={len(markets)}")
    return [r for r in rows if r.get("usable")]


def pair_event_sides(sides: list[dict]) -> list[dict]:
    bags: dict[str, list] = defaultdict(list)
    for s in sides:
        if s.get("kind") != "moneyline":
            continue
        et = str(s.get("event_ticker") or "")
        if not et:
            continue
        bags[et].append(s)
    pairs = []
    for et, ms in bags.items():
        if len(ms) < 2:
            continue
        ms = sorted(ms, key=lambda r: float(r.get("t0_px") or 0), reverse=True)
        fav, dog = ms[0], ms[1]
        if abs(float(fav["t0_px"]) - float(dog["t0_px"])) < 1e-9:
            continue
        pairs.append({
            "event_ticker": et,
            "sport": fav.get("sport"),
            "league": fav.get("league"),
            "kind": "moneyline",
            "source": fav.get("source"),
            "fav_title": fav.get("title"),
            "dog_title": dog.get("title"),
            "t0_fav": fav.get("t0_px"),
            "t0_dog": dog.get("t0_px"),
            "dip_fav": fav.get("max_dip"),
            "dip_dog": dog.get("max_dip"),
            "c0": round(float(fav["t0_px"]) + float(dog["t0_px"]), 4),
            "both_hit": {
                f"d{int(t * 100):02d}": bool(
                    float(fav["max_dip"]) + 1e-12 >= t
                    and float(dog["max_dip"]) + 1e-12 >= t
                )
                for t in THRESH
            },
            "opt_cost": {
                f"d{int(t * 100):02d}": (
                    round(float(fav["t0_px"]) + float(dog["t0_px"]) - 2 * t, 4)
                    if (
                        float(fav["max_dip"]) + 1e-12 >= t
                        and float(dog["max_dip"]) + 1e-12 >= t
                    )
                    else None
                )
                for t in THRESH
            },
        })
    return pairs


def fnum(x):
    s = str(x).strip().replace("$", "").replace("+", "").replace(",", "")
    if s in ("", "—", "-", "n/a", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def dense_html_path() -> Path | None:
    for path in DENSE_HTML_CANDIDATES:
        if path.is_file():
            return path
    return None


def load_dense_tennis_sides() -> tuple[list[dict], list[dict]]:
    path = dense_html_path()
    if path is None:
        return [], []
    raw = path.read_text(errors="replace")
    tables = re.findall(r"<table[^>]*>(.*?)</table>", raw, flags=re.I | re.S)
    if len(tables) < 6:
        return [], []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tables[5], flags=re.I | re.S)
    if not rows:
        return [], []
    hdr = [
        re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", "", c))).strip()
        for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], flags=re.I | re.S)
    ]
    sides = []
    pairs = []
    for tr in rows[1:]:
        cells = [
            re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.I | re.S)
        ]
        d = dict(zip(hdr, cells))
        if (d.get("Still live?") or "").lower() == "yes":
            continue
        ta, tb = fnum(d.get("T0 A")), fnum(d.get("T0 B"))
        da, db = fnum(d.get("Max dip A")), fnum(d.get("Max dip B"))
        match = d.get("Match") or ""
        venue = d.get("Venue") or ""
        if ta is not None and da is not None and 0.005 < ta < 0.995:
            sides.append({
                "ticker": f"dense:{match}:A",
                "title": d.get("Yes A") or "A",
                "sport": "tennis",
                "league": "ALL",
                "kind": "moneyline",
                "t0_px": ta,
                "max_dip": da,
                "source": f"dense_live_tape:{venue}",
                "usable": True,
                "hit": {f"d{int(t * 100):02d}": bool(da + 1e-12 >= t) for t in THRESH},
            })
        if tb is not None and db is not None and 0.005 < tb < 0.995:
            sides.append({
                "ticker": f"dense:{match}:B",
                "title": d.get("Yes B") or "B",
                "sport": "tennis",
                "league": "ALL",
                "kind": "moneyline",
                "t0_px": tb,
                "max_dip": db,
                "source": f"dense_live_tape:{venue}",
                "usable": True,
                "hit": {f"d{int(t * 100):02d}": bool(db + 1e-12 >= t) for t in THRESH},
            })
        if None not in (ta, tb, da, db) and 0.005 < ta < 0.995 and 0.005 < tb < 0.995:
            if ta >= tb:
                t0_fav, t0_dog, dip_fav, dip_dog = ta, tb, da, db
            else:
                t0_fav, t0_dog, dip_fav, dip_dog = tb, ta, db, da
            pairs.append({
                "event_ticker": f"dense:{match}",
                "sport": "tennis",
                "league": "ALL",
                "kind": "moneyline",
                "source": f"dense_live_tape:{venue}",
                "t0_fav": t0_fav,
                "t0_dog": t0_dog,
                "dip_fav": dip_fav,
                "dip_dog": dip_dog,
                "c0": round(ta + tb, 4),
                "both_hit": {
                    f"d{int(t * 100):02d}": bool(da + 1e-12 >= t and db + 1e-12 >= t)
                    for t in THRESH
                },
                "opt_cost": {
                    f"d{int(t * 100):02d}": (
                        round(ta + tb - 2 * t, 4)
                        if (da + 1e-12 >= t and db + 1e-12 >= t)
                        else None
                    )
                    for t in THRESH
                },
            })
    return sides, pairs


def pull_poly_tennis_sample(limit_events: int = 80) -> list[dict]:
    """ATP/WTA moneyline last-trade paths via Gamma + CLOB. Not Yes-ask."""
    sides: list[dict] = []
    seen = load_jsonl_map(POLY_JSONL, "ticker")
    for sport_key, league in (("atp", "ATP"), ("wta", "WTA")):
        time.sleep(SLEEP)
        code, body = http_get(f"{GBASE}/sports")
        # fall back: search recent closed events via public-search is weak; use series
        code, body = http_get(
            f"{GBASE}/events?series_slug={sport_key}&closed=true&limit={limit_events}"
        )
        events = body if isinstance(body, list) else (body.get("events") if isinstance(body, dict) else [])
        if not isinstance(events, list) or not events:
            # alternate: tag search
            code, body = http_get(
                f"{GBASE}/events?tag_slug={sport_key}&closed=true&limit={limit_events}"
            )
            events = body if isinstance(body, list) else []
        n_ev = 0
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            if n_ev >= limit_events // 2:
                break
            markets = ev.get("markets") or []
            ml = None
            for m in markets:
                if not isinstance(m, dict):
                    continue
                q = (m.get("question") or "") + " " + (m.get("groupItemTitle") or "")
                # primary match winner market usually has two player outcomes
                outcomes = m.get("outcomes")
                tokens = m.get("clobTokenIds")
                if isinstance(outcomes, str):
                    try:
                        outcomes = json.loads(outcomes)
                    except json.JSONDecodeError:
                        outcomes = []
                if isinstance(tokens, str):
                    try:
                        tokens = json.loads(tokens)
                    except json.JSONDecodeError:
                        tokens = []
                if not isinstance(outcomes, list) or not isinstance(tokens, list):
                    continue
                if len(outcomes) == 2 and len(tokens) == 2 and "vs" in (ev.get("title") or "").lower():
                    # skip props
                    blob = (m.get("question") or "").lower()
                    if any(x in blob for x in ("set ", "total", "spread", "o/u", "over", "under", "games")):
                        continue
                    if outcomes[0].lower() in ("yes", "no"):
                        continue
                    ml = (m, outcomes, tokens)
                    break
            if not ml:
                continue
            m, outcomes, tokens = ml
            t0_ts = parse_ts(
                ev.get("startTime")
                or m.get("gameStartTime")
                or ev.get("startDate")
            )
            if not t0_ts:
                continue
            n_ev += 1
            end_ts = t0_ts + 6 * 3600
            start_ts = t0_ts - 45 * 60
            for name, tok in zip(outcomes, tokens):
                key = f"poly:{tok}"
                if key in seen and seen[key].get("usable"):
                    sides.append(seen[key])
                    continue
                q = urllib.parse.urlencode({
                    "market": tok,
                    "startTs": start_ts,
                    "endTs": end_ts,
                    "fidelity": 1,
                })
                time.sleep(SLEEP)
                code, body = http_get(f"{CLOB}/prices-history?{q}")
                hist = body.get("history") if isinstance(body, dict) else []
                path = []
                for pt in hist or []:
                    if not isinstance(pt, dict):
                        continue
                    try:
                        path.append([int(pt.get("t")), float(pt.get("p"))])
                    except (TypeError, ValueError):
                        continue
                path.sort()
                metrics = side_metrics(path, t0_ts)
                row = {
                    "ticker": key,
                    "event_ticker": str(ev.get("slug") or ev.get("id") or ""),
                    "title": str(name),
                    "sport": "tennis",
                    "league": league,
                    "kind": "moneyline",
                    "t0_ts": t0_ts,
                    "source": "poly_clob_last_trade",
                    "usable": bool(metrics),
                    "path_n": len(path),
                }
                if metrics:
                    row.update(metrics)
                    sides.append(row)
                append_jsonl(POLY_JSONL, row)
                seen[key] = row
        _out(f"  poly {league}: events_used≈{n_ev} sides_usable={sum(1 for s in sides if s.get('league')==league)}")
    return [s for s in sides if s.get("usable")]


def pctile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    if len(ys) == 1:
        return float(ys[0])
    k = (len(ys) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(ys[int(k)])
    return float(ys[f] * (c - k) + ys[c] * (k - f))


def summarize_dips(sides: list[dict]) -> dict:
    dips = [float(s["max_dip"]) for s in sides if s.get("max_dip") is not None]
    if not dips:
        return {"n": 0}
    hits = {
        f"d{int(t * 100):02d}": round(
            100.0 * sum(1 for s in sides if float(s["max_dip"]) + 1e-12 >= t) / len(sides),
            1,
        )
        for t in THRESH
    }
    return {
        "n": len(dips),
        "mean": round(st.mean(dips), 4),
        "median": round(st.median(dips), 4),
        "stdev": round(st.pstdev(dips), 4) if len(dips) > 1 else 0.0,
        "percentiles": {f"p{p}": round(pctile(dips, p) or 0.0, 4) for p in PCTILES},
        "hit_pct": hits,
    }


def summarize_pairs(pairs: list[dict]) -> dict:
    if not pairs:
        return {"n": 0}
    out = {"n": len(pairs), "both_hit_pct": {}, "opt_cost_when_both": {}}
    for t in THRESH:
        key = f"d{int(t * 100):02d}"
        both = [p for p in pairs if (p.get("both_hit") or {}).get(key)]
        out["both_hit_pct"][key] = round(100.0 * len(both) / len(pairs), 1)
        costs = [float(p["opt_cost"][key]) for p in both if p.get("opt_cost", {}).get(key) is not None]
        if costs:
            out["opt_cost_when_both"][key] = {
                "n": len(costs),
                "mean_cost": round(st.mean(costs), 4),
                "median_cost": round(st.median(costs), 4),
                "mean_edge_vs_1": round(1.0 - st.mean(costs), 4),
            }
        else:
            out["opt_cost_when_both"][key] = {"n": 0}
    return out


def slice_table(sides: list[dict]) -> list[dict]:
    bags: dict[tuple, list] = defaultdict(list)
    for s in sides:
        sport = str(s.get("sport") or "ALL")
        kind = str(s.get("kind") or "ALL")
        band = decile_of(s.get("t0_px")) or "NA"
        bags[(sport, kind, band)].append(s)
        bags[(sport, kind, "ALL")].append(s)
        bags[(sport, "ALL", band)].append(s)
        bags[(sport, "ALL", "ALL")].append(s)
        bags[("ALL", kind, band)].append(s)
        bags[("ALL", kind, "ALL")].append(s)
        bags[("ALL", "ALL", band)].append(s)
        bags[("ALL", "ALL", "ALL")].append(s)
    rows = []
    for (sport, kind, band), bag in sorted(
        bags.items(),
        key=lambda kv: (
            0 if kv[0][0] == "ALL" else 1,
            kv[0][0],
            0 if kv[0][1] == "ALL" else 1,
            kv[0][1],
            0 if kv[0][2] == "ALL" else 1,
            kv[0][2],
        ),
    ):
        if band == "NA":
            continue
        summ = summarize_dips(bag)
        if summ["n"] <= 0:
            continue
        rows.append({
            "sport": sport,
            "kind": kind,
            "decile": band,
            **summ,
        })
    return rows


def role_overlay(sides: list[dict], pairs: list[dict]) -> dict:
    """Favorite vs dog drop comparison using paired moneyline books."""
    fav_sides = []
    dog_sides = []
    for p in pairs:
        fav_sides.append({"t0_px": p["t0_fav"], "max_dip": p["dip_fav"]})
        dog_sides.append({"t0_px": p["t0_dog"], "max_dip": p["dip_dog"]})
    near = [s for s in sides if decile_of(s.get("t0_px")) in ("40-49", "50-59")]
    far = [s for s in sides if decile_of(s.get("t0_px")) in ("0-9", "10-19", "80-89", "90-99")]
    return {
        "favorite": summarize_dips(fav_sides),
        "dog": summarize_dips(dog_sides),
        "near_50_deciles_40_59": summarize_dips(near),
        "far_deciles_0_19_or_80_99": summarize_dips(far),
    }


def fmt_px(x) -> str:
    if x is None:
        return "—"
    return f"{100.0 * float(x):.1f}¢"


def html_report(payload: dict) -> str:
    books = payload.get("books") or {}
    rows_html = []
    for book_name, book in books.items():
        for r in book.get("slices") or []:
            if r.get("decile") == "ALL" and r.get("kind") != "ALL":
                # keep sport/kind ALL-decile and full detail deciles; skip noise later in filter
                pass
            pcts = r.get("percentiles") or {}
            hits = r.get("hit_pct") or {}
            rows_html.append(
                "<tr>"
                f"<td>{esc(book_name)}</td>"
                f"<td>{esc(r.get('sport'))}</td>"
                f"<td>{esc(r.get('kind'))}</td>"
                f"<td>{esc(r.get('decile'))}</td>"
                f"<td class='num'>{r.get('n')}</td>"
                f"<td class='num'>{fmt_px(r.get('mean'))}</td>"
                f"<td class='num'>{fmt_px(r.get('median'))}</td>"
                f"<td class='num'>{fmt_px(pcts.get('p10'))}</td>"
                f"<td class='num'>{fmt_px(pcts.get('p25'))}</td>"
                f"<td class='num'>{fmt_px(pcts.get('p75'))}</td>"
                f"<td class='num'>{fmt_px(pcts.get('p90'))}</td>"
                f"<td class='num'>{fmt_px(pcts.get('p95'))}</td>"
                f"<td class='num'>{hits.get('d05', '—')}</td>"
                f"<td class='num'>{hits.get('d10', '—')}</td>"
                f"<td class='num'>{hits.get('d15', '—')}</td>"
                f"<td class='num'>{hits.get('d20', '—')}</td>"
                f"<td class='num'>{hits.get('d25', '—')}</td>"
                "</tr>"
            )
    pair_blocks = []
    for book_name, book in books.items():
        ps = book.get("pairs_summary") or {}
        if not ps.get("n"):
            continue
        lines = [f"<h3>{esc(book_name)} — both sides dip (N pairs={ps['n']})</h3><ul>"]
        for t in THRESH:
            key = f"d{int(t * 100):02d}"
            hit = (ps.get("both_hit_pct") or {}).get(key)
            cost = (ps.get("opt_cost_when_both") or {}).get(key) or {}
            if cost.get("n"):
                lines.append(
                    f"<li>Both ≥{int(t*100)}¢: {hit}% of pairs. "
                    f"When both hit, optimistic buy-at-T0−{int(t*100)}¢ mean cost "
                    f"{fmt_px(cost.get('mean_cost'))} "
                    f"(median {fmt_px(cost.get('median_cost'))}), "
                    f"mean edge vs $1 = {fmt_px(cost.get('mean_edge_vs_1'))} "
                    f"(N={cost.get('n')}).</li>"
                )
            else:
                lines.append(f"<li>Both ≥{int(t*100)}¢: {hit}% of pairs. No both-hit fills.</li>")
        lines.append("</ul>")
        pair_blocks.append("\n".join(lines))

    case = payload.get("kolar_moeller") or {}
    case_html = ""
    if case:
        case_html = (
            "<h2>Case: Kolar vs Moeller (Polymarket CLOB last-trade)</h2>"
            f"<p>{esc(case.get('note'))}</p>"
            "<ul>"
            + "".join(
                f"<li>{esc(s.get('name'))}: T0≈{fmt_px(s.get('t0_px'))}, "
                f"min after T0={fmt_px(s.get('min_px'))}, "
                f"max dip={fmt_px(s.get('max_dip'))}</li>"
                for s in case.get("sides") or []
            )
            + "</ul>"
        )

    overlay_bits = []
    for book_name, book in books.items():
        ov = book.get("role_overlay") or {}
        if not ov:
            continue
        overlay_bits.append(f"<h3>{esc(book_name)}</h3><ul>")
        for label, key in (
            ("Favorites (paired)", "favorite"),
            ("Dogs (paired)", "dog"),
            ("Near coin-flip T0 (40–59¢)", "near_50_deciles_40_59"),
            ("Lopsided T0 (0–19 or 80–99¢)", "far_deciles_0_19_or_80_99"),
        ):
            s = ov.get(key) or {}
            if not s.get("n"):
                continue
            pcts = s.get("percentiles") or {}
            overlay_bits.append(
                f"<li>{esc(label)}: N={s['n']}, mean dip {fmt_px(s.get('mean'))}, "
                f"median {fmt_px(s.get('median'))}, "
                f"p25 {fmt_px(pcts.get('p25'))}, p75 {fmt_px(pcts.get('p75'))}, "
                f"p90 {fmt_px(pcts.get('p90'))}</li>"
            )
        overlay_bits.append("</ul>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Drop from T0 by decile — 2026-11-02</title>
<style>
body {{ font-family: Georgia, 'Times New Roman', serif; margin: 1.5rem; color: #1a1a1a; background: #f7f4ef; }}
h1,h2,h3 {{ font-family: 'Segoe UI', system-ui, sans-serif; }}
.muted {{ color: #555; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.85rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.35rem 0.45rem; text-align: left; }}
th {{ background: #ebe4d8; position: sticky; top: 0; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.note {{ max-width: 52rem; }}
.swipe {{ overflow-x: auto; }}
</style>
{report_page_extras.SORTABLE_TH_CSS}
</head>
<body>
<h1>Max drop from starting price (T0), by sport / bet / decile</h1>
<p class="muted">Written {esc(payload.get('written_at_et'))}. Research only. Not gold. Not DailyRun.</p>
<div class="note">
<p><strong>Asked:</strong> {esc(ASKED)}</p>
<p>{esc(PLAIN)}</p>
<p>{esc(payload.get('limitation') or '')}</p>
</div>
{case_html}
<h2>Favorite / dog / near-50 overlay</h2>
{''.join(overlay_bits)}
<h2>Gap idea: both sides eventually cheapen by T</h2>
<p class="note">Optimistic: if both max-dips clear T, assume fills at exactly T0−T each
(no queue, no fee). Real fills are worse. Edge vs $1 ignores the ~2¢ fee stack Paul floated.</p>
{''.join(pair_blocks)}
<h2>Drop distribution table</h2>
<p class="muted">{report_page_extras.SWIPE_NOTE_HTML}</p>
<div class="swipe">
<table class="sortable">
<thead><tr>
<th>Book</th><th>Sport</th><th>Bet</th><th>T0 decile</th><th class="num">N</th>
<th class="num">Mean dip</th><th class="num">Median</th>
<th class="num">p10</th><th class="num">p25</th><th class="num">p75</th>
<th class="num">p90</th><th class="num">p95</th>
<th class="num">Hit≥5¢%</th><th class="num">Hit≥10¢%</th><th class="num">Hit≥15¢%</th>
<th class="num">Hit≥20¢%</th><th class="num">Hit≥25¢%</th>
</tr></thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>
</div>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def kolar_moeller_case() -> dict:
    time.sleep(SLEEP)
    code, body = http_get(f"{GBASE}/events?slug=atp-kolar-moeller-2026-11-02")
    events = body if isinstance(body, list) else []
    if not events:
        return {}
    ev = events[0]
    t0_ts = parse_ts(ev.get("startTime") or ev.get("startDate"))
    if not t0_ts:
        return {}
    markets = ev.get("markets") or []
    ml = None
    for m in markets:
        outcomes = m.get("outcomes")
        tokens = m.get("clobTokenIds")
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except json.JSONDecodeError:
                continue
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except json.JSONDecodeError:
                continue
        if (
            isinstance(outcomes, list)
            and isinstance(tokens, list)
            and len(outcomes) == 2
            and outcomes[0].lower() not in ("yes", "no")
            and "vs" in (m.get("question") or ev.get("title") or "").lower()
            and not any(
                x in (m.get("question") or "").lower()
                for x in ("set ", "total", "spread", "o/u", "over", "under", "games")
            )
        ):
            ml = (outcomes, tokens)
            break
    if not ml:
        return {}
    outcomes, tokens = ml
    sides = []
    for name, tok in zip(outcomes, tokens):
        q = urllib.parse.urlencode({
            "market": tok,
            "startTs": t0_ts - 3600,
            "endTs": t0_ts + 6 * 3600,
            "fidelity": 1,
        })
        time.sleep(SLEEP)
        code, body = http_get(f"{CLOB}/prices-history?{q}")
        hist = body.get("history") if isinstance(body, dict) else []
        path = []
        for pt in hist or []:
            try:
                path.append([int(pt["t"]), float(pt["p"])])
            except Exception:
                continue
        path.sort()
        metrics = side_metrics(path, t0_ts)
        if not metrics:
            continue
        sides.append({"name": name, **metrics})
    return {
        "note": (
            "Polymarket listed start 2026-11-02 5:55 PM America/New_York. "
            "CLOB last-trade (not Yes-ask). Matches Paul's window: Kolar ~29–30¢ "
            "into the match, Moeller high-70s with a mid-60s print around 6:16 PM ET. "
            "A simultaneous −10¢ buy on both is not guaranteed — Moeller's max dip "
            "from the listed T0 was only ~7–8¢ on this last-trade tape."
        ),
        "t0_ts": t0_ts,
        "sides": sides,
    }


def build_book(name: str, sides: list[dict], pairs: list[dict] | None = None) -> dict:
    pairs = pairs if pairs is not None else pair_event_sides(sides)
    return {
        "name": name,
        "n_sides": len(sides),
        "n_pairs": len(pairs),
        "overall": summarize_dips(sides),
        "pairs_summary": summarize_pairs(pairs),
        "role_overlay": role_overlay(sides, pairs),
        "slices": slice_table(sides),
    }


def run_pull(args: argparse.Namespace) -> dict:
    DROP_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = load_jsonl_map(SIDE_JSONL, "ticker")
    kalshi_sides: list[dict] = []

    series_list = list(SERIES_META)
    if args.tennis_only:
        series_list = [s for s in series_list if s[1] == "tennis"]
    if args.series:
        want = set(args.series)
        series_list = [s for s in series_list if s[0] in want]

    write_status({"running": True, "phase": "kalshi_pull", "series": [s[0] for s in series_list]})
    for series, sport, league, kind in series_list:
        _out(f"pull {series} ({sport}/{league}/{kind}) limit={args.per_series}")
        rows = pull_kalshi_series(
            series, sport, league, kind, limit=args.per_series, done=done
        )
        kalshi_sides.extend(rows)
        write_status({
            "running": True,
            "phase": "kalshi_pull",
            "current_series": series,
            "n_kalshi_sides": len(kalshi_sides),
        })

    dense_sides, dense_pairs = load_dense_tennis_sides()
    _out(f"dense tennis sides={len(dense_sides)} pairs={len(dense_pairs)}")

    poly_sides: list[dict] = []
    if args.poly:
        write_status({"running": True, "phase": "poly_pull"})
        poly_sides = pull_poly_tennis_sample(limit_events=args.poly_events)

    case = kolar_moeller_case()

    books = {}
    if dense_sides:
        books["A_dense_tennis_live_tape"] = build_book(
            "A_dense_tennis_live_tape", dense_sides, dense_pairs
        )
    if kalshi_sides:
        books["B_kalshi_yes_ask"] = build_book("B_kalshi_yes_ask", kalshi_sides)
    if poly_sides:
        books["C_poly_clob_last_trade"] = build_book("C_poly_clob_last_trade", poly_sides)

    payload = {
        "written_at_et": now_et().strftime("%Y-%m-%d %H:%M %Z"),
        "asked": ASKED,
        "plain": PLAIN,
        "limitation": (
            "Optimistic both-side fills at exactly T0−T ignore queue position, "
            "ask/trade gap, and fees. Kalshi skips markets whose occurrence clock "
            "is at/after close. Book A is tennis-only dense live tape (Oct 21). "
            "Book C is Polymarket last-trade, not Yes-ask. Local price_memory is "
            "not on this cloud VM."
        ),
        "kolar_moeller": case,
        "books": books,
        "pull": {
            "per_series": args.per_series,
            "tennis_only": args.tennis_only,
            "series": [s[0] for s in series_list],
            "n_kalshi_sides": len(kalshi_sides),
            "n_dense_sides": len(dense_sides),
            "n_poly_sides": len(poly_sides),
        },
    }
    text = html_report(payload)
    JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PAGE.write_text(text, encoding="utf-8")
    try:
        STAMP.mkdir(parents=True, exist_ok=True)
        DRIVE_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        DRIVE_PAGE.write_text(text, encoding="utf-8")
    except OSError:
        pass
    write_status({"running": False, "phase": "done", "page": str(PAGE)})
    _out(f"wrote {PAGE}")
    _out(f"wrote {JSON_OUT}")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-series", type=int, default=60, help="Max usable sides per Kalshi series")
    ap.add_argument("--tennis-only", action="store_true")
    ap.add_argument("--poly", action="store_true", help="Also pull Polymarket tennis last-trade sample")
    ap.add_argument("--poly-events", type=int, default=40)
    ap.add_argument("--series", nargs="*", help="Optional Kalshi series tickers")
    ap.add_argument("--report-only", action="store_true", help="Rebuild report from jsonl + dense HTML")
    args = ap.parse_args()
    if args.report_only:
        done = load_jsonl_map(SIDE_JSONL, "ticker")
        kalshi_sides = [r for r in done.values() if r.get("usable")]
        dense_sides, dense_pairs = load_dense_tennis_sides()
        poly_done = load_jsonl_map(POLY_JSONL, "ticker")
        poly_sides = [r for r in poly_done.values() if r.get("usable")]
        books = {}
        if dense_sides:
            books["A_dense_tennis_live_tape"] = build_book(
                "A_dense_tennis_live_tape", dense_sides, dense_pairs
            )
        if kalshi_sides:
            books["B_kalshi_yes_ask"] = build_book("B_kalshi_yes_ask", kalshi_sides)
        if poly_sides:
            books["C_poly_clob_last_trade"] = build_book("C_poly_clob_last_trade", poly_sides)
        payload = {
            "written_at_et": now_et().strftime("%Y-%m-%d %H:%M %Z"),
            "asked": ASKED,
            "plain": PLAIN,
            "limitation": (
                "Report rebuilt from on-disk jsonl. Optimistic fills. "
                "Kalshi occurrence-before-close filter. Book C last-trade only."
            ),
            "kolar_moeller": kolar_moeller_case(),
            "books": books,
            "pull": {
                "report_only": True,
                "n_kalshi_sides": len(kalshi_sides),
                "n_dense_sides": len(dense_sides),
                "n_poly_sides": len(poly_sides),
            },
        }
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        PAGE.write_text(html_report(payload), encoding="utf-8")
        _out(f"wrote {PAGE}")
        return
    run_pull(args)


if __name__ == "__main__":
    main()
