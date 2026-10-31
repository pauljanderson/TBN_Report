"""One Python process per live matched game. No secrets in the log.

Orders: one contract, and only when the locked net is $0.95 or less.

The supervisor looks about every 60 seconds for a new live game to start.
That wait is not the compare rate. A game is live when now is at or after
the listed start and before start plus a typical length. Phase unknown is not live.

Each child reads the event once, then keeps a websocket open for that game.
Gemini's public book stream and Kalshi's signed stream update price and size
as messages arrive. A Polymarket US twin, when one exists, uses the US markets
socket on the same game. Each book update is compared. A burst of ticks is
collapsed in about a twentieth of a second so one tick does not start a process.
If a stream cannot be opened, the child falls back to a request about every 20
seconds. Twin moneyline cards stay on the stream until the deadline: ATP /
ATP Challenger tennis, UFC/MMA fights, table tennis (including Polymarket-only
open cards), and chess matches when both books list them. Catalog sports in
LIVE_HOURS (including pro football / hockey moneyline+spread, soccer, mma,
chess) are watched from listed start through a typical game length. Price
memory records moneyline, spread, and total asks on every poll. A lock at or
under $0.95 net sends one contract on each leg. Pairs under $1 that miss that
bar stay alerts.

HTTP seeds, HTTP fallbacks, and the catalog scan share tools/venue_pace.py.
A websocket update does not wait on that pace.
"""
from __future__ import annotations

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

import live_lock_orders  # noqa: E402
import live_quote_stream  # noqa: E402
import polymarket_us_live  # noqa: E402
import price_memory  # noqa: E402
import stream_health  # noqa: E402
import venue_pace  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"
RAW = STAMP / "raw"
JOBS = RAW / "live_jobs"
STATE = RAW / "live_state"
STATUS = RAW / "live_pollers_status.json"
MOVES = RAW / "live_moves.jsonl"
STOP = RAW / "live_supervisor.stop"
LOG = RAW / "live_supervisor.log"
ET = ZoneInfo("America/New_York")
DEADLINE = datetime(2026, 10, 19, 8, 0, 0, tzinfo=ET)
POLL_SLEEP = 20
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
    "mma": 3.0,
    "chess": 3.0,
}
SPORT_ORDER = [
    "college football",
    "pro football",
    "pro baseball",
    "soccer",
    "pro hockey",
    "mma",
    "chess",
]
# Focus for crossover/dip research. All three kinds are still remembered on each poll.
TRACK_MARKET_KINDS = ("moneyline", "spread", "total")
PLAN_NOTE = (
    "One contract when net is $0.95 or less. The venue that moved more is sent first. "
    "Pairs under $1 that earn less than $0.05 stay alerts. "
    "During-game price memory keeps moneyline + spread (+ total) on every live sport."
)


def now_et() -> datetime:
    return datetime.now(ET)


def iso_now() -> str:
    return now_et().isoformat()


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
    return start_from_tickers(game, scan) or start_from_saved(sport, game, scan)


def iter_matched(scan):
    college = scan.load_college()
    for game in college:
        yield "college football", game
    sports = scan.load_sports()
    for sport in SPORT_ORDER:
        if sport == "college football":
            continue
        for game in sports.get(sport) or []:
            yield sport, game


def live_games(scan, moment: datetime | None = None) -> list[dict]:
    moment = moment or now_et()
    rows = []
    for sport, game in iter_matched(scan):
        hours = LIVE_HOURS.get(sport)
        if hours is None:
            continue
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
    rows.extend(mma_rows(scan))
    rows.extend(table_tennis_rows(scan))
    rows.extend(chess_twin_rows(scan))
    return rows


def _twin_game(match: dict, ticker: str) -> dict:
    """Build a live game row for a Kalshi↔Polymarket (or Polymarket-only) moneyline twin."""
    slug = str(match.get("slug") or "")
    code = re.sub(r"[^a-z0-9]+", "", slug)[:40] or re.sub(r"[^a-z0-9]+", "", ticker)[:40] or "game"
    kalshi = {"game": ticker} if ticker else {}
    return {
        "date": match.get("date") or "",
        "title_kalshi": match.get("title") or ticker or slug,
        "codes": [code],
        "kalshi": kalshi,
        "gemini": {},
        "polymarket_markets": [match],
    }


def _deadline_twin_rows(sport: str, matches: list[dict], *, require_kalshi: bool) -> list[dict]:
    """Watch twin moneylines until the supervisor deadline (same pattern as tennis)."""
    rows = []
    start = (now_et() - timedelta(minutes=1)).isoformat()
    for match in matches:
        if not isinstance(match, dict) or not match.get("slug"):
            continue
        ticker = str(match.get("event_ticker") or "")
        if require_kalshi and not ticker:
            continue
        game = _twin_game(match, ticker)
        # game_key needs scan.game_codes — pass a tiny stub via the caller's scan in wrappers
        rows.append({
            "sport": sport,
            "game": game,
            "title": match.get("title") or ticker or match.get("slug"),
            "start": start,
            "live_until": DEADLINE.isoformat(),
            "_key_sport": sport,
        })
    return rows


def tennis_rows(scan) -> list[dict]:
    """Kalshi ATP / Challenger moneylines that have one Polymarket US twin. Until the deadline."""
    matches = polymarket_us_live.load_tennis_matches(log)
    return _finalize_twin_rows(scan, _deadline_twin_rows("tennis", matches, require_kalshi=True))


def mma_rows(scan) -> list[dict]:
    """Kalshi UFC/MMA fight moneylines with a Polymarket US twin. Until the deadline."""
    matches = polymarket_us_live.load_mma_matches(log)
    return _finalize_twin_rows(scan, _deadline_twin_rows("mma", matches, require_kalshi=True))


def table_tennis_rows(scan) -> list[dict]:
    """Table tennis moneylines from Polymarket (Kalshi twin when open). Until the deadline."""
    matches = polymarket_us_live.load_table_tennis_matches(log)
    return _finalize_twin_rows(scan, _deadline_twin_rows("table tennis", matches, require_kalshi=False))


def chess_twin_rows(scan) -> list[dict]:
    """Kalshi chess match moneylines with a Polymarket US twin. Until the deadline."""
    matches = polymarket_us_live.load_chess_matches(log)
    return _finalize_twin_rows(scan, _deadline_twin_rows("chess", matches, require_kalshi=True))


def _finalize_twin_rows(scan, rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        game = row["game"]
        sport = row["_key_sport"]
        key = game_key(sport, game, scan)
        out.append({
            "key": key,
            "sport": sport,
            "game": game,
            "title": row["title"],
            "start": row["start"],
            "live_until": row["live_until"],
        })
    return out


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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


def _log_check(scan, spec: dict, sport: str, title: str, game: dict, result: dict, started: str, t0: float, transport: str) -> None:
    """Record one comparison. Does not send a phone ping."""
    try:
        stream_health.record_check(
            spec["key"], sport, title, game, scan, result, started, iso_now(),
            (time.perf_counter() - t0) * 1000.0, transport,
        )
    except Exception as exc:
        log(f"health check log {spec.get('key')} {type(exc).__name__}")


def _has_watchable_book(game: dict, scan) -> bool:
    """True when at least one venue book can be read (Kalshi, Gemini, or Polymarket preset)."""
    k_tickers, g_tickers = scan.tickers_of(game)
    preset = game.get("polymarket_markets") if isinstance(game.get("polymarket_markets"), list) else []
    return bool(k_tickers or g_tickers or preset)


def poll_once(scan, spec: dict) -> None:
    game = spec["game"]
    sport = spec["sport"]
    k_tickers, g_tickers = scan.tickers_of(game)
    if not _has_watchable_book(game, scan):
        log(f"poll skip {spec['key']} missing ticker")
        state = read_json(STATE / f"{spec['key']}.json")
        state.update({
            "key": spec["key"],
            "last_poll": iso_now(),
            "last_abs_move": state.get("last_abs_move"),
            "note": "No Kalshi, Gemini, or Polymarket book on this game.",
        })
        write_json(STATE / f"{spec['key']}.json", state)
        return
    gemini_events = [scan.fetch_gemini_event(t) for t in g_tickers]
    kalshi_events = [scan.fetch_kalshi_event(t) for t in k_tickers]
    polymarket = _polymarket_contracts(game, scan, kalshi_events, gemini_events)
    title = scan.game_title_from(gemini_events, kalshi_events, spec.get("title") or fallback_title(game, scan))
    sized = scan.book_size_example(gemini_events, "Gemini") or scan.book_size_example(kalshi_events, "Kalshi")
    if sized:
        log(f"book size {title} {sized}")
    started = iso_now()
    t0 = time.perf_counter()
    result = _compared(scan, game, kalshi_events, gemini_events, polymarket)
    scan.ping_fresh_quotes(sport, title, game, result)
    fresh: list[dict] = []
    price_memory.remember_books(
        sport, title, scan.iso_now(), kalshi_events, gemini_events, game.get("date"), moves_out=fresh,
        polymarket_contracts=polymarket,
    )
    _maybe_lock_orders(scan, sport, title, game, result, fresh)
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
            "orders": "1 contract if net <= 0.95",
            "plan_note": PLAN_NOTE,
        })
    state = read_json(STATE / f"{spec['key']}.json")
    state.update({
        "key": spec["key"],
        "sport": sport,
        "game": title,
        "pid": os.getpid(),
        "last_poll": seen,
        "last_abs_move": abs_move if abs_move is not None else state.get("last_abs_move"),
        "last_abs_move_this_poll": abs_move,
    })
    write_json(STATE / f"{spec['key']}.json", state)
    _log_check(scan, spec, sport, title, game, result, started, t0, "request")
    log(f"poll {spec['key']} {title} abs {abs_move}")


def _worker_should_stop(spec: dict, end) -> bool:
    if now_et() >= DEADLINE or STOP.exists():
        return True
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


def _compared(scan, game, kalshi_events, gemini_events, polymarket) -> dict:
    result = scan.compare_payloads(game, kalshi_events, gemini_events)
    extra = polymarket_us_live.polymarket_candidates(scan, game, kalshi_events, gemini_events, polymarket or [])
    if extra:
        result["candidates"] = list(result.get("candidates") or []) + extra
    return result


def _after_quotes(scan, spec: dict, sport: str, title: str, game: dict, kalshi_events, gemini_events, transport: str, polymarket=None) -> None:
    started = iso_now()
    t0 = time.perf_counter()
    result = _compared(scan, game, kalshi_events, gemini_events, polymarket)
    scan.ping_fresh_quotes(sport, title, game, result)
    fresh: list[dict] = []
    price_memory.remember_books(
        sport, title, scan.iso_now(), kalshi_events, gemini_events, game.get("date"), moves_out=fresh,
        polymarket_contracts=polymarket,
    )
    _maybe_lock_orders(scan, sport, title, game, result, fresh)
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
            "orders": "1 contract if net <= 0.95",
            "plan_note": PLAN_NOTE,
        })
    _record_poll(spec, sport, title, abs_move, transport)
    _log_check(scan, spec, sport, title, game, result, started, t0, transport)


def _maybe_lock_orders(scan, sport: str, title: str, game: dict, result: dict, fresh: list[dict]) -> None:
    try:
        live_lock_orders.execute_locks(scan, sport, title, game, result, fresh, log)
    except Exception as exc:
        text = str(exc)
        lowered = text.lower()
        if any(word in lowered for word in ("signature", "secret", "bearer", "payload", "api key")):
            text = ""
        log(f"order path error {type(exc).__name__} {text[:180]}")


def seed_quotes(scan, spec: dict):
    """One ordinary read so the streams know which contracts belong to this game."""
    game = spec["game"]
    sport = spec["sport"]
    k_tickers, g_tickers = scan.tickers_of(game)
    if not _has_watchable_book(game, scan):
        return None
    gemini_events = [scan.fetch_gemini_event(t) for t in g_tickers]
    kalshi_events = [scan.fetch_kalshi_event(t) for t in k_tickers]
    polymarket = _polymarket_contracts(game, scan, kalshi_events, gemini_events)
    title = scan.game_title_from(gemini_events, kalshi_events, spec.get("title") or fallback_title(game, scan))
    _after_quotes(scan, spec, sport, title, game, kalshi_events, gemini_events, "request", polymarket)
    return title, game, kalshi_events, gemini_events, polymarket


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
    title, game, kalshi_events, gemini_events, polymarket = seeded
    sport = spec["sport"]
    stream_health.configure(spec["key"], sport, title, {
        "gemini": bool(live_quote_stream.gemini_symbols(gemini_events)),
        "kalshi": bool(live_quote_stream.kalshi_contracts(kalshi_events)),
        "polymarket": any(bool(row.get("slug")) for row in (polymarket or [])),
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
                    _after_quotes(scan, spec, sport, title, game, kalshi_events, gemini_events, feed, polymarket)
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
        log(f"worker streams {key} polymarket {len(polymarket)}")
        live_quote_stream.run_until_done(
            scan, spec, gemini_events, kalshi_events, lambda: _worker_should_stop(spec, end), log, on_change, polymarket,
            on_quote=on_quote,
        )
        log(f"worker streams ended {key}")
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
    return [sys.executable, "-u", str(Path(__file__).resolve()), "--poll-one", key]


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
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
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


class Tracked:
    def __init__(self, pid: int, popen: subprocess.Popen | None = None):
        self.pid = pid
        self.popen = popen

    def poll(self):
        if self.popen is not None:
            return self.popen.poll()
        return None if pid_alive(self.pid) else 1

    def terminate(self):
        if self.popen is not None and self.popen.poll() is None:
            self.popen.terminate()


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
        "deadline": DEADLINE.isoformat(),
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
    proc = subprocess.Popen(
        command_for(key),
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    state = read_json(STATE / f"{key}.json")
    state["pid"] = proc.pid
    state["process"] = " ".join(command_for(key))
    write_json(STATE / f"{key}.json", state)
    log(f"spawn {key} pid {proc.pid}")
    return Tracked(proc.pid, proc)


def publish(children: dict[str, Tracked], live: list[dict], scan) -> None:
    games = []
    by_key = {row["key"]: row for row in live}
    for key, proc in children.items():
        state = read_json(STATE / f"{key}.json")
        spec = by_key.get(key) or {}
        games.append({
            "key": key,
            "sport": state.get("sport") or spec.get("sport") or "",
            "game": state.get("game") or spec.get("title") or key,
            "pid": state.get("pid") or proc.pid,
            "process": state.get("process") or " ".join(command_for(key)),
            "last_poll": state.get("last_poll"),
            "last_abs_move": state.get("last_abs_move"),
            "start": spec.get("start"),
            "live_until": spec.get("live_until"),
        })
    if games:
        message = f"{len(games)} live game(s), each with its own poller."
    else:
        message = "No game is live yet."
    write_json(STATUS, {
        "updated_at": iso_now(),
        "deadline": DEADLINE.isoformat(),
        "supervisor_pid": os.getpid(),
        "live_count": len(games),
        "message": message,
        "games": games,
        "orders": "1 contract when net <= 0.95",
        "plan_note": PLAN_NOTE,
    })
    write_progress_within_budget(scan)
    try:
        stream_health.write_page()
    except Exception as exc:
        log(f"stream health page {type(exc).__name__}")


_page_thread: threading.Thread | None = None
_page_started = 0.0


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


def supervise() -> None:
    if STOP.exists():
        STOP.unlink()
    scan = load_scan()
    me = os.getpid()
    write_json(RAW / "live_supervisor.pid", {"pid": me, "started_at": iso_now(), "deadline": DEADLINE.isoformat()})
    log(f"supervisor start pid {me} deadline {DEADLINE.isoformat()}")
    children: dict[str, Tracked] = {}
    while now_et() < DEADLINE and not STOP.exists():
        try:
            live = live_games(scan)
            live_keys = {row["key"] for row in live}
            already = running_poller_pids()
            for row in live:
                key = row["key"]
                proc = children.get(key)
                if proc is not None and proc.poll() is None:
                    continue
                existing = already.get(key)
                if existing and pid_alive(existing) and existing != me:
                    children[key] = Tracked(existing)
                    log(f"adopt {key} pid {existing}")
                    continue
                children[key] = spawn(row, me)
            for key in list(children):
                proc = children[key]
                if key not in live_keys:
                    if proc.poll() is None:
                        proc.terminate()
                        log(f"stop poller {key} pid {proc.pid}")
                    children.pop(key, None)
                    continue
                if proc.poll() is not None:
                    children[key] = spawn(next(r for r in live if r["key"] == key), me)
            publish(children, live, scan)
        except KeyboardInterrupt:
            log("supervisor loop interrupted; continuing")
        except Exception as exc:
            log(f"supervisor loop error {exc}")
        slept = 0
        while slept < SUPERVISOR_SLEEP and now_et() < DEADLINE and not STOP.exists():
            time.sleep(1)
            slept += 1
            if slept == 30:
                try:
                    stream_health.write_page()
                except Exception as exc:
                    log(f"stream health page {type(exc).__name__}")
    for proc in children.values():
        if proc.poll() is None:
            proc.terminate()
    try:
        publish({}, [], scan)
    except KeyboardInterrupt:
        log("final progress page interrupted")
    except Exception as exc:
        log(f"final publish error {exc}")
    log("supervisor exit")


def main() -> None:
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
