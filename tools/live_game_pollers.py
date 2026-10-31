"""One Python process for live matched games. No secrets in the log.

The supervisor looks about every 60 seconds and keeps one --poll-all poller
plus one Lock gap (A) sender alive. It does not spawn --poll-one helpers.
That wait is not the compare rate. A game is live when now is at or after
the listed start and before start plus a typical length. Phase unknown is not live.

Tennis is in-match only. Kalshi+Polymarket twins are not forever-on. The
merged poller subscribes TENNIS_PRE_START_MIN (5) minutes before trusted/listed
start so B/E game-start still has books, stays through in-play, and drops the
game on settle, after a typical length, or 30 minutes after listed start if
the match never went live. Tomorrow's listed tennis is not subscribed today.

The poller holds four shared websockets (Kalshi, Gemini, Polymarket US, Novig)
and writes per-game last prices. It does not place lock bets. Lock gap (A) is
live_lock_sender.py. Tennis crossover (B) is its own Python and reads price
memory files. A poller crash must not kill B.

HTTP seeds, HTTP fallbacks, and the catalog scan share tools/venue_pace.py.
A websocket update does not wait on that pace.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_quote_stream  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402
import price_memory  # noqa: E402
import stream_health  # noqa: E402
import venue_pace  # noqa: E402
import win_hidden  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, PYCACHE_DIR, RAW_DIR as RAW  # noqa: E402
JOBS = RAW / "live_jobs"
STATE = RAW / "live_state"
STATUS = RAW / "live_pollers_status.json"
MOVES = RAW / "live_moves.jsonl"
STOP = RAW / "live_supervisor.stop"
LOG = RAW / "live_supervisor.log"
LOCK_HINTS = RAW / "live_lock_hints"
POLL_ALL_PID = RAW / "live_poll_all.pid"
LOCK_SENDER_SCRIPT = ROOT / "tools" / "live_lock_sender.py"
ET = ZoneInfo("America/New_York")
POLL_SLEEP = 5
SUPERVISOR_SLEEP = 60
# Collapse a burst of ticks. Well under a second. Not the new-game check.
COALESCE_SEC = 0.05
PAGE_WRITE_BUDGET = 12

LIVE_HOURS = {
    "college football": 4.0,
    "pro football": 3.5,
    "pro baseball": 3.5,
    "soccer": 2.5,
    "pro hockey": 3.0,
    "mma": 5.0,
    "chess": 3.0,
    "tennis": 5.0,
}
# Tennis poller lead. B T0 *send* window is live_strategy_b.T0_GRACE_SEC after
# trusted start (30 min from 31 Oct 2026 tape). E/F/G still use
# live_t0_yes.t0_window (T0_LEAD_SEC=15 through T0_GRACE_SEC=300). slate_near_t0
# walks from 15 minutes before listed start. WHEN_LIVE is Novig's fee flag
# (OPEN_INGAME), not a spawn clock. Supervisor loop is 60s, so a 15s lead
# would miss T0. Unmatched books already used 5 minutes; twins use the same.
TENNIS_PRE_START_MIN = 5
TENNIS_NEVER_LIVE_MIN = 30
TENNIS_SETTLED_PERIODS = frozenset({"POST", "FT", "FINAL", "ENDED"})
TENNIS_SETTLED_STATUSES = frozenset({
    "SETTLED", "CLOSED", "FINALIZED", "FINAL", "ENDED", "COMPLETE", "COMPLETED",
})
TENNIS_LIVE_STATUSES = frozenset({"OPEN_INGAME", "INPLAY", "IN_PLAY", "LIVE"})
SPORT_ORDER = [
    "college football",
    "pro football",
    "pro baseball",
    "soccer",
    "pro hockey",
    "mma",
    "chess",
]


def _send_line() -> str:
    """Supervisor status copy. Poller quote path must not import live_lock_orders."""
    import live_lock_orders

    return live_lock_orders.send_line()


def _orders_note() -> str:
    return f"1 contract when net <= {_send_line()}"


def _plan_note() -> str:
    return (
        f"One contract when net is ${_send_line()} or less. The thinner book posts first. "
        "If exactly one fills, new pairs stop and a leftover watch may buy the missed ask "
        f"if it is still under the {_send_line()} cap. The 2s wait is only Kalshi shard-404 retries. "
        "Pairs under $1 that earn less than $0.05 stay on the page. They do not ping the phone."
    )


def now_et() -> datetime:
    return datetime.now(ET)


def iso_now() -> str:
    return now_et().isoformat()


def job_deadline_iso() -> str | None:
    return None


def past_job_deadline(moment: datetime | None = None) -> bool:
    return False


def keep_running() -> bool:
    return not STOP.exists()


def log(msg: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    line = f"{iso_now()} {msg}\n"
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line)


def load_scan():
    path = STAMP / "overnight_scan.py"
    spec = importlib.util.spec_from_file_location("overnight_scan_live", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pid_alive(pid: int) -> bool:
    """True when the process exists. Does not signal or stop it."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def game_key(sport: str, game: dict, scan) -> str:
    codes = scan.game_codes(game) or "game"
    date = str(game.get("date") or "")
    raw = f"{sport}_{codes}_{date}".lower()
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_")


def fallback_title(game: dict, scan) -> str:
    title = game.get("title_gemini") or game.get("title_kalshi")
    if title:
        return str(title)
    teams = game.get("teams") or game.get("codes") or []
    if isinstance(teams, list) and teams:
        return " vs ".join(str(t) for t in teams)
    return scan.game_codes(game) or "unnamed"


def _kalshi_series_kind(prefix: str) -> str | None:
    """Longest token first so TEAMTOTAL is not treated as TOTAL."""
    up = str(prefix or "").upper()
    for token in ("TEAMTOTAL", "SPREAD", "TOTAL", "GAME"):
        if token in up:
            return token
    return None


def _gemini_type_suffix(ticker: str) -> str | None:
    up = str(ticker or "").upper()
    for suffix in ("-TT", "-M", "-S", "-T"):
        if up.endswith(suffix):
            return suffix[1:]
    return None


# Tennis Kalshi spread series are GSPREAD / SSPREAD / GAMESPREAD, not MATCH→SPREAD.
# Football GAME→SPREAD would mint the nonexistent KXATPSPREAD ticker.
TENNIS_SPREAD_SERIES_TOKENS = ("GSPREAD", "SSPREAD", "GAMESPREAD")


def tennis_spread_siblings(ticker: str) -> list[str]:
    """MATCH ↔ game/set spread series that share the same date+player tail."""
    head, sep, tail = str(ticker or "").partition("-")
    prefix = head.upper()
    rest = (sep + tail) if sep else ""
    out: list[str] = []
    if "MATCH" in prefix and "SPREAD" not in prefix:
        for dst in TENNIS_SPREAD_SERIES_TOKENS:
            out.append(prefix.replace("MATCH", dst, 1) + rest)
        return out
    for src in TENNIS_SPREAD_SERIES_TOKENS:
        if src not in prefix:
            continue
        out.append(prefix.replace(src, "MATCH", 1) + rest)
        for dst in TENNIS_SPREAD_SERIES_TOKENS:
            if dst != src:
                out.append(prefix.replace(src, dst, 1) + rest)
        return out
    return out


def expand_sibling_tickers(kalshi: list[str], gemini: list[str], sport: str = "") -> tuple[list[str], list[str]]:
    """If the catalog only listed moneyline, also try spread, total, team-total siblings.

    Does not drop moneyline or spread. Tennis MATCH books also try GSPREAD /
    SSPREAD / GAMESPREAD. Tennis totals stay off this tape. Missing sibling
    HTTP replies are empty events, not a crash.
    Kalshi: KXNFLGAME / KXNFLSPREAD / KXNFLTOTAL / KXNFLTEAMTOTAL.
    Gemini: -M / -S / -T / -TT (tennis, if listed, only -M / -S).
    """
    k_out = [t for t in kalshi if t]
    g_out = [t for t in gemini if t]
    seen_k = {t.upper() for t in k_out}
    seen_g = {t.upper() for t in g_out}

    def add_k(ticker: str) -> None:
        if ticker and ticker.upper() not in seen_k:
            seen_k.add(ticker.upper())
            k_out.append(ticker)

    def add_g(ticker: str) -> None:
        if ticker and ticker.upper() not in seen_g:
            seen_g.add(ticker.upper())
            g_out.append(ticker)

    if str(sport or "").strip().lower() == "tennis":
        for ticker in list(k_out):
            for sib in tennis_spread_siblings(ticker):
                add_k(sib)
        for ticker in list(g_out):
            kind = _gemini_type_suffix(ticker)
            if kind not in ("M", "S"):
                continue
            stem = ticker[: -(len(kind) + 1)]
            add_g(f"{stem}-{'S' if kind == 'M' else 'M'}")
        return k_out, g_out

    k_sibs = ("GAME", "SPREAD", "TOTAL", "TEAMTOTAL")
    for ticker in list(k_out):
        head, sep, tail = ticker.partition("-")
        prefix = head.upper()
        if "MATCH" in prefix or "ATP" in prefix or "WTA" in prefix:
            continue
        src = _kalshi_series_kind(prefix)
        if not src:
            continue
        for dst in k_sibs:
            if dst == src:
                continue
            add_k(prefix.replace(src, dst, 1) + (sep + tail if sep else ""))
    g_sibs = ("M", "S", "T", "TT")
    for ticker in list(g_out):
        kind = _gemini_type_suffix(ticker)
        if not kind:
            continue
        stem = ticker[: -(len(kind) + 1)]
        for dst in g_sibs:
            if dst == kind:
                continue
            add_g(f"{stem}-{dst}")
    return k_out, g_out


def tickers_for_quotes(game: dict, scan, sport: str = "") -> tuple[list[str], list[str]]:
    """Catalog tickers plus synthesized spread/total/team-total siblings. Moneyline stays."""
    k, g = scan.tickers_of(game)
    return expand_sibling_tickers(list(k or []), list(g or []), sport)


def ticker_strings(game: dict, scan) -> list[str]:
    k, g = scan.tickers_of(game)
    return [t for t in (*k, *g) if t]


def start_from_tickers(game: dict, scan) -> datetime | None:
    found = []
    for text in ticker_strings(game, scan):
        when = price_memory.ticker_start(text)
        if when is not None:
            found.append(when)
    if not found:
        return None
    return min(found)


def start_from_saved(sport: str, game: dict, scan) -> datetime | None:
    codes = scan.game_codes(game)
    prefix = scan.SPORT_PREFIX.get(sport, "evt")
    path = RAW / f"{prefix}_{codes}_gemini.json"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'"startTime"\s*:\s*"([^"]+)"', text)
    if match:
        when = price_memory.parse_time(match.group(1))
        if when is not None:
            return when
    return price_memory.description_start(text[:8000])


def listed_start(sport: str, game: dict, scan) -> datetime | None:
    found = start_from_tickers(game, scan) or start_from_saved(sport, game, scan)
    if found is not None:
        return found
    for key in ("listed_start", "startTime", "start"):
        raw = game.get(key)
        if not raw:
            continue
        when = price_memory.parse_time(str(raw))
        if when is not None:
            return when
    return None


def iter_matched(scan):
    college = scan.load_college()
    for game in college:
        yield "college football", game
    sports = scan.load_sports()
    seen = {"college football"}
    for sport in list(SPORT_ORDER) + [name for name in sports if name not in seen]:
        if sport in seen:
            continue
        seen.add(sport)
        for game in sports.get(sport) or []:
            yield sport, game


def live_games(scan, moment: datetime | None = None) -> list[dict]:
    moment = moment or now_et()
    rows = []
    for sport, game in iter_matched(scan):
        hours = LIVE_HOURS.get(sport, 4.0)
        start = listed_start(sport, game, scan)
        if start is None:
            continue
        end = start + timedelta(hours=hours)
        if moment < start or moment >= end:
            continue
        key = game_key(sport, game, scan)
        rows.append({
            "key": key,
            "sport": sport,
            "game": game,
            "title": fallback_title(game, scan),
            "start": start.isoformat(),
            "live_until": end.isoformat(),
        })
    rows.extend(tennis_rows(scan))
    return rows


def _player_token(name: str) -> str:
    parts = [tok for tok in re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split() if tok]
    return parts[-1] if parts else ""


def tennis_identity(title: str, date: str) -> tuple:
    parts = re.split(r"\s+vs\.?\s+", title or "", maxsplit=1, flags=re.I)
    tokens = sorted(_player_token(part) for part in parts if part.strip())
    names = tuple(tok for tok in tokens if tok)
    if len(names) < 2:
        return ()
    return (str(date or ""), names)


def _tennis_codes(title: str, ticker: str, slug: str) -> list[str]:
    if ticker:
        return []
    parts = re.split(r"\s+vs\.?\s+", title or "", maxsplit=1, flags=re.I)
    codes = [_player_token(part)[:6] for part in parts if _player_token(part)]
    if len(codes) == 2:
        return ["".join(codes)]
    if slug:
        return [re.sub(r"[^a-z0-9]+", "", slug.lower())[:24] or "poly"]
    return ["game"]


def has_quote_venues(game: dict, scan) -> bool:
    """True when at least one venue we already poll has a book for this game."""
    k_tickers, g_tickers = scan.tickers_of(game)
    if k_tickers or g_tickers:
        return True
    preset = game.get("polymarket_markets")
    if isinstance(preset, list) and any(isinstance(row, dict) and row.get("slug") for row in preset):
        return True
    novig = game.get("novig_markets")
    if isinstance(novig, list) and any(isinstance(row, dict) and row.get("market_id") for row in novig):
        return True
    return False


def tennis_settled(match: dict) -> bool:
    """True when the catalog says the match is over (POST / settled / ended)."""
    if not isinstance(match, dict):
        return False
    period = str(match.get("period") or "").strip().upper()
    if period in TENNIS_SETTLED_PERIODS:
        return True
    status = str(match.get("status") or match.get("event_status") or "").strip().upper()
    if status in TENNIS_SETTLED_STATUSES:
        return True
    state = match.get("eventState")
    if isinstance(state, dict):
        period = str(state.get("period") or "").strip().upper()
        if period in TENNIS_SETTLED_PERIODS:
            return True
        if state.get("ended") is True:
            return True
        if state.get("live") is False and period in TENNIS_SETTLED_PERIODS:
            return True
    if match.get("ended") is True:
        return True
    return False


def tennis_in_play(match: dict) -> bool:
    """True when the catalog says the match is on court now."""
    if not isinstance(match, dict) or tennis_settled(match):
        return False
    status = str(match.get("status") or match.get("event_status") or "").strip().upper()
    if status in TENNIS_LIVE_STATUSES:
        return True
    period = str(match.get("period") or "").strip().upper()
    if period.startswith("S") and period not in {"SUS", "SUSP"}:
        return True
    if period in {"TB", "SET"}:
        return True
    state = match.get("eventState")
    if isinstance(state, dict) and state.get("live") is True:
        return True
    if match.get("live") is True:
        return True
    return False


def tennis_start_is_future_date(listed, date_text: str, moment: datetime) -> bool:
    """True when listed/trusted start's ET calendar date is after today."""
    today = moment.date()
    if listed is not None:
        try:
            when = listed.astimezone(ET) if getattr(listed, "tzinfo", None) else listed.replace(tzinfo=ET)
        except Exception:
            when = listed
        return when.date() > today
    date = str(date_text or "").strip()
    if len(date) >= 10:
        return date[:10] > today.isoformat()
    return False


def tennis_live_until_iso(listed) -> str | None:
    """Worker backstop: listed start plus a typical tennis length. None if unclocked."""
    if listed is None:
        return None
    hours = LIVE_HOURS.get("tennis", 5.0)
    return (listed + timedelta(hours=hours)).isoformat()


def tennis_collect_now(match: dict, is_twin: bool, moment: datetime | None = None) -> bool:
    """In-match tennis only. Twins use the same window as unmatched books.

    Window: TENNIS_PRE_START_MIN before trusted/listed start through in-play
    until settled, or LIVE_HOURS after start. If the match never went live,
    drop TENNIS_NEVER_LIVE_MIN after listed start. Do not collect a match
    whose listed/trusted start date is after today in America/New_York.
    is_twin is kept for callers; it no longer keeps a helper up all day.
    """
    del is_twin  # twins are not forever-on
    if not isinstance(match, dict):
        return False
    moment = moment or now_et()
    if tennis_settled(match):
        return False
    listed = polymarket_us_live.match_listed_start(match)
    if tennis_start_is_future_date(listed, str(match.get("date") or ""), moment):
        return False
    if tennis_in_play(match):
        return True
    hours = LIVE_HOURS.get("tennis", 5.0)
    if listed is not None:
        if moment < listed - timedelta(minutes=TENNIS_PRE_START_MIN):
            return False
        if moment >= listed + timedelta(hours=hours):
            return False
        if moment >= listed + timedelta(minutes=TENNIS_NEVER_LIVE_MIN):
            return False
        return True
    if match.get("event_ticker") or match.get("slug"):
        date = str(match.get("date") or "")
        today = moment.date().isoformat()
        yesterday = (moment - timedelta(days=1)).date().isoformat()
        return date in ("", today, yesterday)
    return False


def _tennis_row_from_match(scan, match: dict, fallback: str) -> dict | None:
    ticker = str(match.get("event_ticker") or "")
    slug = str(match.get("slug") or "")
    title = str(match.get("title") or ticker or slug)
    if not ticker and not slug:
        return None
    is_twin = bool(ticker and slug)
    if not tennis_collect_now(match, is_twin):
        return None
    listed = polymarket_us_live.match_listed_start(match)
    listed_iso = listed.isoformat() if listed is not None else ""
    kalshi: dict[str, object] = {}
    if ticker:
        if "SPREAD" in ticker.upper():
            kalshi["spread"] = ticker
        else:
            kalshi["game"] = ticker
    spread_ticker = str(match.get("spread_ticker") or "")
    if spread_ticker:
        kalshi["spread"] = spread_ticker
    extras = match.get("spread_tickers")
    if isinstance(extras, list):
        extra_list = [
            str(item) for item in extras
            if item and str(item) not in {kalshi.get("game"), kalshi.get("spread")}
        ]
        if extra_list:
            kalshi["spreads"] = extra_list
    game = {
        "date": match.get("date") or "",
        "title_kalshi": title,
        "kalshi": kalshi,
        "gemini": {},
        "listed_start": listed_iso,
        "codes": _tennis_codes(title, ticker, slug),
        "period": match.get("period") or "",
        "status": match.get("status") or match.get("event_status") or "",
        "startTime": match.get("startTime") or listed_iso,
    }
    poly_markets: list[dict] = []
    extras_poly = [
        row for row in (match.get("spread_markets") or [])
        if isinstance(row, dict) and row.get("slug")
    ]
    kind = str(match.get("kind") or "moneyline").strip().lower()
    if slug and kind != "spread":
        poly_markets.append(match)
    poly_markets.extend(extras_poly)
    if slug and kind == "spread" and not extras_poly:
        poly_markets.append(match)
    if poly_markets:
        game["polymarket_markets"] = poly_markets
    key = game_key("tennis", game, scan)
    return {
        "key": key,
        "sport": "tennis",
        "game": game,
        "title": title,
        "start": listed_iso or fallback,
        "listed_start": listed_iso,
        "period": match.get("period") or "",
        "live_until": tennis_live_until_iso(listed),
    }


def _novig_tennis_snapshot() -> list:
    """Novig ATP/WTA list in the background. Twins must not wait on this HTTP."""
    global _novig_tennis_loading
    with _novig_tennis_lock:
        rows = list(_novig_tennis_cache)
        kick = not _novig_tennis_loading
        if kick:
            _novig_tennis_loading = True

    def _load() -> None:
        global _novig_tennis_loading, _novig_tennis_cache
        try:
            found = novig_live.live_tennis_games()
            with _novig_tennis_lock:
                _novig_tennis_cache = found
        except Exception as exc:
            log(f"novig tennis list {type(exc).__name__}")
        finally:
            with _novig_tennis_lock:
                _novig_tennis_loading = False

    if kick:
        threading.Thread(target=_load, name="novig-tennis", daemon=True).start()
    return rows


def _novig_tennis_rows(scan, identities: set, seen_keys: set, fallback: str, extras=None) -> list[dict]:
    if extras is None:
        extras = _novig_tennis_snapshot()
    rows = []
    for item in extras:
        title = str(item.get("title") or "")
        ident = tennis_identity(title, str(item.get("date") or ""))
        if ident and ident in identities:
            continue
        status = str(item.get("status") or "").upper()
        if status != "OPEN_INGAME" and not tennis_collect_now(item, False):
            continue
        listed = polymarket_us_live.match_listed_start(item)
        listed_iso = listed.isoformat() if listed is not None else str(item.get("startTime") or "")
        game = {
            "date": item.get("date") or "",
            "title_kalshi": title,
            "kalshi": {},
            "gemini": {},
            "novig_markets": item.get("novig_markets") or [],
            "listed_start": listed_iso,
            "codes": _tennis_codes(title, "", str(item.get("event_id") or "")),
            "status": status,
            "event_status": status,
            "startTime": listed_iso,
        }
        if not has_quote_venues(game, scan):
            continue
        key = game_key("tennis", game, scan)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if ident:
            identities.add(ident)
        rows.append({
            "key": key,
            "sport": "tennis",
            "game": game,
            "title": title,
            "start": listed_iso or fallback,
            "listed_start": listed_iso,
            "status": status,
            "live_until": tennis_live_until_iso(listed),
        })
    return rows


def tennis_rows(scan, matches=None, novig_games=None) -> list[dict]:
    """Tennis moneylines and spreads in the live window, not only ATP twins.

    One row per match. Spread books (Kalshi GSPREAD / Poly / Novig) ride the
    same helper as the moneyline. Spawn TENNIS_PRE_START_MIN before trusted
    start; drop tomorrow, settled, and idle twins. Unclocked books still poll
    if the listed date is today or yesterday.
    """
    if matches is None:
        matches = polymarket_us_live.load_all_tennis_books(log)
    rows = []
    seen_keys: set[str] = set()
    identities: set[tuple] = set()
    fallback = (now_et() - timedelta(minutes=1)).isoformat()
    for match in matches:
        row = _tennis_row_from_match(scan, match, fallback)
        if row is None or row["key"] in seen_keys:
            continue
        ident = tennis_identity(str(row.get("title") or ""), str((row.get("game") or {}).get("date") or ""))
        if ident and ident in identities:
            continue
        seen_keys.add(row["key"])
        if ident:
            identities.add(ident)
        rows.append(row)
    rows.extend(_novig_tennis_rows(scan, identities, seen_keys, fallback, extras=novig_games if novig_games is not None else None))
    return rows


def _json_ready(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"not json {type(value).__name__}")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=_json_ready), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def append_move(row: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with venue_pace.FileLock(RAW / "live_moves.lock"):
        with MOVES.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def largest_abs_move(rows: list[dict]) -> str | None:
    best: Decimal | None = None
    for row in rows:
        raw = row.get("move")
        if raw in (None, ""):
            continue
        try:
            value = abs(Decimal(str(raw)))
        except Exception:
            continue
        if best is None or value > best:
            best = value
    if best is None:
        return None
    return format(best.quantize(Decimal("0.0001")), "f")


def _listed_numbers(scan, kalshi_events, gemini_events) -> dict[str, set[str]]:
    found = {"spread": set(), "total": set()}
    for source, events in (("kalshi", kalshi_events or []), ("gemini", gemini_events or [])):
        for view in scan.load_views(events, source):
            kind = view.get("kind")
            number = view.get("number")
            if kind in found and number not in (None, ""):
                found[kind].add(str(number))
    return found


def _polymarket_contracts(game: dict, scan=None, kalshi_events=None, gemini_events=None) -> list[dict]:
    numbers = _listed_numbers(scan, kalshi_events, gemini_events) if scan is not None else None
    markets = polymarket_us_live.markets_from_search(game, numbers)
    contracts = polymarket_us_live.blank_contracts(markets)
    polymarket_us_live.seed_books(contracts)
    return contracts


def _novig_contracts(game: dict, scan=None, kalshi_events=None, gemini_events=None, sport: str = "") -> list[dict]:
    numbers = _listed_numbers(scan, kalshi_events, gemini_events) if scan is not None else None
    contracts = novig_live.markets_from_game(game, numbers, sport)
    novig_live.seed_books(contracts)
    return contracts


def _log_check(scan, spec: dict, sport: str, title: str, game: dict, result: dict, started: str, t0: float, transport: str) -> None:
    """Record one comparison. Does not send a phone ping."""
    try:
        stream_health.record_check(
            spec["key"], sport, title, game, scan, result, started, iso_now(),
            (time.perf_counter() - t0) * 1000.0, transport,
        )
    except Exception as exc:
        log(f"health check log {spec.get('key')} {type(exc).__name__}")


def coverage_counts(scan, sport: str, kalshi_events, gemini_events, polymarket, novig) -> dict:
    """How many moneyline / spread / total books this poller actually quoted."""
    counts = {"moneyline": 0, "spread": 0, "total": 0}
    for venue, events in (("kalshi", kalshi_events or []), ("gemini", gemini_events or [])):
        for view in scan.load_views(events, venue):
            kind = str(view.get("kind") or "")
            if kind in counts:
                counts[kind] += 1
    for contract in list(polymarket or []) + list(novig or []):
        if not isinstance(contract, dict):
            continue
        kind = str(contract.get("kind") or "")
        if kind in counts:
            counts[kind] += 1
    counts["sport"] = sport
    return counts


def _record_coverage(spec: dict, counts: dict) -> None:
    """One coverage row per poller cycle. Does not place an order."""
    try:
        path = RAW / "spread_coverage.jsonl"
        row = {
            "at": iso_now(),
            "key": spec.get("key"),
            "sport": spec.get("sport") or counts.get("sport"),
            "game": spec.get("title") or "",
            "moneyline": int(counts.get("moneyline") or 0),
            "spread": int(counts.get("spread") or 0),
            "total": int(counts.get("total") or 0),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        pass


def poll_once(scan, spec: dict) -> None:
    game = spec["game"]
    sport = spec["sport"]
    k_tickers, g_tickers = tickers_for_quotes(game, scan, sport)
    if not has_quote_venues(game, scan):
        log(f"poll skip {spec['key']} no quote venue")
        state = read_json(STATE / f"{spec['key']}.json")
        state.update({
            "key": spec["key"],
            "last_poll": iso_now(),
            "last_abs_move": state.get("last_abs_move"),
            "note": "No Kalshi, Gemini, Polymarket US, or Novig book for this game.",
        })
        write_json(STATE / f"{spec['key']}.json", state)
        return
    gemini_events = [scan.fetch_gemini_event(t) for t in g_tickers]
    kalshi_events = [scan.fetch_kalshi_event(t) for t in k_tickers]
    polymarket = _polymarket_contracts(game, scan, kalshi_events, gemini_events)
    novig = _novig_contracts(game, scan, kalshi_events, gemini_events, sport)
    title = scan.game_title_from(gemini_events, kalshi_events, spec.get("title") or fallback_title(game, scan))
    sized = scan.book_size_example(gemini_events, "Gemini") or scan.book_size_example(kalshi_events, "Kalshi")
    if sized:
        log(f"book size {title} {sized}")
    started = iso_now()
    t0 = time.perf_counter()
    result = _compared(scan, game, kalshi_events, gemini_events, polymarket, novig)
    scan.ping_fresh_quotes(sport, title, game, result)
    fresh: list[dict] = []
    price_memory.remember_books(
        sport, title, scan.iso_now(), kalshi_events, gemini_events, game.get("date"), moves_out=fresh,
        polymarket_contracts=polymarket,
        novig_contracts=novig,
        listed_start=spec.get("listed_start") or game.get("listed_start") or "",
    )
    _write_lock_hint(spec, sport, title, game, result)
    abs_move = largest_abs_move(fresh)
    seen = iso_now()
    for row in fresh:
        if not row.get("drastic"):
            continue
        append_move({
            "seen_at": row.get("seen_at") or seen,
            "sport": sport,
            "game": title,
            "market_type": row.get("market_type"),
            "side": row.get("side"),
            "number": row.get("number"),
            "venue": row.get("venue"),
            "pay": row.get("pay"),
            "prior_price": row.get("prior_price"),
            "price": row.get("price"),
            "abs_move": str(abs(Decimal(str(row.get("move"))))),
            "pid": os.getpid(),
            "orders": "quotes only; Lock gap (A) is live_lock_sender.py",
            "plan_note": "Merged poller writes prices. It does not place lock bets.",
        })
    try:
        counts = coverage_counts(scan, sport, kalshi_events, gemini_events, polymarket, novig)
        _record_coverage(spec, counts)
    except Exception:
        counts = {}
    state = read_json(STATE / f"{spec['key']}.json")
    state.update({
        "key": spec["key"],
        "sport": sport,
        "game": title,
        "pid": os.getpid(),
        "last_poll": seen,
        "last_abs_move": abs_move if abs_move is not None else state.get("last_abs_move"),
        "last_abs_move_this_poll": abs_move,
        "books_moneyline": int((counts or {}).get("moneyline") or 0),
        "books_spread": int((counts or {}).get("spread") or 0),
        "books_total": int((counts or {}).get("total") or 0),
    })
    write_json(STATE / f"{spec['key']}.json", state)
    _log_check(scan, spec, sport, title, game, result, started, t0, "request")
    log(f"poll {spec['key']} {title} abs {abs_move} ml={state.get('books_moneyline')} spread={state.get('books_spread')} total={state.get('books_total')}")


def _match_from_spec(spec: dict) -> dict:
    """Rebuild a tennis match dict from the job file so the child can self-exit."""
    game = spec.get("game") if isinstance(spec.get("game"), dict) else {}
    poly = game.get("polymarket_markets")
    if isinstance(poly, list) and poly and isinstance(poly[0], dict):
        match = dict(poly[0])
    else:
        match = {}
    kalshi = game.get("kalshi") if isinstance(game.get("kalshi"), dict) else {}
    match.setdefault("event_ticker", kalshi.get("game") or "")
    match.setdefault("date", game.get("date") or spec.get("date") or "")
    match.setdefault(
        "startTime",
        game.get("startTime") or game.get("listed_start") or spec.get("start") or spec.get("listed_start") or "",
    )
    match.setdefault("listed_start", game.get("listed_start") or spec.get("listed_start") or match.get("startTime") or "")
    match.setdefault("period", game.get("period") or spec.get("period") or "")
    match.setdefault("status", game.get("status") or game.get("event_status") or spec.get("status") or "")
    return match


def _worker_should_stop(spec: dict, end) -> bool:
    if past_job_deadline() or STOP.exists():
        return True
    if str(spec.get("sport") or "").lower() == "tennis":
        match = _match_from_spec(spec)
        if tennis_settled(match):
            return True
        listed = polymarket_us_live.match_listed_start(match)
        if tennis_start_is_future_date(listed, str(match.get("date") or ""), now_et()):
            return True
        # Never-live 30 min and in-play/settle come from the supervisor's fresh
        # catalog, not this frozen job file (period/status do not update here).
    if end is not None and now_et() >= end:
        return True
    supervisor_pid = int(read_json(RAW / "live_supervisor.pid").get("pid") or spec.get("supervisor_pid") or 0)
    if supervisor_pid and not pid_alive(supervisor_pid):
        return True
    return False


def _record_poll(spec: dict, sport: str, title: str, abs_move: str | None, transport: str) -> None:
    state = read_json(STATE / f"{spec['key']}.json")
    state.update({
        "key": spec["key"],
        "sport": sport,
        "game": title,
        "pid": os.getpid(),
        "last_poll": iso_now(),
        "transport": transport,
        "last_abs_move": abs_move if abs_move is not None else state.get("last_abs_move"),
        "last_abs_move_this_poll": abs_move,
    })
    write_json(STATE / f"{spec['key']}.json", state)


def _compared(scan, game, kalshi_events, gemini_events, polymarket, novig=None) -> dict:
    result = scan.compare_payloads(game, kalshi_events, gemini_events)
    extra = polymarket_us_live.polymarket_candidates(scan, game, kalshi_events, gemini_events, polymarket or [])
    extra.extend(novig_live.novig_candidates(scan, game, kalshi_events, gemini_events, novig or [], polymarket or []))
    if extra:
        result["candidates"] = list(result.get("candidates") or []) + extra
    return result


def _after_quotes(scan, spec: dict, sport: str, title: str, game: dict, kalshi_events, gemini_events, transport: str, polymarket=None, novig=None) -> None:
    started = iso_now()
    t0 = time.perf_counter()
    result = _compared(scan, game, kalshi_events, gemini_events, polymarket, novig)
    scan.ping_fresh_quotes(sport, title, game, result)
    fresh: list[dict] = []
    price_memory.remember_books(
        sport, title, scan.iso_now(), kalshi_events, gemini_events, game.get("date"), moves_out=fresh,
        polymarket_contracts=polymarket,
        novig_contracts=novig,
        listed_start=spec.get("listed_start") or game.get("listed_start") or "",
    )
    _write_lock_hint(spec, sport, title, game, result)
    abs_move = largest_abs_move(fresh)
    seen = iso_now()
    for row in fresh:
        if not row.get("drastic"):
            continue
        append_move({
            "seen_at": row.get("seen_at") or seen,
            "sport": sport,
            "game": title,
            "market_type": row.get("market_type"),
            "side": row.get("side"),
            "number": row.get("number"),
            "venue": row.get("venue"),
            "pay": row.get("pay"),
            "prior_price": row.get("prior_price"),
            "price": row.get("price"),
            "abs_move": str(abs(Decimal(str(row.get("move"))))),
            "pid": os.getpid(),
            "orders": "quotes only; Lock gap (A) is live_lock_sender.py",
            "plan_note": "Merged poller writes prices. It does not place lock bets.",
        })
    _record_poll(spec, sport, title, abs_move, transport)
    _log_check(scan, spec, sport, title, game, result, started, t0, transport)


def _write_lock_hint(spec: dict, sport: str, title: str, game: dict, result: dict) -> None:
    """Per-game compare snapshot for the A sender. Does not place an order."""
    try:
        write_json(LOCK_HINTS / f"{spec['key']}.json", {
            "key": spec.get("key"),
            "sport": sport,
            "title": title,
            "game": game,
            "candidates": result.get("candidates") or [],
            "written_at": iso_now(),
            "pid": os.getpid(),
        })
    except Exception as exc:
        log(f"lock hint {spec.get('key')} {type(exc).__name__}")


def seed_quotes(scan, spec: dict):
    """One ordinary read so the streams know which contracts belong to this game."""
    game = spec["game"]
    sport = spec["sport"]
    k_tickers, g_tickers = tickers_for_quotes(game, scan, sport)
    if not has_quote_venues(game, scan):
        return None
    gemini_events = [scan.fetch_gemini_event(t) for t in g_tickers]
    kalshi_events = [scan.fetch_kalshi_event(t) for t in k_tickers]
    polymarket = _polymarket_contracts(game, scan, kalshi_events, gemini_events)
    novig = _novig_contracts(game, scan, kalshi_events, gemini_events, sport)
    title = scan.game_title_from(gemini_events, kalshi_events, spec.get("title") or fallback_title(game, scan))
    _after_quotes(scan, spec, sport, title, game, kalshi_events, gemini_events, "request", polymarket, novig)
    return title, game, kalshi_events, gemini_events, polymarket, novig


def worker(key: str) -> None:
    spec = read_json(JOBS / f"{key}.json")
    if not spec:
        log(f"worker {key} missing job file")
        return
    scan = load_scan()
    end = price_memory.parse_time(spec.get("live_until"))
    log(f"worker start {key} pid {os.getpid()} until {spec.get('live_until')}")
    if _worker_should_stop(spec, end):
        log(f"worker stop before seed {key}")
        return
    try:
        seeded = seed_quotes(scan, spec)
    except Exception as exc:
        log(f"worker seed error {key} {exc}")
        seeded = None
    if seeded is None:
        log(f"worker {key} missing ticker; polling")
        _poll_loop(scan, spec, end)
        return
    title, game, kalshi_events, gemini_events, polymarket, novig = seeded
    sport = spec["sport"]
    stream_health.configure(spec["key"], sport, title, {
        "gemini": bool(live_quote_stream.gemini_symbols(gemini_events)),
        "kalshi": bool(live_quote_stream.kalshi_contracts(kalshi_events)),
        "polymarket": any(bool(row.get("slug")) for row in (polymarket or [])),
        "novig": any(bool(row.get("market_id")) for row in (novig or [])),
    })
    seen: set[str] = set()
    compare_lock = threading.Lock()
    compare_state = {"busy": False, "dirty": False}

    def on_change(venue: str) -> None:
        """Compare this book change in this process. A short coalesce only collapses a burst."""
        seen.add(venue)

        def run() -> None:
            while True:
                with compare_lock:
                    compare_state["dirty"] = False
                try:
                    feed = "websocket: " + ", ".join(sorted(seen))
                    _after_quotes(scan, spec, sport, title, game, kalshi_events, gemini_events, feed, polymarket, novig)
                except Exception as exc:
                    log(f"worker stream compare {key} {exc}")
                with compare_lock:
                    if not compare_state["dirty"]:
                        compare_state["busy"] = False
                        return
                time.sleep(COALESCE_SEC)

        with compare_lock:
            if compare_state["busy"]:
                compare_state["dirty"] = True
                return
            compare_state["busy"] = True
        threading.Thread(target=run, name=f"compare-{key}", daemon=True).start()

    def on_quote(venue: str, changed: bool) -> None:
        try:
            stream_health.note_stream(spec["key"], sport, title, venue, changed)
        except Exception as exc:
            log(f"health stream {key} {type(exc).__name__}")

    try:
        log(f"worker streams {key} polymarket {len(polymarket)} novig {len(novig)}")
        live_quote_stream.run_until_done(
            scan, spec, gemini_events, kalshi_events, lambda: _worker_should_stop(spec, end), log, on_change, polymarket,
            on_quote=on_quote,
            novig_contracts=novig,
        )
        log(f"worker streams ended {key}")
        if not _worker_should_stop(spec, end):
            log(f"worker streams ended early {key}; HTTP poll")
            _poll_loop(scan, spec, end)
    except Exception as exc:
        log(f"worker stream error {key} {exc}; falling back to requests")
        _poll_loop(scan, spec, end)


def _poll_loop(scan, spec: dict, end) -> None:
    key = spec["key"]
    while not _worker_should_stop(spec, end):
        try:
            poll_once(scan, spec)
        except Exception as exc:
            log(f"worker error {key} {exc}")
        if _worker_should_stop(spec, end):
            return
        time.sleep(POLL_SLEEP)
    log(f"worker poll loop ended {key}")


def command_for(key: str) -> list[str]:
    """Leftover --poll-one argv. Supervisor does not spawn this."""
    return [sys.executable, "-u", str(Path(__file__).resolve()), "--poll-one", key]


def command_for_merged() -> list[str]:
    return [sys.executable, "-u", str(Path(__file__).resolve()), "--poll-all"]


def command_for_lock_sender() -> list[str]:
    return [sys.executable, "-u", str(LOCK_SENDER_SCRIPT)]


def poller_creationflags() -> int:
    """Hide the helper console. Logging is the file log, not this window."""
    return win_hidden.creationflags(new_group=True)


def running_poller_pids() -> dict[str, int]:
    """Game key to PID for pollers already started. Does not signal them."""
    found: dict[str, int] = {}
    if os.name != "nt":
        return found
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like '*live_game_pollers.py --poll-one*' } | "
        "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"
    )
    try:
        out = win_hidden.check_output(
            win_hidden.powershell_argv(script),
            text=True,
            errors="replace",
            timeout=8,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return found
    for line in out.splitlines():
        if "|" not in line or "--poll-one" not in line:
            continue
        pid_text, cmd = line.split("|", 1)
        parts = cmd.split("--poll-one", 1)
        if len(parts) < 2:
            continue
        key = parts[1].strip().split()[0]
        try:
            found[key] = int(pid_text.strip())
        except ValueError:
            continue
    return found


def _python_cmd_pids(needle: str) -> list[int]:
    """PIDs whose command line contains needle. Does not signal them."""
    found: list[int] = []
    if os.name != "nt":
        return found
    safe = needle.replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -like '*{safe}*' }} | "
        "ForEach-Object { '{0}' -f $_.ProcessId }"
    )
    try:
        out = win_hidden.check_output(
            win_hidden.powershell_argv(script),
            text=True,
            errors="replace",
            timeout=8,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return found
    for line in out.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid and pid not in found:
            found.append(pid)
    return found


def running_merged_pid() -> int:
    for pid in _python_cmd_pids("live_game_pollers.py --poll-all"):
        if pid != os.getpid() and pid_alive(pid):
            return pid
    return 0


def running_lock_sender_pid() -> int:
    for pid in _python_cmd_pids("live_lock_sender.py"):
        if pid != os.getpid() and pid_alive(pid):
            return pid
    return 0


def kill_pid(pid: int) -> None:
    """Stop one helper by PID. Hidden console. Does not steal focus."""
    if not pid or pid <= 0 or pid == os.getpid():
        return
    if os.name == "nt":
        script = f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue"
        try:
            win_hidden.run(win_hidden.powershell_argv(script), check=False, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return
    try:
        os.kill(int(pid), 15)
    except OSError:
        pass


class Tracked:
    def __init__(self, pid: int, popen: subprocess.Popen | None = None):
        self.pid = pid
        self.popen = popen

    def poll(self):
        if self.popen is not None:
            return self.popen.poll()
        return None if pid_alive(self.pid) else 1

    def terminate(self):
        if self.popen is not None:
            try:
                if self.popen.poll() is None:
                    self.popen.terminate()
            except OSError:
                pass
        if self.pid and pid_alive(self.pid):
            kill_pid(self.pid)


def reap_idle_pollers(children: dict[str, Tracked], live_keys: set[str], me: int) -> dict[str, int]:
    """Kill leftover --poll-one helpers. Merged poller is --poll-all, not these."""
    del live_keys
    already = running_poller_pids()
    for key, pid in list(already.items()):
        if not pid or pid == me:
            continue
        proc = children.get(key)
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                log(f"stop leftover poll-one {key} pid {proc.pid}")
            children.pop(key, None)
        else:
            kill_pid(pid)
            log(f"reap leftover poll-one {key} pid {pid}")
    return already


def spawn(spec: dict, supervisor_pid: int) -> Tracked:
    key = spec["key"]
    payload = {
        "key": key,
        "sport": spec["sport"],
        "title": spec["title"],
        "start": spec["start"],
        "live_until": spec["live_until"],
        "game": spec["game"],
        "supervisor_pid": supervisor_pid,
        "deadline": job_deadline_iso(),
    }
    write_json(JOBS / f"{key}.json", payload)
    write_json(STATE / f"{key}.json", {
        "key": key,
        "sport": spec["sport"],
        "game": spec["title"],
        "pid": None,
        "last_poll": None,
        "last_abs_move": None,
    })
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(PYCACHE_DIR)
    proc = win_hidden.popen(
        command_for(key),
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        new_group=True,
    )
    state = read_json(STATE / f"{key}.json")
    state["pid"] = proc.pid
    state["process"] = " ".join(command_for(key))
    write_json(STATE / f"{key}.json", state)
    log(f"spawn leftover poll-one {key} pid {proc.pid}")
    return Tracked(proc.pid, proc)


def _spawn_hidden(argv: list[str], state_path: Path, label: str) -> Tracked:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(PYCACHE_DIR)
    proc = win_hidden.popen(
        argv,
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        new_group=True,
    )
    write_json(state_path, {
        "pid": proc.pid,
        "started_at": iso_now(),
        "process": " ".join(argv),
        "role": label,
    })
    log(f"spawn {label} pid {proc.pid}")
    return Tracked(proc.pid, proc)


def spawn_merged() -> Tracked:
    return _spawn_hidden(command_for_merged(), POLL_ALL_PID, "poll-all")


def spawn_lock_sender() -> Tracked:
    return _spawn_hidden(command_for_lock_sender(), RAW / "live_lock_sender.pid", "lock-sender")


def ensure_tracked(proc: Tracked | None, running_pid: int, spawner, me: int) -> Tracked | None:
    """Adopt one live PID or spawn one. Never a second copy."""
    if proc is not None and proc.poll() is None:
        return proc
    if running_pid and running_pid != me and pid_alive(running_pid):
        log(f"adopt {running_pid}")
        return Tracked(running_pid)
    return spawner()


def publish(merged: Tracked | None, lock_sender: Tracked | None, live: list[dict], scan) -> None:
    games = []
    poller_pid = merged.pid if merged is not None else None
    for spec in live:
        key = spec["key"]
        state = read_json(STATE / f"{key}.json")
        games.append({
            "key": key,
            "sport": state.get("sport") or spec.get("sport") or "",
            "game": state.get("game") or spec.get("title") or key,
            "pid": poller_pid,
            "process": " ".join(command_for_merged()),
            "last_poll": state.get("last_poll"),
            "last_abs_move": state.get("last_abs_move"),
            "start": spec.get("start"),
            "live_until": spec.get("live_until"),
        })
    if games:
        message = f"{len(games)} live game(s), one poller process, four shared sockets."
    else:
        message = "No game is live yet."
    write_json(STATUS, {
        "updated_at": iso_now(),
        "deadline": job_deadline_iso(),
        "supervisor_pid": os.getpid(),
        "poller_pid": poller_pid,
        "lock_sender_pid": lock_sender.pid if lock_sender is not None else None,
        "mode": "merged",
        "live_count": len(games),
        "message": message,
        "games": games,
        "orders": "Lock gap (A) is live_lock_sender.py. This poller quotes only.",
        "plan_note": _plan_note(),
    })
    write_progress_within_budget(scan)
    try:
        stream_health.write_page()
    except Exception as exc:
        log(f"stream health page {type(exc).__name__}")
    try:
        import cheaper_same_bet
        cheaper_same_bet.write_page(fetch_positions_now=False)
    except Exception as exc:
        log(f"cheaper same bet page {type(exc).__name__}")


_page_thread: threading.Thread | None = None
_page_started = 0.0
_status_thread: threading.Thread | None = None
_novig_tennis_lock = threading.Lock()
_novig_tennis_cache: list = []
_novig_tennis_loading = False


def write_progress_within_budget(scan) -> None:
    """Rewrite progress.html on each supervisor loop. A failed write is logged and retried next loop."""
    global _page_thread, _page_started
    if _page_thread is not None and _page_thread.is_alive():
        age = time.time() - _page_started
        if age < SUPERVISOR_SLEEP:
            log("progress page still writing; supervisor continues")
            return
        log(f"progress page still writing after {int(age)}s; retrying")

    def _run() -> None:
        try:
            scan.write_progress_page()
        except Exception as exc:
            log(f"progress page error {exc}")
            return
        log("progress page wrote")

    _page_started = time.time()
    _page_thread = threading.Thread(target=_run, name="progress-page", daemon=True)
    _page_thread.start()
    try:
        _page_thread.join(PAGE_WRITE_BUDGET)
    except KeyboardInterrupt:
        log("progress page interrupted; supervisor continues")
        return
    if _page_thread.is_alive():
        log("progress page slow; supervisor continues")


def refresh_job_status() -> None:
    """Rewrite job_status.html about once a minute. A failed write must not stop quoting."""
    global _status_thread
    if _status_thread is not None and _status_thread.is_alive():
        return

    def _run() -> None:
        try:
            import prediction_job_control

            prediction_job_control = importlib.reload(prediction_job_control)
            prediction_job_control.write_page(prediction_job_control.snapshot())
        except Exception as exc:
            log(f"job status page {type(exc).__name__}")

    _status_thread = threading.Thread(target=_run, name="job-status", daemon=True)
    _status_thread.start()


def poll_all() -> None:
    """One process, many live-window games, four shared sockets. Does not place lock bets."""
    import asyncio

    import live_quote_mux

    scan = load_scan()
    me = os.getpid()
    write_json(POLL_ALL_PID, {"pid": me, "started_at": iso_now(), "role": "poll-all"})
    log(f"poll-all start pid {me}")
    books: dict[str, dict] = {}
    compare_locks: dict[str, threading.Lock] = {}
    compare_state: dict[str, dict] = {}

    def stop() -> bool:
        return STOP.exists()

    def schedule_compare(key: str, venue: str) -> None:
        row = books.get(key)
        if not row:
            return
        lock = compare_locks.setdefault(key, threading.Lock())
        state = compare_state.setdefault(key, {"busy": False, "dirty": False, "seen": set()})
        state["seen"].add(venue)

        def run() -> None:
            while True:
                with lock:
                    state["dirty"] = False
                try:
                    feed = "websocket: " + ", ".join(sorted(state["seen"]))
                    _after_quotes(
                        scan, row["spec"], row["sport"], row["title"], row["game"],
                        row["kalshi_events"], row["gemini_events"], feed,
                        row["polymarket"], row["novig"],
                    )
                except Exception as exc:
                    log(f"poll-all compare {key} {type(exc).__name__}")
                with lock:
                    if not state["dirty"]:
                        state["busy"] = False
                        return
                time.sleep(COALESCE_SEC)

        with lock:
            if state["busy"]:
                state["dirty"] = True
                return
            state["busy"] = True
        threading.Thread(target=run, name=f"compare-{key}", daemon=True).start()

    def on_change(venue: str, keys: set[str]) -> None:
        for key in keys:
            schedule_compare(key, venue)

    def on_quote(venue: str, key: str, changed: bool) -> None:
        row = books.get(key)
        if not row:
            return
        try:
            stream_health.note_stream(key, row["sport"], row["title"], venue, changed)
        except Exception:
            pass

    mux = live_quote_mux.SharedStreams(on_change, log, on_quote)

    def add_game(spec: dict) -> None:
        key = spec["key"]
        try:
            seeded = seed_quotes(scan, spec)
        except Exception as exc:
            log(f"poll-all seed {key} {type(exc).__name__}")
            return
        if seeded is None:
            log(f"poll-all skip {key} no quote venue")
            return
        title, game, kalshi_events, gemini_events, polymarket, novig = seeded
        sport = spec["sport"]
        books[key] = {
            "spec": spec,
            "sport": sport,
            "title": title,
            "game": game,
            "kalshi_events": kalshi_events,
            "gemini_events": gemini_events,
            "polymarket": polymarket or [],
            "novig": novig or [],
        }
        try:
            stream_health.configure(key, sport, title, {
                "gemini": bool(live_quote_stream.gemini_symbols(gemini_events)),
                "kalshi": bool(live_quote_stream.kalshi_contracts(kalshi_events)),
                "polymarket": any(bool(row.get("slug")) for row in (polymarket or [])),
                "novig": any(bool(row.get("market_id")) for row in (novig or [])),
            })
        except Exception:
            pass
        mux.set_game(
            key,
            kalshi=live_quote_stream.kalshi_contracts(kalshi_events),
            gemini=live_quote_stream.gemini_symbols(gemini_events),
            polymarket={str(row.get("slug")): row for row in (polymarket or []) if row.get("slug")},
            novig={str(row.get("market_id")): row for row in (novig or []) if row.get("market_id")},
        )
        log(f"poll-all add {key} {title}")

    def drop_game(key: str) -> None:
        title = str((books.get(key) or {}).get("title") or "")
        books.pop(key, None)
        compare_locks.pop(key, None)
        compare_state.pop(key, None)
        mux.drop_game(key)
        log(f"poll-all drop {key}")
        try:
            import orders_performance_refresh
            orders_performance_refresh.maybe_after_game_complete(
                "removed", game_key=key, title=title, we_touched=None,
            )
        except Exception:
            pass

    def sync_once() -> None:
        live = live_games(scan)
        live_keys = {row["key"] for row in live}
        for row in live:
            key = row["key"]
            write_json(JOBS / f"{key}.json", {
                "key": key,
                "sport": row["sport"],
                "title": row["title"],
                "start": row["start"],
                "live_until": row["live_until"],
                "listed_start": row.get("listed_start") or row.get("start") or "",
                "game": row["game"],
            })
            if key not in books:
                add_game(row)
        for key in list(books):
            if key not in live_keys:
                drop_game(key)

    try:
        asyncio.run(mux.run(stop, sync_once, sync_sec=float(SUPERVISOR_SLEEP)))
    except Exception as exc:
        log(f"poll-all mux {type(exc).__name__}; HTTP poll")
        while not stop():
            try:
                sync_once()
                for key, row in list(books.items()):
                    poll_once(scan, row["spec"])
            except Exception as inner:
                log(f"poll-all http {type(inner).__name__}")
            time.sleep(POLL_SLEEP)
    log("poll-all exit")


def supervise() -> None:
    if STOP.exists():
        STOP.unlink()
    scan = load_scan()
    me = os.getpid()
    write_json(RAW / "live_supervisor.pid", {"pid": me, "started_at": iso_now(), "deadline": job_deadline_iso()})
    log(f"supervisor start pid {me} merged poller + lock sender; no --poll-one")
    refresh_job_status()

    def _opportunities_page() -> None:
        try:
            scan.write_opportunities_page()
        except Exception as exc:
            log(f"opportunities page {type(exc).__name__}")

    threading.Thread(target=_opportunities_page, name="opportunities-page", daemon=True).start()
    leftover: dict[str, Tracked] = {}
    merged: Tracked | None = None
    lock_sender: Tracked | None = None
    while keep_running():
        refresh_job_status()
        try:
            live = live_games(scan)
            live_keys = {row["key"] for row in live}
            reap_idle_pollers(leftover, live_keys, me)
            merged = ensure_tracked(merged, running_merged_pid(), spawn_merged, me)
            lock_sender = ensure_tracked(lock_sender, running_lock_sender_pid(), spawn_lock_sender, me)
            extras = _python_cmd_pids("live_game_pollers.py --poll-all")
            for pid in extras:
                if merged is not None and pid not in (me, merged.pid) and pid_alive(pid):
                    kill_pid(pid)
                    log(f"reap extra poll-all pid {pid}")
            extras_a = _python_cmd_pids("live_lock_sender.py")
            for pid in extras_a:
                if lock_sender is not None and pid not in (me, lock_sender.pid) and pid_alive(pid):
                    kill_pid(pid)
                    log(f"reap extra lock-sender pid {pid}")
            publish(merged, lock_sender, live, scan)
            try:
                import prediction_systems

                started = prediction_systems.ensure_live_bots()
                if started:
                    log("live bots spawned " + ",".join(started) + " (no second tennis crossover)")
            except Exception as exc:
                log(f"live bots spawn {type(exc).__name__}")
            try:
                import odds_snapshots
                odds_snapshots.tick(log)
                odds_snapshots.maybe_rebuild(log)
            except Exception as exc:
                log(f"odds snapshots {type(exc).__name__}")
            try:
                import t0_all_games_stats
                t0_all_games_stats.maybe_rebuild(log)
            except Exception as exc:
                log(f"t0 all-games stats {type(exc).__name__}")
        except KeyboardInterrupt:
            log("supervisor loop interrupted; continuing")
        except Exception as exc:
            log(f"supervisor loop error {exc}")
        slept = 0
        while slept < SUPERVISOR_SLEEP and keep_running():
            time.sleep(1)
            slept += 1
            if slept == 30:
                try:
                    stream_health.write_page()
                except Exception as exc:
                    log(f"stream health page {type(exc).__name__}")
    for proc in leftover.values():
        if proc.poll() is None:
            proc.terminate()
    try:
        publish(merged, lock_sender, [], scan)
    except KeyboardInterrupt:
        log("final progress page interrupted")
    except Exception as exc:
        log(f"final publish error {exc}")
    log("supervisor exit")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--poll-all":
        poll_all()
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "--poll-one":
        worker(sys.argv[2])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--list-live":
        scan = load_scan()
        rows = live_games(scan)
        print(f"live {len(rows)} at {iso_now()}")
        for row in rows:
            print(row["sport"], row["title"], row["start"], row["live_until"])
        return
    supervise()


if __name__ == "__main__":
    main()
