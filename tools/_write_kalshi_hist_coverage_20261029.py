"""Kalshi hist coverage vs live C/D/E — 29 Oct 2026.

Does not place, cancel, or sell. Does not start a second B. Does not bump
stake, leftover-GTC on A, D NFL, or retune C/D/E bands or B dip 0.25 / cap 1.05.
Does not restart a hist pull. Inventory + report only.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP, LOCAL_STAMP, RAW_DIR as RAW

try:
    from compare_format import format_money
except Exception:  # pragma: no cover
    def format_money(value, *, blank="—"):
        if value is None:
            return blank
        n = float(value)
        sign = "-" if n < 0 else ""
        return f"{sign}${abs(n):,.2f}"

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "kalshi_hist_coverage_20261029.html"
DECILE_HTML = STAMP / "sport_league_t0_decile_20261027.html"
DECILE_JSON = STAMP / "sport_league_t0_decile_20261027.json"
CDE_HTML = STAMP / "cde_band_decile_20261029.html"
HIST = LOCAL_STAMP / "hist"
KDIR = HIST / "kalshi"
PDIR = HIST / "poly"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/kalshi_hist_coverage_20261029.html"
)
DECILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/sport_league_t0_decile_20261027.html"
)

ASKED = (
    "Kalshi doesn't support the college football favorite system at all, but I feel "
    "like we are still collecting data, aren't we? CFB 50-99 deciles seem lite. "
    "System D: Kalshi doesn't support any system on spreads. These are the only "
    "winners but very little data: soccer ALL Spread 10-19 N=2; basketball ALL "
    "Spread 80-89 N=1; baseball ALL Spread 80-89 N=1; basketball ALL Spread 20-29 "
    "N=4. The only winners for system E with any kind of data: hockey ALL Moneyline "
    "50-59 N=21; soccer ALL Moneyline 10-19 N=15; pro football ALL Moneyline 10-19 "
    "N=41; baseball ALL Moneyline 90-99 N=2211. But I think we are out of season "
    "for all these sports. Is Kalshi history done?"
)
PLAIN = (
    "Kalshi history is the old Yes-ask tape we candle from Kalshi’s own kickoff "
    "clock. Live C, D, and E are a different kitchen: they look at Kalshi, Gemini, "
    "Polymarket, and Novig at game start and send one contract. College football "
    "favorite (C) is who wins the game, priced 51–89 cents. D is favorite-to-cover "
    "spreads (does the team beat the point line), not NFL, not the over/under. "
    "E is tennis underdogs 11–49 cents only — hockey, soccer, football, and baseball "
    "cells on the sport sheet are not system E. This page answers whether the Kalshi "
    "history pull finished, why CFB 50–99 looks thin on that sheet, and which "
    "platforms are still collecting live C/D/E. We did not restart the history pull "
    "and did not change any live band."
)

PRIORITY = (
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
    "KXPGARYDERMATCH", "KXPRESCUPMATCH", "KXTGLMATCH",
    "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH", "KXITFMATCH", "KXITFWMATCH",
)
HOLES_LISTED = (
    "KXSERIEASPREAD", "KXSERIEATOTAL",
    "KXLALIGAGAME", "KXLALIGASPREAD", "KXLALIGATOTAL",
    "KXLIGUE1GAME", "KXLIGUE1SPREAD", "KXLIGUE1TOTAL",
    "KXUFCFIGHT",
    "KXMLSSPREAD", "KXMLSTOTAL",
    "KXATPMATCH", "KXWTAMATCH",
    "KXUCLSPREAD", "KXEPLTOTAL", "KXEPLSPREAD", "KXBUNDESLIGATOTAL",
    "KXUCLGAME", "KXEPLGAME", "KXBUNDESLIGA",
)
POLY_KEYS = (
    "nfl", "cfb", "nba", "nhl", "mlb", "wnba", "atp", "wta",
    "ufc", "pga", "epl", "mls", "ucl", "ncaab",
)
DECADES = (
    "0-9", "10-19", "20-29", "30-39", "40-49",
    "50-59", "60-69", "70-79", "80-89", "90-99",
)
PAUL_D = (
    ("soccer", "ALL", "Spread", "10-19", 2, 1),
    ("basketball", "ALL", "Spread", "80-89", 1, 1),
    ("baseball", "ALL", "Spread", "80-89", 1, 1),
    ("basketball", "ALL", "Spread", "20-29", 4, 1),
)
PAUL_E = (
    ("hockey", "ALL", "Moneyline", "50-59", 21, 13, 21, 1.81, 0.09),
    ("soccer", "ALL", "Moneyline", "10-19", 15, 3, 15, 0.49, 0.03),
    ("pro football", "ALL", "Moneyline", "10-19", 41, 7, 41, 0.62, 0.02),
    ("baseball", "ALL", "Moneyline", "90-99", 2211, 1067, 1, 0.01, 0.01),
)


def esc(value) -> str:
    return html_mod.escape(str(value if value is not None else ""), quote=True)


def now_et() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


def mtime_et(path: Path) -> str:
    if not path.is_file():
        return "—"
    ts = datetime.fromtimestamp(path.stat().st_mtime, ET)
    return ts.strftime("%Y-%m-%d %H:%M ET")


def line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for _ in fh:
            n += 1
    return n


def load_json(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def decile_of(px) -> str | None:
    if px is None:
        return None
    try:
        x = float(px)
    except (TypeError, ValueError):
        return None
    if x < 0:
        return None
    if x >= 0.90:
        return "90-99"
    bucket = min(int(x * 10), 8)
    return DECADES[bucket]


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], *, total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    if total:
        body.append('<tr class="total-row">' + "".join(f"<td>{cell}</td>" for cell in total) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h2 = ""
        self.h3 = ""
        self.in_h2 = False
        self.in_h3 = False
        self.in_cell = False
        self.capture = False
        self.buf = ""
        self.row: list[str] = []
        self.cur_table: list[list[str]] = []
        self.tables: list[tuple[str, str, list[list[str]]]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.in_h2 = True
            self.buf = ""
        elif tag == "h3":
            self.in_h3 = True
            self.buf = ""
        elif tag == "table":
            self.cur_table = []
            self.capture = True
        elif tag in {"td", "th"} and self.capture:
            self.in_cell = True
            self.buf = ""

    def handle_endtag(self, tag):
        if tag == "h2":
            self.in_h2 = False
            self.h2 = " ".join(self.buf.split()).strip()
        elif tag == "h3":
            self.in_h3 = False
            self.h3 = " ".join(self.buf.split()).strip()
        elif tag in {"td", "th"} and self.capture:
            self.row.append(" ".join(self.buf.split()).strip())
            self.in_cell = False
        elif tag == "tr" and self.capture:
            if self.row:
                self.cur_table.append(self.row)
            self.row = []
        elif tag == "table" and self.capture:
            self.tables.append((self.h2, self.h3, self.cur_table))
            self.capture = False

    def handle_data(self, data):
        if self.in_h2 or self.in_h3 or self.in_cell:
            self.buf += data


def _parse_int(text: str) -> int:
    t = (text or "").replace(",", "").strip()
    if not t or t in {"—", "-"}:
        return 0
    try:
        return int(float(t))
    except ValueError:
        return 0


def _parse_pnl(text):
    t = (text or "").replace(",", "").replace("−", "-").replace("$", "").strip()
    if t in {"", "—", "-"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_hist_cells(html_text: str) -> dict:
    parser = TableParser()
    parser.feed(html_text)
    out = {}
    for h2, _h3, tbl in parser.tables:
        if "Kalshi historical" not in h2 or not tbl:
            continue
        hdr = tbl[0]
        if "Decile" not in hdr or "Sport" not in hdr:
            continue
        idx = {name: i for i, name in enumerate(hdr)}
        for row in tbl[1:]:
            if len(row) <= idx.get("With-fee P&L", 8):
                continue
            sport = row[idx["Sport"]]
            league = row[idx["League"]]
            kind = row[idx["Bet type"]]
            dec = row[idx["Decile"]]
            out[f"{sport}|{league}|{kind}|{dec}"] = {
                "n": _parse_int(row[idx["N settled"]]),
                "n_win": _parse_int(row[idx["Wins"]]),
                "n_fee": _parse_int(row[idx["N with fee"]]),
                "pnl_sum": _parse_pnl(row[idx["With-fee P&L"]]),
                "avg": _parse_pnl(row[idx.get("Avg P&L", 9)] if "Avg P&L" in idx else ""),
            }
    return out


def parse_live_cells(html_text: str) -> dict:
    parser = TableParser()
    parser.feed(html_text)
    out = {}
    for h2, _h3, tbl in parser.tables:
        if "11-day four-platform" not in h2 and "Book 1" not in h2 and "live tape" not in h2.lower():
            if h2 and "Kalshi historical" in h2:
                continue
            if "Named-Yes T0" not in h2 and "sport / league" not in h2.lower() and "Live tape" not in h2:
                continue
        if not tbl:
            continue
        hdr = tbl[0]
        if "Decile" not in hdr or "Sport" not in hdr:
            continue
        if "Kalshi historical" in h2:
            continue
        idx = {name: i for i, name in enumerate(hdr)}
        if "N settled" not in idx or "Wins" not in idx:
            continue
        for row in tbl[1:]:
            if len(row) <= idx.get("N settled", 4):
                continue
            key = "|".join([
                row[idx["Sport"]], row[idx["League"]],
                row[idx["Bet type"]], row[idx["Decile"]],
            ])
            out[key] = {
                "n": _parse_int(row[idx["N settled"]]),
                "n_win": _parse_int(row[idx["Wins"]]),
                "n_fee": _parse_int(row[idx.get("N with fee", 0)]) if "N with fee" in idx else 0,
                "pnl_sum": _parse_pnl(row[idx["With-fee P&L"]]) if "With-fee P&L" in idx else None,
            }
    return out


def inventory_kalshi() -> dict:
    t0_dir = KDIR / "t0"
    ev_dir = KDIR / "events"
    t0_files = {p.stem: p for p in t0_dir.glob("*.jsonl")} if t0_dir.is_dir() else {}
    ev_files = {p.stem: p for p in ev_dir.glob("*.jsonl")} if ev_dir.is_dir() else {}
    coverage = load_json(HIST / "coverage.json") or []
    cov_by = {}
    for row in coverage:
        if row.get("platform") == "kalshi" and row.get("series"):
            cov_by[str(row["series"])] = row
    rows = []
    for ticker in PRIORITY:
        t0p = t0_files.get(ticker)
        evp = ev_files.get(ticker)
        cov = cov_by.get(ticker) or {}
        n_t0 = line_count(t0p) if t0p else 0
        n_ev = line_count(evp) if evp else 0
        if t0p and n_t0 > 0:
            status = "t0 candled"
        elif evp and n_ev > 0:
            status = "events only (no T0 candles)"
        else:
            status = "missing"
        if ticker == "KXUFCFIGHT" and n_t0 > 0:
            # pull.log stopped mid-candle around t0=350 of ~776 events
            if n_t0 < 1400:
                status = "t0 partial (UFC pull interrupted)"
        if ticker == "KXLIGUE1SPREAD" and n_t0 > 0 and n_t0 < 400:
            status = "t0 in progress"
        rows.append({
            "series": ticker,
            "kind": (
                "spread" if ticker.endswith("SPREAD")
                else "total" if ticker.endswith("TOTAL")
                else "moneyline"
            ),
            "status": status,
            "n_t0": n_t0,
            "n_events_file": n_ev,
            "cov_t0": cov.get("n_t0"),
            "cov_miss": cov.get("n_missing"),
            "cov_fetched": cov.get("candles_fetched"),
            "span": f"{cov.get('span_lo') or '—'} .. {cov.get('span_hi') or '—'}",
            "t0_mtime": mtime_et(t0p) if t0p else "—",
            "ev_mtime": mtime_et(evp) if evp else "—",
        })
    extra_t0 = sorted(set(t0_files) - set(PRIORITY))
    extra_ev = sorted(set(ev_files) - set(PRIORITY) - set(t0_files))
    return {
        "rows": rows,
        "extra_t0": extra_t0,
        "extra_ev": extra_ev,
        "coverage_n": len(coverage),
        "coverage_mtime": mtime_et(HIST / "coverage.json"),
        "books_k_mtime": mtime_et(HIST / "books_kalshi.json"),
        "books_p_mtime": mtime_et(HIST / "books_poly.json"),
        "pull_log_mtime": mtime_et(HIST / "pull.log"),
        "n_priority_t0": sum(1 for r in rows if r["n_t0"] > 0),
        "n_priority": len(PRIORITY),
        "missing": [r["series"] for r in rows if r["status"] == "missing"],
        "events_only": [r["series"] for r in rows if "events only" in r["status"]],
        "partial": [r["series"] for r in rows if "partial" in r["status"] or "in progress" in r["status"]],
    }


def inventory_poly() -> list[dict]:
    t0_dir = PDIR / "t0"
    ev_dir = PDIR / "events"
    coverage = load_json(HIST / "coverage.json") or []
    cov_by = {}
    for row in coverage:
        if str(row.get("platform") or "").startswith("poly"):
            key = str(row.get("league") or row.get("sport") or "").lower()
            cov_by[key] = row
    out = []
    for key in POLY_KEYS:
        t0p = t0_dir / f"{key}.jsonl"
        evp = ev_dir / f"{key}.jsonl"
        n_t0 = line_count(t0p)
        n_ev = line_count(evp)
        cov = cov_by.get(key) or {}
        if n_t0 > 0:
            status = "t0 on disk"
        elif n_ev > 0:
            status = "events only"
        else:
            status = "not started / empty"
        out.append({
            "sport": key,
            "status": status,
            "n_t0": n_t0,
            "n_events": n_ev,
            "cov_t0": cov.get("n_t0"),
            "cov_fetched": cov.get("candles_fetched"),
            "span": f"{cov.get('span_lo') or '—'} .. {cov.get('span_hi') or '—'}",
            "mtime": mtime_et(t0p) if t0p.is_file() else (mtime_et(evp) if evp.is_file() else "—"),
        })
    return out


def cfb_t0_counts() -> dict:
    path = KDIR / "t0" / "KXNCAAFGAME.jsonl"
    by_all = Counter()
    by_fav = Counter()
    missing_ask = 0
    n = 0
    n_ask = 0
    endpoints = Counter()
    fav_px: list[float] = []
    pairs: dict[str, list] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            n += 1
            endpoints[str(row.get("endpoint") or "")] += 1
            px = row.get("yes_ask")
            if px is None:
                missing_ask += 1
                continue
            try:
                x = float(px)
            except (TypeError, ValueError):
                missing_ask += 1
                continue
            n_ask += 1
            dec = decile_of(x)
            if dec:
                by_all[dec] += 1
            ev = str(row.get("event_ticker") or "")
            pairs[ev].append(x)
    n_games = 0
    n_close = 0  # fav in 50-89
    n_chalk = 0  # fav 90+
    n_dog_only = 0
    for _ev, xs in pairs.items():
        n_games += 1
        fav = max(xs)
        fav_px.append(fav)
        d = decile_of(fav)
        if d:
            by_fav[d] += 1
        if fav >= 0.90:
            n_chalk += 1
        elif fav >= 0.50:
            n_close += 1
        else:
            n_dog_only += 1
    fav_px.sort()

    def pct(xs, q):
        if not xs:
            return None
        i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
        return xs[i]

    return {
        "n_rows": n,
        "n_ask": n_ask,
        "missing_ask": missing_ask,
        "by_all": dict(by_all),
        "by_fav": dict(by_fav),
        "n_games": n_games,
        "n_close": n_close,
        "n_chalk": n_chalk,
        "n_dog_only": n_dog_only,
        "fav_p50": pct(fav_px, 0.50),
        "fav_p10": pct(fav_px, 0.10),
        "fav_p90": pct(fav_px, 0.90),
        "endpoints": dict(endpoints),
        "mtime": mtime_et(path),
    }


def live_cde() -> dict:
    dash = load_json(RAW / "dashboard_cache.json") or {}
    trades = list(dash.get("trades") or dash.get("all_rows") or dash.get("rows") or [])
    if not trades:
        for key in ("today_rows", "open_rows", "settled_rows", "history_rows"):
            trades.extend(dash.get(key) or [])
    # de-dupe by order_id + system + when
    seen = set()
    uniq = []
    for row in trades:
        oid = str(row.get("order_id") or "")
        key = (oid, str(row.get("system") or ""), str(row.get("when_raw") or row.get("when") or ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(row)

    def by_sys(letter: str) -> list[dict]:
        return [r for r in uniq if str(r.get("system") or "").upper() == letter]

    def venue_counts(rows: list[dict]) -> dict:
        c = Counter(str(r.get("venue") or "—") for r in rows)
        return dict(c)

    c_rows = by_sys("C")
    d_rows = by_sys("D")
    e_rows = by_sys("E")
    cfb_watch = load_json(RAW / "cfb_favorite_watch.json") or {}
    spread_watch = load_json(RAW / "spread_t0_watch.json") or {}
    dog_watch = load_json(RAW / "tennis_t0_dog_watch.json") or {}

    def watch_venues(watch: dict) -> dict:
        c = Counter()
        for m in watch.get("matches") or []:
            v = str(m.get("venue") or "")
            if v:
                c[v] += 1
        return dict(c)

    c_venues_fill = venue_counts(c_rows)
    # live tape CFB ML 50-99 from decile JSON live_cells
    dump = load_json(DECILE_JSON) or {}
    live_cells = dump.get("live_cells") or {}
    cfb_live = {}
    for dec in DECADES:
        rec = live_cells.get(f"college football|ALL|Moneyline|{dec}") or live_cells.get(
            f"college football|CFB|Moneyline|{dec}"
        ) or {}
        cfb_live[dec] = rec
    d_live_spread = {}
    for sport in ("college football", "soccer", "hockey", "pro hockey", "basketball", "baseball"):
        for dec in DECADES:
            rec = live_cells.get(f"{sport}|ALL|Spread|{dec}") or {}
            if rec:
                d_live_spread[f"{sport}|{dec}"] = rec

    return {
        "dash_at": dash.get("trades_at") or dash.get("updated_at") or "",
        "c_n": len(c_rows),
        "d_n": len(d_rows),
        "e_n": len(e_rows),
        "c_venues": c_venues_fill,
        "d_venues": venue_counts(d_rows),
        "e_venues": venue_counts(e_rows),
        "c_watch": {
            "enabled": cfb_watch.get("enabled"),
            "pid": cfb_watch.get("pid"),
            "updated_at": cfb_watch.get("updated_at"),
            "last_send": cfb_watch.get("last_send"),
            "last_action": cfb_watch.get("last_action"),
            "last_skip": cfb_watch.get("last_skip_reason"),
            "open": cfb_watch.get("currently_open"),
            "venues": watch_venues(cfb_watch),
        },
        "d_watch": {
            "enabled": spread_watch.get("enabled"),
            "pid": spread_watch.get("pid"),
            "updated_at": spread_watch.get("updated_at"),
            "last_send": spread_watch.get("last_send"),
            "last_action": spread_watch.get("last_action"),
            "open": spread_watch.get("currently_open"),
            "venues": watch_venues(spread_watch),
        },
        "e_watch": {
            "enabled": dog_watch.get("enabled"),
            "pid": dog_watch.get("pid"),
            "updated_at": dog_watch.get("updated_at"),
            "last_send": dog_watch.get("last_send"),
            "last_action": dog_watch.get("last_action"),
            "open": dog_watch.get("currently_open"),
        },
        "c_sample": [
            {
                "when": r.get("when"),
                "game": r.get("game"),
                "venue": r.get("venue"),
                "wire": r.get("wire"),
                "outcome": r.get("outcome"),
            }
            for r in sorted(c_rows, key=lambda x: str(x.get("when_raw") or ""), reverse=True)[:12]
        ],
        "cfb_live_ml": cfb_live,
        "d_live_spread": d_live_spread,
        "live_grand_n": (dump.get("grand") or {}).get("n"),
        "hist_meta": dump.get("hist") or {},
    }


def write_html(inv: dict, poly: list[dict], cfb: dict, live: dict, hist_cells: dict, live_html_cells: dict) -> str:
    now = now_et()
    missing = inv["missing"]
    events_only = inv["events_only"]
    partial = inv["partial"]
    kalshi_done = not missing and not events_only and not partial
    poly_started = any(r["n_t0"] > 0 for r in poly)
    poly_done = all(r["n_t0"] > 0 or r["status"] == "t0 on disk" for r in poly) and all(
        r["n_t0"] > 0 for r in poly if r["sport"] != "ncaab"
    )
    # ncaab may legitimately be empty; still not "done" if epl/mls/ucl empty
    poly_empty_keys = [r["sport"] for r in poly if r["n_t0"] == 0]
    if kalshi_done and poly_done:
        verdict = "Done"
    elif not kalshi_done and poly_started:
        verdict = "Kalshi partial + Polymarket in progress (not empty, not finished)"
    elif not kalshi_done and not poly_started:
        verdict = "Kalshi partial + Polymarket not started"
    else:
        verdict = "Kalshi done-enough; Polymarket not finished"

    cov_rows = []
    for r in inv["rows"]:
        cov_rows.append([
            esc(r["series"]),
            esc(r["kind"]),
            esc(r["status"]),
            str(r["n_t0"]),
            str(r["n_events_file"]),
            "yes" if r["cov_fetched"] else ("no" if r["cov_fetched"] is False else "—"),
            str(r["cov_t0"] if r["cov_t0"] is not None else "—"),
            str(r["cov_miss"] if r["cov_miss"] is not None else "—"),
            esc(r["span"]),
            esc(r["t0_mtime"]),
        ])
    cov_tbl = table(
        [
            ("Series", "text"), ("Type", "text"), ("Status", "text"),
            ("T0 jsonl N", "num"), ("Events jsonl N", "num"),
            ("coverage candles_fetched", "text"),
            ("coverage n_t0", "num"), ("coverage missing", "num"),
            ("Span", "text"), ("T0 last write", "date"),
        ],
        cov_rows,
    )

    hole_rows = []
    by_series = {r["series"]: r for r in inv["rows"]}
    for name in (
        "KXSERIEASPREAD", "KXSERIEATOTAL",
        "KXLALIGAGAME", "KXLALIGASPREAD", "KXLALIGATOTAL",
        "KXLIGUE1GAME", "KXLIGUE1SPREAD", "KXLIGUE1TOTAL",
        "KXUFCFIGHT", "KXMLSSPREAD", "KXMLSTOTAL",
        "KXATPMATCH", "KXWTAMATCH",
        "KXUCLSPREAD", "KXUCLTOTAL", "KXEPLSPREAD", "KXEPLTOTAL",
        "KXBUNDESLIGASPREAD", "KXBUNDESLIGATOTAL",
        "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH",
        "KXMMAFIGHT", "KXPGARYDERMATCH", "KXPRESCUPMATCH", "KXTGLMATCH",
        "KXITFMATCH", "KXITFWMATCH",
    ):
        r = by_series.get(name) or {
            "series": name, "status": "missing", "n_t0": 0,
            "cov_miss": None, "t0_mtime": "—",
        }
        listed = "yes — 10/27 page" if name in HOLES_LISTED or name.startswith("KXLIGUE1") or name.startswith("KXLALIGA") or name.startswith("KXSERIEA") or name == "KXUFCFIGHT" else "priority leftover"
        hole_rows.append([
            esc(name),
            esc(listed),
            esc(r.get("status") or "missing"),
            str(r.get("n_t0") or 0),
            str(r.get("cov_miss") if r.get("cov_miss") is not None else "—"),
            esc(r.get("t0_mtime") or "—"),
        ])
    hole_tbl = table(
        [
            ("Series", "text"), ("On 10/27 hole list?", "text"),
            ("Now", "text"), ("T0 N", "num"), ("Candle miss (coverage)", "num"),
            ("T0 last write", "date"),
        ],
        hole_rows,
    )

    poly_rows = [[
        esc(r["sport"]), esc(r["status"]), str(r["n_t0"]), str(r["n_events"]),
        "yes" if r["cov_fetched"] else ("no" if r["cov_fetched"] is False else "—"),
        esc(r["span"]), esc(r["mtime"]),
    ] for r in poly]
    poly_tbl = table(
        [
            ("Poly sport key", "text"), ("Status", "text"), ("T0 jsonl N", "num"),
            ("Events jsonl N", "num"), ("coverage candles_fetched", "text"),
            ("Span", "text"), ("Last write", "date"),
        ],
        poly_rows,
    )

    def dec_row(label, counter):
        rows = []
        for dec in DECADES:
            n = int(counter.get(dec) or 0)
            rows.append([esc(label), esc(dec), str(n)])
        return rows

    cfb_dec = table(
        [("Slice", "text"), ("Decile", "text"), ("N", "num")],
        dec_row("Kalshi hist CFB ML — all named Yes", cfb["by_all"])
        + dec_row("Kalshi hist CFB ML — favorite side (max Yes-ask per game)", cfb["by_fav"])
        + [
            [
                "Live tape CFB ML (four-platform kitchen tape on the 10/27 sheet)",
                dec,
                str((live["cfb_live_ml"].get(dec) or {}).get("n") or 0),
            ]
            for dec in DECADES
        ],
    )
    n049 = sum(int(cfb["by_all"].get(d) or 0) for d in ("0-9", "10-19", "20-29", "30-39", "40-49"))
    n5089 = sum(int(cfb["by_all"].get(d) or 0) for d in ("50-59", "60-69", "70-79", "80-89"))
    n9099 = int(cfb["by_all"].get("90-99") or 0)
    n09 = int(cfb["by_all"].get("0-9") or 0)
    fav5089 = sum(int(cfb["by_fav"].get(d) or 0) for d in ("50-59", "60-69", "70-79", "80-89"))
    fav90 = int(cfb["by_fav"].get("90-99") or 0)
    sheet_cfb = []
    for dec in DECADES:
        rec = hist_cells.get(f"college football|CFB|Moneyline|{dec}") or hist_cells.get(
            f"college football|ALL|Moneyline|{dec}"
        ) or {}
        sheet_cfb.append([
            esc(dec),
            str(int(cfb["by_all"].get(dec) or 0)),
            str(int(cfb["by_fav"].get(dec) or 0)),
            str(rec.get("n") or 0),
            str(rec.get("n_win") or 0),
            str(rec.get("n_fee") or 0),
            str((live["cfb_live_ml"].get(dec) or {}).get("n") or 0),
        ])
    sheet_vs_raw = table(
        [
            ("Decile", "text"),
            ("Kalshi jsonl all named Yes", "num"),
            ("Kalshi jsonl favorite side", "num"),
            ("10/27 Book 2 sheet N", "num"),
            ("Book 2 wins", "num"),
            ("Book 2 n_fee", "num"),
            ("Live four-platform tape N", "num"),
        ],
        sheet_cfb,
    )

    c_venue_rows = [[esc(v), str(n)] for v, n in sorted((live["c_venues"] or {}).items())]
    if not c_venue_rows:
        c_venue_rows = [["(none in dashboard_cache)", "0"]]
    c_venue_tbl = table([("C fill venue", "text"), ("N kitchen rows", "num")], c_venue_rows)
    d_venue_tbl = table(
        [("D fill venue", "text"), ("N kitchen rows", "num")],
        [[esc(v), str(n)] for v, n in sorted((live["d_venues"] or {}).items())] or [["(none)", "0"]],
    )
    e_venue_tbl = table(
        [("E fill venue", "text"), ("N kitchen rows", "num")],
        [[esc(v), str(n)] for v, n in sorted((live["e_venues"] or {}).items())] or [["(none)", "0"]],
    )
    c_sample_tbl = table(
        [("When", "date"), ("Game", "text"), ("Venue", "text"), ("Wire", "num"), ("Outcome", "text")],
        [[
            esc(r.get("when")), esc(r.get("game")), esc(r.get("venue")),
            esc(r.get("wire")), esc(r.get("outcome")),
        ] for r in live["c_sample"]],
    )

    spread_series = [r for r in inv["rows"] if r["kind"] == "spread"]
    spread_tbl = table(
        [("Kalshi spread series", "text"), ("Status", "text"), ("T0 N", "num"), ("Last write", "date")],
        [[esc(r["series"]), esc(r["status"]), str(r["n_t0"]), esc(r["t0_mtime"])] for r in spread_series],
    )

    def cell_lookup(sport, league, kind, dec):
        keys = [
            f"{sport}|{league}|{kind}|{dec}",
            f"{sport}|ALL|{kind}|{dec}",
        ]
        if sport == "hockey":
            keys += [f"hockey|NHL|{kind}|{dec}", f"pro hockey|ALL|{kind}|{dec}"]
        if sport == "baseball":
            keys += [f"baseball|MLB|{kind}|{dec}", f"pro baseball|ALL|{kind}|{dec}"]
        if sport == "basketball":
            keys += [f"basketball|NBA|{kind}|{dec}", f"basketball|WNBA|{kind}|{dec}"]
        for k in keys:
            if k in hist_cells:
                return k, hist_cells[k]
        return "", None

    d_paul_rows = []
    for sport, league, kind, dec, n, w in PAUL_D:
        key, rec = cell_lookup(sport, league, kind, dec)
        live_rec = (live_html_cells.get(f"{sport}|{league}|{kind}|{dec}")
                    or live["d_live_spread"].get(f"{sport}|{dec}")
                    or {})
        d_paul_rows.append([
            esc(f"{sport} {league} {kind} {dec}"),
            str(n), str(w),
            esc(key or "not found in Book 2 HTML"),
            str((rec or {}).get("n") if rec else "—"),
            str((rec or {}).get("n_win") if rec else "—"),
            format_money((rec or {}).get("pnl_sum")) if rec else "—",
            str(live_rec.get("n") or 0),
            str(live_rec.get("n_win") or 0),
            "Kalshi hist Book 2 (tiny N). Not live D 51–89." if rec else "not on Book 2 as pasted",
        ])
    d_paul_tbl = table(
        [
            ("Paul cell", "text"), ("Paul N", "num"), ("Paul wins", "num"),
            ("Book 2 key matched", "text"), ("Book 2 N", "num"), ("Book 2 wins", "num"),
            ("Book 2 P&L", "num"),
            ("Live tape N (same sport/decile if present)", "num"),
            ("Live tape wins", "num"),
            ("Note", "text"),
        ],
        d_paul_rows,
    )

    e_paul_rows = []
    for sport, league, kind, dec, n, w, n_fee, pnl, avg in PAUL_E:
        key, rec = cell_lookup(sport, league, kind, dec)
        is_e = sport == "tennis" and kind == "Moneyline" and dec in {
            "10-19", "20-29", "30-39", "40-49",
        }
        e_paul_rows.append([
            esc(f"{sport} {league} {kind} {dec}"),
            str(n), str(w), str(n_fee), format_money(pnl),
            esc(key or "not found"),
            str((rec or {}).get("n") if rec else "—"),
            str((rec or {}).get("n_win") if rec else "—"),
            str((rec or {}).get("n_fee") if rec else "—"),
            format_money((rec or {}).get("pnl_sum")) if rec else "—",
            "YES — this is live E" if is_e else "NO — not System E",
            "Kalshi hist all-sport moneyline Book 2. Live E is tennis 11–49 only.",
        ])
    e_paul_tbl = table(
        [
            ("Paul cell", "text"), ("Paul N", "num"), ("Paul W", "num"),
            ("Paul n_fee", "num"), ("Paul P&L", "num"),
            ("Book 2 key", "text"), ("Book 2 N", "num"), ("Book 2 W", "num"),
            ("Book 2 n_fee", "num"), ("Book 2 P&L", "num"),
            ("Is live System E?", "text"), ("Note", "text"),
        ],
        e_paul_rows,
    )

    season_tbl = table(
        [("Sport in those cells", "text"), ("As of Thu 29 Oct 2026", "text"), ("Collecting live?", "text")],
        [
            ["NFL / pro football", "In season (Thursday night / Sunday slate). Not out of season.", "Live A/D skip NFL on D; C is CFB not NFL. NFL moneyline hist is not E."],
            ["NHL / hockey", "Typical NHL season is underway in late October. In season.", "Live D can take NHL spreads (non-NFL). Hockey moneyline is not E."],
            ["Soccer (EPL / UCL / other leagues)", "EPL and Champions League are in season (Aug–May).", "Live D can take soccer spreads. Soccer moneyline is not E."],
            ["MLB / baseball", "Regular season is over. Postseason / World Series is typically late October — do not stamp “done for the year” without a final; likely postseason or just finished.", "Live D can take baseball spreads if listed. Baseball moneyline 90–99 is not E."],
            ["College football", "In season (Thu–Sat). C last skip today: TXST vs USU T0 window passed.", "Yes — live C four-platform."],
            ["Tennis (actual System E)", "Year-round. Kitchen filled E today (WTA/ITF on Polymarket).", "Yes — live E tennis 11–49."],
        ],
    )

    live_vs = table(
        [
            ("System", "text"), ("Live freeze", "text"), ("Kalshi hist?", "text"),
            ("Live platforms", "text"), ("Kitchen N (dashboard_cache)", "num"),
            ("Process", "text"),
        ],
        [
            [
                "C CFB moneyline favorite",
                "51–89¢, hold to end, four platforms, cheapest Yes",
                f"KXNCAAFGAME candled (T0 N={by_series.get('KXNCAAFGAME', {}).get('n_t0', 0)}). 50–89 named-Yes is sparse because most Kalshi CFB favorites sit at 90¢+ at T0.",
                "Kalshi + Gemini + Polymarket + Novig quotes. Sends go to the cheapest that can fill.",
                str(live["c_n"]),
                (
                    f"enabled={live['c_watch'].get('enabled')} pid={live['c_watch'].get('pid')} "
                    f"updated {live['c_watch'].get('updated_at')} last_send {live['c_watch'].get('last_send')} "
                    f"skip={live['c_watch'].get('last_skip')}"
                ),
            ],
            [
                "D T0 spread fav-to-cover",
                "51–89¢ closest line to 50¢, no NFL, not Points Total",
                "Kalshi lists CFB/NBA/NHL/MLB/WNBA/soccer spreads (not only KXNFLSPREAD). Live D still quotes Gemini/Poly/Novig even if a Kalshi series is thin.",
                "Kalshi + Gemini + Polymarket + Novig",
                str(live["d_n"]),
                (
                    f"enabled={live['d_watch'].get('enabled')} pid={live['d_watch'].get('pid')} "
                    f"updated {live['d_watch'].get('updated_at')} last_send {live['d_watch'].get('last_send')}"
                ),
            ],
            [
                "E tennis T0 dog",
                "11–49¢ skip-if-B, cheapest of four",
                "Kalshi ATP/WTA candled (Challenger/ITF not candled). Hockey/soccer/NFL/MLB moneyline cells are not E.",
                "Kalshi + Gemini + Polymarket + Novig",
                str(live["e_n"]),
                (
                    f"enabled={live['e_watch'].get('enabled')} pid={live['e_watch'].get('pid')} "
                    f"updated {live['e_watch'].get('updated_at')} last_send {live['e_watch'].get('last_send')}"
                ),
            ],
        ],
    )

    p50 = cfb["fav_p50"]
    p50_s = f"{p50:.2f}" if p50 is not None else "—"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Kalshi hist coverage vs live C/D/E 29 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.hold {{ background: #fef3c7; border-color: #f59e0b; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Kalshi history vs live C / D / E</h1>
<p class="note">Written {esc(now)}. Inventory of the history pull and the live kitchen.
Did not sell tickets, start a second Tennis crossover (B), bump stake, leftover-GTC on A,
wire D NFL, retune C/D/E bands, or retune B’s 0.25 dip / 1.05 cap. Did not restart the
hist pull. Click column headers to sort.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>

<div class="callout hold">
<h2>Is Kalshi history done? — {esc(verdict)}</h2>
<p>Kalshi T0 candles exist for {inv['n_priority_t0']} of {inv['n_priority']} priority
series. Still missing or unfinished: {esc(", ".join(missing + events_only + partial) or "none")}.
A Kalshi candle job is still writing Ligue 1 spread. A separate Polymarket job is still
writing (last sport started: EPL). The 10/27 decile page said Polymarket hist N=0; that
is stale — Poly last-trade files are on disk now, but the pull is not finished and this
page did not wait for it. We did not start a third pull.</p>
<p class="tiny">hist dir
<code>local/paul_experiments/prediction_market_arb_exhaustive_20261017/hist/</code>.
coverage.json mtime {esc(inv['coverage_mtime'])}; books_kalshi.json {esc(inv['books_k_mtime'])};
books_poly.json {esc(inv['books_p_mtime'])}; pull.log {esc(inv['pull_log_mtime'])}.</p>
</div>

<h2>Answers in one screen</h2>
<ul>
<li><strong>Kalshi hist:</strong> not done. Soccer/UFC/golf/Challenger leftovers remain.
Serie A spread/total, La Liga, Ligue 1 moneyline, ATP/WTA, UCL, EPL, Bundesliga, MLS
spread/total now have T0 files. Ligue 1 spread is in progress. Ligue 1 total, UFC
finish, golf, MMA, Challenger/ITF are not candled.</li>
<li><strong>Poly hist:</strong> started and large (NFL/CFB/NBA/NHL/MLB/WNBA/ATP/WTA/UFC/PGA
on disk). EPL in progress; MLS/UCL/NCAAB not yet. Not the empty <code>books_poly.json</code>
from the 10/27 page.</li>
<li><strong>CFB favorite live:</strong> yes, four platforms. Process C is running today.
Kalshi-only history will still look empty in 50–89 even while Gemini/Poly/Novig collect.</li>
<li><strong>Why CFB 50–99 is lite on the sheet:</strong> Kalshi lists CFB moneyline
(<code>KXNCAAFGAME</code>, {cfb['n_rows']} T0 rows). Raw candles are <em>not</em> empty
in 50–89 (named-Yes N={n5089}; favorite-side games N={fav5089}). The 10/27 Book 2 table
looks lite because that page keeps one cheaper named Yes per game — the dog — so 0–49
matches the jsonl and 50–99 is almost empty by construction. Live C bets the favorite
51–89 on four platforms, which is the opposite side.</li>
<li><strong>D spreads:</strong> Kalshi has CFB and soccer/NBA/NHL/MLB/WNBA spread series,
not only <code>KXNFLSPREAD</code>. Paul’s four “only winners” cells are tiny Kalshi hist
Book 2 rows, not live D. Live D 50–89 non-NFL on the 10/29 C/D/E page is N=97.</li>
<li><strong>Those E “winners”:</strong> they are all-sport Kalshi hist moneyline cells,
not live tennis E. Hockey 50–59 and baseball 90–99 are not system E. NFL, NHL, and EPL
are in season today; MLB is postseason / likely done with the regular season — not “all
four sports are out of season.”</li>
</ul>

<h2>Priority Kalshi series</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>
{cov_tbl}

<h2>Holes the 10/27 page listed, plus leftover priority</h2>
{hole_tbl}

<h2>Polymarket last-trade hist</h2>
<p class="note">Parent note that <code>books_poly.json</code> was empty was true on the
10/27 page (settled N=0). It is not true now. Do not mix Poly last-trade with Kalshi Yes-ask.</p>
{poly_tbl}

<h2>CFB moneyline T0 by 10-cent bucket</h2>
<p class="note">Kalshi hist from <code>hist/kalshi/t0/KXNCAAFGAME.jsonl</code>
({cfb['n_rows']} rows, {cfb['n_ask']} with Yes-ask, {cfb['missing_ask']} missing ask,
{cfb['n_games']} games, last write {esc(cfb['mtime'])}). Named Yes is both teams.
Favorite side is the higher Yes-ask on that game. Median favorite Yes-ask on Kalshi T0
is {esc(p50_s)}. Favorites 90¢+: {cfb['n_chalk']} of {cfb['n_games']} games.
Favorites 50–89¢: {cfb['n_close']} games. Named-Yes 0–49 N={n049}; 50–89 N={n5089};
90–99 N={n9099}; 0–9 N={n09}.</p>
{sheet_vs_raw}
{cfb_dec}
<p class="note">Three facts, not one. (1) Kalshi <em>does</em> list CFB moneyline —
coverage missing candles is 6 of 3902, not the hole. (2) At T0 many Kalshi favorites
are already 90¢+ (chalk {cfb['n_chalk']} games), and the other named Yes sits in 0–9
(N={n09}). (3) The 10/27 sheet is still lite in 50–99 even though jsonl 50–89 named-Yes
is {n5089}, because Book 2 runs <code>pick_one_side</code>: one cheaper Yes per game.
That keeps the dog (0–49 jsonl matches the sheet exactly) and drops the favorite.
50–59 on the sheet is N=24 vs jsonl 127. 80–89 on the sheet is N=0 vs jsonl 225.
90–99 on the sheet is N=99 with n_fee=0 (Yes-ask of $1 has no documented Kalshi fee).
Live C is the opposite trade: favorite 51–89, cheapest of Kalshi / Gemini / Polymarket /
Novig. A Kalshi-only hist sheet will look empty for C even while live C is collecting
on the other three venues. Kitchen C fills so far: Kalshi 4, Novig 1, Gemini 0,
Polymarket 0. Process C is running today (last skip TXST vs USU, T0 window passed).</p>

<h2>Live C / D / E vs Kalshi</h2>
<p class="note">Kitchen dashboard_cache {esc(live.get('dash_at') or '')}.
Live tape settled N on the 10/27 JSON: {live.get('live_grand_n')}.
Kalshi hist settled N on that page: {(live.get('hist_meta') or {}).get('kalshi_n')};
Poly hist N on that page: {(live.get('hist_meta') or {}).get('poly_n')} (stale vs files now).</p>
{live_vs}
<h3>C kitchen fills by venue</h3>
{c_venue_tbl}
<p class="note">Watch-file venues on C matches: {esc(live['c_watch'].get('venues'))}.
Code path <code>live_t0_yes.collect_quotes</code> always pulls Kalshi, Gemini, Polymarket,
and Novig. A send uses the cheapest Yes in band. No Kalshi contract does not skip the
other three.</p>
<h3>Recent C kitchen rows</h3>
{c_sample_tbl}
<h3>D kitchen fills by venue</h3>
{d_venue_tbl}
<h3>E kitchen fills by venue</h3>
{e_venue_tbl}

<h2>D — Kalshi spread series vs live D</h2>
<p class="note">Paul: “Kalshi doesn’t support any system on spreads.” Kalshi does list
spreads beyond NFL. Live D skips NFL and Points Total and takes the line closest to 50¢
in 51–89. The four tiny winner cells below sit outside that freeze (10–19 / 20–29 /
80–89) and are Book 2 hist, N=1–4.</p>
{spread_tbl}
{d_paul_tbl}
<p class="note">Live D on
<a href="{esc(str(CDE_HTML))}">cde_band_decile_20261029.html</a>:
non-NFL spread 50–89 N=97 WR 75.3% avg $0.05 (11-day four-platform tape). Kalshi hist
same band N=352 avg −$0.33. Do not blend.</p>

<h2>E — those “winners” are not System E</h2>
<p class="note">Live E is tennis moneyline underdog 11–49¢, skip-if-B, cheapest of four.
Hockey 50–59, soccer 10–19, pro football 10–19, and baseball 90–99 are all-sport
moneyline cells on the sport sheet. They are Kalshi hist Book 2 (baseball 90–99 N=2211
cannot be the 11-day live tape, whose whole book is 1734 settled). n_fee=1 on baseball
90–99 is a fee-doc hole, not “one live E ticket.”</p>
{e_paul_tbl}

<h2>Season check — Thursday 29 Oct 2026</h2>
<p class="note">Do not rubber-stamp “all out of season.” NFL is in season. NHL is in
season. EPL/UCL soccer is in season. MLB regular season is over; October is postseason
territory. Tennis (the actual E sport) filled today.</p>
{season_tbl}

<p class="tiny">Sources: <code>{esc(HIST.as_posix())}</code>,
<code>tools/_pull_pm_hist_t0_20261028.py</code> priority list,
<a href="{esc(DECILE_URL)}">sport_league_t0_decile_20261027.html</a>,
<code>tools/live_t0_yes.py</code> four-platform quotes,
<code>{esc((RAW / 'cfb_favorite_watch.json').as_posix())}</code>,
<code>{esc((RAW / 'dashboard_cache.json').as_posix())}</code>.
Did not mix sportsbook closes. Did not commit. File URL {esc(FILE_URL)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return str(PAGE)


def main() -> int:
    print("inventory kalshi", flush=True)
    inv = inventory_kalshi()
    print("inventory poly", flush=True)
    poly = inventory_poly()
    print("cfb t0 counts", flush=True)
    cfb = cfb_t0_counts()
    print("live cde", flush=True)
    live = live_cde()
    print("parse decile html", flush=True)
    html_text = DECILE_HTML.read_text(encoding="utf-8") if DECILE_HTML.is_file() else ""
    hist_cells = parse_hist_cells(html_text) if html_text else {}
    live_html_cells = parse_live_cells(html_text) if html_text else {}
    print(f"hist cells {len(hist_cells)} live html cells {len(live_html_cells)}", flush=True)
    path = write_html(inv, poly, cfb, live, hist_cells, live_html_cells)
    print(f"wrote {path}", flush=True)
    print(
        "kalshi missing={0} events_only={1} partial={2} c_n={3} c_venues={4} "
        "cfb_games={5} fav_50_89={6} fav_90={7} hist_cells={8}".format(
            inv["missing"], inv["events_only"], inv["partial"],
            live["c_n"], live["c_venues"], cfb["n_games"], cfb["n_close"],
            cfb["n_chalk"], len(hist_cells),
        ),
        flush=True,
    )
    for sport, league, kind, dec, n, w, *rest in [
        ("hockey", "ALL", "Moneyline", "50-59", 21, 13),
        ("soccer", "ALL", "Moneyline", "10-19", 15, 3),
        ("pro football", "ALL", "Moneyline", "10-19", 41, 7),
        ("baseball", "ALL", "Moneyline", "90-99", 2211, 1067),
        ("soccer", "ALL", "Spread", "10-19", 2, 1),
        ("basketball", "ALL", "Spread", "80-89", 1, 1),
        ("baseball", "ALL", "Spread", "80-89", 1, 1),
        ("basketball", "ALL", "Spread", "20-29", 4, 1),
    ]:
        rec = hist_cells.get(f"{sport}|{league}|{kind}|{dec}")
        print(f"  book2 {sport}|{league}|{kind}|{dec} {rec}", flush=True)
    print("cfb by_all", dict(cfb["by_all"]), flush=True)
    print("cfb by_fav", dict(cfb["by_fav"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
