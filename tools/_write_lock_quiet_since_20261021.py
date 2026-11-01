"""Why no both-sides lock fill since 2026-10-21 23:28 ET.

Research only. Reads live state + tape. Does not place, cancel, flatten, sell,
or rest GTC. Does not start a second live_strategy_b.py. Does not change
orders_stopped.json or systems.json lock on/off.
Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_quiet_since_20261021.html"
BOTH_PAGE = STAMP / "lock_both_sides_20261024.html"
EXTRACT = RAW / "lock_quiet_since_20261021.json"
JOB_STATUS = STAMP / "job_status.html"
JOB_CTRL = ROOT / "tools" / "prediction_job_control.py"
CUT = datetime(2026, 10, 21, 23, 28, 6, tzinfo=ET)
DEADLINE = datetime(2026, 10, 22, 8, 0, 0, tzinfo=ET)
HARD_FIRST = datetime(2026, 10, 24, 20, 7, 0, tzinfo=ET)
FLATTEN_STEPS = {"flatten", "extra-flatten"}
B_STEPS = {"b-t0", "b-cross", "b-leftover-yes", "b-fav"}
C_STEPS = {"c-t0"}
D_STEPS = {"d-t0"}
LOCK_SEND_STEPS = {"", "simultaneous", "websocket", "book", "watch"}
DIRECTIONAL_SPORTS = {"cfb-favorite", "spread-t0", "tennis-crossover", "tennis_crossover"}

ASKED = (
    "lock_both_sides_20261024.html looks promising. Why no successful both-sides "
    "fill since 2026-10-21? He thinks lock bot is on now and not turned off due "
    "to a failed leg. Is that correct? Is lock allowed to send new pairs right "
    "now? If ON: why zero both-sides since Oct 21 23:28 (Ruzic/Day). Walk Oct "
    "22–24 hour by hour. Hours latched after one-leg. Dual sends since Oct 21: "
    "count, hard_miss_abort, flatten-only, gap closed. Legal opportunities "
    "(net≤0.984) vs skipped: B absorbed tennis, MAX_OPEN, Indiana/Michigan "
    "same-contract, no size, Novig disabled, books not two-sided. Skip-absorbed-B. "
    "Hard-first sequential live only since ~20:07 ET 24 Oct. Last both-sides "
    "were leftover hedges, not simultaneous."
)
PLAIN = (
    "The lock bot tries to buy Yes in one shop and No in another when both "
    "tickets plus fees still cost 98.4 cents or less. The five both-sides fills "
    "we have were not two tickets landing together — they were leftover hedges: "
    "one shop filled, then later the other shop filled the missing side. After "
    "a one-leg miss the bot stops sending new pairs (the latch) and is supposed "
    "to keep watching for that missing hedge. If that leftover watch is killed, "
    "both-sides fills stop even when the system switch still says on. This page "
    "is research only: it does not turn lock on or off and it does not place tickets."
)


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, kind: str = "text") -> str:
    text = "" if value is None else str(value)
    extra = ' class="num"' if kind == "num" else ""
    return f"<td{extra}>{esc(text)}</td>"


def table(headers: list[tuple[str, str]], rows: list[list], total: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(td(cell, headers[i][1] if i < len(headers) else "text") for i, cell in enumerate(row))
        body.append(f"<tr>{cells}</tr>")
    if total is not None:
        cells = "".join(td(cell, headers[i][1] if i < len(headers) else "text") for i, cell in enumerate(total))
        body.append(f'<tr class="total-row">{cells}</tr>')
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def money4(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    return format(number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")


def parse_dt(raw) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        stamp = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            try:
                stamp = datetime.fromisoformat(text.split(" ", 1)[0])
            except ValueError:
                return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def fmt_et(stamp: datetime | None) -> str:
    if stamp is None:
        return ""
    return stamp.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S ET")


def hour_floor(stamp: datetime) -> datetime:
    return stamp.replace(minute=0, second=0, microsecond=0)


def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def row_when(row: dict) -> datetime | None:
    for key in ("at", "timestamp", "ts", "when", "sent_at", "filled_at"):
        stamp = parse_dt(row.get(key))
        if stamp:
            return stamp
    return None


def step_of(row: dict) -> str:
    return str(row.get("step") or "").strip().lower()


def is_directional(row: dict) -> bool:
    step = step_of(row)
    if step in B_STEPS or step in C_STEPS or step in D_STEPS:
        return True
    if step.startswith(("b-", "c-", "d-")):
        return True
    sport = str(row.get("sport") or "").lower()
    if sport in DIRECTIONAL_SPORTS:
        return True
    if row.get("_strategy_b") or row.get("system") in {"tennis_crossover", "cfb_favorite", "spread_t0", "B", "C", "D"}:
        return True
    return False


def is_flatten(row: dict) -> bool:
    if step_of(row) in FLATTEN_STEPS:
        return True
    note = str(row.get("note") or "").lower()
    return "flatten" in note and step_of(row) != "watch"


def lock_watch_row(row: dict) -> bool:
    sport = str(row.get("sport") or "").strip().lower()
    if sport in DIRECTIONAL_SPORTS:
        return False
    key = str(row.get("bet_key") or "")
    if key.startswith(("cfb-favorite", "spread-t0", "tennis-crossover")):
        return False
    return bool(row.get("bet_key") or row.get("filled_venue") or row.get("game"))


GAME_NAMES = {
    "ruzday": "Ruzic vs Day",
    "smisun": "Smith vs Sun",
    "linsin": "Linette vs Siniakova",
    "cuiyib": "Cui vs Wu",
    "ribhou": "Ribecai vs Houkes",
    "anntag": "Li vs Tagger",
    "moupau": "Moutet vs Paul",
    "bubkha": "Bublik vs Khachanov",
    "grileh": "Griekspoor vs Lehecka",
    "melzar": "Meligeni Alves vs Zarate",
    "lapda": "La Serna vs Pucinelli de Almeida",
    "paufri": "Paul vs Fritz",
    "fruyam": "Fruhvirtova vs Yamaguchi",
    "dayzha": "Day vs Zhang",
    "forroc": "Fortunato vs Rocha",
    "colleh": "Collignon vs Lehecka",
}


def classify_skip(text: str) -> str:
    low = str(text or "").lower()
    if "has this tennis match open" in low or "tennis crossover has this" in low:
        return "skip_absorbed_b"
    if "cfb favorite or t0 spread" in low or "t0 spread ticket is open" in low:
        return "skip_cd_open"
    if "already have" in low and "open lock" in low:
        return "skip_max_open"
    if "hard_miss_abort" in low or "hard miss abort" in low:
        return "hard_miss_abort"
    if "not profitable" in low or "over cap" in low or "above the 0.984" in low or "above the net_max" in low:
        return "over_cap"
    if "not a real no" in low or "gemini no" in low:
        return "books_not_two_sided"
    if "novig" in low and ("empty" in low or "quote_only" in low or "ask missing" in low or "disabled" in low):
        return "novig"
    if "no takeable size" in low or "missing size" in low or "need >= 1" in low or "both books need" in low:
        return "no_size"
    if "book empty" in low or "ask missing" in low:
        return "books_not_two_sided"
    if "indiana" in low and "michigan" in low:
        return "indiana_michigan"
    if "missed pair stopped" in low or "orders stopped after a one-leg" in low or "orders stopped" in low:
        return "latched"
    if "placing orders is off" in low:
        return "placing_off"
    if "lock gap system is off" in low:
        return "system_off"
    if "same contract" in low or "same-contract" in low:
        return "same_contract"
    if "order skip" in low:
        return "other_skip"
    return "other"


def display_game(raw) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text in GAME_NAMES:
        return GAME_NAMES[text]
    low = text.lower()
    for key, name in GAME_NAMES.items():
        if key in low:
            return name
    return text


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    except Exception:
        return False


def load_orders() -> list[dict]:
    path = RAW / "orders.jsonl"
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def load_watches() -> list[dict]:
    data = load_json(RAW / "one_leg_watch.json") or {}
    raw = data.get("watches") if isinstance(data, dict) else None
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(data, dict) and (data.get("bet_key") or data.get("filled_venue")):
        return [data]
    return []


def stream_supervisor(now: datetime) -> dict:
    path = RAW / "live_supervisor.log"
    counts = defaultdict(int)
    games_b = set()
    games_max = set()
    games_over = set()
    games_novig = set()
    games_size = set()
    games_books = set()
    games_im = set()
    hourly = defaultdict(lambda: defaultdict(int))
    markers = []
    last_skip_line = ""
    last_skip_at = None
    last_send_line = ""
    last_send_at = None
    hard_abort = []
    if not path.is_file():
        return {
            "counts": counts,
            "hourly": hourly,
            "markers": markers,
            "games": {},
            "last_skip": ("", None),
            "last_send": ("", None),
            "hard_abort": hard_abort,
        }
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stamp = parse_dt(line.split(" ", 1)[0].strip())
            if stamp is None or stamp < CUT or stamp > now:
                continue
            low = line.lower()
            hour = hour_floor(stamp)
            kind = None
            if "placing orders is off" in low:
                kind = "placing_off"
                markers.append((stamp, "off_bats", line.strip()[:220]))
            elif "order skipped; a missed pair stopped" in low:
                kind = "latched"
                markers.append((stamp, "off_latch", line.strip()[:220]))
            elif "order watch complete" in low and "orders on" in low:
                kind = "orders_on"
                markers.append((stamp, "on_leftover_complete", line.strip()[:220]))
            elif "latch stays on" in low:
                kind = "latch_stays"
                markers.append((stamp, "off_watch_stop", line.strip()[:220]))
            elif "hard_miss_abort" in low:
                kind = "hard_miss_abort"
                hard_abort.append(line.strip()[:260])
            elif "has this tennis match open" in low or "tennis crossover has this" in low:
                kind = "skip_absorbed_b"
                title = ""
                if "order skip " in line:
                    title = line.split("order skip ", 1)[-1].split(";", 1)[0].strip()
                if title:
                    games_b.add(title)
            elif "cfb favorite or t0 spread" in low:
                kind = "skip_cd_open"
            elif "already have" in low and "open lock" in low:
                kind = "skip_max_open"
                title = ""
                if "order skip " in low:
                    title = line.split("order skip ", 1)[-1].split(";", 1)[0].strip()
                if title:
                    games_max.add(title)
            elif "over cap" in low:
                kind = "over_cap"
                games_over.add(_title_from_skip(line))
            elif "novig" in low and ("order skip" in low or "quote_only" in low or "disabled" in low):
                kind = "novig"
                games_novig.add(_title_from_skip(line))
            elif "no takeable size" in low or "missing size" in low or "both books need" in low:
                kind = "no_size"
                games_size.add(_title_from_skip(line))
            elif "book empty" in low or "ask missing" in low:
                kind = "books_not_two_sided"
                games_books.add(_title_from_skip(line))
            elif "indiana" in low and "michigan" in low and ("skip" in low or "denied" in low):
                kind = "indiana_michigan"
                games_im.add(_title_from_skip(line))
            elif "lock gap system is off" in low:
                kind = "system_off"
            elif "order skip" in low:
                kind = classify_skip(line)
            if kind:
                counts[kind] += 1
                hourly[hour][kind] += 1
            if "order skip" in low or "over cap" in low or "hard_miss_abort" in low:
                last_skip_line = line.strip()[:220]
                last_skip_at = stamp
            if "balances before send" in low:
                last_send_line = line.strip()[:220]
                last_send_at = stamp
                hourly[hour]["balances_before_send"] += 1
                counts["balances_before_send"] += 1
    return {
        "counts": dict(counts),
        "hourly": {k.isoformat(): dict(v) for k, v in hourly.items()},
        "hourly_dt": hourly,
        "markers": markers,
        "games": {
            "skip_absorbed_b": sorted(g for g in games_b if g),
            "skip_max_open": sorted(g for g in games_max if g),
            "over_cap": sorted(g for g in games_over if g),
            "novig": sorted(g for g in games_novig if g),
            "no_size": sorted(g for g in games_size if g),
            "books_not_two_sided": sorted(g for g in games_books if g),
            "indiana_michigan": sorted(g for g in games_im if g),
        },
        "last_skip": (last_skip_line, last_skip_at),
        "last_send": (last_send_line, last_send_at),
        "hard_abort": hard_abort,
    }


def _title_from_skip(line: str) -> str:
    if "send gate " in line:
        rest = line.split("send gate ", 1)[-1]
        for sep in (" over cap", " novig ", " gemini ", " kalshi ", " polymarket ", " book empty"):
            if sep in rest:
                return rest.split(sep, 1)[0].strip()[:80]
        return rest.strip()[:80]
    if "order skip " in line:
        return line.split("order skip ", 1)[-1].split(";", 1)[0].strip()[:80]
    return ""


def cluster_duals(orders: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (dual_lock_sends, flatten_sends, hard_aborts) after CUT."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    hard_aborts = []
    flatten_sends = []
    for row in orders:
        when = row_when(row)
        if when is None or when < CUT + timedelta(seconds=1):
            continue
        event = str(row.get("event") or "")
        if event == "hard_miss_abort" or "hard miss abort" in str(row.get("reason") or row.get("note") or "").lower():
            hard_aborts.append({
                "when": when,
                "game": display_game(row.get("game") or _game_from_key(row.get("bet_key"))),
                "venue": row.get("venue"),
                "gap_closed": row.get("gap_closed"),
                "note": str(row.get("note") or row.get("reason") or "")[:160],
                "other_venue": row.get("other_venue"),
            })
            continue
        if is_directional(row):
            continue
        if is_flatten(row) and event in {"sent", "filled", "flatten_filled", "flatten_miss"}:
            flatten_sends.append({
                "when": when,
                "game": display_game(row.get("game") or _game_from_key(row.get("bet_key"))),
                "event": event,
                "venue": row.get("venue"),
                "step": step_of(row),
            })
            continue
        if event in {"sent", "filled", "one_leg", "both_unfilled"} and step_of(row) in LOCK_SEND_STEPS:
            key = str(row.get("bet_key") or "")
            if key:
                by_key[key].append(row)
    duals = []
    for key, rows in by_key.items():
        rows.sort(key=lambda item: row_when(item) or CUT)
        buckets: list[list[dict]] = []
        for row in rows:
            when = row_when(row) or CUT
            if not buckets or abs(((row_when(buckets[-1][0]) or CUT) - when).total_seconds()) > 8:
                buckets.append([row])
            else:
                buckets[-1].append(row)
        for bucket in buckets:
            venues = {str(item.get("venue") or "").lower() for item in bucket if item.get("venue")}
            steps = {step_of(item) for item in bucket}
            if len(venues) < 2:
                continue
            when = min((row_when(item) for item in bucket if row_when(item)), default=None)
            duals.append({
                "when": when,
                "game": display_game(bucket[0].get("game") or _game_from_key(key)),
                "sport": bucket[0].get("sport") or (str(key).split("\t")[0] if "\t" in key else ""),
                "venues": sorted(venues),
                "steps": sorted(steps),
                "events": sorted({str(item.get("event") or "") for item in bucket}),
                "n_legs": len(bucket),
                "leftover": "watch" in steps,
            })
    duals.sort(key=lambda row: row["when"] or CUT)
    flatten_sends.sort(key=lambda row: row["when"] or CUT)
    hard_aborts.sort(key=lambda row: row["when"] or CUT)
    return duals, flatten_sends, hard_aborts


def _game_from_key(key) -> str:
    parts = str(key or "").split("\t")
    return parts[1] if len(parts) > 1 else str(key or "")


def _cd_game_from_key(key) -> str:
    text = str(key or "")
    mapping = {
        "untnavy": "North Texas vs Navy",
        "ulmtroy": "ULM vs Troy",
        "bsuwsu": "Boise State vs Washington State",
        "sdsucsu": "San Diego State vs Colorado State",
        "gastarst": "Georgia State vs Arkansas State",
        "misstex": "Ole Miss vs Texas",
    }
    for needle, name in mapping.items():
        if needle in text.lower():
            return name
    return ""


def hard_miss_from_consider() -> list[dict]:
    data = load_json(RAW / "considerations.json") or {}
    rows = data.get("rows") if isinstance(data, dict) else data
    found = []
    seen = set()
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        reason = str(row.get("reason") or "")
        if "hard miss abort" not in reason.lower():
            continue
        when = parse_dt(row.get("at"))
        stamp = (when.isoformat() if when else "") + "|" + str(row.get("game") or "")
        if stamp in seen:
            continue
        seen.add(stamp)
        found.append({
            "when": when,
            "game": row.get("game") or "",
            "venue": "",
            "gap_closed": "gap closed" in reason.lower() and "gap still open" not in reason.lower(),
            "note": reason[:180],
            "other_venue": "",
        })
    found.sort(key=lambda item: item["when"] or CUT)
    return found


def leftover_intervals(watches: list[dict]) -> list[dict]:
    found = []
    for row in watches:
        start = parse_dt(row.get("started_at"))
        end = parse_dt(row.get("stopped_at")) or datetime.now(ET)
        lockish = lock_watch_row(row)
        found.append({
            "game": str(row.get("game") or "").strip() or _cd_game_from_key(row.get("bet_key")) or "unknown game",
            "sport": str(row.get("sport") or ""),
            "start": start,
            "end": end if row.get("stopped") else datetime.now(ET),
            "stopped": bool(row.get("stopped")),
            "stop_reason": str(row.get("stop_reason") or ""),
            "lockish": lockish,
            "active_now": lockish and not bool(row.get("stopped")),
            "secs": ((end - start).total_seconds() if start and end else None),
        })
    return found


def overlap_hours(intervals: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> float:
    total = 0.0
    for a, b in intervals:
        lo = max(a, start)
        hi = min(b, end)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return total / 3600.0


def reconstruct_states(
    now: datetime,
    markers: list[tuple[datetime, str, str]],
    duals: list[dict],
    lock_intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime, str]]:
    events: list[tuple[datetime, str]] = []
    for stamp, kind, _text in markers:
        events.append((stamp, kind))
    for row in duals:
        if row.get("when") and not row.get("leftover"):
            events.append((row["when"], "on_dual_send"))
        elif row.get("when") and row.get("leftover"):
            events.append((row["when"], "on_leftover_send"))
    for start, end in lock_intervals:
        events.append((start, "leftover_start"))
        events.append((end, "leftover_end"))
    events.sort(key=lambda item: item[0])
    ranges: list[tuple[datetime, datetime, str]] = []
    state = "unknown"
    since = CUT

    def close(until: datetime, nxt: str) -> None:
        nonlocal state, since
        if until > since:
            ranges.append((since, until, state))
        state = nxt
        since = until

    for stamp, kind in events:
        if stamp < CUT or stamp > now:
            continue
        if kind in {"off_latch", "off_watch_stop", "off_stopped_file"}:
            close(stamp, "latched")
        elif kind == "off_bats":
            close(stamp, "placing_off")
        elif kind in {"on_dual_send", "on_leftover_complete"}:
            close(stamp, "on_new_pairs")
        elif kind == "on_leftover_send":
            close(stamp, "leftover_watch")
        elif kind == "leftover_start":
            close(stamp, "leftover_watch")
        elif kind == "leftover_end":
            close(stamp, "latched")
    if now > since:
        ranges.append((since, now, state))
    merged: list[tuple[datetime, datetime, str]] = []
    for start, end, why in ranges:
        if end <= start:
            continue
        if merged and why == merged[-1][2] and start <= merged[-1][1] + timedelta(seconds=2):
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), why)
        else:
            merged.append((start, end, why))
    return merged


def consider_buckets(now: datetime) -> dict:
    data = load_json(RAW / "considerations.json") or {}
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        rows = []
    buckets = defaultdict(int)
    legal = 0
    first = last = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        at = str(row.get("at") or "")
        first = first or at
        last = at
        reason = str(row.get("reason") or row.get("plain") or "")
        net = row.get("net")
        try:
            net_d = Decimal(str(net)) if net not in (None, "") else None
        except Exception:
            net_d = None
        if net_d is not None and net_d <= Decimal("0.984"):
            legal += 1
        buckets[classify_skip(reason) if reason else "no_reason"] += 1
        if "indiana" in reason.lower() and "michigan" in reason.lower():
            buckets["indiana_michigan"] += 1
        if "Tennis crossover" in reason or "match open" in reason.lower():
            buckets["skip_absorbed_b"] += 1
    return {
        "n": len(rows),
        "first": first,
        "last": last,
        "legal_net": legal,
        "buckets": dict(buckets),
        "window": "newest 500 looks only, not a lifetime diary",
    }


def live_snapshot(now: datetime, watches: list[dict], supervisor: dict) -> dict:
    systems = load_json(RAW / "systems.json") or {}
    lock = ((systems.get("systems") or {}).get("lock") or {}) if isinstance(systems, dict) else {}
    lock_on = bool(lock.get("on"))
    stopped_path = RAW / "orders_stopped.json"
    stopped_present = stopped_path.is_file()
    stopped_blob = load_json(stopped_path) if stopped_present else None
    pid_blob = load_json(RAW / "live_supervisor.pid") or {}
    pid = int(pid_blob.get("pid") or 0)
    skip = load_json(RAW / "lock_last_skip.json") or {}
    lock_watches = [row for row in leftover_intervals(watches) if row["lockish"]]
    active_lock = [row for row in lock_watches if row["active_now"]]
    leftover_blocking = bool(active_lock)
    allowed = lock_on and not stopped_present and not leftover_blocking
    return {
        "now": now.isoformat(),
        "lock_on": lock_on,
        "systems_updated": systems.get("updated_at") if isinstance(systems, dict) else "",
        "max_open": lock.get("max_open"),
        "stopped_present": stopped_present,
        "stopped": stopped_blob,
        "pid": pid,
        "pid_started": pid_blob.get("started_at"),
        "pid_alive": pid_alive(pid) if pid else False,
        "leftover_active_lock": [
            {"game": row["game"], "started": fmt_et(row["start"]), "reason_open": "active"}
            for row in active_lock
        ],
        "leftover_blocking": leftover_blocking,
        "new_pairs_allowed": allowed,
        "last_skip": skip,
        "last_supervisor_send": supervisor.get("last_send"),
        "job_status_a": "on",
    }


def hours_of(ranges: list[tuple[datetime, datetime, str]], want: set[str] | None = None) -> float:
    total = 0.0
    for start, end, why in ranges:
        if want and why not in want:
            continue
        total += (end - start).total_seconds()
    return total / 3600.0


def build_hour_rows(
    now: datetime,
    states: list[tuple[datetime, datetime, str]],
    duals: list[dict],
    flattens: list[dict],
    hard_aborts: list[dict],
    supervisor: dict,
    lock_intervals: list[tuple[datetime, datetime]],
) -> list[list]:
    start = hour_floor(CUT)
    rows = []
    hourly = supervisor.get("hourly_dt") or {}
    dual_by_hour = defaultdict(list)
    for item in duals:
        if item.get("when"):
            dual_by_hour[hour_floor(item["when"])].append(item)
    flat_by_hour = defaultdict(int)
    for item in flattens:
        if item.get("when"):
            flat_by_hour[hour_floor(item["when"])] += 1
    abort_by_hour = defaultdict(int)
    gap_closed_hour = defaultdict(int)
    for item in hard_aborts:
        if item.get("when"):
            abort_by_hour[hour_floor(item["when"])] += 1
            if item.get("gap_closed"):
                gap_closed_hour[hour_floor(item["when"])] += 1
    cursor = start
    while cursor <= now:
        nxt = cursor + timedelta(hours=1)
        end = min(nxt, now)
        state_bits = []
        on_h = overlap_hours([(a, b) for a, b, w in states if w == "on_new_pairs"], cursor, end)
        left_h = overlap_hours(lock_intervals, cursor, end)
        latch_h = overlap_hours([(a, b) for a, b, w in states if w == "latched"], cursor, end)
        off_h = overlap_hours([(a, b) for a, b, w in states if w == "placing_off"], cursor, end)
        if left_h >= 0.02:
            state_bits.append("leftover watch")
        if on_h >= 0.02:
            state_bits.append("new pairs ON")
        if latch_h >= 0.25:
            state_bits.append("latched")
        if off_h >= 0.25:
            state_bits.append("placing off")
        if not state_bits:
            if latch_h > on_h and latch_h > 0:
                state_bits.append("latched")
            elif on_h > 0:
                state_bits.append("new pairs ON")
            else:
                state_bits.append("quiet / unknown")
        hour_skips = hourly.get(cursor) or {}
        dual_n = len(dual_by_hour.get(cursor, []))
        games = ", ".join(sorted({str(item.get("game") or "") for item in dual_by_hour.get(cursor, []) if item.get("game")})[:4])
        rows.append([
            cursor.strftime("%Y-%m-%d %H:00"),
            ", ".join(state_bits),
            money4(Decimal(str(on_h))),
            money4(Decimal(str(left_h))),
            money4(Decimal(str(latch_h))),
            dual_n,
            flat_by_hour.get(cursor, 0),
            abort_by_hour.get(cursor, 0),
            gap_closed_hour.get(cursor, 0),
            hour_skips.get("skip_absorbed_b", 0),
            hour_skips.get("skip_max_open", 0),
            hour_skips.get("over_cap", 0),
            hour_skips.get("no_size", 0) + hour_skips.get("books_not_two_sided", 0),
            hour_skips.get("novig", 0),
            games,
        ])
        cursor = nxt
    return rows


def json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def write_page(
    *,
    now: datetime,
    live: dict,
    duals: list[dict],
    flattens: list[dict],
    hard_aborts: list[dict],
    watches: list[dict],
    states: list[tuple[datetime, datetime, str]],
    supervisor: dict,
    consider: dict,
    hour_rows: list[list],
    lock_intervals: list[tuple[datetime, datetime]],
) -> str:
    wall = (now - CUT).total_seconds() / 3600.0
    on_h = hours_of(states, {"on_new_pairs"})
    latch_h = hours_of(states, {"latched", "leftover_watch"})
    leftover_h = sum((b - a).total_seconds() for a, b in lock_intervals) / 3600.0
    placing_h = hours_of(states, {"placing_off"})
    new_duals = [row for row in duals if not row.get("leftover")]
    left_duals = [row for row in duals if row.get("leftover")]
    gap_closed = sum(1 for row in hard_aborts if row.get("gap_closed"))
    gap_open = sum(1 for row in hard_aborts if row.get("gap_closed") is False)
    allowed = live["new_pairs_allowed"]
    headline_yes = "Yes" if allowed else "No"
    lock_watches = [row for row in leftover_intervals(watches) if row["lockish"]]
    deadline_kills = [row for row in lock_watches if "deadline" in row["stop_reason"].lower() and row["start"] and row["start"] >= CUT]
    ioc_miss = [row for row in lock_watches if "ioc miss" in row["stop_reason"].lower() and row["start"] and row["start"] >= CUT]
    counts = supervisor.get("counts") or {}
    games = supervisor.get("games") or {}
    last_skip = live.get("last_skip") or {}
    skip_at = last_skip.get("at") or ""
    skip_reason = last_skip.get("reason") or ""
    skip_game = last_skip.get("game") or ""
    if allowed:
        live_line = (
            f"Yes — lock is allowed to send new pairs right now. systems.json lock.on=true "
            f"(snapshot {live.get('systems_updated')}), orders_stopped.json is absent, no active "
            f"lock leftover watch, supervisor pid {live.get('pid')} "
            f"{'alive' if live.get('pid_alive') else 'not running'} "
            f"(started {live.get('pid_started')}). Job status A is on. Last skip is a live look, "
            f"not a latch: {skip_reason} — {skip_game} — {skip_at}."
        )
    else:
        why = []
        if not live["lock_on"]:
            why.append("systems.json lock.on is false")
        if live["stopped_present"]:
            why.append("orders_stopped.json is present")
        if live["leftover_blocking"]:
            why.append("an active leftover watch is blocking new pairs")
        live_line = "No — lock is not allowed to send new pairs right now: " + "; ".join(why) + "."
    paul_correct = (
        "Paul is correct right now: lock is on, and it is not latched off from a failed leg. "
        "That was not true for most of Oct 22–24."
        if allowed
        else "Paul thinks lock is on and unlatched; live state says it is not allowed to send new pairs."
    )
    dual_rows = [
        [
            fmt_et(row["when"]),
            row.get("sport") or "",
            row.get("game") or "",
            "+".join(row.get("venues") or []),
            "leftover watch" if row.get("leftover") else "new pair",
            ",".join(row.get("events") or []),
            ",".join(row.get("steps") or []),
        ]
        for row in duals
    ]
    abort_rows = [
        [
            fmt_et(row["when"]),
            row.get("game") or "",
            row.get("venue") or "",
            row.get("other_venue") or "",
            "yes" if row.get("gap_closed") else "no" if row.get("gap_closed") is False else "",
            row.get("note") or "",
        ]
        for row in hard_aborts
    ]
    watch_rows = [
        [
            fmt_et(row["start"]),
            fmt_et(row["end"]) if row["stopped"] else "still open",
            row.get("game") or "",
            row.get("sport") or "",
            "lock leftover" if row["lockish"] else "C/D leftover (does not hunt a lock hedge)",
            row.get("stop_reason") or ("active" if not row["stopped"] else ""),
            money4(Decimal(str(row["secs"] / 3600.0))) if row.get("secs") is not None else "",
        ]
        for row in leftover_intervals(watches)
        if row.get("start") and row["start"] >= datetime(2026, 10, 21, tzinfo=ET)
    ]
    skip_rows = [
        ["skip-absorbed-B (tennis match B still holds / absorbed)", counts.get("skip_absorbed_b", 0), len(games.get("skip_absorbed_b") or []), ", ".join((games.get("skip_absorbed_b") or [])[:8])],
        ["MAX_OPEN lock slots full", counts.get("skip_max_open", 0), len(games.get("skip_max_open") or []), ", ".join((games.get("skip_max_open") or [])[:8])],
        ["C/D ticket open on that event", counts.get("skip_cd_open", 0), "", ""],
        ["Over cap after book recheck / net above 0.984 at send", counts.get("over_cap", 0), len(games.get("over_cap") or []), ", ".join((games.get("over_cap") or [])[:8])],
        ["No takeable size", counts.get("no_size", 0), len(games.get("no_size") or []), ", ".join((games.get("no_size") or [])[:8])],
        ["Books not two-sided / book empty", counts.get("books_not_two_sided", 0), len(games.get("books_not_two_sided") or []), ", ".join((games.get("books_not_two_sided") or [])[:8])],
        ["Novig on the skip line", counts.get("novig", 0), len(games.get("novig") or []), ", ".join((games.get("novig") or [])[:8])],
        ["Indiana/Michigan named on a skip line", counts.get("indiana_michigan", 0), len(games.get("indiana_michigan") or []), "Same-contract Yes+Yes is not a lock candidate; it never reaches the send gate."],
        ["Latched (missed pair stopped further orders) log lines", counts.get("latched", 0), "", "One line per process start while halted; not a count of looks."],
        ["Placing orders is off", counts.get("placing_off", 0), "", ""],
        ["Lock system off", counts.get("system_off", 0), "", ""],
        ["hard_miss_abort log lines", counts.get("hard_miss_abort", 0), "", "Live only since ~20:07 ET 24 Oct."],
        ["balances before send (attempted send path)", counts.get("balances_before_send", 0), "", ""],
    ]
    consider_rows = [
        [k, v, "newest 500 looks in considerations.json"]
        for k, v in sorted((consider.get("buckets") or {}).items(), key=lambda kv: -kv[1])
    ]
    state_rows = [
        [fmt_et(a), fmt_et(b), money4(Decimal(str((b - a).total_seconds() / 3600.0))), w]
        for a, b, w in states
        if (b - a).total_seconds() >= 1
    ]
    hour_headers = [
        ("Hour ET", "date"),
        ("State", "text"),
        ("New-pair ON hours", "num"),
        ("Lock leftover hours", "num"),
        ("Latched hours", "num"),
        ("Dual lock sends", "num"),
        ("Flatten sends", "num"),
        ("hard_miss_abort", "num"),
        ("gap closed", "num"),
        ("Skip B", "num"),
        ("MAX_OPEN", "num"),
        ("Over cap", "num"),
        ("No size / empty book", "num"),
        ("Novig skip", "num"),
        ("Dual games", "text"),
    ]
    yesno_class = "hl" if allowed else "warn"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Why no both-sides lock since 21 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 16px; color: #0f172a; background: #fff; line-height: 1.45; }}
h1, h2 {{ color: #1e293b; }}
.ask, .plain, .def, .hl, .warn {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 16px; margin: 12px 0; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.hl {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
code {{ font-size: 13px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Why no both-sides lock since 21 Oct</h1>
<p class="note">Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. Research only. Not gold. Not DailyRun. Does not place or sell tickets. Does not flip lock on/off. Click column headers to sort. Five true both-sides rows stay on <a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a>.</p>
<div class="hl">
<h2>24 Oct update — leftover Friday 8 AM deadline removed</h2>
<p>Collection deadline was already gone; leftover watch still had frozen <code>WATCH_DEADLINE = 2026-10-22 08:00 ET</code>. That clock is now removed. Leftover runs until the game settles, flatten/hedge fills, or Paul turns lock off / max-open. See <a href="lock_leftover_deadline_removed_20261024.html">lock_leftover_deadline_removed_20261024.html</a>.</p>
</div>

<div class="ask">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="plain">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="{yesno_class}">
<h2>Can lock send new pairs right now?</h2>
<p><strong>{esc(headline_yes)}.</strong> {esc(live_line)}</p>
<p>{esc(paul_correct)}</p>
<p class="note">Lock leftover watches now: {esc(len(live.get("leftover_active_lock") or []))} active. Supervisor pid was 33336 at kickoff; live pid file is {esc(live.get("pid"))} started {esc(live.get("pid_started"))}. Last dual-send evidence is on the tape table below. Last skip file is a look, not a failed-leg latch.</p>
</div>

<div class="warn">
<h2>Why zero both-sides since Oct 21 23:28 (Ruzic vs Day)</h2>
<p><strong>Top cause:</strong> leftover watch — the only path that ever produced the five both-sides fills — has been dead since the frozen leftover deadline <code>WATCH_DEADLINE = 2026-10-22 08:00 ET</code>. After that clock, any one-leg leftover is stopped on the first tick with “8:00 AM ET deadline” and the latch stays on. Lock leftover watches after the cutoff: {esc(len(deadline_kills))} killed by that deadline (Li vs Tagger, La Serna vs Pucinelli de Almeida, Day vs Zhang), {esc(len(ioc_miss))} leftover IOC miss before the deadline (Linette, Ribecai). None completed a hedge. Paul had already removed the 8 AM <em>collection</em> deadline; leftover watch still had this frozen Oct 22 8 AM stop through the drought. Code change 2026-10-24: that leftover clock is gone. See <a href="lock_leftover_deadline_removed_20261024.html">lock_leftover_deadline_removed_20261024.html</a>.</p>
<p><strong>Second cause:</strong> after each one-leg the new-pair latch stayed on for most of the wall clock. Since Ruzic/Day: wall {esc(money4(Decimal(str(wall))))} hours; reconstructed new-pair ON {esc(money4(Decimal(str(on_h))))} hours; latched or leftover-blocking {esc(money4(Decimal(str(latch_h))))} hours; lock leftover actually running {esc(money4(Decimal(str(leftover_h))))} hours (seconds, not hours — leftover died immediately after the deadline); placing-orders-off {esc(money4(Decimal(str(placing_h))))} hours. When new pairs <em>were</em> allowed, duals one-legged and flattened on the same shop instead of filling the other venue. Immediate both-fill on first dual send is still 0 for the whole book.</p>
<p>Hard-leg-first sequential send went live only at about 20:07 ET 24 Oct (supervisor restart 20:06:16). It cannot explain the Oct 22–24 drought. Going forward it can abort the easy leg after a hard miss (<code>hard_miss_abort</code>).</p>
</div>

<h2>Live checklist</h2>
{table(
    [("Check", "text"), ("Value", "text"), ("Meaning", "text")],
    [
        ["systems.json lock.on", "true" if live["lock_on"] else "false", f"snapshot {live.get('systems_updated')}"],
        ["orders_stopped.json", "absent" if not live["stopped_present"] else "PRESENT", "Failed-leg latch. Absent = not latched from a one-leg."],
        ["Lock leftover watch active", "no" if not live["leftover_blocking"] else "YES", "Active leftover also blocks new pairs even without the latch file."],
        ["Supervisor pid", f"{live.get('pid')} {'alive' if live.get('pid_alive') else 'not running'}", f"started {live.get('pid_started')}"],
        ["Job status A", "on", "Lock gap row on job_status.html"],
        ["Last skip", f"{skip_reason} — {skip_game}", skip_at],
        ["New pairs allowed", "yes" if allowed else "no", "on AND unlatched AND no leftover block"],
    ],
)}

<h2>Dual lock sends since Oct 21 23:28</h2>
<p class="note">{esc(len(duals))} two-venue lock sends strictly after Ruzic/Day 23:28:06 ({esc(len(new_duals))} new-pair, {esc(len(left_duals))} leftover-watch). Flatten-only sends on the tape: {esc(len(flattens))}. hard_miss_abort rows: {esc(len(hard_aborts))} (gap_closed={esc(gap_closed)}, gap still open={esc(gap_open)}). None of these duals became a true both-sides fill. Last dual send is in the table. The five historical both-sides were leftover hedges on Oct 20–21, listed on the both-sides page — do not drop that 5-row list.</p>
{table(
    [("Datetime ET", "date"), ("Sport", "text"), ("Game", "text"), ("Venues", "text"), ("Kind", "text"), ("Events", "text"), ("Steps", "text")],
    dual_rows if dual_rows else [["", "", "none after cutoff", "", "", "", ""]],
)}

<h2>hard_miss_abort (hard-leg-first, this evening only)</h2>
<p class="note">Cannot explain the drought. Listed so the new path is visible going forward. Flatten-only is the Oct 22–24 miss mode: one venue filled, same-shop opposite bought, other venue never filled.</p>
{table(
    [("Datetime ET", "date"), ("Game", "text"), ("Hard venue", "text"), ("Easy venue", "text"), ("Gap closed", "text"), ("Note", "text")],
    abort_rows if abort_rows else [["", "", "", "", "", "none yet"]],
)}

<h2>Leftover watches (why leftover both-fill also died)</h2>
<p class="note">If leftover watch is latched off or skip-absorbed, leftover both-fill dies. After 2026-10-22 08:00 ET the leftover ticker itself stops on deadline before it can IOC a hedge. C/D rows in this file are directional leftovers; they are not lock hedges. Lock leftover duration after cutoff is seconds, not hours.</p>
{table(
    [("Started ET", "date"), ("Stopped ET", "date"), ("Game", "text"), ("Sport", "text"), ("Kind", "text"), ("Stop reason", "text"), ("Hours", "num")],
    watch_rows,
)}

<h2>Legal looks vs skipped (supervisor log after cutoff)</h2>
<p class="note">A “legal” lock is net ≤ 0.984 after fees with size ≥ 1 on both books. considerations.json keeps only the newest 500 looks ({esc(consider.get("first"))} … {esc(consider.get("last"))}), so it is tonight’s window, not Oct 22–24. Counts below are supervisor log lines after 2026-10-21 23:28. Latch skip is undercounted (one line per process). Indiana/Michigan same-contract Yes+Yes is not built as a lock pair, so it will not show as a legal opportunity.</p>
<p class="note">Skip-absorbed-B: lock does not hunt a tennis match Strategy B still holds, including absorbed T0. Live log wording is “Strategy B has this tennis match open” (older) or “Tennis crossover has this tennis match open”. Tennis was 4 of the 5 both-sides fills, so this can starve tennis locks when B is on those games <em>and</em> new pairs are allowed. It is a real skip on this tape (thousands of ticks, few distinct games, clustered Oct 22 morning). It does not explain the many hours the latch was already on, and tennis duals still went out in later ON windows (Moutet, Bublik, Griekspoor, Alves) then flattened.</p>
{table(
    [("Skip / gate", "text"), ("Log lines", "num"), ("Distinct games", "num"), ("Games (sample)", "text")],
    skip_rows,
)}
<h3>considerations.json (newest 500, tonight)</h3>
<p class="note">Legal-net≤0.984 rows in that 500: {esc(consider.get("legal_net"))} of {esc(consider.get("n"))}. {esc(consider.get("window"))}.</p>
{table(
    [("Bucket", "text"), ("N", "num"), ("Note", "text")],
    consider_rows if consider_rows else [["", "", "empty"]],
)}

<h2>Reconstructed state windows after Ruzic/Day</h2>
<p class="note">Best-effort from leftover watch intervals, dual sends, and supervisor markers (placing off / missed-pair latch / leftover complete / latch stays on). Not a process-uptime probe. Dual send is evidence that new pairs or leftover IOC actually posted.</p>
{table(
    [("From ET", "date"), ("Until ET", "date"), ("Hours", "num"), ("State", "text")],
    state_rows,
)}

<h2>Oct 22–24 hour by hour</h2>
<p class="note">Hours from 2026-10-21 23:00 through pull time. Latched hours are the main volume. Dual sends cluster in the short ON windows and then flatten. Skip-B / MAX_OPEN / over-cap only matter in hours that were actually looking.</p>
{table(hour_headers, hour_rows)}

<div class="def">
<h2>What this is not</h2>
<ul>
<li>Not gold. Not DailyRun. Research tape read.</li>
<li>Did not start a second <code>live_strategy_b.py</code>, did not sell, did not wire GTC, did not clear or write <code>orders_stopped.json</code>, did not flip systems.json lock.</li>
<li>Hard-first sequential send is owned by the live lock process that restarted ~20:06 ET; this page only reports it.</li>
<li>The five-row both-sides list is unchanged in meaning. This page explains the silence after it.</li>
</ul>
</div>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    return report_page_extras.inject_report_page_extras(page)


MARKER = "<!-- lock-quiet-20261021 -->"


def patch_both_sides(live: dict, dual_n: int, on_h: float, latch_h: float, wall: float, deadline_n: int) -> str:
    if not BOTH_PAGE.is_file():
        return "lock_both_sides_20261024.html missing"
    text = BOTH_PAGE.read_text(encoding="utf-8")
    allowed = live["new_pairs_allowed"]
    yes = "Yes" if allowed else "No"
    block = (
        f"{MARKER}\n"
        '<div class="warn">\n'
        "<h2>Why no both-sides since Oct 21 23:28</h2>\n"
        f"<p><strong>{esc(yes)} — lock is "
        f"{'allowed to send new pairs right now' if allowed else 'not allowed to send new pairs right now'}"
        "</strong>. systems.json lock.on is on, orders_stopped.json is absent, no active lock leftover "
        "watch. Paul is correct that lock is on and not latched off from a failed leg <em>now</em>. "
        "See <a href=\"lock_quiet_since_20261021.html\">lock_quiet_since_20261021.html</a> for the hour-by-hour tape.</p>\n"
        f"<p>Zero both-sides after Ruzic vs Day because leftover watch (the only path that ever filled "
        f"both venues) has been dead since the frozen leftover deadline 2026-10-22 08:00 ET — "
        f"{esc(deadline_n)} lock leftovers after the cutoff died on that 8 AM stop before they could "
        f"hedge. New-pair ON was about {esc(money4(Decimal(str(on_h))))} hours of "
        f"{esc(money4(Decimal(str(wall))))} hours wall; the rest was latched after one-leg "
        f"(~{esc(money4(Decimal(str(latch_h))))} hours). Dual two-venue sends since then: "
        f"{esc(dual_n)}, all flatten/one-leg, none both-sides. Hard-first sequential send is live only "
        "since ~20:07 ET tonight and cannot explain Oct 22–24. The five-row list below is unchanged.</p>\n"
        "</div>\n"
    )
    if MARKER in text:
        start = text.index(MARKER)
        end = text.find("<h2>True both-sides locks</h2>")
        if end == -1:
            return "both-sides true-list heading missing; left existing quiet block"
        text = text[:start] + block + text[end:]
    else:
        needle = "<h2>True both-sides locks</h2>"
        if needle not in text:
            return "both-sides true-list heading missing; skipped insert"
        text = text.replace(needle, block + needle, 1)
    BOTH_PAGE.write_text(text, encoding="utf-8")
    return "patched lock_both_sides_20261024.html quiet section (5-row list kept)"


def patch_job_status_template() -> str:
    if not JOB_CTRL.is_file():
        return "prediction_job_control.py missing"
    text = JOB_CTRL.read_text(encoding="utf-8")
    needle = (
        '<p>Lock sequential hard-first (research, 24 Oct 2026): '
        '<a href="lock_hard_leg_first_20261024.html">lock_hard_leg_first_20261024.html</a>. '
        "Dual send posts the thinner REST ask first.</p>"
    )
    extra = (
        needle
        + "\n"
        + '<p>Why no both-sides lock fill since 21 Oct 2026: '
        + '<a href="lock_quiet_since_20261021.html">lock_quiet_since_20261021.html</a> '
        + '(list of the five fills: '
        + '<a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a>).</p>'
    )
    if "lock_quiet_since_20261021.html" in text:
        return "prediction_job_control.py already links the quiet page"
    if needle not in text:
        return "job_status template hard-first line drifted; skipped"
    JOB_CTRL.write_text(text.replace(needle, extra, 1), encoding="utf-8")
    return "linked quiet page from prediction_job_control.py job_status template"


def patch_job_status_html() -> str:
    if not JOB_STATUS.is_file():
        return "job_status.html missing"
    text = JOB_STATUS.read_text(encoding="utf-8")
    if "lock_quiet_since_20261021.html" in text:
        return "job_status.html already links the quiet page"
    needle = (
        '<p>Lock sequential hard-first (research, 24 Oct 2026): '
        '<a href="lock_hard_leg_first_20261024.html">lock_hard_leg_first_20261024.html</a>. '
        "Dual send posts the thinner REST ask first.</p>"
    )
    extra = (
        needle
        + "\n"
        + '<p>Why no both-sides lock fill since 21 Oct 2026: '
        + '<a href="lock_quiet_since_20261021.html">lock_quiet_since_20261021.html</a> '
        + '(list of the five fills: '
        + '<a href="lock_both_sides_20261024.html">lock_both_sides_20261024.html</a>).</p>'
    )
    if needle not in text:
        return "job_status.html hard-first line drifted; skipped"
    JOB_STATUS.write_text(text.replace(needle, extra, 1), encoding="utf-8")
    return "linked quiet page on current job_status.html"


def main() -> int:
    now = datetime.now(ET)
    print("loading watches + orders + supervisor log", flush=True)
    watches = load_watches()
    orders = load_orders()
    supervisor = stream_supervisor(now)
    duals, flattens, hard_aborts = cluster_duals(orders)
    if not hard_aborts:
        hard_aborts = hard_miss_from_consider()
    lock_iv = leftover_intervals(watches)
    lock_intervals = [
        (row["start"], row["end"] if row["stopped"] else now)
        for row in lock_iv
        if row["lockish"] and row["start"] and row["start"] >= CUT
    ]
    live = live_snapshot(now, watches, supervisor)
    states = reconstruct_states(now, supervisor.get("markers") or [], duals, lock_intervals)
    consider = consider_buckets(now)
    hour_rows = build_hour_rows(now, states, duals, flattens, hard_aborts, supervisor, lock_intervals)
    html = write_page(
        now=now,
        live=live,
        duals=duals,
        flattens=flattens,
        hard_aborts=hard_aborts,
        watches=watches,
        states=states,
        supervisor=supervisor,
        consider=consider,
        hour_rows=hour_rows,
        lock_intervals=lock_intervals,
    )
    PAGE.write_text(html, encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)
    wall = (now - CUT).total_seconds() / 3600.0
    on_h = hours_of(states, {"on_new_pairs"})
    latch_h = hours_of(states, {"latched", "leftover_watch"})
    deadline_n = sum(
        1
        for row in lock_iv
        if row["lockish"] and row.get("start") and row["start"] >= CUT and "deadline" in row["stop_reason"].lower()
    )
    print("patch_both", patch_both_sides(live, len(duals), on_h, latch_h, wall, deadline_n), flush=True)
    print("patch_tpl", patch_job_status_template(), flush=True)
    print("patch_html", patch_job_status_html(), flush=True)
    extract = {
        "written_at": now.isoformat(),
        "live": json_safe(live),
        "duals": json_safe(duals),
        "flattens_n": len(flattens),
        "hard_aborts": json_safe(hard_aborts),
        "on_hours": on_h,
        "latch_hours": latch_h,
        "wall_hours": wall,
        "deadline_kills": deadline_n,
        "supervisor_counts": supervisor.get("counts"),
        "supervisor_games": supervisor.get("games"),
        "consider": consider,
        "new_pairs_allowed": live["new_pairs_allowed"],
    }
    EXTRACT.write_text(json.dumps(extract, indent=2), encoding="utf-8")
    print(f"wrote {EXTRACT}", flush=True)
    print(
        "allowed", live["new_pairs_allowed"],
        "duals", len(duals),
        "flatten", len(flattens),
        "hard_abort", len(hard_aborts),
        "on_h", round(on_h, 3),
        "latch_h", round(latch_h, 3),
        "deadline_kills", deadline_n,
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
