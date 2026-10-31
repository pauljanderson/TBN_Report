"""Resumable Kalshi through-game 1-min yes_ask path pull.

Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not leftover-GTC A.
Does not DailyRun. Does not retune live B/C/D/E. Does not rewrite dashboard.html.
Does not start a leftover T0 candle pull. Does not overwrite T0 jsonl.
Stores the in-play path (not one T0 bar). Resume-safe.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import _pull_pm_hist_t0_20261028 as t0pull  # noqa: E402
from prediction_paths import LOCAL_STAMP  # noqa: E402
import _write_sport_league_t0_decile_20261027 as decile_w  # noqa: E402

HIST = LOCAL_STAMP / "hist"
INPLAY = HIST / "kalshi" / "inplay"
STATUS = HIST / "inplay_status.json"
LOG = HIST / "inplay_pull.log"
BOOKS = HIST / "books_kalshi.json"
CUTOFF_TS = int(t0pull.CUTOFF.timestamp())
SLEEP = 0.12
WORKERS = 2
CHUNK_SEC = 3600
MIN_POST = 5
COMBO_5425 = {
    "sport": "tennis",
    "kind": "moneyline",
    "decile": "90-99",
    "league": "ALL",
    "label": "tennis ALL Moneyline 90-99",
}
SERIES_PRIORITY = (
    "KXATPMATCH", "KXWTAMATCH",
    "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH",
    "KXITFMATCH", "KXITFWMATCH", "KXCHALLENGERMATCH",
    "KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL",
    "KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL",
    "KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL",
    "KXNHLGAME", "KXNHLSPREAD", "KXNHLTOTAL",
    "KXMLBGAME", "KXMLBSPREAD", "KXMLBTOTAL",
    "KXWNBAGAME", "KXWNBASPREAD", "KXWNBATOTAL",
    "KXEPLGAME", "KXEPLSPREAD", "KXEPLTOTAL",
    "KXMLSGAME", "KXMLSSPREAD", "KXMLSTOTAL",
    "KXUCLGAME", "KXUCLSPREAD", "KXUCLTOTAL",
    "KXBUNDESLIGAGAME", "KXBUNDESLIGASPREAD", "KXBUNDESLIGATOTAL",
    "KXSERIEAGAME", "KXSERIEASPREAD", "KXSERIEATOTAL",
    "KXLALIGAGAME", "KXLALIGASPREAD", "KXLALIGATOTAL",
    "KXLIGUE1GAME", "KXLIGUE1SPREAD", "KXLIGUE1TOTAL",
    "KXUFCFIGHT", "KXMMAFIGHT",
)
DURATION_SEC = {
    "tennis": 6 * 3600,
    "pro football": int(4.5 * 3600),
    "college football": int(4.5 * 3600),
    "football": int(4.5 * 3600),
    "basketball": int(3.5 * 3600),
    "hockey": int(3.5 * 3600),
    "baseball": 4 * 3600,
    "soccer": int(2.5 * 3600),
    "mma": int(1.5 * 3600),
    "golf": 6 * 3600,
}
_LOCK = threading.Lock()
_STATUS_LOCK = threading.Lock()


def _out(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with LOG.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        pass


def series_from_ticker(ticker: str) -> str:
    u = (ticker or "").upper()
    known = sorted(set(SERIES_PRIORITY) | set(t0pull.PRIORITY_TICKER), key=len, reverse=True)
    for series in known:
        if u == series or u.startswith(series + "-"):
            return series
    return u.split("-")[0] if u else ""


def chunk_windows(start_ts: int, end_ts: int, chunk_sec: int = CHUNK_SEC) -> list[tuple[int, int]]:
    if end_ts <= start_ts:
        return [(int(start_ts), int(start_ts) + 60)]
    out = []
    cur = int(start_ts)
    stop = int(end_ts)
    while cur < stop:
        nxt = min(cur + int(chunk_sec), stop)
        out.append((cur, nxt))
        cur = nxt
    return out


def path_from_candles(candles: list) -> list[list]:
    """Keep every yes_ask.close bar, not just the last T0 close."""
    best: dict[int, float] = {}
    for candle in candles or []:
        if not isinstance(candle, dict):
            continue
        try:
            ts = int(candle.get("end_period_ts"))
        except (TypeError, ValueError):
            continue
        px = t0pull._px_float(candle.get("yes_ask"))
        if px is None:
            continue
        if px < 0 or px > 1:
            continue
        best[ts] = float(px)
    return [[ts, best[ts]] for ts in sorted(best)]


def n_post(path: list, t0_ts: int) -> int:
    t0 = int(t0_ts or 0)
    n = 0
    for ts, px in path or []:
        if int(ts) <= t0:
            continue
        if 0.0 < float(px) < 1.0:
            n += 1
    return n


def path_usable(path: list, t0_ts: int, min_post: int = MIN_POST) -> bool:
    return n_post(path, t0_ts) >= int(min_post)


def t0_px(book: dict) -> float | None:
    px = book.get("t0_fav")
    if px is None:
        px = book.get("t0_a")
    try:
        return float(px)
    except (TypeError, ValueError):
        return None


def is_combo_5425(book: dict) -> bool:
    sport = str(book.get("sport") or "").lower()
    kind = str(book.get("kind") or "").lower()
    band = decile_w.decile_of(t0_px(book))
    return sport == "tennis" and kind == "moneyline" and band == "90-99"


def skip_extreme_t0(book: dict) -> bool:
    """1.00 / 0.00 T0 has no +G sell and often no 1-min path (hourly settle close)."""
    px = t0_px(book)
    if px is None:
        return True
    return px <= 0.005 or px >= 0.995


def is_live_endpoint(book: dict) -> bool:
    try:
        return int(book.get("t0_ts") or 0) >= CUTOFF_TS
    except (TypeError, ValueError):
        return False


def priority_tuple(book: dict) -> tuple:
    ticker = str(book.get("ticker") or "")
    series = series_from_ticker(ticker)
    try:
        series_i = SERIES_PRIORITY.index(series)
    except ValueError:
        series_i = 80 + (0 if str(book.get("sport") or "").lower() == "tennis" else 40)
    combo = 0 if is_combo_5425(book) else 1
    tennis = 0 if str(book.get("sport") or "").lower() == "tennis" else 1
    ml = 0 if str(book.get("kind") or "") == "moneyline" else 1
    live = 0 if is_live_endpoint(book) else 1
    return (live, tennis, ml, combo, series_i, ticker)


def candle_url(series: str, ticker: str, start_ts: int, end_ts: int, *, hist: bool, interval: int = 1) -> str:
    q = urllib.parse.urlencode({
        "start_ts": int(start_ts),
        "end_ts": int(end_ts),
        "period_interval": int(interval),
        "include_latest_before_start": "true",
    })
    tok = urllib.parse.quote(ticker)
    if hist:
        return f"{t0pull.KBASE}/historical/markets/{tok}/candlesticks?{q}"
    return (
        f"{t0pull.KBASE}/series/{urllib.parse.quote(series)}/markets/{tok}/candlesticks?{q}"
    )


def fetch_candles(series: str, ticker: str, start_ts: int, end_ts: int, *, hist: bool) -> tuple[int, list]:
    url = candle_url(series, ticker, start_ts, end_ts, hist=hist, interval=1)
    delay = 1.5
    for attempt in range(6):
        time.sleep(SLEEP)
        code, body = t0pull.http(url)
        if code == 429 and attempt < 5:
            time.sleep(delay)
            delay = min(delay * 2, 40)
            continue
        candles = []
        if isinstance(body, dict):
            candles = body.get("candlesticks") or []
        if not isinstance(candles, list):
            candles = []
        return int(code), candles
    return 429, []


def merge_path(parts: list[list[list]]) -> list[list]:
    best: dict[int, float] = {}
    for part in parts:
        for ts, px in part or []:
            best[int(ts)] = float(px)
    return [[ts, best[ts]] for ts in sorted(best)]


def fetch_path(series: str, ticker: str, t0_ts: int, end_ts: int) -> dict:
    use_hist = int(t0_ts) < CUTOFF_TS
    start = int(t0_ts) - 45 * 60
    stop = max(int(end_ts), int(t0_ts) + 90)
    # Live (post 2026-08-29): one through-game 1-min window (DAL-PHI T0 + tennis HURRUN).
    if not use_hist:
        http_last, candles = fetch_candles(series, ticker, start, stop, hist=False)
        path = path_from_candles(candles)
        return {
            "http": http_last,
            "endpoint": "live",
            "n_candles": len(candles),
            "path": path,
            "chunked": False,
        }
    # Historical: 90-min slices (API caps ~72 1-min bars). Empty first slice → stop.
    windows = chunk_windows(start, min(stop, start + 90 * 60), 90 * 60)
    rest = chunk_windows(start + 90 * 60, stop, 90 * 60) if stop > start + 90 * 60 else []
    parts: list[list[list]] = []
    n_candles = 0
    http_last = 0
    endpoint = "historical"
    for i, (a, b) in enumerate(windows + rest):
        http_last, candles = fetch_candles(series, ticker, a, b, hist=True)
        n_candles += len(candles)
        part = path_from_candles(candles)
        parts.append(part)
        if i == 0 and not part:
            break
        if not part:
            break
    path = merge_path(parts)
    return {
        "http": http_last,
        "endpoint": endpoint,
        "n_candles": n_candles,
        "path": path,
        "chunked": True,
    }


def duration_for(book: dict) -> int:
    sport = str(book.get("sport") or "").lower()
    return int(DURATION_SEC.get(sport, 4 * 3600))


def load_done(series: str) -> dict:
    path = INPLAY / f"{series}.jsonl"
    return t0pull.load_jsonl_map(path, "ticker")


def write_row(series: str, row: dict) -> None:
    t0pull.append_jsonl(INPLAY / f"{series}.jsonl", row)


def empty_status() -> dict:
    return {
        "written_at": "",
        "pid": os.getpid(),
        "running": False,
        "cmd": "python -u tools/_pull_kalshi_inplay_path_20261030.py",
        "combo_5425": COMBO_5425["label"],
        "n_target": 0,
        "n_done": 0,
        "n_with_path": 0,
        "n_usable": 0,
        "n_target_5425": 0,
        "n_done_5425": 0,
        "n_usable_5425": 0,
        "n_usable_tennis": 0,
        "current_series": "",
        "note": (
            "Kalshi 1-min yes_ask through-game pull. Not a leftover T0 pull. "
            "Not a full hist gain study until usable paths exist."
        ),
        "poly_note": (
            "Polymarket CLOB prices-history can return through-game last-trade; "
            "that is not Yes-ask and is not mixed into this Kalshi book. Not started."
        ),
    }


def write_status(rec: dict) -> None:
    rec = dict(rec)
    rec["written_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    rec["pid"] = os.getpid()
    with _STATUS_LOCK:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATUS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        tmp.replace(STATUS)


def read_status() -> dict:
    if not STATUS.is_file():
        return empty_status()
    try:
        rec = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_status()
    if not isinstance(rec, dict):
        return empty_status()
    out = empty_status()
    out.update(rec)
    return out


def census_inplay() -> dict:
    n_done = n_with = n_usable = n_u5425 = n_u_ten = n_d5425 = 0
    by_series: dict[str, dict] = defaultdict(lambda: {"n": 0, "usable": 0})
    if INPLAY.is_dir():
        for path in sorted(INPLAY.glob("*.jsonl")):
            series = path.stem
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        rec = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    n_done += 1
                    by_series[series]["n"] += 1
                    path_bars = rec.get("path") or []
                    if path_bars:
                        n_with += 1
                    t0_ts = int(rec.get("t0_ts") or 0)
                    usable = path_usable(path_bars, t0_ts)
                    if usable:
                        n_usable += 1
                        by_series[series]["usable"] += 1
                    if rec.get("combo_5425"):
                        n_d5425 += 1
                        if usable:
                            n_u5425 += 1
                    if str(rec.get("sport") or "").lower() == "tennis" and usable:
                        n_u_ten += 1
    st = read_status()
    st.update({
        "n_done": n_done,
        "n_with_path": n_with,
        "n_usable": n_usable,
        "n_done_5425": n_d5425 or st.get("n_done_5425") or 0,
        "n_usable_5425": n_u5425,
        "n_usable_tennis": n_u_ten,
        "by_series": {k: dict(v) for k, v in sorted(by_series.items())},
    })
    return st


def load_work() -> list[dict]:
    sides = decile_w.load_json_list(BOOKS)
    bags: dict[str, dict] = {}
    n_extreme = 0
    for book in sides:
        ticker = str(book.get("ticker") or "")
        if not ticker or book.get("void"):
            continue
        if skip_extreme_t0(book):
            n_extreme += 1
            continue
        if ticker in bags:
            continue
        bags[ticker] = book
    _out(f"worklist unique mid-price tickers={len(bags)} skipped_extreme_t0={n_extreme}")
    return list(bags.values())


def pull_one(book: dict) -> dict:
    ticker = str(book["ticker"])
    series = series_from_ticker(ticker)
    t0_ts = int(book.get("t0_ts") or 0)
    end_ts = t0_ts + duration_for(book)
    got = fetch_path(series, ticker, t0_ts, end_ts)
    path = got.get("path") or []
    rec = {
        "ticker": ticker,
        "series": series,
        "event_ticker": book.get("game") or book.get("game_n") or "",
        "sport": book.get("sport") or "",
        "league": book.get("league") or "",
        "kind": book.get("kind") or "",
        "t0_ts": t0_ts,
        "end_ts": end_ts,
        "t0_a": book.get("t0_a") or book.get("t0_fav"),
        "decile": decile_w.decile_of(book.get("t0_fav") or book.get("t0_a")),
        "combo_5425": is_combo_5425(book),
        "http": got.get("http"),
        "endpoint": got.get("endpoint"),
        "n_candles": got.get("n_candles") or 0,
        "n_post": n_post(path, t0_ts),
        "path": path,
        "price_kind": "yes_ask.close",
        "chunked": bool(got.get("chunked")),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    write_row(series, rec)
    return rec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kalshi through-game yes_ask path pull")
    parser.add_argument("--status-only", action="store_true")
    parser.add_argument("--max", type=int, default=0, help="cap new tickers this run")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args(argv)
    if args.status_only:
        st = census_inplay()
        print(json.dumps({k: st.get(k) for k in (
            "n_target", "n_done", "n_usable", "n_usable_5425", "n_usable_tennis",
            "combo_5425", "running", "pid",
        )}, indent=2))
        return 0

    INPLAY.mkdir(parents=True, exist_ok=True)
    _out("loading books_kalshi.json worklist")
    work = load_work()
    work.sort(key=priority_tuple)
    n_target = len(work)
    n_target_5425 = sum(1 for b in work if is_combo_5425(b))
    done_by_series: dict[str, dict] = {}

    def already(ticker: str, series: str) -> bool:
        if series not in done_by_series:
            done_by_series[series] = load_done(series)
        rec = done_by_series[series].get(ticker)
        # Resume: skip any ticker we already fetched (empty or usable).
        return rec is not None

    pending = []
    n_skip = 0
    for book in work:
        ticker = str(book["ticker"])
        series = series_from_ticker(ticker)
        if already(ticker, series):
            n_skip += 1
            continue
        pending.append(book)
    if args.max and args.max > 0:
        pending = pending[: args.max]
    st = empty_status()
    st.update({
        "running": True,
        "n_target": n_target,
        "n_target_5425": n_target_5425,
        "n_skip_resume": n_skip,
        "n_pending": len(pending),
        "workers": int(args.workers),
    })
    cen = census_inplay()
    st["n_done"] = cen.get("n_done") or 0
    st["n_usable"] = cen.get("n_usable") or 0
    st["n_usable_5425"] = cen.get("n_usable_5425") or 0
    st["n_usable_tennis"] = cen.get("n_usable_tennis") or 0
    write_status(st)
    _out(
        f"target={n_target} combo5425={n_target_5425} resume_skip={n_skip} "
        f"pending={len(pending)} pid={os.getpid()}"
    )
    workers = max(1, int(args.workers))
    n_new = 0
    n_ok = 0
    n_ok_5425 = 0

    def bump(rec: dict) -> None:
        nonlocal n_new, n_ok, n_ok_5425
        n_new += 1
        usable = path_usable(rec.get("path") or [], rec.get("t0_ts") or 0)
        if usable:
            n_ok += 1
            if rec.get("combo_5425"):
                n_ok_5425 += 1
        if n_new % 25 == 0 or n_new <= 3:
            st2 = read_status()
            st2.update({
                "running": True,
                "n_target": n_target,
                "n_target_5425": n_target_5425,
                "n_new_this_run": n_new,
                "n_usable_this_run": n_ok,
                "n_usable_5425_this_run": n_ok_5425,
                "current_series": rec.get("series") or "",
                "last_ticker": rec.get("ticker") or "",
                "last_n_post": rec.get("n_post") or 0,
            })
            cen2 = census_inplay()
            st2["n_done"] = cen2.get("n_done") or st2.get("n_done")
            st2["n_usable"] = cen2.get("n_usable") or 0
            st2["n_usable_5425"] = cen2.get("n_usable_5425") or 0
            st2["n_usable_tennis"] = cen2.get("n_usable_tennis") or 0
            write_status(st2)
            _out(
                f"new={n_new} usable_run={n_ok} last={rec.get('ticker')} "
                f"n_post={rec.get('n_post')} usable_disk={st2.get('n_usable')}"
            )

    if workers == 1:
        for book in pending:
            try:
                rec = pull_one(book)
            except Exception as exc:
                _out(f"ERR {book.get('ticker')} {type(exc).__name__}: {exc}")
                continue
            bump(rec)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(pull_one, book): book for book in pending}
            for fut in as_completed(futs):
                book = futs[fut]
                try:
                    rec = fut.result()
                except Exception as exc:
                    _out(f"ERR {book.get('ticker')} {type(exc).__name__}: {exc}")
                    continue
                bump(rec)

    st = census_inplay()
    st["running"] = False
    st["n_target"] = n_target
    st["n_target_5425"] = n_target_5425
    st["n_new_this_run"] = n_new
    write_status(st)
    _out(f"done new={n_new} usable={st.get('n_usable')} combo5425_usable={st.get('n_usable_5425')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
