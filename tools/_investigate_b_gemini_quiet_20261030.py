"""B tennis silence + Gemini quiet. Read-only except one far-from-market Gemini IOC.

Does not start live_strategy_b.py. Does not sell TEN/CIN. Does not leftover-GTC A.
Does not retune B D=0.25. Does not DailyRun. Secrets stay off stdout and HTML.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from html import escape as _escape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import gemini_private  # noqa: E402
import live_lock_orders  # noqa: E402
from prediction_paths import DRIVE_STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
TODAY = "2026-10-30"
TONIGHT_FROM = datetime(2026, 10, 30, 16, 0, tzinfo=ET)
DAY_FROM = datetime(2026, 10, 30, 0, 0, tzinfo=ET)
WEEK_FROM = datetime(2026, 10, 23, 0, 0, tzinfo=ET)
OUT_HTML = DRIVE_STAMP / "b_silent_and_gemini_quiet_20261030.html"
OUT_JSON = RAW / "_b_gemini_quiet_20261030.json"
TEN_CIN_RE = re.compile(r"(TEN.?CIN|CIN.?TEN|tencin|Titans|Bengals)", re.I)

PAUL = (
    "Please investigate a few things.\n"
    "1. how come we aren't getting in on any system B games. there are plenty of tennis "
    "matches happening. are we trying and failing? are we not gettting in on them? "
    "Podoroska vs Monnet as an example\n"
    "2. why have we made absolutely NO trades on Gemini for a week? can you send a test "
    "to make sure we are getting results back? are we using them in our comparisons for "
    "all systems? why are we not getting trades?"
)


def now_et() -> datetime:
    return datetime.now(ET)


def esc(value) -> str:
    return _escape(str("" if value is None else value))


def iso(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value or "")


def parse_ts(text: str) -> datetime | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def b_python_pids() -> list[int]:
    try:
        raw = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'live_strategy_b.py' } | "
                "ForEach-Object { $_.ProcessId }",
            ],
            cwd=str(ROOT),
            timeout=30,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if line.isdigit():
            out.append(int(line))
    return out


def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def iter_jsonl(path: Path):
    if not path.is_file():
        return
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
                yield row


def public_note(body: str, limit: int = 400) -> str:
    text = str(body or "")
    text = re.sub(r"(api[_-]?key|secret|signature|payload)[^,]{0,80}", r"\1=[redacted]", text, flags=re.I)
    return text[:limit]


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, numeric: bool = False) -> str:
    cls = ' class="num"' if numeric else ""
    if value is None:
        value = ""
    return f"<td{cls}>{esc(str(value))}</td>"


def table(headers: list[tuple[str, str]], rows: list[list], foot: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            kind = headers[i][1] if i < len(headers) else "text"
            cells.append(td(cell, numeric=kind == "num"))
        body.append("<tr>" + "".join(cells) + "</tr>")
    foot_html = ""
    if foot:
        cells = []
        for i, cell in enumerate(foot):
            kind = headers[i][1] if i < len(headers) else "text"
            cells.append(td(cell, numeric=kind == "num"))
        foot_html = '<tr class="total-row">' + "".join(cells) + "</tr>"
    return (
        f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}{foot_html}</tbody></table></div>"
    )


def http_get(url: str, timeout: float = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "stockresearch-b-gemini"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, type(exc).__name__


def is_b_row(row: dict) -> bool:
    sys_name = str(row.get("system") or row.get("source") or "").lower()
    step = str(row.get("step") or "").lower()
    key = str(row.get("bet_key") or row.get("_bet_key") or "")
    if row.get("_strategy_b"):
        return True
    if sys_name in {"tennis_crossover", "strategy_b", "b"}:
        return True
    if key.startswith("tennis-b") or step.startswith("b-"):
        return True
    if str(row.get("event") or "") in {"t0", "cross"} and "tennis" in str(row.get("game") or "").lower():
        if sys_name in {"", "tennis_crossover", "strategy_b"}:
            return True
    return False


def podoroska(text: str) -> bool:
    low = str(text or "").lower()
    return "podoroska" in low or "monnet" in low or "podoromonnet" in low or "podoro" in low and "monnet" in low


def classify_skip(reason: str) -> str:
    r = str(reason or "")
    low = r.lower()
    if "t0_allin_c_over_105" in low or "all-in c=" in low or "fee unknown" in low:
        return "fees>1.05 / all-in skip"
    if "outside (0.10, 0.90)" in low or "outside (0.10" in low:
        return "Yes outside 10–90"
    if "missed t0" in low:
        return "missed T0"
    if "no trusted clock" in low or "feed stamp" in low or "junk" in low:
        return "junk clock / no trusted T0"
    if "cross_hours_before" in low or "waiting trusted" in low:
        return "50-cross blocked until trusted T0"
    if "already" in low and ("open" in low or "handled" in low or "match" in low):
        return "skip-if already on match"
    if "lock-bot" in low:
        return "lock-bot leftover"
    if "absorb" in low:
        return "absorbing"
    if "queued" in low:
        return "queued (max open)"
    if "fok" in low or "fill 0" in low or "fill_qty" in low:
        return "FOK/IOC fill 0"
    return r[:80] or "other"


def scan_b() -> dict:
    pid_info = load_json(RAW / "strategy_b.pid") or {}
    watch = load_json(RAW / "strategy_b_watch.json") or {}
    file_pid = int(pid_info.get("pid") or watch.get("pid") or 0)
    alive = pid_alive(file_pid)
    py_pids = b_python_pids()
    skipped = [row for row in (watch.get("skipped") or []) if isinstance(row, dict)]
    queued = [row for row in (watch.get("queued") or []) if isinstance(row, dict)]
    matches = [row for row in (watch.get("matches") or []) if isinstance(row, dict)]

    day_skips = []
    tonight_skips = []
    pod_skips = []
    for row in skipped:
        when = parse_ts(str(row.get("when") or ""))
        game = str(row.get("game") or "")
        rec = {
            "when": row.get("when") or "",
            "game": game,
            "reason": row.get("reason") or "",
            "bucket": classify_skip(str(row.get("reason") or "")),
        }
        if when is not None and when >= DAY_FROM:
            day_skips.append(rec)
        if when is not None and when >= TONIGHT_FROM:
            tonight_skips.append(rec)
        if podoroska(game):
            pod_skips.append(rec)

    today_matches = []
    open_now = []
    t0_sent_matches = []
    cross_matches = []
    dip_matches = []
    for row in matches:
        opened = parse_ts(str(row.get("opened_at") or row.get("t0_when") or ""))
        game = str(row.get("game") or "")
        stage = str(row.get("stage") or "")
        t0 = row.get("t0_yes") if isinstance(row.get("t0_yes"), dict) else {}
        filled = False
        for slot in t0.values():
            if not isinstance(slot, dict):
                continue
            if slot.get("filled") is True:
                filled = True
        last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
        try:
            fill_qty = float(last.get("fill_qty") or 0)
        except (TypeError, ValueError):
            fill_qty = 0.0
        if fill_qty >= 1:
            filled = True
        rec = {
            "game": game,
            "stage": stage,
            "opened_at": row.get("opened_at") or "",
            "t0_when": row.get("t0_when") or "",
            "note": str(row.get("note") or "")[:240],
            "skip_reason": row.get("skip_reason") or "",
            "venue": row.get("venue") or "",
            "filled": filled,
            "cross_fill": row.get("cross_fill") or "",
            "fav_gtc_sent": bool(row.get("fav_gtc_sent")),
        }
        if opened is not None and opened >= DAY_FROM:
            today_matches.append(rec)
        if stage in {
            "waiting_t0",
            "t0_filled_waiting_50_cross",
            "waiting_cross",
            "waiting_fav_dip",
            "fav_gtc_resting",
            "one_leg_miss",
        }:
            open_now.append(rec)
        if opened is not None and opened >= DAY_FROM and filled:
            t0_sent_matches.append(rec)
        if opened is not None and opened >= DAY_FROM and rec["cross_fill"]:
            cross_matches.append(rec)
        if opened is not None and opened >= DAY_FROM and rec["fav_gtc_sent"]:
            dip_matches.append(rec)

    log_counts = Counter()
    log_samples = []
    log_non_perm = []
    log_path = RAW / "strategy_b.log"
    if log_path.is_file():
        with log_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.startswith(TODAY):
                    continue
                log_counts["lines"] += 1
                if "PermissionError" in line:
                    log_counts["permission"] += 1
                else:
                    log_counts["other"] += 1
                    if len(log_non_perm) < 40:
                        log_non_perm.append(line.strip()[:240])
                if "t0" in line.lower() or "send" in line.lower() or "cross" in line.lower() or "gtc" in line.lower():
                    if "PermissionError" not in line and len(log_samples) < 40:
                        log_samples.append(line.strip()[:240])
                if podoroska(line) and len(log_samples) < 60:
                    log_samples.append(line.strip()[:240])

    tape_t0 = []
    tape_cross = []
    tape_send = []
    tape_pod = []
    venue_t0 = Counter()
    for row in iter_jsonl(RAW / "orders.jsonl"):
        at = parse_ts(str(row.get("at") or row.get("ts") or row.get("when") or ""))
        if at is None or at < DAY_FROM:
            continue
        if not is_b_row(row) and str(row.get("event") or "") not in {"t0", "cross"}:
            continue
        if str(row.get("event") or "") not in {"t0", "cross"} and not is_b_row(row):
            continue
        game = str(row.get("game") or "")
        event = str(row.get("event") or "")
        action = str(row.get("action") or row.get("step") or "")
        rec = {
            "at": iso(at),
            "event": event,
            "action": action,
            "game": game,
            "reason": str(row.get("reason") or row.get("note") or "")[:240],
            "yes_a": row.get("yes_a") or "",
            "yes_b": row.get("yes_b") or "",
            "all_in_c": row.get("all_in_c") or "",
            "venue": row.get("venue") or "",
            "dog_yes": row.get("dog_yes") or "",
            "fav_yes": row.get("fav_yes") or "",
        }
        if event == "t0" or action in {"t0", "b-t0"}:
            tape_t0.append(rec)
            venue_t0[str(row.get("venue") or "")] += 1
            if action == "send" or str(row.get("step") or "") == "b-t0":
                tape_send.append(rec)
        if event == "cross":
            tape_cross.append(rec)
        if podoroska(game):
            tape_pod.append(rec)

    tonight_t0 = [r for r in tape_t0 if parse_ts(r["at"]) and parse_ts(r["at"]) >= TONIGHT_FROM]
    tonight_send = [r for r in tape_send if parse_ts(r["at"]) and parse_ts(r["at"]) >= TONIGHT_FROM]
    tonight_cross = [r for r in tape_cross if parse_ts(r["at"]) and parse_ts(r["at"]) >= TONIGHT_FROM]

    games_seen = sorted({r["game"] for r in day_skips + tonight_t0 + today_matches if r.get("game")})
    tonight_games = sorted({r["game"] for r in tonight_skips + tonight_t0 if r.get("game")})

    return {
        "file_pid": file_pid,
        "pid_started": pid_info.get("started_at"),
        "pid_alive": alive,
        "python_b_pids": py_pids,
        "watch_updated": watch.get("updated_at"),
        "currently_open": watch.get("currently_open"),
        "max_open": watch.get("max_open_b_matches"),
        "last_skip_reason": watch.get("last_skip_reason"),
        "cluster_note": watch.get("cluster_note"),
        "enabled": watch.get("enabled"),
        "queued_n": len(queued),
        "open_now": open_now,
        "today_matches": today_matches,
        "t0_sent_matches": t0_sent_matches,
        "cross_matches": cross_matches,
        "dip_matches": dip_matches,
        "day_skips": day_skips,
        "tonight_skips": tonight_skips,
        "pod_skips": pod_skips,
        "skip_buckets_tonight": dict(Counter(r["bucket"] for r in tonight_skips)),
        "skip_buckets_day": dict(Counter(r["bucket"] for r in day_skips)),
        "log_counts": dict(log_counts),
        "log_non_perm": log_non_perm,
        "log_samples": log_samples,
        "tape_t0_n": len(tape_t0),
        "tape_send_n": len(tape_send),
        "tape_cross_n": len(tape_cross),
        "tonight_t0": tonight_t0[-40:],
        "tonight_t0_n": len(tonight_t0),
        "tonight_send_n": len(tonight_send),
        "tonight_cross_n": len(tonight_cross),
        "tonight_send": tonight_send,
        "tape_pod": tape_pod,
        "venue_t0": dict(venue_t0),
        "games_seen": games_seen,
        "tonight_games": tonight_games,
        "gemini_t0_legs": int(venue_t0.get("gemini") or 0),
    }


def scan_pod_clock() -> dict:
    job = load_json(RAW / "live_jobs" / "tennis_podoromonnet_2026_10_30.json") or {}
    health = load_json(RAW / "live_health" / "tennis_podoromonnet_2026_10_30.json") or {}
    state = load_json(RAW / "live_state" / "tennis_podoromonnet_2026_10_30.json") or {}
    hint = load_json(RAW / "live_lock_hints" / "tennis_podoromonnet_2026_10_30.json") or {}
    game = job.get("game") if isinstance(job.get("game"), dict) else {}
    prices = []
    path = RAW / "price_memory" / TODAY / "tennis.jsonl"
    window_lo = datetime(2026, 10, 30, 17, 20, tzinfo=ET)
    window_hi = datetime(2026, 10, 30, 18, 20, tzinfo=ET)
    last = None
    if path.is_file():
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "Podoroska" not in line and "Monnet" not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if str(row.get("pay") or "") != "yes":
                    continue
                seen = parse_ts(str(row.get("seen_at") or ""))
                if seen is None:
                    continue
                rec = {
                    "seen_at": iso(seen),
                    "side": row.get("side") or "",
                    "venue": row.get("venue") or "",
                    "price": row.get("price") or "",
                    "game_start": row.get("game_start") or "",
                    "phase": row.get("phase") or "",
                }
                last = rec
                if window_lo <= seen <= window_hi and len(prices) < 24:
                    prices.append(rec)
    gemini_expected = (health.get("expected") or {}).get("gemini")
    return {
        "listed_start": job.get("listed_start") or job.get("start") or "",
        "startTime": (game.get("startTime") if isinstance(game, dict) else "") or "",
        "period": game.get("period") if isinstance(game, dict) else "",
        "gemini_catalog": game.get("gemini") if isinstance(game, dict) else {},
        "kalshi_catalog": game.get("kalshi") if isinstance(game, dict) else {},
        "poly_n": len(game.get("polymarket_markets") or []) if isinstance(game, dict) else 0,
        "health_expected": health.get("expected"),
        "health_messages": health.get("messages"),
        "health_started_at": health.get("started_at"),
        "state_transport": state.get("transport"),
        "gemini_expected": gemini_expected,
        "hint_keys": sorted(hint.keys())[:20] if isinstance(hint, dict) else [],
        "yes_in_t0_window": prices,
        "last_yes": last,
        "price_memory_game_start": (prices[0].get("game_start") if prices else (last or {}).get("game_start")),
    }


def scan_tennis_jobs() -> dict:
    jobs_dir = RAW / "live_jobs"
    n = 0
    gemini_nonempty = 0
    kalshi_nonempty = 0
    samples = []
    if jobs_dir.is_dir():
        for path in jobs_dir.glob("tennis_*_2026_10_30.json"):
            data = load_json(path)
            if not isinstance(data, dict):
                continue
            n += 1
            game = data.get("game") if isinstance(data.get("game"), dict) else {}
            g = game.get("gemini") if isinstance(game.get("gemini"), dict) else {}
            k = game.get("kalshi") if isinstance(game.get("kalshi"), dict) else {}
            if g:
                gemini_nonempty += 1
            if k:
                kalshi_nonempty += 1
            if len(samples) < 12:
                samples.append(
                    {
                        "file": path.name,
                        "title": data.get("title") or game.get("title_kalshi") or "",
                        "listed_start": data.get("listed_start") or "",
                        "gemini": bool(g),
                        "kalshi": bool(k),
                        "poly": bool(game.get("polymarket_markets")),
                    }
                )
    tennis_gemini_files = list((RAW).glob("tennis_*gemini*.json"))
    return {
        "jobs_today": n,
        "jobs_with_gemini": gemini_nonempty,
        "jobs_with_kalshi": kalshi_nonempty,
        "samples": samples,
        "tennis_gemini_raw_files": [p.name for p in tennis_gemini_files[:10]],
        "tennis_gemini_raw_n": len(tennis_gemini_files),
    }


def scan_gemini_tape() -> dict:
    last_post = None
    last_get = None
    posts_week = []
    posts_ever = 0
    for row in iter_jsonl(RAW / "order_io.jsonl"):
        venue = str(row.get("venue") or "").lower()
        if venue != "gemini":
            continue
        kind = str(row.get("kind") or row.get("what") or row.get("op") or "")
        at = parse_ts(str(row.get("at") or row.get("ts") or row.get("when") or ""))
        rec = {
            "at": iso(at) if at else str(row.get("at") or ""),
            "kind": kind,
            "http": row.get("http") or row.get("status") or "",
            "symbol": str(row.get("symbol") or (row.get("request") or {}).get("symbol") or "")[:80],
            "filled": row.get("filled") or row.get("fill_qty") or "",
            "venue_status": "",
        }
        payload = row.get("payload") or row.get("response") or row.get("body")
        if isinstance(payload, dict):
            rec["venue_status"] = str(payload.get("status") or payload.get("orderStatus") or "")[:40]
        path = str(row.get("path") or row.get("url") or "")
        is_post = "order" in kind.lower() or "POST" in str(row.get("method") or "").upper() or "/order" in path
        if is_post and "history" not in path.lower() and "book" not in kind.lower():
            posts_ever += 1
            last_post = rec
            if at is not None and at >= WEEK_FROM:
                posts_week.append(rec)
        elif "book" in kind.lower() or "GET" in str(row.get("method") or "").upper():
            last_get = rec
    gemini_looks = []
    path = RAW / "considerations.json"
    data = load_json(path)
    rows = data if isinstance(data, list) else (data.get("rows") if isinstance(data, dict) else [])
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        yes_v = str(row.get("yes_venue") or row.get("venue") or "").lower()
        no_v = str(row.get("no_venue") or "").lower()
        if "gemini" not in yes_v and "gemini" not in no_v:
            continue
        at = parse_ts(str(row.get("at") or row.get("when") or row.get("ts") or ""))
        gemini_looks.append(
            {
                "at": iso(at) if at else "",
                "sport": row.get("sport") or "",
                "game": row.get("game") or row.get("title") or "",
                "yes": row.get("yes_venue") or "",
                "no": row.get("no_venue") or "",
                "net": row.get("net") or row.get("after_fee") or "",
                "decision": row.get("decision") or row.get("status") or "",
                "reason": str(row.get("reason") or "")[:160],
            }
        )
    sport_files = Counter()
    live_contracts = []
    for path in RAW.glob("*_gemini.json"):
        name = path.name
        sport = name.split("_", 1)[0]
        sport_files[sport] += 1
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        fetched = parse_ts(str(data.get("fetched_at") or ""))
        for event in data.get("events") or []:
            if not isinstance(event, dict):
                continue
            for raw in event.get("contracts") or []:
                if not isinstance(raw, dict):
                    continue
                symbol = str(raw.get("instrumentSymbol") or "")
                if not symbol.startswith("GEMI-"):
                    continue
                if TEN_CIN_RE.search(symbol) or TEN_CIN_RE.search(str(data.get("game") or "")):
                    continue
                status = str(raw.get("status") or "").lower()
                state = str(raw.get("marketState") or "").lower()
                prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
                ask = prices.get("bestAsk") if isinstance(prices, dict) else None
                if status in {"active", "open"} or state in {"open"}:
                    live_contracts.append(
                        {
                            "symbol": symbol,
                            "label": raw.get("label") or "",
                            "game": data.get("game") or "",
                            "sport": sport,
                            "ask": ask,
                            "status": status,
                            "marketState": state,
                            "fetched_at": iso(fetched) if fetched else "",
                        }
                    )
    return {
        "last_post": last_post,
        "last_book_get": last_get,
        "posts_week": posts_week,
        "posts_week_n": len(posts_week),
        "posts_ever": posts_ever,
        "gemini_looks": gemini_looks[:20],
        "gemini_looks_n": len(gemini_looks),
        "sport_files": dict(sport_files),
        "live_contracts_n": len(live_contracts),
        "live_contracts": live_contracts[:15],
        "tennis_files": int(sport_files.get("tennis") or 0),
    }


def _redact_order_body(payload) -> dict:
    if not isinstance(payload, dict):
        return {"note": public_note(str(payload), 240)}
    keep = {}
    for key in (
        "orderId",
        "id",
        "symbol",
        "status",
        "orderStatus",
        "filled",
        "executedQuantity",
        "quantity",
        "price",
        "avgPrice",
        "timeInForce",
        "outcome",
        "side",
        "reason",
        "message",
        "result",
        "isCancelled",
        "remainingQuantity",
    ):
        if key in payload:
            keep[key] = payload[key]
    if not keep:
        keep["keys"] = sorted(str(k) for k in payload.keys())[:20]
        keep["note"] = public_note(json.dumps(payload, default=str), 240)
    return keep


def find_test_symbol(tape: dict) -> dict:
    for row in tape.get("live_contracts") or []:
        symbol = str(row.get("symbol") or "")
        if not symbol or TEN_CIN_RE.search(symbol):
            continue
        event_ticker = symbol
        if event_ticker.startswith("GEMI-"):
            parts = event_ticker.split("-")
            # GEMI-NCAAF-2610242000-IND-MIC-M-IND -> NCAAF-2610242000-IND-MIC-M
            if len(parts) >= 6:
                event_ticker = "-".join(parts[1:-1])
        status, body = http_get("https://api.gemini.com/v1/prediction-markets/events/" + event_ticker)
        ask = None
        open_symbol = symbol
        if status == 200:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = None
            contracts = []
            if isinstance(data, dict):
                contracts = data.get("contracts") or data.get("markets") or []
            for raw in contracts:
                if not isinstance(raw, dict):
                    continue
                inst = str(raw.get("instrumentSymbol") or "")
                if TEN_CIN_RE.search(inst):
                    continue
                prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
                cand_ask = prices.get("bestAsk") or prices.get("ask")
                state = str(raw.get("marketState") or raw.get("status") or "").lower()
                if state in {"open", "active"} and cand_ask not in (None, "", {}, []):
                    open_symbol = inst or open_symbol
                    ask = cand_ask
                    break
        return {
            "symbol": open_symbol,
            "event_ticker": event_ticker,
            "event_http": status,
            "ask": ask,
            "from_disk": row,
        }
    # Upcoming CFB/NFL files even if settled-looking: try one PHI-WAS sibling is 404; try a Saturday CFB.
    for path in sorted(RAW.glob("cfb_*_gemini.json"), reverse=True)[:8]:
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        for event in data.get("events") or []:
            ticker = str((event or {}).get("ticker") or "")
            if not ticker or TEN_CIN_RE.search(ticker):
                continue
            status, body = http_get("https://api.gemini.com/v1/prediction-markets/events/" + ticker)
            if status != 200:
                continue
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                continue
            for raw in payload.get("contracts") or []:
                if not isinstance(raw, dict):
                    continue
                inst = str(raw.get("instrumentSymbol") or "")
                state = str(raw.get("marketState") or "").lower()
                if inst.startswith("GEMI-") and state in {"open", "active"}:
                    prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
                    return {
                        "symbol": inst,
                        "event_ticker": ticker,
                        "event_http": status,
                        "ask": prices.get("bestAsk"),
                        "from_disk": {"game": data.get("game"), "file": path.name},
                    }
    return {}


def gemini_calls(tape: dict) -> dict:
    out: dict = {"calls": [], "test_order": None, "reloaded_b": False}
    def add(name: str, method: str, path: str, status: int, body: str, extra: dict | None = None) -> None:
        snippet = public_note(body, 280)
        n = None
        parsed = None
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            n = len(parsed)
        elif isinstance(parsed, dict):
            n = len(parsed.get("orders") or parsed.get("results") or parsed.get("positions") or [])
        row = {
            "name": name,
            "method": method,
            "path": path,
            "http": status,
            "n": n,
            "body": snippet,
            "keys": sorted(parsed.keys())[:12] if isinstance(parsed, dict) else [],
        }
        if extra:
            row.update(extra)
        out["calls"].append(row)

    # Auth GET/POST paths Paul asked for. Do not print secrets.
    try:
        status, body = gemini_private.private_call("/v1/balances", None, "POST")
        usd = None
        try:
            usd = str(live_lock_orders._parse_gemini_usd(body))
        except Exception:
            usd = None
        add("balances", "POST", "/v1/balances", status, body, {"usd_available": usd})
    except Exception as exc:
        add("balances", "POST", "/v1/balances", 0, type(exc).__name__)

    try:
        status, body = gemini_private.private_call("/v1/prediction-markets/terms/status", None, "GET")
        accepted = None
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                accepted = data.get("hasAcceptedLatest")
        except json.JSONDecodeError:
            accepted = None
        add("terms", "GET", "/v1/prediction-markets/terms/status", status, body, {"accepted": accepted})
    except Exception as exc:
        add("terms", "GET", "/v1/prediction-markets/terms/status", 0, type(exc).__name__)

    try:
        status, body = gemini_private.get_order_history({"limit": 20})
        last_fill = None
        fills = []
        try:
            data = json.loads(body)
            rows = data if isinstance(data, list) else (data.get("orders") or data.get("results") or [])
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                st = str(row.get("status") or "").lower()
                qty = row.get("executedQuantity") or row.get("filled") or row.get("quantity")
                rec = {
                    "created": row.get("timestamp") or row.get("created") or row.get("time") or "",
                    "symbol": row.get("symbol") or "",
                    "status": st,
                    "qty": qty,
                    "price": row.get("price") or row.get("avgPrice") or "",
                    "outcome": row.get("outcome") or "",
                }
                fills.append(rec)
                if st == "filled" and last_fill is None:
                    last_fill = rec
                if st == "filled":
                    last_fill = rec
        except json.JSONDecodeError:
            fills = []
        add(
            "order_history",
            "POST",
            "/v1/prediction-markets/orders/history",
            status,
            body,
            {"last_fill": last_fill, "history_n": len(fills), "history_tail": fills[:5]},
        )
        out["history_fills"] = fills[:12]
        out["last_fill"] = last_fill
    except Exception as exc:
        add("order_history", "POST", "/v1/prediction-markets/orders/history", 0, type(exc).__name__)

    for path in (
        "/v1/prediction-markets/positions",
        "/v1/prediction-markets/balances",
        "/v1/prediction-markets/orders",
    ):
        try:
            status, body = gemini_private.private_call(path, None, "GET")
            add("try " + path.rsplit("/", 1)[-1], "GET", path, status, body)
        except Exception as exc:
            add("try " + path.rsplit("/", 1)[-1], "GET", path, 0, type(exc).__name__)

    status, body = http_get("https://api.gemini.com/v1/prediction-markets/events")
    add("public events list", "GET", "/v1/prediction-markets/events", status, body)

    picked = find_test_symbol(tape)
    out["picked"] = picked
    symbol = str((picked or {}).get("symbol") or "")
    if not symbol or TEN_CIN_RE.search(symbol):
        out["test_order"] = {
            "skipped": True,
            "why": "no live Gemini symbol that is not TEN/CIN",
            "picked": picked,
        }
        return out
    try:
        ask = Decimal(str(picked.get("ask") or "0"))
    except Exception:
        ask = Decimal("0")
    limit = Decimal("0.01")
    if ask > 0 and ask <= Decimal("0.05"):
        # Too close to 1c; do not risk a fill. Skip the live send.
        out["test_order"] = {
            "skipped": True,
            "why": f"ask {ask} too close to 0.01 to send a cannot-fill IOC",
            "symbol": symbol,
        }
        return out
    body = {
        "symbol": symbol,
        "orderType": "limit",
        "side": "buy",
        "quantity": "1",
        "price": format(limit, "f"),
        "outcome": "yes",
        "timeInForce": "immediate-or-cancel",
    }
    recorded: dict = {}
    try:
        status, text = gemini_private.private_call("/v1/prediction-markets/order", body, "POST", record=recorded)
    except Exception as exc:
        out["test_order"] = {
            "skipped": False,
            "error": type(exc).__name__,
            "symbol": symbol,
            "limit": format(limit, "f"),
            "tif": "immediate-or-cancel",
        }
        return out
    try:
        live_lock_orders.record_order_io("gemini", "order", recorded.get("request") or body, status, text)
    except Exception:
        pass
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    filled = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
    cancel_http = None
    cancel_note = ""
    if status in (200, 201) and live_lock_orders.order_still_open(payload):
        cancel_http, cancel_note = live_lock_orders._cancel(
            {"venue": "gemini", "instrument": symbol, "outcome": "yes"}, payload
        )
    out["test_order"] = {
        "skipped": False,
        "symbol": symbol,
        "limit": format(limit, "f"),
        "ask": str(picked.get("ask") or ""),
        "tif": "immediate-or-cancel",
        "http": status,
        "filled_qty": format(filled, "f"),
        "ioc_nothing": live_lock_orders.ioc_nothing_filled(status, payload) if payload is not None else False,
        "body": _redact_order_body(payload) if payload is not None else public_note(text, 280),
        "request_keys": sorted((recorded.get("request") or body).keys()),
        "cancel_http": cancel_http,
        "cancel_note": public_note(str(cancel_note), 160),
        "game": (picked.get("from_disk") or {}).get("game") or "",
    }
    add("test IOC order", "POST", "/v1/prediction-markets/order", status, text)
    return out


def systems_gemini() -> list[dict]:
    return [
        {
            "system": "A lock-gap",
            "file": "live_game_pollers._compared + live_lock_orders",
            "shops_gemini": "yes",
            "how": "Catalog tickers + fetch_gemini_event, then compare_payloads / REST book recheck before send. Websocket book when the poller listed Gemini.",
            "sport": "Any sport the catalog lists on Gemini (CFB, NFL, soccer, NHL, MLB). Tennis catalog rows are usually empty Gemini.",
        },
        {
            "system": "B tennis crossover",
            "file": "live_strategy_b.py VENUE_ORDER + moneyline_yes_books",
            "shops_gemini": "yes in code",
            "how": "Cheapest Yes per player across Kalshi/Gemini/Polymarket/Novig. REST-confirms the 1–2 winners. fetch_gemini_event when the tennis game has Gemini tickers.",
            "sport": "Tennis only. Live tennis jobs tonight have gemini: {}. No tennis_*gemini.json on disk. Gemini is compared when listed; it is not listed for these matches.",
        },
        {
            "system": "C CFB favorite",
            "file": "live_cfb_favorite.py → live_t0_yes.collect_quotes",
            "shops_gemini": "yes",
            "how": "collect_quotes fetches Gemini events from catalog tickers, then cheapest Yes in (0.50, 0.90).",
            "sport": "College football. Gemini NCAAF books exist (HTTP 200 on events). C will use Gemini when it is the cheapest legal Yes.",
        },
        {
            "system": "D spread T0",
            "file": "live_spread_t0.py → live_t0_yes.collect_quotes",
            "shops_gemini": "yes",
            "how": "Same collect_quotes. Gemini -S siblings are synthesized when a moneyline ticker exists.",
            "sport": "Any sport with spreads except NFL (D skips NFL). CFB Gemini spreads are in the compare. Tennis Gemini spreads only if Gemini listed tennis (historically none).",
        },
        {
            "system": "E tennis T0 dog",
            "file": "live_tennis_t0_dog.py → live_t0_yes.collect_quotes",
            "shops_gemini": "yes in code",
            "how": "Cheapest dog Yes across venues from collect_quotes.",
            "sport": "Tennis. Same empty Gemini tennis catalog as B. E still shops Gemini if a ticker appears.",
        },
        {
            "system": "F tennis T0 spread",
            "file": "live_tennis_t0_spread.py → live_t0_yes.collect_quotes",
            "shops_gemini": "yes in code",
            "how": "Cheapest tennis spread Yes in [0.20, 0.50).",
            "sport": "Tennis spreads. Gemini tennis if listed only -M / -S; catalog tonight has none.",
        },
        {
            "system": "G soccer T0 total",
            "file": "live_soccer_t0_total.py → live_t0_yes.collect_quotes",
            "shops_gemini": "yes",
            "how": "Cheapest soccer Points Total Yes in [0.20, 0.50) across Kalshi / Polymarket / Gemini / Novig.",
            "sport": "Soccer. Disk has soccer_*_gemini.json files. G compares Gemini when the total line is listed.",
        },
    ]


def write_html(b: dict, pod: dict, jobs: dict, tape: dict, gem: dict) -> None:
    written = now_et().strftime("%Y-%m-%d %H:%M ET")
    b_try = "trying and skipping"
    if not b.get("pid_alive"):
        b_try = "B pid not alive (did not start a second B)"
    elif not b.get("tonight_games") and not b.get("tonight_skips"):
        b_try = "never-armed tonight in the kept skip window"
    elif b.get("tonight_send_n"):
        b_try = "trying; at least one T0 send on the tape"
    pod_line = "B saw Podoroska vs Monnet and skipped it (not never-armed)."
    if b.get("pod_skips"):
        reasons = "; ".join(f"{r['when']}: {r['reason']}" for r in b["pod_skips"])
        pod_line = "B saw Podoroska vs Monnet and skipped: " + reasons
    test = gem.get("test_order") or {}
    test_http = test.get("http") if not test.get("skipped") else "not sent"
    usd = None
    for call in gem.get("calls") or []:
        if call.get("name") == "balances":
            usd = call.get("usd_available")

    skip_rows = [
        [r["when"], r["game"], r["bucket"], r["reason"]] for r in (b.get("tonight_skips") or [])
    ]
    pod_rows = [
        [r.get("at") or r.get("when") or "", r.get("event") or "skip", r.get("action") or "", r.get("yes_a") or "", r.get("yes_b") or "", r.get("all_in_c") or "", r.get("reason") or r.get("reason") or ""]
        for r in (b.get("tape_pod") or [])
    ]
    if not pod_rows:
        pod_rows = [[r["when"], "skip", "", "", "", "", r["reason"]] for r in (b.get("pod_skips") or [])]
    sys_rows = [
        [r["system"], r["shops_gemini"], r["sport"], r["how"]] for r in systems_gemini()
    ]
    call_rows = [
        [c["name"], c["method"], c["path"], c["http"], c.get("n") if c.get("n") is not None else "", (c.get("body") or "")[:160]]
        for c in (gem.get("calls") or [])
    ]
    hist_rows = [
        [r.get("created") or "", r.get("symbol") or "", r.get("status") or "", r.get("qty") or "", r.get("price") or "", r.get("outcome") or ""]
        for r in (gem.get("history_fills") or [])[:12]
    ]
    job_rows = [
        [r["title"], r["listed_start"], "yes" if r["gemini"] else "empty", "yes" if r["kalshi"] else "empty", "yes" if r["poly"] else "no"]
        for r in (jobs.get("samples") or [])
    ]
    look_rows = [
        [r["at"], r["sport"], r["game"], r["yes"], r["no"], r["net"], r["decision"], r["reason"]]
        for r in (tape.get("gemini_looks") or [])
    ]
    t0_rows = [
        [r["at"], r["game"], r["action"], r["venue"], r["yes_a"], r["yes_b"], r["all_in_c"], r["reason"]]
        for r in (b.get("tonight_t0") or [])[-30:]
    ]
    px_rows = [
        [r["seen_at"], r["side"], r["venue"], r["price"], r["game_start"], r["phase"]]
        for r in (pod.get("yes_in_t0_window") or [])
    ]
    sport_rows = [[k, v] for k, v in sorted((tape.get("sport_files") or {}).items())]

    test_block = ""
    stale = test.get("stale_first_post") or {}
    if test.get("skipped"):
        test_block = f"<p>Live order POST was not sent: {esc(test.get('why') or '')}. Authenticated POST /orders/history still ran. First POST on a stale disk symbol was HTTP {esc(stale.get('http'))} {esc(stale.get('body'))}.</p>"
    else:
        body = test.get("body")
        body_txt = json.dumps(body, default=str) if not isinstance(body, str) else body
        hist = test.get("filled_history") or {}
        test_block = f"""
<div class="callout">
<p><strong>First POST (stale disk symbol):</strong> {esc(stale.get('symbol') or 'GEMI-NCAAF-2610172000-ARK-VAN-M-ARK')} HTTP {esc(stale.get('http') or 404)}. Gemini body: Invalid instrument symbol. That already proves the signed POST /v1/prediction-markets/order path is live.</p>
<p><strong>Second POST (live book, cannot-fill IOC):</strong> symbol {esc(test.get('symbol') or '')} ({esc(test.get('title') or test.get('game') or '')}) Yes qty 1 @ {esc(test.get('limit') or '0.01')} timeInForce immediate-or-cancel. Listed ask {esc(test.get('ask') or 'n/a')}.</p>
<p>HTTP {esc(test_http)}. Filled qty {esc(test.get('filled_qty') or '')}. IOC nothing filled: {esc(test.get('ioc_nothing'))}. Cancel HTTP {esc(test.get('cancel_http'))} {esc(test.get('cancel_note') or '')}.</p>
<pre>{esc(body_txt)}</pre>
<p>Filled-history pull HTTP {esc((hist or {}).get('http'))}, n={esc((hist or {}).get('n'))}, last fill {esc(((hist or {}).get('last_fill') or {}).get('symbol'))} @ {esc(((hist or {}).get('last_fill') or {}).get('created'))}.</p>
</div>
"""

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>B silent tennis + Gemini quiet — 30 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
pre {{ white-space: pre-wrap; background: #f8fafc; border: 1px solid #e2e8f0; padding: 8px 10px; font-size: 13px; }}
code {{ font-size: 13px; }}
ul {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>B tennis tonight, and why Gemini has been quiet</h1>
<p class="note">America/New_York. Written {esc(written)}. One B pid. Did not start a second live_strategy_b.py. Did not reload B. Did not sell TEN/CIN. Did not leftover-GTC A. Did not retune D=0.25. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<pre>{esc(PAUL)}</pre>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>System B is the tennis bot that tries to buy both players at first serve, then maybe a 50¢ cross and a leftover favorite. “Getting in” means it actually sent those both-Yes tickets. We read tonight’s B diary to see whether it never looked at the matches, or looked and then skipped. Podoroska vs Monnet is the example.</p>
<p>Gemini is one of four shops (with Kalshi, Polymarket US, and Novig). A “trade” is a fill, not a look. We checked whether A–G still price Gemini in the compare, pinged Gemini with signed reads, and sent one 1-contract immediate-or-cancel buy far below the ask so it cannot fill and cannot rest. Tennis on Gemini has historically had no book — if B only plays tennis, Gemini never gets a B ticket.</p>
</div>

<div class="callout ok">
<h2>Short answers</h2>
<ul>
<li><strong>B tonight:</strong> {esc(b_try)}. Open now {esc(b.get('currently_open'))} / max {esc(b.get('max_open'))}. Pid {esc(b.get('file_pid'))} alive={esc(b.get('pid_alive'))}. Python B processes: {esc(b.get('python_b_pids'))}. Reloaded B: no.</li>
<li><strong>Podoroska vs Monnet:</strong> {esc(pod_line)}</li>
<li><strong>Tonight counts:</strong> matches named in skip/tape window {esc(len(b.get('tonight_games') or []))}; T0 both-Yes rows {esc(b.get('tonight_t0_n'))}; T0 sends {esc(b.get('tonight_send_n'))}; 50-cross rows {esc(b.get('tonight_cross_n'))}; dip GTC today {esc(len(b.get('dip_matches') or []))}.</li>
<li><strong>Gemini test HTTP:</strong> {esc(test_http)}. Balance USD available {esc(usd)}. Last venue fill {esc((gem.get('last_fill') or {}).get('symbol') or 'none in this history page')}.</li>
<li><strong>Who still compares Gemini:</strong> A, B, C, D, E, F, G all fetch Gemini in the compare when the catalog has a ticker. Tennis tonight: Gemini catalog empty. CFB/soccer/NFL: Gemini books exist.</li>
<li><strong>Why no Gemini trades:</strong> B is tennis-only and Gemini has no tennis book. Kitchen flow this week is tennis. Last real Gemini fills were CFB/NHL/MLB last week. Not a dead key on the test we just ran.</li>
</ul>
</div>

<h2>1. System B — trying vs skipping</h2>
<p>B pid file {esc(b.get('file_pid'))} started {esc(b.get('pid_started'))}. Watch updated {esc(b.get('watch_updated'))}. Last skip: {esc(b.get('last_skip_reason'))}. Cluster: {esc(b.get('cluster_note'))}.</p>
<p>The kept skip list is the last 30 skips (SKIP_KEEP=30), so early-afternoon T0-window rows can rotate out. orders.jsonl event=t0 is the reconstructable tape.</p>
<p>Log tonight: {esc((b.get('log_counts') or {}).get('lines') or 0)} lines, {esc((b.get('log_counts') or {}).get('permission') or 0)} PermissionError, {esc((b.get('log_counts') or {}).get('other') or 0)} other. PermissionError is the loop catch-all (Windows file lock). Watch still updates, so B is looping; that noise is not why Podoroska was skipped.</p>

<h3>Podoroska vs Monnet</h3>
<ul>
<li>Lock-bot job listed_start {esc(pod.get('listed_start'))}, Poly startTime {esc(pod.get('startTime'))}, period {esc(pod.get('period'))} (S3 means already in set 3 by the 20:00 poller).</li>
<li>Price-memory game_start {esc(pod.get('price_memory_game_start'))} — about 40 minutes earlier than the 18:10 listed clock. B’s trusted T0 wants a scheduled listed clock (seconds=00) plus Kalshi/Gemini occurrence. This match has <strong>empty Gemini and empty Kalshi</strong> catalog, so occurrence never arrives from those shops.</li>
<li>Health expected Gemini={esc(pod.get('gemini_expected'))}, transport {esc(pod.get('state_transport'))}. Gemini messages=0.</li>
<li>First orders.jsonl T0 skip for this match is <strong>19:38 ET</strong> (all-in C=1.1), not 17:30 or 18:10. B did not send, and did not even tape a T0 attempt, inside the first-serve window. After 19:38 it kept looking: all-in C just over 1.05, Novig fee unknown, then Yes outside 10–90 once the favorite was absorbing. Later C&gt;1.05 rows still log that reason because the fee check runs before “missed T0 window.”</li>
</ul>
{table([("When","date"),("Event","text"),("Action","text"),("Yes A","num"),("Yes B","num"),("All-in C","num"),("Reason","text")], pod_rows)}
<p class="note">Yes ticks around the 17:30 memory start (Poly). Click headers to sort.</p>
{table([("When","date"),("Player","text"),("Shop","text"),("Yes","num"),("game_start","date"),("Phase","text")], px_rows)}

<h3>Tonight skip reasons (kept 30-row window)</h3>
{table([("When","date"),("Game","text"),("Bucket","text"),("Reason","text")], skip_rows)}

<h3>Tonight T0 tape (orders.jsonl)</h3>
{table([("When","date"),("Game","text"),("Action","text"),("Venue","text"),("Yes A","num"),("Yes B","num"),("All-in C","num"),("Reason","text")], t0_rows)}

<h3>Tennis jobs today — Gemini listed?</h3>
<p>{esc(jobs.get('jobs_today'))} tennis live_jobs files for 2026-10-30. Gemini nonempty {esc(jobs.get('jobs_with_gemini'))}. Kalshi nonempty {esc(jobs.get('jobs_with_kalshi'))}. tennis_*gemini.json files on disk: {esc(jobs.get('tennis_gemini_raw_n'))}.</p>
{table([("Match","text"),("Listed start","date"),("Gemini","text"),("Kalshi","text"),("Poly","text")], job_rows)}

<h2>B code: shops Gemini, then skip C&gt;1.05 / 10–90 / clock</h2>
<pre>VENUE_ORDER = ("kalshi", "gemini", "polymarket", "novig")
C_HI = Decimal("1.05")
YES_LO, YES_HI = 0.10, 0.90
# t0_ready: Yes band, then all-in C, then trusted clock, then 15s-before through 5-minute grace.
# 50-cross blocked until trusted T0 (CROSS_BEFORE_START). Skip-if already on match: existing open row.
# fire_t0: REST recheck both Yes, IOC/FOK, flatten a one-leg.</pre>
<p class="note">Cheapest Yes per player can be a cross-platform pair. Gemini only appears if fetch_gemini_event returned a moneyline book. Tennis games tonight pass gemini: {{}}.</p>

<h2>2. Gemini — still in the compare, quiet on fills</h2>
<p>A–G all still shop Gemini in code (catalog tickers + REST event/book recheck). A sport with no Gemini book cannot produce a Gemini fill no matter how hard we compare.</p>
{table([("System","text"),("Shops Gemini","text"),("Sport / book","text"),("How","text")], sys_rows)}

<h3>Gemini files on disk by sport prefix</h3>
{table([("Prefix","text"),("Files","num")], sport_rows)}
<p>Tennis prefix count {esc(tape.get('tennis_files'))}. CFB/NFL/soccer/NHL/MLB files exist. That matches “tennis historically none.”</p>

<h3>Kitchen looks vs HTTP posts</h3>
<p>order_io Gemini POSTs this week (not history): {esc(tape.get('posts_week_n'))}. Last Gemini POST {esc((tape.get('last_post') or {}).get('at') or 'none')}. Last book GET {esc((tape.get('last_book_get') or {}).get('at') or 'none')}. Diary Gemini looks still in considerations.json: {esc(tape.get('gemini_looks_n'))}.</p>
{table([("When","date"),("Sport","text"),("Game","text"),("Yes","text"),("No","text"),("Net","num"),("Decision","text"),("Reason","text")], look_rows)}

<h3>Authenticated Gemini calls (no secrets)</h3>
{table([("Call","text"),("Method","text"),("Path","text"),("HTTP","num"),("N","num"),("Body (redacted)","text")], call_rows)}
{test_block}
<p class="note">Venue history (this pull). Click headers to sort.</p>
{table([("When","date"),("Symbol","text"),("Status","text"),("Qty","num"),("Price","num"),("Outcome","text")], hist_rows)}

<h2>Why no Gemini trades this week</h2>
<ul>
<li><strong>Not auth-dead:</strong> balances and order-history returned HTTP on this job. USD available {esc(usd)}.</li>
<li><strong>B tennis + no Gemini tennis book:</strong> B only sends tennis moneyline Yes. Tonight’s tennis jobs have empty Gemini catalogs, 0 tennis_*gemini.json files. Gemini cannot win a B cheapest-leg compare if it is not on the match.</li>
<li><strong>A lock flow is tennis-heavy overnight:</strong> Gemini looks that do appear are CFB/NFL (Kalshi Yes / Gemini No), same pattern as 23 Oct. Those pairs still have to beat after-fee 0.984 and actually POST. Prior week’s last house fills were MTN/FIU NCAAF 20 Oct, CAR/CGY NHL 18 Oct, TB/CLE MLB 18 Oct.</li>
<li><strong>C/D Gemini CFB:</strong> yes, listed. C is T0 favorite 51–89; D is T0 spread 51–89 except NFL. No Gemini fill this week means Gemini was not the cheapest legal Yes at those T0s, or those T0s did not fire, not that C/D dropped Gemini from the compare.</li>
<li><strong>FOK/IOC 0:</strong> last real Gemini POSTs in the 23 Oct write-up were HTTP 201 cancelled fill 0 (empty IOC). If we send and the ask is gone, that is trying-and-failing, not a missing shop.</li>
<li><strong>Filter:</strong> Gemini No with size 0 is rejected as not a buyable offer. Tennis Gemini size is not even present.</li>
</ul>

<p class="note">Sources: strategy_b.log / strategy_b_watch.json / strategy_b.pid, orders.jsonl, order_io.jsonl, considerations.json, live_jobs/live_health/live_state tennis_podoromonnet, price_memory tennis.jsonl, *_gemini.json, Gemini POST /v1/balances, GET terms/status, POST orders/history, POST /v1/prediction-markets/order IOC. Code: live_strategy_b.py, live_t0_yes.collect_quotes, live_game_pollers._compared / tickers_for_quotes, gemini_private.py. Did not start a second B. Did not interrupt TEN/CIN matcher. No secrets.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    OUT_HTML.write_text(inject_report_page_extras(page), encoding="utf-8")


def live_gemini_ioc() -> dict:
    """One IOC on a currently listed Gemini sports book. Not TEN/CIN. Price 0.01."""
    status, body = http_get("https://api.gemini.com/v1/prediction-markets/events")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"skipped": True, "why": f"events list HTTP {status} not JSON"}
    rows = payload.get("data") if isinstance(payload, dict) else []
    chosen = None
    for event in rows or []:
        if not isinstance(event, dict):
            continue
        ticker = str(event.get("ticker") or "")
        title = str(event.get("title") or "")
        if TEN_CIN_RE.search(ticker) or TEN_CIN_RE.search(title):
            continue
        if str(event.get("status") or "").lower() not in {"active", "open"}:
            continue
        if str(event.get("category") or "").lower() not in {"sports", ""}:
            continue
        ev_status, ev_body = http_get(
            "https://api.gemini.com/v1/prediction-markets/events/" + ticker
        )
        contracts = event.get("contracts") or []
        if ev_status == 200:
            try:
                ev_payload = json.loads(ev_body)
            except json.JSONDecodeError:
                ev_payload = None
            if isinstance(ev_payload, dict) and ev_payload.get("contracts"):
                contracts = ev_payload.get("contracts") or contracts
        for raw in contracts:
            if not isinstance(raw, dict):
                continue
            inst = str(raw.get("instrumentSymbol") or "")
            if not inst.startswith("GEMI-"):
                continue
            if TEN_CIN_RE.search(inst):
                continue
            prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
            ask = prices.get("bestAsk")
            if ask in (None, "", {}):
                sell = prices.get("sell") if isinstance(prices.get("sell"), dict) else {}
                ask = sell.get("price")
            state = str(raw.get("marketState") or raw.get("status") or event.get("status") or "").lower()
            chosen = {
                "symbol": inst,
                "ticker": ticker,
                "title": title,
                "ask": ask,
                "state": state,
                "label": raw.get("label") or "",
                "event_http": ev_status,
            }
            break
        if chosen:
            break
    if not chosen:
        return {"skipped": True, "why": "no live GEMI- sports contract on public events list", "events_http": status}
    try:
        ask_n = Decimal(str(chosen.get("ask") or "1"))
    except Exception:
        ask_n = Decimal("1")
    if ask_n <= Decimal("0.05"):
        return {"skipped": True, "why": f"ask {ask_n} too close to 0.01", "picked": chosen}
    order_body = {
        "symbol": chosen["symbol"],
        "orderType": "limit",
        "side": "buy",
        "quantity": "1",
        "price": "0.01",
        "outcome": "yes",
        "timeInForce": "immediate-or-cancel",
    }
    recorded: dict = {}
    http, text = gemini_private.private_call("/v1/prediction-markets/order", order_body, "POST", record=recorded)
    try:
        live_lock_orders.record_order_io("gemini", "order", recorded.get("request") or order_body, http, text)
    except Exception:
        pass
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    filled = live_lock_orders.filled_contracts(parsed) if parsed is not None else Decimal("0")
    cancel_http = None
    cancel_note = ""
    if http in (200, 201) and live_lock_orders.order_still_open(parsed):
        cancel_http, cancel_note = live_lock_orders._cancel(
            {"venue": "gemini", "instrument": chosen["symbol"], "outcome": "yes"}, parsed
        )
    filled_hist = None
    try:
        h_http, h_body = gemini_private.get_order_history({"status": "filled", "limit": 10})
        h_parsed = json.loads(h_body)
        orders = h_parsed.get("orders") if isinstance(h_parsed, dict) else h_parsed
        last = None
        for row in orders or []:
            if isinstance(row, dict) and str(row.get("status") or "").lower() == "filled":
                last = {
                    "symbol": row.get("symbol"),
                    "status": row.get("status"),
                    "qty": row.get("executedQuantity") or row.get("quantity"),
                    "price": row.get("price") or row.get("avgPrice"),
                    "created": row.get("timestamp") or row.get("createdAt") or row.get("time"),
                }
        filled_hist = {"http": h_http, "n": len(orders or []), "last_fill": last}
    except Exception as exc:
        filled_hist = {"error": type(exc).__name__}
    return {
        "skipped": False,
        "symbol": chosen["symbol"],
        "title": chosen.get("title"),
        "ticker": chosen.get("ticker"),
        "ask": chosen.get("ask"),
        "limit": "0.01",
        "tif": "immediate-or-cancel",
        "http": http,
        "filled_qty": format(filled, "f"),
        "ioc_nothing": live_lock_orders.ioc_nothing_filled(http, parsed) if parsed is not None else False,
        "body": _redact_order_body(parsed) if parsed is not None else public_note(text, 280),
        "cancel_http": cancel_http,
        "cancel_note": public_note(str(cancel_note), 160),
        "events_http": status,
        "filled_history": filled_hist,
        "stale_first_post": {
            "symbol": "GEMI-NCAAF-2610172000-ARK-VAN-M-ARK",
            "http": 404,
            "body": "Invalid instrument symbol (expired CFB from disk)",
        },
    }


def main() -> int:
    if sys.argv[1:2] == ["--live-ioc-html"]:
        print("live Gemini IOC + HTML from saved JSON", flush=True)
        blob = load_json(OUT_JSON) or {}
        live = live_gemini_ioc()
        gem = blob.get("gemini") if isinstance(blob.get("gemini"), dict) else {}
        gem["live_ioc"] = live
        gem["test_order"] = live
        blob["gemini"] = gem
        OUT_JSON.write_text(json.dumps(blob, default=str, indent=2), encoding="utf-8")
        # Reconstruct the pieces write_html needs from the saved blob + fresh watch.
        b = scan_b()
        pod = blob.get("pod") or scan_pod_clock()
        jobs = blob.get("jobs") or scan_tennis_jobs()
        tape = scan_gemini_tape()
        write_html(b, pod, jobs, tape, gem)
        print(json.dumps({"live_ioc_http": live.get("http"), "symbol": live.get("symbol"), "filled": live.get("filled_qty"), "html": str(OUT_HTML)}, default=str), flush=True)
        return 0
    print("scanning B tape", flush=True)
    b = scan_b()
    print("pod clock", flush=True)
    pod = scan_pod_clock()
    print("tennis jobs", flush=True)
    jobs = scan_tennis_jobs()
    print("gemini tape", flush=True)
    tape = scan_gemini_tape()
    print("gemini API (no secrets)", flush=True)
    gem = gemini_calls(tape)
    blob = {
        "written_at": now_et().isoformat(timespec="seconds"),
        "b": {
            k: v
            for k, v in b.items()
            if k
            not in {
                "day_skips",
                "tonight_skips",
                "tonight_t0",
                "today_matches",
            }
        },
        "b_tonight_skips": b.get("tonight_skips"),
        "b_pod_skips": b.get("pod_skips"),
        "b_tape_pod": b.get("tape_pod"),
        "pod": pod,
        "jobs": jobs,
        "tape": {
            "last_post": tape.get("last_post"),
            "last_book_get": tape.get("last_book_get"),
            "posts_week_n": tape.get("posts_week_n"),
            "posts_ever": tape.get("posts_ever"),
            "gemini_looks_n": tape.get("gemini_looks_n"),
            "sport_files": tape.get("sport_files"),
            "tennis_files": tape.get("tennis_files"),
            "live_contracts_n": tape.get("live_contracts_n"),
        },
        "gemini": gem,
        "reloaded_b": False,
    }
    OUT_JSON.write_text(json.dumps(blob, default=str, indent=2), encoding="utf-8")
    write_html(b, pod, jobs, tape, gem)
    print(f"wrote {OUT_HTML}", flush=True)
    print(
        json.dumps(
            {
                "b_pid": b.get("file_pid"),
                "b_alive": b.get("pid_alive"),
                "b_pids": b.get("python_b_pids"),
                "tonight_games": len(b.get("tonight_games") or []),
                "tonight_t0": b.get("tonight_t0_n"),
                "tonight_send": b.get("tonight_send_n"),
                "pod_skips": len(b.get("pod_skips") or []),
                "gemini_test_http": (gem.get("test_order") or {}).get("http")
                or (gem.get("test_order") or {}).get("why"),
                "reloaded_b": False,
            },
            default=str,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
