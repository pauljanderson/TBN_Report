"""Live-checker health log. No orders. No secrets.

Each game process keeps counts in memory and appends one compact row per
minute, plus one row when a buyable under-$1 gap opens or closes.
raw/live_checks.jsonl is rotated so it cannot grow without bound.
stream_health.html is rewritten by the supervisor about every 30 seconds,
and again when a gap opens or closes. A websocket tick does not rewrite it.
"""
from __future__ import annotations

import html
import json
import os
import threading
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import venue_pace  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML  # noqa: E402
HEALTH_DIR = RAW / "live_health"
CHECKS = RAW / "live_checks.jsonl"
CHECKS_PREV = RAW / "live_checks.prev.jsonl"
PAGE = STAMP / "stream_health.html"
ONE_LEG_LOG = RAW / "one_leg_alerts.jsonl"
ONE_LEG_PAGE = STAMP / "one_leg_note.html"
STATUS = RAW / "live_pollers_status.json"
SUPERVISOR_PID = RAW / "live_supervisor.pid"
ET = ZoneInfo("America/New_York")
VENUES = ("gemini", "kalshi", "polymarket", "novig")
QUIET_SEC = 120
HEARTBEAT_SEC = 15
STATE_FLUSH_SEC = 15
JSONL_MAX_BYTES = 8_000_000
LIFETIME_CAP = 5000
SIZE_CAP = 2000
LATEST_CAP = 12
_page_lock = threading.Lock()
_trackers: dict[str, "Tracker"] = {}
_trackers_guard = threading.Lock()

ASKED = (
    "I want more data. please log how often the streams update prices, and how quickly we are doing checks. "
    "How often our checks result in no gap under $1 vs. gaps under $1 and on average how long those gaps live. "
    "how many contracts are available on both sides when the gap is under $1 and buyable. "
    "what other data can you provide to show me that this is working as expected and not just frozen."
)
PLAIN = (
    "This page is a pulse check for the live Kalshi, Gemini, and Polymarket US comparison. "
    "It does not place orders. Each live game has its own checker. A stream message is any quote that arrives "
    "for that game. A price update is counted only when the price or the size actually changes. "
    "A repeated quote is not an update and does not start another comparison. "
    "A check is one comparison of the two sides of a bet. "
    "No gap under $1 means every pair added up to $1 or more before fees. "
    "Under $1 before fee means at least one pair added up to less than $1 before fees. "
    "Buyable means both sides offer at least one contract, the No side is a real offer, "
    "and the cost is still under $1 after the documented fee. "
    "The page times how long a buyable gap stays open, and it lists the contract counts on each side. "
    "If a game's price streams have been silent for more than two minutes while its checker is still running, "
    "the row says quiet."
)


def now_et() -> datetime:
    return datetime.now(ET)


def iso_now() -> str:
    return now_et().isoformat(timespec="seconds")


def minute_key(moment: datetime | None = None) -> str:
    moment = moment or now_et()
    return moment.strftime("%Y-%m-%d %H:%M")


def pid_alive(pid: int) -> bool:
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


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ET)
    return moment.astimezone(ET)


def _size(value) -> Decimal | None:
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in ("unknown", "not offered", "none", "null"):
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float(ordered[mid - 1] + ordered[mid]) / 2.0


def _fmt_num(value, digits: int = 1) -> str:
    if value is None:
        return ""
    number = float(value)
    text = f"{number:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{_esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def _age_sec(text: str | None, moment: datetime) -> float | None:
    when = _parse_time(text)
    if when is None:
        return None
    return (moment - when).total_seconds()


def is_buyable(cand: dict, scan) -> bool:
    """Both sizes at least 1, a real No offer, and net under $1 after the documented fee."""
    if not isinstance(cand, dict):
        return False
    if not cand.get("yes_price") or not cand.get("no_price"):
        return False
    if not cand.get("net_under_1"):
        return False
    if "novig" in (str(cand.get("yes_venue") or "").lower(), str(cand.get("no_venue") or "").lower()):
        return False
    reject = scan.gemini_no_rejection(cand)
    if reject:
        return False
    yes = _size(cand.get("yes_size"))
    no = _size(cand.get("no_size"))
    if yes is None or no is None:
        return False
    return yes >= 1 and no >= 1


def _gap_snapshot(cand: dict) -> dict:
    yes = _size(cand.get("yes_size"))
    no = _size(cand.get("no_size"))
    smaller = None
    if yes is not None and no is not None:
        smaller = min(yes, no)
    return {
        "market_type": str(cand.get("market_type") or ""),
        "side": str(cand.get("side") or ""),
        "number": str(cand.get("number") or ""),
        "yes_venue": str(cand.get("yes_venue") or ""),
        "no_venue": str(cand.get("no_venue") or ""),
        "yes_size": str(cand.get("yes_size") or ""),
        "no_size": str(cand.get("no_size") or ""),
        "smaller": "" if smaller is None else format(smaller, "f"),
        "gross": str(cand.get("gross") or ""),
        "net": str(cand.get("net") or ""),
    }


class Tracker:
    def __init__(self, key: str, sport: str, title: str):
        self.key = key
        self.sport = sport
        self.title = title
        self.lock = threading.Lock()
        self.started_at = iso_now()
        self.pid = os.getpid()
        self.expected = {name: False for name in VENUES}
        self.transport = ""
        self.messages = {name: 0 for name in VENUES}
        self.updates = {name: 0 for name in VENUES}
        self.last_message = {name: "" for name in VENUES}
        self.last_update = {name: "" for name in VENUES}
        self.minute = minute_key()
        self.m_messages = {name: 0 for name in VENUES}
        self.m_updates = {name: 0 for name in VENUES}
        self.m_checks = 0
        self.m_no_gap = 0
        self.m_under = 0
        self.m_buyable = 0
        self.m_ms_sum = 0.0
        self.m_ms_max = 0.0
        self.checks = 0
        self.no_gap = 0
        self.under = 0
        self.buyable_checks = 0
        self.ms_sum = 0.0
        self.last_compare_started = ""
        self.last_compare_ended = ""
        self.last_compare_ms = None
        self.open_gaps: dict[str, dict] = {}
        self.recent: list[dict] = []
        self.closed_n = 0
        self.closed_sum = 0.0
        self.closed_lifetimes: list[float] = []
        self.lifetimes_truncated = False
        self.smaller_sizes: list[float] = []
        self.pending: list[dict] = []
        self.last_state_flush = 0.0
        self.write_lock = threading.Lock()
        self._stop = threading.Event()
        self._hb: threading.Thread | None = None

    def start_heartbeat(self) -> None:
        if self._hb is not None and self._hb.is_alive():
            return
        self._hb = threading.Thread(target=self._beat, name=f"health-{self.key}", daemon=True)
        self._hb.start()

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SEC):
            try:
                self.flush(force=True)
            except Exception:
                continue

    def set_expected(self, expected: dict) -> None:
        with self.lock:
            for name in VENUES:
                if name in expected:
                    self.expected[name] = bool(expected[name])
        self.flush(force=True)

    def note_stream(self, venue: str, changed: bool) -> None:
        if venue not in self.messages:
            return
        stamp = iso_now()
        with self.write_lock:
            with self.lock:
                self._roll(stamp)
                self.messages[venue] += 1
                self.m_messages[venue] += 1
                self.last_message[venue] = stamp
                if changed:
                    self.updates[venue] += 1
                    self.m_updates[venue] += 1
                    self.last_update[venue] = stamp
                due = bool(self.pending) or (time.monotonic() - self.last_state_flush) >= STATE_FLUSH_SEC
                if due:
                    pending = self._take_pending()
                    snap = self.snapshot()
                    self.last_state_flush = time.monotonic()
                else:
                    pending = []
                    snap = None
            self._write_files(pending, snap)

    def record_check(self, game: dict, scan, result: dict, started_at: str, ended_at: str, duration_ms: float, transport: str) -> None:
        cands = [c for c in (result.get("candidates") or []) if isinstance(c, dict)]
        buyable = [c for c in cands if is_buyable(c, scan)]
        any_gross = any(c.get("gross_under_1") for c in cands)
        current: dict[str, dict] = {}
        for cand in buyable:
            try:
                bet_key = scan._trade_bet_key(self.sport, game, cand)
            except Exception:
                bet_key = "\t".join([
                    self.sport,
                    str(cand.get("market_type") or ""),
                    str(cand.get("side_key") or cand.get("side") or ""),
                    str(cand.get("number") or ""),
                    str(cand.get("yes_venue") or ""),
                    str(cand.get("no_venue") or ""),
                ])
            current[bet_key] = _gap_snapshot(cand)
        gap_changed = False
        with self.write_lock:
            self._record_check_locked(game, scan, buyable, any_gross, current, started_at, ended_at, duration_ms, transport)
            return

    def _record_check_locked(self, game, scan, buyable, any_gross, current, started_at, ended_at, duration_ms, transport) -> None:
        gap_changed = False
        with self.lock:
            self.transport = transport or self.transport
            self._roll(ended_at)
            self.m_checks += 1
            self.checks += 1
            if buyable:
                self.m_buyable += 1
                self.buyable_checks += 1
                self.m_under += 1
                self.under += 1
            elif any_gross:
                self.m_under += 1
                self.under += 1
            else:
                self.m_no_gap += 1
                self.no_gap += 1
            self.m_ms_sum += float(duration_ms)
            self.ms_sum += float(duration_ms)
            if float(duration_ms) > self.m_ms_max:
                self.m_ms_max = float(duration_ms)
            self.last_compare_started = started_at
            self.last_compare_ended = ended_at
            self.last_compare_ms = round(float(duration_ms), 1)
            for bet_key, snap in current.items():
                if bet_key not in self.open_gaps:
                    row = dict(snap)
                    row["opened_at"] = ended_at
                    row["bet_key"] = bet_key
                    self.open_gaps[bet_key] = row
                    self._remember_recent(row, "open")
                    smaller = _size(snap.get("smaller"))
                    if smaller is not None:
                        self.smaller_sizes.append(float(smaller))
                        if len(self.smaller_sizes) > SIZE_CAP:
                            self.smaller_sizes = self.smaller_sizes[-SIZE_CAP:]
                    self.pending.append(self._gap_row("gap_open", row, ended_at, None))
                    gap_changed = True
                else:
                    self.open_gaps[bet_key].update(snap)
            for bet_key in list(self.open_gaps):
                if bet_key in current:
                    continue
                row = self.open_gaps.pop(bet_key)
                opened = _parse_time(row.get("opened_at"))
                ended = _parse_time(ended_at)
                life = 0.0
                if opened is not None and ended is not None:
                    life = max(0.0, (ended - opened).total_seconds())
                self.closed_n += 1
                self.closed_sum += life
                self.closed_lifetimes.append(round(life, 3))
                if len(self.closed_lifetimes) > LIFETIME_CAP:
                    self.closed_lifetimes = self.closed_lifetimes[-LIFETIME_CAP:]
                    self.lifetimes_truncated = True
                closed = dict(row)
                closed["closed_at"] = ended_at
                closed["lifetime_sec"] = round(life, 3)
                self._remember_recent(closed, "closed")
                self.pending.append(self._gap_row("gap_close", closed, ended_at, life))
                gap_changed = True
            need = gap_changed or bool(self.pending) or (time.monotonic() - self.last_state_flush) >= STATE_FLUSH_SEC
            if need:
                pending = self._take_pending()
                snap = self.snapshot()
                self.last_state_flush = time.monotonic()
            else:
                pending = []
                snap = None
        self._write_files(pending, snap)
        if gap_changed:
            try:
                write_page()
            except Exception:
                pass

    def _remember_recent(self, row: dict, state: str) -> None:
        item = dict(row)
        item["state"] = state
        self.recent.append(item)
        if len(self.recent) > LATEST_CAP:
            self.recent = self.recent[-LATEST_CAP:]

    def _gap_row(self, kind: str, row: dict, at: str, life: float | None) -> dict:
        payload = {
            "type": kind,
            "at": at,
            "game_key": self.key,
            "sport": self.sport,
            "game": self.title,
            "market_type": row.get("market_type") or "",
            "side": row.get("side") or "",
            "number": row.get("number") or "",
            "yes_venue": row.get("yes_venue") or "",
            "no_venue": row.get("no_venue") or "",
            "yes_size": row.get("yes_size") or "",
            "no_size": row.get("no_size") or "",
            "smaller": row.get("smaller") or "",
            "gross": row.get("gross") or "",
            "net": row.get("net") or "",
            "opened_at": row.get("opened_at") or "",
        }
        if life is not None:
            payload["lifetime_sec"] = round(life, 3)
        return payload

    def _roll(self, stamp: str) -> None:
        moment = _parse_time(stamp) or now_et()
        key = minute_key(moment)
        if key == self.minute:
            return
        self.pending.append(self._minute_row(self.minute))
        self.minute = key
        self.m_messages = {name: 0 for name in VENUES}
        self.m_updates = {name: 0 for name in VENUES}
        self.m_checks = 0
        self.m_no_gap = 0
        self.m_under = 0
        self.m_buyable = 0
        self.m_ms_sum = 0.0
        self.m_ms_max = 0.0

    def _minute_row(self, minute: str) -> dict:
        return {
            "type": "minute",
            "minute": minute,
            "game_key": self.key,
            "sport": self.sport,
            "game": self.title,
            "pid": self.pid,
            "transport": self.transport,
            "messages": dict(self.m_messages),
            "updates": dict(self.m_updates),
            "checks": self.m_checks,
            "no_gap": self.m_no_gap,
            "under_1": self.m_under,
            "buyable": self.m_buyable,
            "compare_ms_sum": round(self.m_ms_sum, 1),
            "compare_ms_max": round(self.m_ms_max, 1),
            "last_compare_started": self.last_compare_started,
            "last_compare_ended": self.last_compare_ended,
        }

    def _take_pending(self) -> list[dict]:
        rows = self.pending
        self.pending = []
        return rows

    def snapshot(self) -> dict:
        return {
            "key": self.key,
            "sport": self.sport,
            "game": self.title,
            "pid": self.pid,
            "started_at": self.started_at,
            "updated_at": iso_now(),
            "transport": self.transport,
            "minute": self.minute,
            "expected": dict(self.expected),
            "messages": dict(self.messages),
            "updates": dict(self.updates),
            "last_message": dict(self.last_message),
            "last_update": dict(self.last_update),
            "minute_messages": dict(self.m_messages),
            "minute_updates": dict(self.m_updates),
            "minute_checks": self.m_checks,
            "minute_no_gap": self.m_no_gap,
            "minute_under_1": self.m_under,
            "minute_buyable": self.m_buyable,
            "minute_compare_ms_sum": round(self.m_ms_sum, 1),
            "minute_compare_ms_max": round(self.m_ms_max, 1),
            "checks": self.checks,
            "no_gap": self.no_gap,
            "under_1": self.under,
            "buyable_checks": self.buyable_checks,
            "compare_ms_sum": round(self.ms_sum, 1),
            "last_compare_started": self.last_compare_started,
            "last_compare_ended": self.last_compare_ended,
            "last_compare_ms": self.last_compare_ms,
            "open_gaps": list(self.open_gaps.values()),
            "recent": list(self.recent),
            "closed_n": self.closed_n,
            "closed_sum_sec": round(self.closed_sum, 3),
            "closed_lifetimes": list(self.closed_lifetimes),
            "lifetimes_truncated": self.lifetimes_truncated,
            "smaller_sizes": list(self.smaller_sizes),
        }

    def flush(self, force: bool = False) -> None:
        with self.write_lock:
            with self.lock:
                self._roll(iso_now())
                if not force and (time.monotonic() - self.last_state_flush) < STATE_FLUSH_SEC and not self.pending:
                    return
                pending = self._take_pending()
                snap = self.snapshot()
                self.last_state_flush = time.monotonic()
            self._write_files(pending, snap)

    def _write_files(self, pending: list[dict], snap: dict | None) -> None:
        if pending:
            _append_jsonl(pending)
        if snap is not None:
            _write_state(self.key, snap)


def _get(key: str, sport: str, title: str) -> Tracker:
    with _trackers_guard:
        tracker = _trackers.get(key)
        created = tracker is None
        if tracker is None:
            tracker = Tracker(key, sport, title)
            _trackers[key] = tracker
        else:
            if sport:
                tracker.sport = sport
            if title:
                tracker.title = title
    if created:
        tracker.start_heartbeat()
    return tracker


def configure(key: str, sport: str, title: str, expected: dict | None = None) -> Tracker:
    tracker = _get(key, sport, title)
    if expected:
        with tracker.lock:
            for name in VENUES:
                if name in expected:
                    tracker.expected[name] = bool(expected[name])
    tracker.flush(force=True)
    tracker.start_heartbeat()
    return tracker


def note_stream(key: str, sport: str, title: str, venue: str, changed: bool) -> None:
    tracker = _get(key, sport, title)
    tracker.note_stream(venue, changed)


def record_check(key: str, sport: str, title: str, game: dict, scan, result: dict, started_at: str, ended_at: str, duration_ms: float, transport: str) -> None:
    tracker = _get(key, sport, title)
    tracker.record_check(game if isinstance(game, dict) else {}, scan, result or {}, started_at, ended_at, duration_ms, transport)


def _append_jsonl(rows: list[dict]) -> None:
    if not rows:
        return
    RAW.mkdir(parents=True, exist_ok=True)
    with venue_pace.FileLock(RAW / "live_checks.lock"):
        if CHECKS.exists() and CHECKS.stat().st_size > JSONL_MAX_BYTES:
            if CHECKS_PREV.exists():
                CHECKS_PREV.unlink()
            CHECKS.replace(CHECKS_PREV)
        with CHECKS.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_state(key: str, snap: dict) -> None:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in key)[:180] or "game"
    path = HEALTH_DIR / f"{safe}.json"
    tmp = HEALTH_DIR / f"{safe}.json.tmp"
    tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _load_health() -> list[dict]:
    if not HEALTH_DIR.exists():
        return []
    rows = []
    for path in sorted(HEALTH_DIR.glob("*.json")):
        row = _read_json(path)
        if row.get("key"):
            rows.append(row)
    return rows


def _venue_label(name: str) -> str:
    if name == "polymarket":
        return "Polymarket US"
    if name == "novig":
        return "Novig"
    return name[:1].upper() + name[1:]


def _venue_cell(health: dict, name: str, moment: datetime, alive: bool) -> tuple[str, str]:
    """Status word and a short evidence string for one venue."""
    expected = bool((health.get("expected") or {}).get(name))
    if not expected:
        return "not in this game", ""
    last = str((health.get("last_message") or {}).get(name) or "")
    age = _age_sec(last, moment)
    minute_msgs = int((health.get("minute_messages") or {}).get(name) or 0)
    minute_ups = int((health.get("minute_updates") or {}).get(name) or 0)
    detail = f"msg {minute_msgs} / upd {minute_ups}"
    if not last:
        started = _parse_time(health.get("started_at"))
        if alive and started is not None and (moment - started).total_seconds() <= QUIET_SEC:
            return "starting", detail
        return "quiet" if alive else "stopped", detail
    if age is not None and age > QUIET_SEC:
        return "quiet" if alive else "stopped", detail
    return "ticking", detail


def _game_status(health: dict, alive: bool, moment: datetime) -> str:
    if not alive:
        return "stopped"
    labels = []
    for name in VENUES:
        label, _detail = _venue_cell(health, name, moment, alive)
        if label != "not in this game":
            labels.append(label)
    transport = str(health.get("transport") or "")
    if not labels:
        last = _age_sec(health.get("last_compare_ended"), moment)
        if "websocket" not in transport:
            if last is None:
                return "starting"
            if last > QUIET_SEC:
                return "quiet"
            return "polling"
        return "starting"
    if any(label == "ticking" for label in labels):
        return "ticking"
    if any(label == "starting" for label in labels):
        return "starting"
    return "quiet"


def _clock(text: str | None) -> str:
    moment = _parse_time(text)
    if moment is None:
        return ""
    return moment.strftime("%Y-%m-%d %H:%M:%S ET")


def _gap_page_row(game: dict, gap: dict, state: str) -> dict:
    return {
        "game": game.get("game") or "",
        "state": state,
        "opened_at": gap.get("opened_at") or "",
        "closed_at": gap.get("closed_at") or "",
        "lifetime_sec": gap.get("lifetime_sec"),
        "market_type": gap.get("market_type") or "",
        "side": gap.get("side") or "",
        "number": gap.get("number") or "",
        "yes_venue": gap.get("yes_venue") or "",
        "no_venue": gap.get("no_venue") or "",
        "yes_size": gap.get("yes_size") or "",
        "no_size": gap.get("no_size") or "",
        "smaller": gap.get("smaller") or "",
        "gross": gap.get("gross") or "",
        "net": gap.get("net") or "",
    }


ONE_LEG_ASKED = (
    "A live lock filled one side and not the other, and the phone never got a separate alert. "
    "Add a one-leg message, written to the supervisor log and attempted once on the phone, "
    "and keep a note on the page for when the phone channel times out."
)
ONE_LEG_ASKED_LATEST = (
    "send me a detailed analysis of the trade we just made that was one-leg only. "
    "we bought mateus cardoso alves to win over jose pereria. for 0.24. "
    "this page says file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/one_leg_note.html http 404 insufficient_shard_balance: "
    "insufficient shard balance do we know what that error is exactly, yet? "
    "Also, one-leg note page SHOULD tell us what we tried on the other side. "
    "in this example, we should have tried Kalshi at ?? and then when it failed we should have tried "
    "a higher price up to where it would no longer be a profitable trade. "
    "this trade SHOULD also appear on this page file:///C:/Users/songg/Downloads/stockresearch/drive/"
    "paul_experiments/prediction_market_arb_exhaustive_20261017/orders.html "
    "give me a detail of what we tried and when we gave up and what you plan to do about it?"
)
ONE_LEG_PLAIN = (
    "A lock is supposed to buy both sides of the same bet so the $1 payout covers the cost. "
    "Both legs are now sent at the same time at the quoted limits. "
    "If exactly one side fills, we send one recovery on the missed venue at the highest price that still keeps "
    "the pair profitable after the actual fill (websocket, then book, then midway, never above that max). "
    "If that recovery also misses, new pairs stop, and a 20-second all-venues watch may still buy the "
    "opposite bet — including on the origin venue — if it falls to a profitable price. Orders turn back on only after that second fill. "
    "This note lists the fill, every price tried on the other side, "
    "the HTTP result, and that max profitable price. "
    "There is no Polymarket-first preference anymore. "
    "Repeating the same price after HTTP 404 insufficient_shard_balance is only a Kalshi shard retry "
    "(up to two more posts, two seconds apart on that Kalshi thread alone). It is not the normal leg delay, "
    "and it does not block the parallel partner send. "
    "That 404 means Kalshi has no account on the shard for that sport. Tennis is shard 3. "
    "The phone attempt can time out. This page is the copy you can still open."
)


def load_one_leg_alerts() -> list[dict]:
    if not ONE_LEG_LOG.exists():
        return []
    rows = []
    try:
        text = ONE_LEG_LOG.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _io_by_instrument() -> dict[tuple, list[dict]]:
    path = RAW / "order_io.jsonl"
    found: dict[tuple, list[dict]] = {}
    if not path.exists():
        return found
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return found
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or str(row.get("kind") or "") != "order":
            continue
        request = row.get("request") if isinstance(row.get("request"), dict) else {}
        instrument = str(request.get("marketSlug") or request.get("ticker") or request.get("symbol") or "")
        venue = str(row.get("venue") or "")
        if not instrument:
            continue
        found.setdefault((venue, instrument), []).append(row)
    return found


def _error_fields(row: dict) -> tuple[str, str, str]:
    response = row.get("response") if isinstance(row.get("response"), dict) else {}
    error = response.get("error") if isinstance(response.get("error"), dict) else {}
    return (
        str(error.get("code") or ""),
        str(error.get("message") or ""),
        str(error.get("details") or ""),
    )


def _poly_fill_bits(row: dict | None) -> dict:
    blank = {"outcome": "", "intent": "", "avg": "", "fee": "", "state": ""}
    if not isinstance(row, dict):
        return blank
    response = row.get("response")

    def walk(value) -> None:
        if isinstance(value, dict):
            state = str(value.get("state") or "")
            if "FILLED" in state:
                blank["state"] = state
            intent = str(value.get("intent") or "")
            if "LONG" in intent or "SHORT" in intent:
                blank["intent"] = intent
            meta = value.get("marketMetadata")
            if isinstance(meta, dict) and meta.get("outcome"):
                blank["outcome"] = str(meta.get("outcome"))
            avg = value.get("avgPx")
            if isinstance(avg, dict) and str(avg.get("value") or "") not in {"", "0", "0.0", "0.00", "0.000", "0.0000"}:
                blank["avg"] = str(avg.get("value"))
            fee = value.get("commissionNotionalTotalCollected")
            if isinstance(fee, dict) and "FILLED" in state:
                blank["fee"] = str(fee.get("value") or "0")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(response)
    return blank


def _one_leg_facts() -> list[dict]:
    """One-leg pairs from orders.jsonl, with each send on the other side."""
    import order_ledger

    orders = order_ledger._load_jsonl(order_ledger.ORDERS)
    io_rows = _io_by_instrument()
    times = order_ledger._send_times()
    used: dict[tuple, int] = {}
    io_cursor: dict[tuple, int] = {}
    facts = []
    try:
        import live_lock_orders
    except Exception:
        live_lock_orders = None
    for context, events in order_ledger._attempts(orders):
        if not any(item.get("event") == "one_leg" for item in events):
            continue
        sends = [item for item in events if item.get("event") == "sent"]
        terminal = next(item for item in reversed(events) if item.get("event") == "one_leg")
        filled = next((item for item in events if item.get("event") == "filled"), None)
        first = next((item for item in sends if str(item.get("venue") or "") == str(terminal.get("venue") or "")), None)
        second_venue = str(terminal.get("second_venue") or "")
        second = [item for item in sends if str(item.get("venue") or "") == second_venue]
        attempts = []
        for item in sends:
            venue = str(item.get("venue") or "")
            instrument = str(item.get("instrument") or "")
            side = str(item.get("side") or "")
            limit = str(item.get("limit_price") or "")
            http = str(item.get("http_status") or "")
            key = (venue, instrument, side, limit, http)
            slots = times.get(key) or []
            cursor = used.get(key, 0)
            when = slots[cursor] if cursor < len(slots) else ""
            used[key] = cursor + 1
            io_key = (venue, instrument)
            io_list = io_rows.get(io_key) or []
            attempt_no = int(item.get("attempt") or 0)
            io_match = None
            for candidate in io_list:
                try:
                    same = int(candidate.get("attempt") or 0) == attempt_no and attempt_no
                except (TypeError, ValueError):
                    same = False
                if same:
                    io_match = candidate
                    break
            if io_match is None and io_list:
                cursor = io_cursor.get(io_key, 0)
                if cursor < len(io_list):
                    io_match = io_list[cursor]
                    io_cursor[io_key] = cursor + 1
            request = (io_match or {}).get("request") if isinstance((io_match or {}).get("request"), dict) else {}
            if "SHORT" in str(request.get("intent") or ""):
                side = "no"
            elif "LONG" in str(request.get("intent") or ""):
                side = "yes"
            code, message, details = _error_fields(io_match or {})
            if not when and isinstance(io_match, dict):
                when = str(io_match.get("timestamp") or "")
            attempts.append({
                "when": when,
                "venue": venue,
                "instrument": instrument,
                "side": side,
                "limit": limit,
                "size": str(item.get("size") or "1"),
                "http": http,
                "step": str(item.get("step") or ""),
                "attempt": str(item.get("attempt") or ""),
                "code": code,
                "message": message,
                "details": details,
                "order_id": str(item.get("order_id") or ""),
            })
        poly_io = None
        if first:
            poly_list = list(io_rows.get((str(first.get("venue") or ""), str(first.get("instrument") or ""))) or [])
            poly_io = poly_list[0] if poly_list else None
        poly_bits = _poly_fill_bits(poly_io)
        fee = poly_bits.get("fee") or "0"
        other_price = str((first or {}).get("limit_price") or (filled or {}).get("price") or "")
        cap = ""
        if live_lock_orders is not None and second_venue and other_price and fee != "":
            try:
                amount = live_lock_orders.max_leg_price(second_venue, Decimal(other_price), Decimal(fee))
            except Exception:
                amount = None
            if amount is not None:
                cap = format(amount, "f")
        second_limits = [row["limit"] for row in attempts if row["venue"] == second_venue]
        unique = set(second_limits)
        if not second_limits:
            walk = "not sent"
        elif len(unique) <= 1:
            walk = "same price repeated"
        else:
            walk = "more than one price"
        facts.append({
            "game": str(context.get("game") or ""),
            "market": " ".join(
                part for part in (str(context.get("market_type") or ""), str(context.get("side") or "")) if part
            ),
            "filled_venue": str((filled or terminal).get("venue") or ""),
            "contract": str((filled or terminal).get("instrument") or ""),
            "side": (
            "no" if "SHORT" in str(poly_bits.get("intent") or "")
            else "yes" if "LONG" in str(poly_bits.get("intent") or "")
            else str((filled or first or terminal).get("side") or "")
        ),
            "price": str((filled or {}).get("price") or ""),
            "limit": other_price,
            "fee": fee,
            "order_id": str((first or {}).get("order_id") or ""),
            "outcome_name": poly_bits.get("outcome") or "",
            "intent": poly_bits.get("intent") or "",
            "other_venue": second_venue,
            "other_contract": str((second[0].get("instrument") if second else "") or ""),
            "other_side": str((second[0].get("side") if second else "") or ""),
            "cap": cap,
            "walk": walk,
            "attempts": attempts,
            "note": str(terminal.get("note") or ""),
        })
    return facts


def _walk_sentence(fact: dict) -> str:
    other = [row for row in fact["attempts"] if row["venue"] == fact["other_venue"]]
    if not other:
        return "The other side has no sent order in the ledger."
    prices = ", ".join(row["limit"] for row in other)
    http = ", ".join(row["http"] for row in other)
    if fact["walk"] == "same price repeated":
        move = (
            f"All {len(other)} {fact['other_venue']} sends used the same limit ({prices}). "
            "The price was not walked up. A higher price was not sent."
        )
    else:
        move = f"{fact['other_venue']} limits sent: {prices}."
    cap = fact.get("cap") or "not computed"
    unit = (
        "That cap is the highest No cost (one minus the Kalshi ask), not the ask itself. "
        if fact.get("other_side") == "no" and fact.get("other_venue") == "kalshi"
        else "That cap is the highest price on the unfilled leg. "
    )
    try:
        import live_lock_orders

        send_cap = live_lock_orders.send_line()
    except Exception:
        send_cap = "NET_MAX"
    return (
        f"{move} HTTP {http}. "
        f"Profit cap on the {fact['other_venue']} leg, using the filled leg's sent price {fact.get('limit')} "
        f"and fee {fact.get('fee')}, is {cap}. "
        f"{unit}"
        f"The two prices must stay under $1 and the net at or under ${send_cap}. "
        "Kalshi is charged $0 in that check until a fill returns a fee."
    )


def _one_leg_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        cells = [
            row.get("seen_at") or "",
            row.get("game") or "",
            row.get("market") or "",
            row.get("filled_venue") or "",
            row.get("contract") or "",
            row.get("side") or "",
            row.get("price") or "",
            row.get("order_id") or "",
            row.get("other_venue") or "",
            row.get("other_contract") or "",
            row.get("other_side") or "",
            row.get("other_result") or "",
            row.get("note") or "",
        ]
        body.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>")
    headers = [
        ("When", "text"),
        ("Game", "text"),
        ("Market", "text"),
        ("Filled venue", "text"),
        ("Contract", "text"),
        ("Side", "text"),
        ("Price", "num"),
        ("Order id", "text"),
        ("Other venue", "text"),
        ("Other contract", "text"),
        ("Other side", "text"),
        ("Other leg result", "text"),
        ("Note", "text"),
    ]
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + "".join(_th(label, kind) for label, kind in headers)
        + "</tr></thead><tbody>"
        + ("".join(body) if body else "<tr><td>No one-leg fill has been recorded.</td></tr>")
        + "</tbody></table></div>"
    )


def _attempt_table(facts: list[dict]) -> str:
    headers = [
        ("Game", "text"),
        ("Attempt", "num"),
        ("Time", "date"),
        ("Venue", "text"),
        ("Instrument", "text"),
        ("Side", "text"),
        ("Limit sent", "num"),
        ("Size", "num"),
        ("HTTP", "num"),
        ("Step", "text"),
        ("Error code", "text"),
        ("Error message", "text"),
        ("Error details", "text"),
        ("Order id", "text"),
    ]
    body = []
    for fact in facts:
        for row in fact["attempts"]:
            cells = [
                fact.get("game") or "",
                row.get("attempt") or "",
                row.get("when") or "",
                row.get("venue") or "",
                row.get("instrument") or "",
                row.get("side") or "",
                row.get("limit") or "",
                row.get("size") or "",
                row.get("http") or "",
                row.get("step") or "",
                row.get("code") or "",
                row.get("message") or "",
                row.get("details") or "",
                row.get("order_id") or "",
            ]
            body.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + "".join(_th(label, kind) for label, kind in headers)
        + "</tr></thead><tbody>"
        + ("".join(body) if body else "<tr><td>No sends are on the ledger.</td></tr>")
        + "</tbody></table></div>"
    )


def _summary_from_facts(facts: list[dict]) -> str:
    headers = [
        ("Game", "text"),
        ("Filled venue", "text"),
        ("Contract", "text"),
        ("Book side", "text"),
        ("Outcome", "text"),
        ("Fill price", "num"),
        ("Fee", "num"),
        ("Order id", "text"),
        ("Other venue", "text"),
        ("Other contract", "text"),
        ("Other side", "text"),
        ("Other prices sent", "text"),
        ("Profit cap", "num"),
        ("Walked up?", "text"),
    ]
    body = []
    for fact in facts:
        prices = ", ".join(
            row["limit"] for row in fact["attempts"] if row["venue"] == fact["other_venue"]
        )
        cells = [
            fact.get("game") or "",
            fact.get("filled_venue") or "",
            fact.get("contract") or "",
            fact.get("side") or "",
            fact.get("outcome_name") or "",
            fact.get("price") or "",
            fact.get("fee") or "",
            fact.get("order_id") or "",
            fact.get("other_venue") or "",
            fact.get("other_contract") or "",
            fact.get("other_side") or "",
            prices,
            fact.get("cap") or "",
            fact.get("walk") or "",
        ]
        body.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + "".join(_th(label, kind) for label, kind in headers)
        + "</tr></thead><tbody>"
        + ("".join(body) if body else "<tr><td>No one-leg fill has been recorded.</td></tr>")
        + "</tbody></table></div>"
    )


def _page_shell(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
{body}
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def _write_html(path: Path, title: str, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(_page_shell(title, body), encoding="utf-8")
    tmp.replace(path)
    return path


def write_one_leg_note(rows: list[dict] | None = None) -> Path:
    """Small page that is not wiped by the 30-second stream-health rewrite."""
    facts = _one_leg_facts()
    narratives = []
    for fact in facts:
        who = fact.get("outcome_name") or fact.get("game")
        narratives.append(
            f"<h2>{_esc(fact.get('game') or '')}</h2>"
            f"<p>{_esc(who)} on { _esc(fact.get('filled_venue') or '') } "
            f"{_esc(fact.get('side') or '')} filled at {_esc(fact.get('price') or '')} "
            f"(order {_esc(fact.get('order_id') or '')}, fee {_esc(fact.get('fee') or '')}). "
            f"{_esc(_walk_sentence(fact))}</p>"
        )
    fallback = ""
    if not facts:
        fallback = _one_leg_table(load_one_leg_alerts() if rows is None else rows)
    body = f"""
<h1>One leg filled</h1>
<p class="note">America/New_York. Research only. Not gold. Not DailyRun. This page does not place or cancel orders. Click column headers to sort. Orders are still stopped.</p>
<div class="callout"><h2>What you asked</h2><p>{_esc(ONE_LEG_ASKED)}</p><p>{_esc(ONE_LEG_ASKED_LATEST)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{_esc(ONE_LEG_PLAIN)}</p></div>
<p class="note">The Alves vs Pereira writeup is <a href="alves_pereira_one_leg_20261019.html">alves_pereira_one_leg_20261019.html</a>. The sent orders are on <a href="orders.html">orders.html</a>.</p>
<p class="note">Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{''.join(narratives)}
<h2>One-leg fills</h2>
{_summary_from_facts(facts)}
<h2>Every price that was sent</h2>
<p class="note">One row per order the ledger recorded. A Kalshi HTTP 404 with code insufficient_shard_balance and details starting with "Exchange user not found" means there is no Kalshi user on that sport's shard. The same limit was sent again. That is not a higher price.</p>
{_attempt_table(facts)}
{fallback}
"""
    return _write_html(ONE_LEG_PAGE, "One leg filled", body)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>One leg filled</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
{body}
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    ONE_LEG_PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ONE_LEG_PAGE.parent / (ONE_LEG_PAGE.name + ".tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(ONE_LEG_PAGE)
    return ONE_LEG_PAGE


def write_alves_one_leg_page() -> Path:
    """Stand-alone writeup for the 2026-10-19 Alves vs Pereira one-leg. Does not send an order."""
    try:
        import live_lock_orders
    except Exception:
        live_lock_orders = None
    fact = next((row for row in _one_leg_facts() if row.get("game") == "Alves vs Pereira"), None)
    if fact is None:
        body = "<h1>Alves vs Pereira</h1><p>No Alves one-leg row is on the ledger.</p>"
        return _write_html(STAMP / "alves_pereira_one_leg_20261019.html", "Alves vs Pereira one leg", body)
    lines = []
    for row in fact["attempts"]:
        lines.append(
            f"<li>{_esc(row.get('when') or 'time not on the log')} "
            f"{_esc(row.get('venue'))} {_esc(row.get('side'))} {_esc(row.get('instrument'))} "
            f"limit {_esc(row.get('limit'))} size {_esc(row.get('size'))} "
            f"HTTP {_esc(row.get('http'))} step {_esc(row.get('step') or 'unknown')} "
            f"attempt {_esc(row.get('attempt') or '')} "
            f"order {_esc(row.get('order_id') or 'none')} "
            f"code {_esc(row.get('code') or '')} "
            f"message {_esc(row.get('message') or '')} "
            f"details {_esc(row.get('details') or '')}</li>"
        )
    body = f"""
<h1>Alves vs Pereira, one leg only</h1>
<p class="note">America/New_York. Research only. Not gold. Not DailyRun. This page does not place or cancel orders. Orders are still stopped. Nothing here moves Kalshi funds.</p>
<div class="callout"><h2>What you asked</h2><p>{_esc(ONE_LEG_ASKED_LATEST)}</p></div>
<div class="callout"><h2>In plain English</h2>
<p>We bought Mateus Cardoso Alves to win, on Polymarket, one contract. The order was a buy-long Yes at 0.230, and the venue filled it at 0.2300. The phone note said about 0.24. The ledger fill is 0.2300, not 0.24. The other side was Jose Pereira to win on Kalshi, ticker KXATPCHALLENGERMATCH-26OCT19ALVPER-PER, Yes, at 0.6600. Kalshi rejected that three times with the same price. We did not try a higher Kalshi price. The pair would have stopped being profitable at a Kalshi Yes price of {_esc(fact.get('cap') or '')}. We gave up because Kalshi has no user on the tennis shard, then the lock turned orders off. A higher price cannot create that user.</p>
</div>
<h2>What the 404 means on this response</h2>
<p>Each Kalshi response for this trade was HTTP 404. The error object was code <code>insufficient_shard_balance</code>, message <code>insufficient shard balance</code>, details <code>Exchange user not found. For Predictions: reference documentation Exchange Sharding documentation.</code> That is the same code and message as the earlier tennis 404s. The details field is the full sentence, not only the words "Exchange user not found." Kalshi shards predictions. Tennis is shard 3. A balance read around 12:48 PM ET showed about $22.53 on shard 0 and $0.00 on shards 1, 2, and 3. The 3:08 PM ET balance line after this fill still showed kalshi=22.53, which is the cash the default balance read sees. It does not show a funded tennis shard. Retrying the same order cannot create the shard user. The repo has no transfer function. This job did not move money.</p>
<h2>Timeline</h2>
<p>Exchange create time on the Polymarket fill is 2026-10-19T19:08:33.222119636Z, which is 15:08:33 ET. The local log times below are when this machine recorded the HTTP result.</p>
<ul>
{''.join(lines)}
</ul>
<p>Supervisor log, America/New_York:</p>
<ul>
<li>15:08:34.906 order sent Polymarket Yes aec-atp-matalv-josper-2026-10-19 limit 0.230 size 1 HTTP 200. Order id D6SKMGHG10JK. Intent ORDER_INTENT_BUY_LONG. Outcome Mateus Cardoso Alves. Average price 0.2300. Fee 0.0100. State ORDER_STATE_FILLED. Size 1.</li>
<li>15:08:35.235 Kalshi Yes KXATPCHALLENGERMATCH-26OCT19ALVPER-PER limit 0.6600 size 1 HTTP 404. Attempt 1. Step websocket. Same client order id on the retries.</li>
<li>15:08:35.236 log: order retry shard user missing, waiting 2 seconds.</li>
<li>15:08:37.493 same Kalshi order again, limit still 0.6600, HTTP 404. Attempt 2.</li>
<li>15:08:37.494 waiting 2 seconds.</li>
<li>15:08:39.750 same Kalshi order again, limit still 0.6600, HTTP 404. Attempt 3.</li>
<li>15:08:39.751 ONE LEG Polymarket Yes price 0.2300.</li>
<li>15:08:39.840 one-leg log line. It says no further order was sent.</li>
<li>15:08:40 orders_stopped.json: stopped true, reason "one leg filled and the other missed".</li>
<li>15:08:40.477 balances after fill: kalshi=22.53 gemini=25.02 polymarket=50.19.</li>
</ul>
<h2>Did we walk the Kalshi price up?</h2>
<p>No. The three Kalshi limits in orders.jsonl and order_io.jsonl are 0.6600, 0.6600, and 0.6600. The step on each row is websocket. There is no book step and no midway step. The profit-cap walk (websocket, then book ask, then halfway to the cap) runs only when an immediate-or-cancel comes back cancelled with nothing filled. This 404 is not that. The separate 404 rule sent the same limit up to two more times, two seconds apart. That retry is not a higher price. After the third 404 the sender stopped. The profit cap, from the Polymarket limit 0.230 and the 0.01 fee on that fill, is {_esc(fact.get('cap') or '')} on the Kalshi Yes. 0.6600 is under that cap, so the price was not the reason we stopped. Net at the prices we sent is 0.230 + 0.6600 + 0.01 = 0.90, still at or under {live_lock_orders.send_line() if live_lock_orders is not None else 'NET_MAX'}, with the Kalshi fee counted as 0 because Kalshi never returned a fill fee.</p>
<h2>Later read of the Polymarket account</h2>
<p>A read-only GET /v1/orders/D6SKMGHG10JK returned HTTP 404 with message "The server was unable to process your request." That is not the Kalshi shard error. A read-only GET /v1/portfolio/positions returned HTTP 200 with an empty positions list (eof true). So that positions call does not independently show the share still open. The fill we can quote is the order response saved at send time: cumQuantity 1, avgPx 0.2300, fee 0.0100, ORDER_STATE_FILLED, outcome Mateus Cardoso Alves.</p>
<h2>What should change</h2>
<p>Paul funds tennis shard 3 on the Kalshi website. Until that user exists, tennis Kalshi legs will 404. This code will not transfer money and will not turn orders back on. The useful code change, which this page is, is to show the attempted price and the profit cap even when the walk-up never ran. A higher price cannot fix "exchange user not found."</p>
<p class="note">Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
<h2>Sends on this pair</h2>
{_attempt_table([fact])}
"""
    return _write_html(STAMP / "alves_pereira_one_leg_20261019.html", "Alves vs Pereira one leg", body)


def append_one_leg_alert(row: dict) -> None:
    """Append one row and refresh the note. Does not send an order."""
    ONE_LEG_LOG.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ONE_LEG_LOG.with_suffix(".lock")
    with venue_pace.FileLock(lock_path):
        with ONE_LEG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        write_one_leg_note()


def write_page() -> Path:
    """Cheap rewrite from the small per-game state files. Does not scan the JSONL."""
    with _page_lock:
        return _write_page_locked()


def _write_page_locked() -> Path:
    moment = now_et()
    status = _read_json(STATUS)
    supervisor = _read_json(SUPERVISOR_PID)
    supervisor_pid = int(status.get("supervisor_pid") or supervisor.get("pid") or 0)
    supervisor_alive = pid_alive(supervisor_pid)
    listed = status.get("games") if isinstance(status.get("games"), list) else []
    by_key = {}
    for row in _load_health():
        by_key[str(row.get("key"))] = row
    games = []
    seen = set()
    for row in listed:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "")
        if not key:
            continue
        seen.add(key)
        health = by_key.get(key) or {}
        merged = dict(health)
        merged.setdefault("key", key)
        merged.setdefault("sport", row.get("sport") or "")
        merged.setdefault("game", row.get("game") or key)
        if not merged.get("pid"):
            merged["pid"] = row.get("pid")
        if not merged.get("transport"):
            merged["transport"] = row.get("transport") or ""
        if not merged.get("last_compare_ended") and row.get("last_poll"):
            merged["last_compare_ended"] = row.get("last_poll")
        games.append(merged)
    for key, health in by_key.items():
        if key in seen:
            continue
        updated = _age_sec(health.get("updated_at"), moment)
        if updated is not None and updated < 600:
            games.append(health)
    alive_children = 0
    for game in games:
        try:
            pid = int(game.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid_alive(pid):
            alive_children += 1
    checks_min = sum(int(g.get("minute_checks") or 0) for g in games)
    updates_min = 0
    messages_min = 0
    for game in games:
        for name in VENUES:
            updates_min += int((game.get("minute_updates") or {}).get(name) or 0)
            messages_min += int((game.get("minute_messages") or {}).get(name) or 0)
    quiet_n = 0
    ticking_n = 0
    body_rows = []
    gap_rows = []
    lifetimes: list[float] = []
    lifetime_n = 0
    lifetime_sum = 0.0
    truncated = False
    sizes: list[float] = []
    longest_open = None
    open_now = 0
    for game in games:
        try:
            pid = int(game.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        alive = pid_alive(pid)
        status_word = _game_status(game, alive, moment)
        if status_word == "quiet":
            quiet_n += 1
        elif status_word == "ticking":
            ticking_n += 1
        minute_label = str(game.get("minute") or "")
        current_minute = minute_key(moment)
        stale_minute = bool(minute_label) and minute_label != current_minute
        def minute_count(field: str) -> str:
            if not game.get("updated_at"):
                return ""
            if stale_minute:
                return "0"
            return str(int(game.get(field) or 0))
        cells = [
            _esc(game.get("game") or game.get("key") or ""),
            _esc(game.get("sport") or ""),
            _esc(status_word),
            _esc(pid or ""),
            "yes" if alive else "no",
            _esc(game.get("transport") or ""),
            _esc(_clock(game.get("last_compare_ended")) or "none yet"),
            _esc(_fmt_num((float(game["last_compare_ms"]) / 1000.0) if game.get("last_compare_ms") not in (None, "") else None, 3)),
            minute_count("minute_checks"),
            minute_count("minute_no_gap"),
            minute_count("minute_under_1"),
            minute_count("minute_buyable"),
        ]
        for name in VENUES:
            label, _detail = _venue_cell(game, name, moment, alive)
            last_msg = (game.get("last_message") or {}).get(name) or ""
            last_upd = (game.get("last_update") or {}).get(name) or ""
            if stale_minute or not game.get("updated_at"):
                msg_n = "0" if game.get("updated_at") else ""
                upd_n = "0" if game.get("updated_at") else ""
            else:
                msg_n = str(int((game.get("minute_messages") or {}).get(name) or 0))
                upd_n = str(int((game.get("minute_updates") or {}).get(name) or 0))
            cells.extend([
                _esc(label),
                msg_n,
                upd_n,
                _esc(_clock(last_msg) or ""),
                _esc(_clock(last_upd) or ""),
            ])
        open_gaps = [g for g in (game.get("open_gaps") or []) if isinstance(g, dict)]
        open_now += len(open_gaps)
        longest_here = None
        for gap in open_gaps:
            age = _age_sec(gap.get("opened_at"), moment)
            if age is None:
                continue
            if longest_here is None or age > longest_here:
                longest_here = age
            if longest_open is None or age > longest_open:
                longest_open = age
        cells.append(str(len(open_gaps)))
        cells.append(_fmt_num(longest_here, 1))
        body_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
        lifetime_n += int(game.get("closed_n") or 0)
        lifetime_sum += float(game.get("closed_sum_sec") or 0)
        for life in game.get("closed_lifetimes") or []:
            try:
                lifetimes.append(float(life))
            except (TypeError, ValueError):
                continue
        if game.get("lifetimes_truncated"):
            truncated = True
        for size in game.get("smaller_sizes") or []:
            try:
                sizes.append(float(size))
            except (TypeError, ValueError):
                continue
        for gap in open_gaps:
            gap_rows.append(_gap_page_row(game, gap, "open"))
        for gap in game.get("recent") or []:
            if isinstance(gap, dict) and gap.get("state") == "closed":
                gap_rows.append(_gap_page_row(game, gap, "closed"))
    headers = [
        ("Game", "text"),
        ("Sport", "text"),
        ("Status", "text"),
        ("PID", "num"),
        ("PID alive", "text"),
        ("Feed", "text"),
        ("Last check end", "text"),
        ("Last check seconds", "num"),
        ("Checks this minute", "num"),
        ("No gap under $1", "num"),
        ("Under $1 before fee", "num"),
        ("Buyable", "num"),
    ]
    for name in VENUES:
        label = _venue_label(name)
        headers.extend([
            (f"{label} stream", "text"),
            (f"{label} messages this minute", "num"),
            (f"{label} price updates this minute", "num"),
            (f"{label} last message", "text"),
            (f"{label} last price update", "text"),
        ])
    headers.extend([
        ("Open buyable gaps", "num"),
        ("Longest open seconds", "num"),
    ])
    game_table = (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + "".join(_th(label, kind) for label, kind in headers)
        + "</tr></thead><tbody>"
        + ("".join(body_rows) if body_rows else "<tr><td>No live checker has reported yet.</td></tr>")
        + "</tbody></table></div>"
    )
    gap_rows.sort(key=lambda item: str(item.get("opened_at") or ""), reverse=True)
    gap_body = []
    for gap in gap_rows[:40]:
        life = gap.get("lifetime_sec")
        if life in (None, "") and gap.get("state") == "open":
            life_txt = _fmt_num(_age_sec(gap.get("opened_at"), moment), 1)
        else:
            life_txt = _fmt_num(life, 1) if life not in (None, "") else ""
        gap_body.append(
            "<tr>"
            f"<td>{_esc(gap.get('game'))}</td>"
            f"<td>{_esc(gap.get('state') or '')}</td>"
            f"<td>{_esc(gap.get('market_type'))}</td>"
            f"<td>{_esc(gap.get('side'))}</td>"
            f"<td>{_esc(gap.get('number'))}</td>"
            f"<td>{_esc(gap.get('yes_venue'))}</td>"
            f"<td>{_esc(gap.get('yes_size'))}</td>"
            f"<td>{_esc(gap.get('no_venue'))}</td>"
            f"<td>{_esc(gap.get('no_size'))}</td>"
            f"<td>{_esc(gap.get('smaller'))}</td>"
            f"<td>{_esc(gap.get('gross'))}</td>"
            f"<td>{_esc(gap.get('net'))}</td>"
            f"<td>{_esc(_clock(gap.get('opened_at')))}</td>"
            f"<td>{_esc(_clock(gap.get('closed_at')))}</td>"
            f"<td>{_esc(life_txt)}</td>"
            "</tr>"
        )
    gap_table = (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + _th("Game", "text")
        + _th("State", "text")
        + _th("Market", "text")
        + _th("Side", "text")
        + _th("Number", "text")
        + _th("Yes venue", "text")
        + _th("Yes size", "num")
        + _th("No venue", "text")
        + _th("No size", "num")
        + _th("Smaller leg", "num")
        + _th("Gross", "num")
        + _th("Net after fee", "num")
        + _th("Opened", "text")
        + _th("Closed", "text")
        + _th("Lifetime seconds", "num")
        + "</tr></thead><tbody>"
        + ("".join(gap_body) if gap_body else "<tr><td>No buyable under-$1 gap has been logged yet.</td></tr>")
        + "</tbody></table></div>"
    )
    avg_life = (lifetime_sum / lifetime_n) if lifetime_n else None
    med_life = _median(lifetimes)
    med_note = ""
    if truncated or (lifetime_n and len(lifetimes) < lifetime_n):
        med_note = f" Median uses the last {len(lifetimes)} closed gaps. Average uses all {lifetime_n}."
    size_min = min(sizes) if sizes else None
    size_med = _median(sizes)
    size_max = max(sizes) if sizes else None
    summary_rows = [
        ("Supervisor PID", str(supervisor_pid or "none")),
        ("Supervisor alive", "yes" if supervisor_alive else "no"),
        ("Child checkers listed", str(len(games))),
        ("Child checkers alive", str(alive_children)),
        ("Games ticking", str(ticking_n)),
        ("Games quiet", str(quiet_n)),
        ("Stream messages this minute", str(messages_min)),
        ("Price updates this minute", str(updates_min)),
        ("Checks this minute", str(checks_min)),
        ("Open buyable gaps", str(open_now)),
        ("Longest open gap seconds", _fmt_num(longest_open, 1) or "none"),
        ("Closed buyable gaps", str(lifetime_n)),
        ("Average gap lifetime seconds", _fmt_num(avg_life, 1) or "none yet"),
        ("Median gap lifetime seconds", _fmt_num(med_life, 1) or "none yet"),
        ("Smaller-leg size min", _fmt_num(size_min, 2) or "none yet"),
        ("Smaller-leg size median", _fmt_num(size_med, 2) or "none yet"),
        ("Smaller-leg size max", _fmt_num(size_max, 2) or "none yet"),
        ("Buyable gaps sampled for size", str(len(sizes))),
    ]
    summary = (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + _th("Metric", "text")
        + _th("Value", "text")
        + "</tr></thead><tbody>"
        + "".join(f"<tr><td>{_esc(label)}</td><td>{_esc(value)}</td></tr>" for label, value in summary_rows)
        + "</tbody></table></div>"
    )
    empty_note = ""
    if not games:
        empty_note = (
            "<p class=\"note\">No checker state is on disk yet. "
            "Counts stay blank until a restarted live checker runs for about a minute.</p>"
        )
    body = f"""
<h1>Live stream health</h1>
<p class="note">America/New_York. Research only. Not gold. Not DailyRun. No orders from this page. Click column headers to sort.</p>
<div class="callout"><h2>What you asked</h2><p>{_esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{_esc(PLAIN)}</p></div>
<p class="note">Kalshi is not charged a fee in this check. Gemini's fee is on the Gemini leg. Polymarket US uses that market's fee coefficient: fee = coefficient × contracts × price × (1 − price), rounded half-even to the cent, on the Polymarket leg only. A buyable gap uses the same trade identity as the phone alert and does not send a second phone ping. Quiet means that venue's price stream has had no message for more than two minutes while the checker process is still alive. This minute is the clock minute in Eastern Time. The page rewrites about every 30 seconds, and when a buyable gap opens or closes.</p>
<p class="note">{_esc(med_note.strip())}</p>
{SWIPE_NOTE_HTML}
<h2>Is it moving</h2>
{summary}
{empty_note}
<h2>Each live game</h2>
<p class="note">Messages are quotes that arrived. Price updates are quotes whose price or size changed. Checks this minute count comparisons, not raw ticks.</p>
{game_table}
<h2>One leg filled, other leg did not</h2>
<p class="note">Separate from the under-$1 phone ping. A row here means one side filled and the other did not. No repair order is sent. The same rows are on <a href="one_leg_note.html">one_leg_note.html</a>.</p>
{_one_leg_table(load_one_leg_alerts())}
<h2>Buyable gaps</h2>
<p class="note">Latest open and recently closed buyable gaps. Size is the number of contracts offered on that leg. Smaller leg is the thinner of the two.</p>
{gap_table}
<p class="note">Updated {_esc(moment.strftime("%Y-%m-%d %H:%M:%S ET"))}.</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live stream health</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
a {{ color: #1d4ed8; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
{body}
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.parent / (PAGE.name + ".tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE
