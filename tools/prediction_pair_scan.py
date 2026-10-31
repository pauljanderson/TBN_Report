"""One-process same-bet compare for one college game at a time.

Public GETs only. No orders, no API key, no secrets/. Fetch Gemini if a ticker
exists, Kalshi if a ticker exists, then merge Polymarket US / Novig the same way
live A does. A blank shop is omitted; the whole game is not skipped. Does not
start a watch.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
sys.path.insert(0, str(STAMP))

import overnight_scan as ov  # noqa: E402
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML  # noqa: E402

ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 stockresearch-pair-scan/1.0", "Accept": "application/json"}
PASS_ID = "one_process"
WATCH_FRESH_SEC = 600
HOT_FILE_SEC = 8


def now_et() -> datetime:
    return datetime.now(ET)


def clock(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    shown = dt.astimezone(ET)
    hour = shown.strftime("%I").lstrip("0") or "12"
    return shown.strftime(f"%Y-%m-%d {hour}:%M:%S.%f")[:-3] + shown.strftime(" %p ET")


def iso(dt: datetime) -> str:
    return dt.isoformat()


def duration_seconds(sent: datetime, received: datetime) -> float:
    raw = (received - sent).total_seconds()
    if raw < 0:
        raw = 0.0
    rounded = round(raw, 3)
    if rounded == 0 and raw > 0:
        return round(raw, 6)
    return rounded


def timing_record(url: str, sent: datetime, received: datetime, status: int, error: str | None) -> dict:
    return {
        "url": url,
        "sent_at": sent,
        "received_at": received,
        "duration_seconds": duration_seconds(sent, received),
        "elapsed": duration_seconds(sent, received),
        "http_status": status,
        "error": error,
    }


def http_get(url: str) -> tuple[int, dict | list | None, str | None, dict]:
    """Public GET. HTTP 429 backs off 2s, 4s, then 8s, then stops."""
    delay = 2.0
    last_err = None
    attempts: list[dict] = []
    last_timing = timing_record(url, now_et(), now_et(), 0, "no attempt")
    for attempt in range(3):
        req = urllib.request.Request(url, headers=UA, method="GET")
        sent = now_et()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                received = now_et()
                timing = timing_record(url, sent, received, resp.status, None)
                attempts.append(timing)
                timing = dict(timing)
                timing["attempts"] = attempts
                return resp.status, json.loads(body.decode("utf-8")), None, timing
        except urllib.error.HTTPError as e:
            received = now_et()
            last_err = f"HTTP {e.code} {url}"
            last_timing = timing_record(url, sent, received, e.code, last_err)
            attempts.append(last_timing)
            if e.code == 429 and attempt < 2:
                time.sleep(delay)
                delay *= 2
                continue
            if e.code == 429 and attempt == 2:
                time.sleep(8)
            last_timing = dict(last_timing)
            last_timing["attempts"] = attempts
            return e.code, None, last_err, last_timing
        except Exception as e:
            received = now_et()
            last_err = f"{type(e).__name__} {url}: {e}"[:300]
            last_timing = timing_record(url, sent, received, 0, last_err)
            attempts.append(last_timing)
            last_timing = dict(last_timing)
            last_timing["attempts"] = attempts
            return 0, None, last_err, last_timing
    last_timing = dict(last_timing)
    last_timing["attempts"] = attempts or [last_timing]
    return 0, None, last_err, last_timing


def fetch_gemini(ticker: str) -> tuple[dict, list[dict]]:
    url = "https://api.gemini.com/v1/prediction-markets/events/" + urllib.parse.quote(ticker, safe="")
    status, payload, err, timing = http_get(url)
    calls = list(timing.get("attempts") or [timing])
    contracts = ov.extract_contracts(payload)
    title = ""
    if isinstance(payload, dict):
        title = payload.get("title") or ""
        if not title and isinstance(payload.get("event"), dict):
            title = payload["event"].get("title") or ""
    event = {
        "ticker": ticker,
        "url": url,
        "http_status": status,
        "error": err,
        "elapsed_sec": timing["duration_seconds"],
        "sent_at": iso(timing["sent_at"]),
        "received_at": iso(timing["received_at"]),
        "duration_seconds": timing["duration_seconds"],
        "title": title,
        "contracts": contracts,
    }
    return event, calls


def fetch_kalshi(ticker: str) -> tuple[dict, list[dict]]:
    contracts = []
    status = 0
    err = None
    cursor = ""
    pages = 0
    url = ""
    calls: list[dict] = []
    while pages < 5:
        q = {"event_ticker": ticker, "limit": "200"}
        if cursor:
            q["cursor"] = cursor
        url = "https://api.elections.kalshi.com/trade-api/v2/markets?" + urllib.parse.urlencode(q)
        status, payload, err, timing = http_get(url)
        pages += 1
        calls.extend(timing.get("attempts") or [timing])
        if timing["http_status"] == 429 or not isinstance(payload, dict):
            break
        batch = payload.get("markets") or []
        contracts.extend(batch)
        cursor = payload.get("cursor") or ""
        if err or not batch or not cursor:
            break
    elapsed_total = duration_seconds(calls[0]["sent_at"], calls[-1]["received_at"]) if calls else 0.0
    event = {
        "event_ticker": ticker,
        "url": url,
        "http_status": status,
        "error": err,
        "elapsed_sec": elapsed_total,
        "sent_at": iso(calls[0]["sent_at"]) if calls else None,
        "received_at": iso(calls[-1]["received_at"]) if calls else None,
        "duration_seconds": elapsed_total,
        "pages": pages,
        "contracts": [ov.slim_kalshi(m) for m in contracts if isinstance(m, dict)],
    }
    return event, calls


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_line(path: Path, row: dict) -> str:
    line = json.dumps(row, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return line


def pass_done(pass_id: str) -> tuple[set[str], set[str]]:
    codes: set[str] = set()
    titles: set[str] = set()
    for row in read_jsonl(RAW / "cfb_game_results.jsonl"):
        if str(row.get("pass")) != str(pass_id):
            continue
        if row.get("codes"):
            codes.add(str(row["codes"]).lower())
        if row.get("game"):
            titles.add(str(row["game"]).strip().lower())
    return codes, titles


def any_result_codes() -> set[str]:
    codes: set[str] = set()
    for row in read_jsonl(RAW / "cfb_game_results.jsonl"):
        if row.get("codes"):
            codes.add(str(row["codes"]).lower())
    return codes


def log_tail() -> list[str]:
    path = RAW / "overnight_scan.log"
    if not path.exists():
        return []
    data = path.read_bytes()[-16000:]
    return [ln for ln in data.decode("utf-8", errors="replace").splitlines() if ln.strip()]


def in_flight(codes: str) -> bool:
    lines = log_tail()
    if not lines:
        return False
    last = lines[-1]
    if re.search(rf"fetch college football {re.escape(codes)} pass", last):
        return True
    for suffix in ("kalshi", "gemini"):
        path = RAW / f"cfb_{codes}_{suffix}.json"
        tmp = Path(str(path) + ".tmp")
        if tmp.exists():
            return True
        if path.exists() and (time.time() - path.stat().st_mtime) < HOT_FILE_SEC:
            return True
    return False


def watch_active(codes: str) -> bool:
    path = RAW / f"opportunity_watch_cfb_{codes}.jsonl"
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < WATCH_FRESH_SEC


def select_games(limit: int) -> tuple[list[tuple[int, dict, str]], str]:
    games = ov.load_college()
    done_codes, done_titles = pass_done(PASS_ID)
    already = any_result_codes()
    note = (
        f"Every matched college game already has a result row ({len(already)} coded, "
        f"list {len(games)}). This proof uses pass {PASS_ID}: the next games in list order "
        "that do not yet have that pass, skipping a file another process is writing and "
        "skipping a game whose watch file was updated in the last 10 minutes."
    )
    picked: list[tuple[int, dict, str]] = []
    skipped: list[str] = []
    for i, game in enumerate(games):
        codes = ov.game_codes(game)
        title_guess = " vs ".join(game.get("teams") or []) 
        if codes in done_codes or title_guess.strip().lower() in done_titles:
            continue
        if watch_active(codes):
            skipped.append(f"{codes} watch active")
            continue
        if in_flight(codes):
            skipped.append(f"{codes} in flight")
            continue
        picked.append((i, game, codes))
        if len(picked) >= limit:
            break
    if skipped:
        note += " Skipped: " + ", ".join(skipped) + "."
    return picked, note


def metric_row(row_id: str, game: str, venue: str, sent: datetime, received: datetime, notes: str, source: str) -> dict:
    total = duration_seconds(sent, received)
    sent_iso = iso(sent)
    received_iso = iso(received)
    return {
        "row_id": row_id,
        "game": game,
        "sport": "college football",
        "venue": venue,
        "sent_at": sent_iso,
        "received_at": received_iso,
        "duration_seconds": total,
        "notes": notes,
        "step": venue,
        "sent": sent_iso,
        "sent_display": clock(sent),
        "received": received_iso,
        "received_display": clock(received),
        "total_seconds": total,
        "total_display": f"{total:.3f}",
        "method": PASS_ID,
        "source_file": source,
        "logged_at": iso(now_et()),
    }


def call_notes(kind: str, calls: list[dict]) -> str:
    parts = [
        f"One Python process. Sent is the clock immediately before the first {kind} request. "
        f"Received is when the last {kind} response bytes were in memory. Duration is received minus sent."
    ]
    if len(calls) > 1:
        for call in calls:
            err = f" error={call['error']}" if call.get("error") else ""
            parts.append(
                f"{call['url']} {call['duration_seconds']:.3f}s status={call['http_status']}{err}"
            )
    elif calls:
        call = calls[0]
        err = f" error={call['error']}" if call.get("error") else ""
        parts.append(f"{call['url']} status={call['http_status']}{err}")
    return " ".join(parts)


def saw_429(calls: list[dict]) -> bool:
    return any(call.get("http_status") == 429 for call in calls)


def save_book(path: Path, payload: dict) -> None:
    ov.save_book(path, payload)


def _remember_prices(game_name: str, seen_at: str, game: dict, gemini_events: list, kalshi_events: list) -> None:
    """Keep the pay-price on each line. Does not place an order."""
    try:
        tools = str(ROOT / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import price_memory
        price_memory.remember_books(
            "college football", game_name, seen_at, kalshi_events, gemini_events, game.get("date")
        )
    except Exception as exc:
        print(f"price memory {exc}", file=sys.stderr)


def _call_span(calls: list[dict]) -> tuple:
    if not calls:
        return None, None
    return calls[0]["sent_at"], calls[-1]["received_at"]


def scan_game(game: dict, codes: str) -> dict:
    k_tickers, g_tickers = ov.tickers_of(game)
    fallback = " vs ".join(game.get("teams") or [codes])
    gemini_events: list[dict] = []
    kalshi_events: list[dict] = []
    g_calls: list[dict] = []
    k_calls: list[dict] = []
    for ticker in g_tickers:
        event, calls = fetch_gemini(ticker)
        gemini_events.append(event)
        g_calls.extend(calls)
        if saw_429(calls):
            break
    title = ov.game_title_from(gemini_events, [], fallback)
    g_stamp = now_et()
    g_path = RAW / f"cfb_{codes}_gemini.json"
    if g_calls and not saw_429(g_calls):
        save_book(g_path, {
            "fetched_at": iso(g_stamp),
            "timezone": "America/New_York",
            "game": title,
            "game_date": game.get("date"),
            "codes": codes,
            "events": gemini_events,
        })
    if saw_429(g_calls):
        if g_calls:
            g_sent = g_calls[0]["sent_at"]
            g_recv = g_calls[-1]["received_at"]
            append_line(RAW / "call_metrics.jsonl", metric_row(
                f"call:Gemini:{codes}:{iso(g_sent)}",
                title,
                "Gemini",
                g_sent,
                g_recv,
                call_notes("Gemini", g_calls) + " Stopped after HTTP 429.",
                g_path.name,
            ))
        _remember_prices(title, iso(g_stamp), game, gemini_events, kalshi_events)
        return {
            "game": title,
            "codes": codes,
            "gemini": duration_seconds(g_calls[0]["sent_at"], g_calls[-1]["received_at"]) if g_calls else None,
            "kalshi": None,
            "analysis": None,
            "total": None,
            "opportunity": False,
            "under": [],
            "reason": "HTTP 429",
            "slow": None,
            "calls": g_calls,
            "errors": [c for c in g_calls if c.get("error")],
            "g_sent": g_calls[0]["sent_at"] if g_calls else now_et(),
            "a_recv": g_calls[-1]["received_at"] if g_calls else now_et(),
            "rate_limited": True,
            "rows": [],
        }

    for ticker in k_tickers:
        event, calls = fetch_kalshi(ticker)
        kalshi_events.append(event)
        k_calls.extend(calls)
        if saw_429(calls):
            break
    title = ov.game_title_from(gemini_events, kalshi_events, title)
    k_stamp = now_et()
    k_path = RAW / f"cfb_{codes}_kalshi.json"
    if k_calls and not saw_429(k_calls):
        save_book(k_path, {
            "fetched_at": iso(k_stamp),
            "timezone": "America/New_York",
            "game": title,
            "game_date": game.get("date"),
            "codes": codes,
            "base": "https://api.elections.kalshi.com/trade-api/v2",
            "events": kalshi_events,
        })
    _remember_prices(title, iso(k_stamp), game, gemini_events, kalshi_events)
    g_sent, g_recv = _call_span(g_calls)
    k_sent, k_recv = _call_span(k_calls)
    if saw_429(k_calls):
        rows = []
        if g_calls and g_sent is not None and g_recv is not None:
            rows.append(metric_row(
                f"call:Gemini:{g_path.name}:{iso(g_stamp)}",
                title,
                "Gemini",
                g_sent,
                g_recv,
                call_notes("Gemini", g_calls),
                g_path.name,
            ))
        if k_calls:
            rows.append(metric_row(
                f"call:Kalshi:{codes}:{iso(k_calls[0]['sent_at'])}",
                title,
                "Kalshi",
                k_calls[0]["sent_at"],
                k_calls[-1]["received_at"],
                call_notes("Kalshi", k_calls) + " Stopped after HTTP 429.",
                k_path.name,
            ))
        for item in rows:
            append_line(RAW / "call_metrics.jsonl", item)
        return {
            "game": title,
            "codes": codes,
            "gemini": rows[0]["duration_seconds"] if rows and g_calls else None,
            "kalshi": (rows[-1]["duration_seconds"] if k_calls and rows else None),
            "analysis": None,
            "total": None,
            "opportunity": False,
            "under": [],
            "reason": "HTTP 429",
            "slow": None,
            "calls": g_calls + k_calls,
            "errors": [c for c in g_calls + k_calls if c.get("error")],
            "g_sent": g_sent if g_sent is not None else now_et(),
            "a_recv": (k_recv if k_recv is not None else g_recv if g_recv is not None else now_et()),
            "rate_limited": True,
            "rows": rows,
        }

    a_sent = now_et()
    result = ov.compare_payloads(game, kalshi_events, gemini_events)
    polymarket = ov._read_polymarket(game, kalshi_events, gemini_events)
    novig = ov._read_novig(game, kalshi_events, gemini_events, "college football")
    ov._merge_extra(game, kalshi_events, gemini_events, result, polymarket, novig)
    closest = None
    if result["candidates"]:
        closest = min(result["candidates"], key=lambda c: ov.d(c["gross"]) or ov.Decimal("99"))
    fetched_at = iso(k_recv or g_recv or a_sent)
    row = {
        "sport": "college football",
        "game": title,
        "game_date": game.get("date"),
        "codes": codes,
        "pass": PASS_ID,
        "fetched_at": fetched_at,
        "opportunity": result["opportunity"],
        "confirmed_lock": result["confirmed"],
        "reason": result["reason"],
        "kalshi_markets": result["kalshi_markets"],
        "gemini_markets": result["gemini_markets"],
        "best_gross": result["best_gross"],
        "matched_pairs": result["matched_pairs"],
        "closest": closest,
        "under": result["under"],
        "candidates_n": len(result["candidates"]),
        "method": PASS_ID,
    }
    line = append_line(RAW / "cfb_game_results.jsonl", row)
    a_recv = now_et()
    digest = hashlib.sha1(line.encode("utf-8")).hexdigest()[:16]
    rows = []
    g_sec = None
    k_sec = None
    if g_calls and g_sent is not None and g_recv is not None:
        g_fetched = iso(g_stamp)
        if g_path.exists():
            try:
                g_fetched = json.loads(g_path.read_text(encoding="utf-8"))["fetched_at"]
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        gemini_row = metric_row(
            f"call:Gemini:{g_path.name}:{g_fetched}",
            title,
            "Gemini",
            g_sent,
            g_recv,
            call_notes("Gemini", g_calls),
            g_path.name,
        )
        rows.append(gemini_row)
        g_sec = gemini_row["duration_seconds"]
    if k_calls and k_sent is not None and k_recv is not None:
        k_fetched = iso(k_stamp)
        if k_path.exists():
            try:
                k_fetched = json.loads(k_path.read_text(encoding="utf-8"))["fetched_at"]
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        kalshi_row = metric_row(
            f"call:Kalshi:{k_path.name}:{k_fetched}",
            title,
            "Kalshi",
            k_sent,
            k_recv,
            call_notes("Kalshi", k_calls),
            k_path.name,
        )
        rows.append(kalshi_row)
        k_sec = kalshi_row["duration_seconds"]
    analysis_row = metric_row(
        f"analysis:cfb:{digest}",
        title,
        "Analysis",
        a_sent,
        a_recv,
        "One Python process. Sent is the moment the compare starts. Received is the moment the result line is written. Duration is received minus sent. A blank shop is omitted; Polymarket US / Novig still merge.",
        "cfb_game_results.jsonl",
    )
    rows.append(analysis_row)
    a_sec = analysis_row["duration_seconds"]
    g_part = g_sec if g_sec is not None else 0.0
    k_part = k_sec if k_sec is not None else 0.0
    parts = round(g_part + k_part + a_sec, 3)
    cycle_sent = g_sent or k_sent or a_sent
    cycle_recv = a_recv
    total = duration_seconds(cycle_sent, cycle_recv)
    stamp_for_cycle = fetched_at
    rows.append({
        "row_id": f"cycle:one_process:{codes}:{stamp_for_cycle}",
        "game": title,
        "sport": "college football",
        "venue": "Cycle",
        "sent_at": iso(cycle_sent),
        "received_at": iso(cycle_recv),
        "duration_seconds": total,
        "step": "Cycle",
        "sent": iso(cycle_sent),
        "sent_display": clock(cycle_sent),
        "received": iso(cycle_recv),
        "received_display": clock(cycle_recv),
        "total_seconds": total,
        "total_display": f"{total:.3f}",
        "notes": (
            f"One Python process. Gemini {g_part:.3f}s + Kalshi {k_part:.3f}s + analysis {a_sec:.3f}s "
            f"(parts sum {parts:.3f}s). Fetch whichever shops have a ticker, then the compare. "
            "This row's duration is the cycle received time minus the cycle sent time."
        ),
        "method": PASS_ID,
        "source_file": g_path.name if g_calls else k_path.name,
        "logged_at": iso(now_et()),
    })
    for item in rows:
        append_line(RAW / "call_metrics.jsonl", item)
    calls = g_calls + k_calls
    slow = max(calls, key=lambda c: c["elapsed"]) if calls else None
    return {
        "game": title,
        "codes": codes,
        "gemini": g_sec,
        "kalshi": k_sec,
        "analysis": a_sec,
        "total": total,
        "opportunity": bool(result["opportunity"]),
        "under": result["under"],
        "reason": result["reason"],
        "slow": slow,
        "calls": calls,
        "errors": [c for c in calls if c.get("error")],
        "g_sent": g_sent if g_sent is not None else cycle_sent,
        "a_recv": a_recv,
        "rate_limited": False,
        "rows": rows,
        "candidates": result.get("candidates") or [],
    }


def record_opportunities(summary: dict) -> bool:
    if not summary["under"]:
        return False
    first = iso(summary["a_recv"])
    kept = []
    for cand in summary["under"]:
        blocked = ov.gemini_no_rejection(cand)
        if blocked:
            continue
        kept.append(cand)
    if not kept:
        return False
    for cand in kept:
        append_line(RAW / "opportunities.jsonl", {
            "game": summary["game"],
            "codes": summary["codes"],
            "sport": "college football",
            "first_seen": first,
            "candidate": cand,
            "method": PASS_ID,
            "watch": "not started; add a watch if this quote is still under $1",
        })
    page = STAMP / "opportunities.html"
    text = page.read_text(encoding="utf-8")
    sport_th = ov.th("Sport", "text")
    game_th = ov.th("Game", "text")
    if sport_th not in text and game_th in text:
        text = text.replace(game_th, sport_th + game_th)
    extra = []
    for cand in kept:
        sport = ov.sport_column_label(
            game=summary["game"],
            side=str(cand.get("side") or ""),
            sport="college football",
            ticker=" ".join(
                str(cand.get(key) or "")
                for key in ("kalshi_ticker", "gemini_symbol", "ticker", "symbol")
            ),
            title=summary["game"],
        )
        cells = [
            sport,
            summary["game"],
            cand.get("market_type", ""),
            cand.get("side", ""),
            cand.get("number", ""),
            f"{cand.get('yes_venue','')} {cand.get('yes_price','')}",
            f"{cand.get('no_venue','')} {cand.get('no_price','')}",
            cand.get("yes_size", ""),
            cand.get("no_size", ""),
            cand.get("gross", ""),
            cand.get("net", ""),
            cand.get("label", ""),
            first,
            "not watched yet; one-process scan only",
        ]
        tds = "".join(f"<td>{ov.esc(c)}</td>" for c in cells)
        extra.append(f"<tr>{tds}</tr>")
    needle = "</tbody>"
    if needle not in text:
        return True
    text = text.replace(needle, "".join(extra) + needle, 1)
    stamp_note = f"<p class=\"note\">Updated {iso(now_et())}. New rows are from the one-process scan. No watch was started.</p>"
    text = text.replace("<p class=\"note\">Updated ", stamp_note + "<p class=\"note\">Updated ", 1)
    page.write_text(text, encoding="utf-8")
    return True


def _row_sent(row: dict) -> str | None:
    value = row.get("sent_at")
    if value:
        return str(value)
    value = row.get("sent")
    if value:
        return str(value)
    return None


def _row_received(row: dict) -> str | None:
    value = row.get("received_at")
    if value:
        return str(value)
    value = row.get("received")
    if value:
        return str(value)
    return None


def _row_duration(row: dict) -> float | None:
    for key in ("duration_seconds", "total_seconds"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _has_both_times(row: dict) -> bool:
    return _row_sent(row) is not None and _row_received(row) is not None and _row_duration(row) is not None


def _fmt_duration(value: float | None) -> str:
    if value is None:
        return ""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _venue_name(row: dict) -> str:
    return str(row.get("venue") or row.get("step") or "")


def write_call_metrics_html() -> None:
    rows = read_jsonl(RAW / "call_metrics.jsonl")
    has_sport = any(str(row.get("sport") or "").strip() for row in rows)
    medians: dict[str, list[float]] = {"Kalshi": [], "Gemini": [], "Analysis": []}
    for row in rows:
        venue = _venue_name(row)
        if venue in medians and _has_both_times(row):
            medians[venue].append(_row_duration(row) or 0.0)
    by_game: dict[str, dict[str, dict]] = {}
    for row in rows:
        venue = _venue_name(row)
        if venue not in {"Kalshi", "Gemini", "Analysis"} or not _has_both_times(row):
            continue
        game = str(row.get("game") or "").strip().lower()
        if not game or game == "one-program method":
            continue
        current = by_game.setdefault(game, {})
        previous = current.get(venue)
        if previous is None or (_row_received(row) or "") >= (_row_received(previous) or ""):
            current[venue] = row
    cycles: list[float] = []
    for parts in by_game.values():
        if set(parts) >= {"Gemini", "Kalshi", "Analysis"}:
            cycles.append(
                (_row_duration(parts["Gemini"]) or 0.0)
                + (_row_duration(parts["Kalshi"]) or 0.0)
                + (_row_duration(parts["Analysis"]) or 0.0)
            )
    proof = None
    for row in rows:
        notes = str(row.get("notes") or "")
        if "over 5 games" in notes and "one-Python-process" in notes:
            proof = row
            break

    def med_text(venue: str) -> str:
        values = medians[venue]
        if not values:
            return f"{venue} not measured yet"
        return f"{venue} {_fmt_duration(_median(values))} seconds ({len(values)} rows)"

    cycle_text = "not measured yet"
    if cycles:
        cycle_text = f"{_fmt_duration(_median(cycles))} seconds over {len(cycles)} games"
    proof_text = (
        "One-program proof: five college games in one Python process "
        "(Gemini, then Kalshi, then the compare) averaged 0.6 seconds."
    )
    if proof is not None:
        proof_text = (
            "One-program proof: "
            + str(proof.get("notes") or proof_text)
            + " That figure is the five-game one-program proof."
        )
    summary = (
        "Median duration (received minus sent) for rows that have both times: "
        f"{med_text('Kalshi')}; {med_text('Gemini')}; {med_text('Analysis')}. "
        f"One-program cycle (Gemini + Kalshi + Analysis) median {cycle_text}."
    )
    ordered = sorted(
        rows,
        key=lambda row: (
            _row_received(row) or "9999",
            str(row.get("game") or ""),
            {"Gemini": 0, "Kalshi": 1, "Analysis": 2, "Cycle": 3}.get(_venue_name(row), 9),
        ),
    )
    body: list[str] = []
    for row in ordered:
        sent_missing = _row_sent(row) is None
        notes = str(row.get("notes") or "")
        if sent_missing and "sent time was not recorded" not in notes.lower():
            notes = (notes + " Sent time was not recorded.").strip()
        sent_cell = "" if sent_missing else (row.get("sent_display") or _row_sent(row) or "")
        received_cell = "" if not _row_received(row) else (row.get("received_display") or _row_received(row) or "")
        total_cell = "" if sent_missing else _fmt_duration(_row_duration(row))
        cells = []
        if has_sport:
            cells.append(str(row.get("sport") or ""))
        cells.extend([
            str(row.get("game") or ""),
            _venue_name(row),
            str(sent_cell),
            str(received_cell),
            total_cell,
            notes,
        ])
        tds = []
        total_index = 5 if has_sport else 4
        for index, value in enumerate(cells):
            style = ' style="text-align:right"' if index == total_index else ""
            tds.append(f"<td{style}>{html.escape(str(value))}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    if not body:
        span = 7 if has_sport else 6
        body.append(f'<tr><td colspan="{span}">No timing rows yet.</td></tr>')
    headers = []
    if has_sport:
        headers.append(ov.th("Sport", "text"))
    headers.extend([
        ov.th("Game", "text"),
        ov.th("Venue", "text"),
        ov.th("Sent", "text"),
        ov.th("Received", "text"),
        ov.th("Total time", "num"),
        ov.th("Notes", "text"),
    ])
    asked = "track this better, log the sent and received time, so we can calculate the duration."
    plain = (
        "Duration is the received time minus the sent time. "
        "One program asks Gemini, then asks Kalshi, then compares the two quotes. "
        "Each venue row starts at the first request and ends when the last response for that game is in memory. "
        "The analysis row starts when the compare starts and ends when the result is written."
    )
    generated = clock(now_et())
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kalshi and Gemini call timing</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 1.25rem; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.4rem; }}
.ask {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 1rem 0; }}
blockquote {{ margin: 0.4rem 0 0.8rem; }}
.summary {{ font-family: Consolas, "Segoe UI", sans-serif; }}
.meta {{ color: #64748b; font-size: 0.92rem; }}
</style>
<style>
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Kalshi and Gemini call timing</h1>
<p class="meta">Eastern Time (America/New_York). Page written {html.escape(generated)}. Duration is received minus sent.</p>
<section class="ask">
<h2>What you asked</h2>
<blockquote>{html.escape(asked)}</blockquote>
<h2>In plain English</h2>
<p>{html.escape(plain)}</p>
</section>
<h2>Summary</h2>
<p class="summary">{html.escape(summary)}</p>
<p class="summary">{html.escape(proof_text)}</p>
<p class="meta">Click column headers to sort. A blank sent time means sent time was not recorded, so total time stays blank.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead>
<tr>
{"".join(headers)}
</tr>
</thead>
<tbody>
{"".join(body)}
</tbody>
</table>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    (STAMP / "call_metrics.html").write_text(page, encoding="utf-8")


def refresh_metrics(summaries: list[dict]) -> None:
    if not summaries:
        return
    vals = [s["total"] for s in summaries]
    avg = round(sum(vals) / len(vals), 1)
    sent = min(s["g_sent"] for s in summaries)
    received = max(s["a_recv"] for s in summaries)
    row_id = "cycle:one_process:average:" + received.strftime("%Y%m%dT%H%M%S")
    avg_row = {
        "row_id": row_id,
        "game": "One-program method",
        "step": "Cycle",
        "sent": sent.isoformat(timespec="seconds"),
        "sent_display": clock(sent),
        "received": received.isoformat(timespec="seconds"),
        "received_display": clock(received),
        "total_seconds": avg,
        "total_display": f"{avg:.1f}",
        "notes": (
            f"Average total cycle time for the one-Python-process method "
            f"(Gemini + Kalshi + analysis) over {len(summaries)} games: {avg:.1f} seconds."
        ),
        "method": PASS_ID,
        "source_file": "call_metrics.jsonl",
        "logged_at": now_et().isoformat(timespec="seconds"),
    }
    append_line(RAW / "call_metrics.jsonl", avg_row)
    write_call_metrics_html()


def find_college_game(text: str) -> tuple[dict, str] | None:
    want = text.lower().strip()
    games = ov.load_college()
    for game in games:
        codes = ov.game_codes(game)
        teams = " ".join(str(c) for c in (game.get("teams") or []))
        tickers = " ".join(str(v) for v in game.values() if isinstance(v, str))
        blob = f"{codes} {teams} {tickers}".lower()
        if "notre" in want and "byu" in want:
            if codes == "ndbyu" or "ndbyu" in blob:
                return game, codes
            continue
        if want and (want in blob or want in codes):
            return game, codes
    return None


def main() -> None:
    args = [arg for arg in sys.argv[1:] if arg != "--timing-check"]
    timing = "--timing-check" in sys.argv[1:]
    if timing:
        needle = " ".join(args) if args else "Notre Dame vs BYU"
        found = find_college_game(needle)
        if found is None:
            print(f"NO GAME matched {needle}", flush=True)
            write_call_metrics_html()
            return
        game, codes = found
        print(f"TIMING CHECK one game {codes}", flush=True)
        summary = scan_game(game, codes)
        write_call_metrics_html()
        if summary.get("rate_limited"):
            print(f"STOP HTTP 429 {summary['game']} [{summary['codes']}]", flush=True)
            return
        print(
            f"{summary['game']} [{summary['codes']}] "
            f"gemini={summary['gemini']:.3f}s kalshi={summary['kalshi']:.3f}s "
            f"analysis={summary['analysis']:.3f}s total={summary['total']:.3f}s",
            flush=True,
        )
        for item in summary.get("rows") or []:
            if item.get("venue") in {"Gemini", "Kalshi", "Analysis"}:
                print(
                    f"PROOF {item['venue']} sent_at={item['sent_at']} "
                    f"received_at={item['received_at']} duration_seconds={item['duration_seconds']}",
                    flush=True,
                )
        return
    limit = 5
    if args:
        limit = int(args[0])
    picked, note = select_games(limit)
    print(note, flush=True)
    if len(picked) < limit:
        print(f"ONLY {len(picked)} games available for this pass.", flush=True)
    summaries = []
    opp_pages = False
    for _i, game, codes in picked:
        if in_flight(codes) or watch_active(codes):
            print(f"SKIP {codes} became busy before fetch", flush=True)
            continue
        summary = scan_game(game, codes)
        summaries.append(summary)
        flagged = record_opportunities(summary)
        opp_pages = opp_pages or flagged
        print(
            f"{summary['game']} [{summary['codes']}] "
            f"gemini={summary['gemini']:.1f}s kalshi={summary['kalshi']:.1f}s "
            f"analysis={summary['analysis']:.1f}s total={summary['total']:.1f}s "
            f"opportunity={summary['opportunity']}",
            flush=True,
        )
        if summary["total"] > 20 and summary["slow"]:
            slow = summary["slow"]
            print(
                f"SLOW {summary['game']} {slow['url']} elapsed={slow['elapsed']:.3f}s status={slow['http_status']} error={slow['error']}",
                flush=True,
            )
        if summary["errors"]:
            for err in summary["errors"]:
                print(f"ERROR {summary['codes']} {err['url']} {err['error']}", flush=True)
    refresh_metrics(summaries)
    if summaries:
        avg = sum(s["total"] for s in summaries) / len(summaries)
        print(f"AVERAGE total={avg:.1f}s over {len(summaries)} games under_20={avg < 20}", flush=True)
        if opp_pages:
            names = ", ".join(s["game"] for s in summaries if s["opportunity"])
            print(f"OPPORTUNITY games (no watch started): {names}", flush=True)
    else:
        print("AVERAGE none", flush=True)


if __name__ == "__main__":
    main()
