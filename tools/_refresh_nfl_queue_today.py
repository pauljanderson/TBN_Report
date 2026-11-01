"""Refresh today's NFL (pro football) into sports_queue.json with spread siblings.

Hidden poller spawn only. Does not start a second live_strategy_b.py.
Does not sell. Does not kill D unless this file is run with --reload-d (not default).
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_game_pollers  # noqa: E402
import live_t0_yes  # noqa: E402
import prediction_job_control  # noqa: E402
import price_memory  # noqa: E402
import win_hidden  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW, ROOT as REPO  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 stockresearch-public-quote-scan/1.0", "Accept": "application/json"}
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
NFL_CODES = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAC", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN",
    "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS", "WSH",
}
ALIAS_TO_KALSHI = {"JAX": "JAC", "WSH": "WAS"}
ALIAS_TO_GEMINI = {"JAC": "JAX", "WSH": "WAS"}
QUEUE_PATH = RAW / "sports_queue.json"
PAGE_PATH = STAMP / "nfl_d_queue.html"
GEMINI_SLOTS = (
    "1700", "1715", "2000", "2005", "2015", "2020", "2025", "2030",
    "0000", "0015", "0020", "0030", "0115", "0120",
)


def now_et() -> datetime:
    return datetime.now(ET)


def http_json(url: str, timeout: int = 30) -> tuple[int, object | None]:
    req = urllib.request.Request(url, headers=UA, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return 0, None


def split_codes(suffix: str) -> list[str] | None:
    text = str(suffix or "").upper()

    def rec(chunk: str) -> list[str] | None:
        if not chunk:
            return []
        for n in (3, 2):
            if len(chunk) >= n and chunk[:n] in NFL_CODES:
                rest = rec(chunk[n:])
                if rest is not None:
                    return [chunk[:n]] + rest
        return None

    out = rec(text)
    if out and len(out) == 2:
        return out
    return None


def parse_kalshi_ticker(ticker: str) -> tuple[str, list[str]] | None:
    raw = str(ticker or "").upper()
    match = re.search(r"-(\d{2})([A-Z]{3})(\d{2})([A-Z]{2,})$", raw)
    if not match:
        return None
    yy, mon, dd, tail = match.groups()
    month = MONTHS.get(mon)
    if not month:
        return None
    try:
        date = datetime(2000 + int(yy), month, int(dd)).date().isoformat()
    except ValueError:
        return None
    codes = split_codes(tail)
    if not codes:
        return None
    return date, [ALIAS_TO_KALSHI.get(c, c) for c in codes]


def canon(code: str) -> str:
    return ALIAS_TO_KALSHI.get(str(code or "").upper(), str(code or "").upper())


def gemini_code(code: str) -> str:
    c = str(code or "").upper()
    return ALIAS_TO_GEMINI.get(c, c)


def pair_key(codes: list[str], date: str) -> tuple:
    return (date, tuple(sorted(canon(c) for c in codes)))


def kalshi_open(series: str) -> list[dict]:
    rows: list[dict] = []
    cursor = ""
    for _ in range(10):
        query = {
            "series_ticker": series,
            "status": "open",
            "limit": "200",
            "with_nested_markets": "true",
        }
        if cursor:
            query["cursor"] = cursor
        url = "https://api.elections.kalshi.com/trade-api/v2/events?" + urllib.parse.urlencode(query)
        status, payload = http_json(url)
        if status != 200 or not isinstance(payload, dict):
            break
        batch = payload.get("events") or []
        if not isinstance(batch, list):
            break
        for event in batch:
            if isinstance(event, dict):
                rows.append(event)
        cursor = str(payload.get("cursor") or "")
        if not batch or not cursor:
            break
    return rows


def espn_kickoffs(dates: list[str]) -> dict[tuple, datetime]:
    found: dict[tuple, datetime] = {}
    for day in dates:
        stamp = day.replace("-", "")
        url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={stamp}"
        status, payload = http_json(url)
        if status != 200 or not isinstance(payload, dict):
            continue
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            comps = event.get("competitions") or []
            if not comps or not isinstance(comps[0], dict):
                continue
            comp = comps[0]
            teams = []
            for row in comp.get("competitors") or []:
                if not isinstance(row, dict):
                    continue
                team = row.get("team") if isinstance(row.get("team"), dict) else {}
                abbr = canon(str(team.get("abbreviation") or ""))
                if abbr:
                    teams.append(abbr)
            if len(teams) != 2:
                continue
            raw = str(comp.get("date") or event.get("date") or "")
            when = price_memory.parse_time(raw)
            if when is None:
                continue
            date = when.astimezone(ET).date().isoformat()
            found[pair_key(teams, date)] = when
            # SNF after 8pm ET can list as next UTC calendar day on Gemini
            utc_date = when.astimezone(ZoneInfo("UTC")).date().isoformat()
            if utc_date != date:
                found[pair_key(teams, utc_date)] = when
    return found


def gemini_stamp(when: datetime) -> tuple[str, str]:
    utc = when.astimezone(ZoneInfo("UTC"))
    return utc.strftime("%y%m%d"), utc.strftime("%H%M")


def gemini_tickers(codes: list[str], when: datetime) -> dict[str, str]:
    day, hm = gemini_stamp(when)
    a, b = gemini_code(codes[0]), gemini_code(codes[1])
    stem = f"NFL-{day}{hm}-{a}-{b}"
    return {
        "moneyline": stem + "-M",
        "spread": stem + "-S",
        "total": stem + "-T",
        "team_total": stem + "-TT",
    }


def probe_gemini(codes: list[str], when: datetime | None, date: str) -> tuple[dict[str, str], datetime | None]:
    tries: list[datetime] = []
    if when is not None:
        tries.append(when)
        for delta in (-5, 5, 25, -25):
            tries.append(when + timedelta(minutes=delta))
    else:
        day = datetime.fromisoformat(date).date()
        for hm in ("1700", "2000", "2005", "2025", "0020"):
            hour, minute = int(hm[:2]), int(hm[2:])
            utc_day = day + timedelta(days=1) if hour < 6 else day
            utc = datetime(utc_day.year, utc_day.month, utc_day.day, hour, minute, tzinfo=ZoneInfo("UTC"))
            tries.append(utc.astimezone(ET))
    seen = set()
    for cand in tries:
        key = cand.astimezone(ZoneInfo("UTC")).strftime("%y%m%d%H%M")
        if key in seen:
            continue
        seen.add(key)
        tickers = gemini_tickers(codes, cand)
        status, payload = http_json(
            "https://api.gemini.com/v1/prediction-markets/events/"
            + urllib.parse.quote(tickers["spread"], safe="")
        )
        if status == 200 and isinstance(payload, dict) and (payload.get("contracts") or payload.get("title")):
            start = price_memory.parse_time(str(payload.get("startTime") or "")) or cand
            return tickers, start
        if when is not None and len(seen) >= 2:
            break
    if when is not None:
        return gemini_tickers(codes, when), when
    return {}, None


def market_clock(event: dict) -> datetime | None:
    for key in ("target_datetime", "strike_date", "expiration_time", "close_time"):
        when = price_memory.parse_time(str(event.get(key) or ""))
        if when is not None:
            return when
    for market in event.get("markets") or []:
        if not isinstance(market, dict):
            continue
        for key in ("expected_expiration_time", "close_time", "expiration_time", "latest_expiration_time"):
            when = price_memory.parse_time(str(market.get(key) or ""))
            if when is not None:
                return when
    return None


def build_matched(today: str) -> tuple[list[dict], dict]:
    game_events = kalshi_open("KXNFLGAME")
    spread_events = kalshi_open("KXNFLSPREAD")
    total_events = kalshi_open("KXNFLTOTAL")
    team_total_events = kalshi_open("KXNFLTEAMTOTAL")
    espn = espn_kickoffs([today, (datetime.fromisoformat(today).date() + timedelta(days=1)).isoformat()])
    by_key: dict[tuple, dict] = {}

    def ensure(event: dict, kind: str) -> dict | None:
        ticker = str(event.get("event_ticker") or event.get("ticker") or "")
        parsed = parse_kalshi_ticker(ticker)
        if parsed is None:
            return None
        date, codes = parsed
        key = pair_key(codes, date)
        row = by_key.get(key)
        if row is None:
            row = {
                "date": date,
                "codes": codes,
                "kalshi_codes": codes,
                "gemini_codes": [gemini_code(c) for c in codes],
                "league": "NFL",
                "title_kalshi": str(event.get("title") or ""),
                "title_gemini": "",
                "kalshi": {},
                "gemini": {},
            }
            by_key[key] = row
        if not row.get("title_kalshi"):
            row["title_kalshi"] = str(event.get("title") or "")
        row["kalshi"][kind] = ticker
        clock = market_clock(event)
        if clock is not None and not row.get("_clock"):
            row["_clock"] = clock.isoformat()
        return row

    for event in game_events:
        ensure(event, "game")
    for event in spread_events:
        ensure(event, "spread")
    for event in total_events:
        ensure(event, "total")
    for event in team_total_events:
        ensure(event, "team_total")

    stats = {
        "kalshi_game": len(game_events),
        "kalshi_spread": len(spread_events),
        "kalshi_total": len(total_events),
        "kalshi_team_total": len(team_total_events),
        "espn_kickoffs": len(espn),
        "gemini_confirmed": 0,
        "gemini_constructed": 0,
    }
    matched = []
    for key, row in sorted(by_key.items(), key=lambda item: (item[1]["date"], item[1]["codes"])):
        if row["date"] < today:
            continue
        if not row["kalshi"].get("spread") and row["kalshi"].get("game"):
            row["kalshi"]["spread"] = row["kalshi"]["game"].replace("KXNFLGAME", "KXNFLSPREAD", 1)
        if not row["kalshi"].get("total") and row["kalshi"].get("game"):
            row["kalshi"]["total"] = row["kalshi"]["game"].replace("KXNFLGAME", "KXNFLTOTAL", 1)
        if not row["kalshi"].get("team_total") and row["kalshi"].get("game"):
            row["kalshi"]["team_total"] = row["kalshi"]["game"].replace("KXNFLGAME", "KXNFLTEAMTOTAL", 1)
        clock = espn.get(key)
        if clock is None and row.get("_clock"):
            clock = price_memory.parse_time(str(row["_clock"]))
        gem, start = probe_gemini(row["codes"], clock, row["date"])
        if gem:
            row["gemini"] = gem
            if start is not None:
                row["listed_start"] = start.isoformat()
                row["startTime"] = start.isoformat()
                row["title_gemini"] = row.get("title_gemini") or row.get("title_kalshi") or ""
            if clock is not None and gemini_stamp(clock) == gemini_stamp(start or clock):
                stats["gemini_confirmed"] += 1
            else:
                stats["gemini_constructed"] += 1
        elif clock is not None:
            row["gemini"] = gemini_tickers(row["codes"], clock)
            row["listed_start"] = clock.isoformat()
            row["startTime"] = clock.isoformat()
            stats["gemini_constructed"] += 1
        row.pop("_clock", None)
        k, g = live_game_pollers.expand_sibling_tickers(
            [
                row["kalshi"].get("game"),
                row["kalshi"].get("spread"),
                row["kalshi"].get("total"),
                row["kalshi"].get("team_total"),
            ],
            [
                row["gemini"].get("moneyline"),
                row["gemini"].get("spread"),
                row["gemini"].get("total"),
                row["gemini"].get("team_total"),
            ],
            "pro football",
        )
        if "KXNFLSPREAD" not in " ".join(k):
            # keep explicit spread even if sibling expander missed a nonstandard ticker
            if row["kalshi"].get("spread"):
                k.append(row["kalshi"]["spread"])
        matched.append(row)
    stats["matched"] = len(matched)
    stats["with_spread"] = sum(1 for row in matched if (row.get("kalshi") or {}).get("spread") or (row.get("gemini") or {}).get("spread"))
    return matched, stats


def merge_queue(matched: list[dict]) -> dict:
    blob = {}
    if QUEUE_PATH.exists():
        try:
            blob = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = {}
    backup = QUEUE_PATH.with_suffix(".json.bak_20261025")
    if QUEUE_PATH.exists() and not backup.exists():
        backup.write_text(QUEUE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    sports = list(blob.get("sports") or [])
    found = False
    entry = {
        "sport": "pro football",
        "matched_count": len(matched),
        "unmatched_counts": {"kalshi_only": 0, "gemini_only": 0},
        "matched": matched,
    }
    for i, sport in enumerate(sports):
        if str(sport.get("sport") or "").lower() == "pro football":
            sports[i] = entry
            found = True
            break
    if not found:
        sports.insert(0, entry)
    blob["sports"] = sports
    blob["fetched_at"] = now_et().isoformat()
    blob["nfl_refresh_note"] = (
        "Pro football matched list refreshed for 2026-10-25 kickoffs with Kalshi "
        "KXNFLGAME/KXNFLSPREAD/KXNFLTOTAL/KXNFLTEAMTOTAL plus Gemini NFL-*-S/-T/-TT siblings."
    )
    tmp = QUEUE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    tmp.replace(QUEUE_PATH)
    return blob


def supervisor_pid() -> int:
    data = live_game_pollers.read_json(RAW / "live_supervisor.pid")
    try:
        return int(data.get("pid") or 0)
    except (TypeError, ValueError):
        return 0


def spawn_nfl_pollers(scan, matched: list[dict]) -> list[dict]:
    already = live_game_pollers.running_poller_pids()
    me = supervisor_pid() or 1
    moment = now_et()
    spawned = []
    hours = live_game_pollers.LIVE_HOURS.get("pro football", 3.5)
    for game in matched:
        start = live_game_pollers.listed_start("pro football", game, scan)
        if start is None:
            continue
        end = start + timedelta(hours=hours)
        if moment >= end:
            continue
        # Keep 4pm / SNF / MNF pollers up before listed start so T0 quotes exist.
        if moment < start - timedelta(hours=8):
            continue
        key = live_game_pollers.game_key("pro football", game, scan)
        if key in already and live_game_pollers.pid_alive(already[key]):
            spawned.append({"key": key, "pid": already[key], "title": live_game_pollers.fallback_title(game, scan), "start": start.isoformat(), "status": "already"})
            continue
        spec = {
            "key": key,
            "sport": "pro football",
            "game": game,
            "title": live_game_pollers.fallback_title(game, scan),
            "start": start.isoformat(),
            "live_until": end.isoformat(),
        }
        tracked = live_game_pollers.spawn(spec, me)
        spawned.append({
            "key": key,
            "pid": tracked.pid,
            "title": spec["title"],
            "start": spec["start"],
            "status": "spawned",
        })
    return spawned


def restart_scan_only() -> str:
    jobs = prediction_job_control.classify(prediction_job_control._ps_rows())
    pids = [row["pid"] for row in jobs.get("scan") or []]
    if pids:
        prediction_job_control._stop_pids(pids)
        deadline = time.time() + 15
        while time.time() < deadline:
            left = prediction_job_control.classify(prediction_job_control._ps_rows()).get("scan") or []
            if not left:
                break
            time.sleep(0.4)
    prediction_job_control._spawn(
        prediction_job_control.SCAN_SCRIPT,
        RAW / "overnight_scan.console.log",
        hidden=True,
    )
    time.sleep(1.2)
    jobs = prediction_job_control.classify(prediction_job_control._ps_rows())
    rows = jobs.get("scan") or []
    if rows:
        return f"restarted pid {rows[0]['pid']}"
    return "spawned, pid not listed yet"


def d_pid() -> str:
    jobs = prediction_job_control.classify(prediction_job_control._ps_rows())
    rows = jobs.get("spread_t0") or []
    if rows:
        return str(rows[0]["pid"])
    path = RAW / "spread_t0.pid.json"
    if not path.exists():
        path = RAW / "spread_t0_watch.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    return str(data.get("pid") or "down")


def write_html(matched: list[dict], stats: dict, spawned: list[dict], slate: list[dict], dpid: str, scan_note: str) -> None:
    def th(label: str, kind: str) -> str:
        return (
            f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
            f'role="columnheader" aria-sort="none">{html.escape(label)}'
            f'<span class="sort-ind"></span></th>'
        )

    rows = []
    for game in matched:
        kalshi = game.get("kalshi") or {}
        gem = game.get("gemini") or {}
        title = game.get("title_kalshi") or game.get("title_gemini") or " ".join(game.get("codes") or [])
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(game.get('date') or ''))}</td>"
            f"<td>{html.escape(str(title))}</td>"
            f"<td>{html.escape(str(game.get('listed_start') or ''))}</td>"
            f"<td>{html.escape(str(kalshi.get('spread') or ''))}</td>"
            f"<td>{html.escape(str(gem.get('spread') or ''))}</td>"
            f"<td>{html.escape(str(kalshi.get('game') or ''))}</td>"
            f"<td>{html.escape(str(gem.get('moneyline') or ''))}</td>"
            "</tr>"
        )
    poller_rows = []
    for row in spawned:
        poller_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('key') or ''))}</td>"
            f"<td>{html.escape(str(row.get('title') or ''))}</td>"
            f"<td>{html.escape(str(row.get('start') or ''))}</td>"
            f"<td>{html.escape(str(row.get('pid') or ''))}</td>"
            f"<td>{html.escape(str(row.get('status') or ''))}</td>"
            "</tr>"
        )
    slate_txt = "; ".join(
        f"{row.get('title')} @ {row.get('start')}" for row in slate
    ) or "none in the 15-minute T0 window yet"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFL spreads in D queue</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #475569; font-size: 0.95rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>NFL spreads in D queue</h1>
<p class="note">Pulled {html.escape(now_et().strftime("%Y-%m-%d %H:%M ET"))}.</p>
<div class="callout">
<h2>What you asked</h2>
<p>D T0 spreads is on, NFL is in the universe, max 4, open 0 — but sports_queue.json was frozen 2026-10-17. Zero NFL pollers today. Overnight scan looping old CFB. Refresh today's NFL with spread siblings and spawn hidden pollers so D can fire at remaining kickoffs.</p>
<h2>In plain English</h2>
<p>The saved Sunday-football list was a week old, so the T0 spread bot could not see today's games. This job rebuilt that list from Kalshi (who-wins, spread, and total books) and Gemini spread twins, started hidden quote helpers for those games, and left D pid {html.escape(dpid)} running. It did not place a sell. Trusted T0 is kickoff, with a few minutes of grace after.</p>
</div>
<p><strong>Today's NFL in catalog: yes.</strong> {stats.get("matched", 0)} games, {stats.get("with_spread", 0)} with a spread sibling. D pid {html.escape(dpid)} (not reloaded; it rereads the queue each tick). Catalog scan {html.escape(scan_note)}. NFL pollers {len(spawned)}.</p>
<p class="note">slate_near_t0 now: {html.escape(slate_txt)}</p>
<p class="note">Kalshi GAME {stats.get("kalshi_game")} / SPREAD {stats.get("kalshi_spread")} / TOTAL {stats.get("kalshi_total")}. ESPN kickoffs {stats.get("espn_kickoffs")}. Gemini confirmed {stats.get("gemini_confirmed")}, constructed {stats.get("gemini_constructed")}.</p>
<h2>Matched NFL games</h2>
{SWIPE_NOTE_HTML}
<p class="note">Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>{th("Date", "date")}{th("Game", "text")}{th("Listed start", "date")}{th("Kalshi spread", "text")}{th("Gemini spread", "text")}{th("Kalshi ML", "text")}{th("Gemini ML", "text")}</tr></thead>
<tbody>
{''.join(rows) or '<tr><td colspan="7">No NFL games matched.</td></tr>'}
</tbody>
</table></div>
<h2>NFL pollers</h2>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable">
<thead><tr>{th("Key", "text")}{th("Game", "text")}{th("Start", "date")}{th("PID", "num")}{th("Status", "text")}</tr></thead>
<tbody>
{''.join(poller_rows) or '<tr><td colspan="5">No NFL pollers spawned.</td></tr>'}
</tbody>
</table></div>
<p class="note">Sources: Kalshi GET /trade-api/v2/events series KXNFLGAME, KXNFLSPREAD, KXNFLTOTAL; Gemini GET /v1/prediction-markets/events/{{ticker}}; ESPN scoreboard for kickoff clock; local sports_queue.json. Code: live_game_pollers.py, live_t0_yes.slate_near_t0, overnight_scan.load_sports. Did not start a second live_strategy_b.py. Did not sell. Hidden CREATE_NO_WINDOW spawn only.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    page = inject_report_page_extras(page)
    tmp = PAGE_PATH.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE_PATH)


def main() -> int:
    today = now_et().date().isoformat()
    print(f"refresh NFL queue {today}", flush=True)
    matched, stats = build_matched(today)
    print(json.dumps(stats, default=str), flush=True)
    merge_queue(matched)
    scan = live_game_pollers.load_scan()
    spawned = spawn_nfl_pollers(scan, matched)
    print(f"pollers {len(spawned)}", flush=True)
    slate = live_t0_yes.slate_near_t0(scan, "spread_t0")
    nfl_slate = [row for row in slate if str(row.get("sport") or "").lower() == "pro football"]
    print(f"slate nfl {len(nfl_slate)} / all {len(slate)}", flush=True)
    scan_note = restart_scan_only()
    dpid = d_pid()
    write_html(matched, stats, spawned, nfl_slate, dpid, scan_note)
    snap = prediction_job_control.snapshot()
    prediction_job_control.write_page(snap)
    summary = {
        "today": today,
        "nfl_in_catalog": bool(matched),
        "games": len(matched),
        "spreads": stats.get("with_spread"),
        "d_pid": dpid,
        "nfl_pollers": len(spawned),
        "slate_nfl": [
            {"title": row.get("title"), "start": row.get("start")} for row in nfl_slate
        ],
        "scan": scan_note,
        "sample": [
            {
                "date": g.get("date"),
                "title": g.get("title_kalshi"),
                "kalshi_spread": (g.get("kalshi") or {}).get("spread"),
                "gemini_spread": (g.get("gemini") or {}).get("spread"),
                "listed_start": g.get("listed_start"),
            }
            for g in matched[:8]
        ],
    }
    print(json.dumps(summary, indent=2, default=str), flush=True)
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
